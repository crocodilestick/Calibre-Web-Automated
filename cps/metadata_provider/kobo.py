# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import concurrent.futures
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import os
import time
from http.cookies import SimpleCookie

try:
    from curl_cffi import requests as creq  # type: ignore
except ImportError:
    import requests as creq  # Fallback to regular requests if curl-cffi not available
    
from bs4 import BeautifulSoup as BS
from bs4.element import Tag
from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

log = logger.create()


class Kobo(Metadata):
    """Kobo metadata provider via web scraping.

    Accepts a query string and a language ISO-2 code (e.g., "en", "ja").
    Scrapes Kobo search results and follows detail pages to extract:
    Title, Authors, Year, Series Name, Series Number, Language, Cover, Synopsis.
    """

    __name__ = "Kobo"
    __id__ = "kobo"

    DESCRIPTION = "Kobo Books"
    META_URL = "https://www.kobo.com/"

    # Centralized selectors and patterns for maintainability
    SERIES_DT_TESTID = "series-product-type-and-number"
    SERIES_LINK_SELECTOR = "a[href*='series/']"
    TITLE_SELECTORS = [
        "h1[data-testid='title']",
        "[data-testid='product-title']",
        "[data-testid='product-header-title']",
        "[data-testid='title'] .link--label",
        "[data-testid='title']",
        "h1[itemprop='name']",
        "h1",
    ]
    AUTHOR_SELECTORS = [
        "dd[data-testid='authors'] a[data-testid='book-attribute-link'] .link--label",
        "dd[data-testid='authors'] a[href*='author/'] .link--label",
        "[data-automation='author-name']",
        "a[href*='/search?query='][href*='contributor']",
        "a[href*='author/']",
    ]
    DESC_SELECTORS = [
        "[data-full-synopsis]",
        "[data-testid='synopsis']",
        "[data-testid='description']",
        "[data-automation='synopsis']",
        "[data-automation='book-description']",
        "[itemprop='description']",
        ".text-synopsis",
    ]
    BOOK_DT_PREFIX_RE = re.compile(r"^\s*Book\b", re.I)
    CARD_SELECTORS = (
        "[data-testid=\"book-card-search-result-items\"], [data-testid=\"search-result-widget\"]"
    )

    headers = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8"
        ),
        "accept-language": "en-US,en;q=0.9",
        "upgrade-insecure-requests": "1",
        "accept-encoding": "gzip, deflate, br, zstd",
        "referer": "https://www.kobo.com/",
        "sec-ch-ua": '"Google Chrome";v="120", "Chromium";v="120", "Not:A-Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-full-version-list": '"Google Chrome";v="120.0.0.0", "Chromium";v="120.0.0.0", "Not:A-Brand";v="99.0.0.0"',
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document",
        "sec-fetch-user": "?1",
    }
    
    def __init__(self):
        super().__init__()
        self.session = None
        self._last_request_time = 0
        self._min_request_interval = 0.5  # Minimum 500ms between requests
        
    def _get_session(self):
        """Get or create a session with proper configuration."""
        if self.session is None:
            try:
                # Try curl-cffi with impersonation first
                self.session = creq.Session(impersonate="chrome120")
            except (TypeError, AttributeError):
                # Fallback to regular requests session
                self.session = creq.Session()
            self.session.headers.update(self.headers)
        return self.session
        
    def _close_session(self):
        """Properly close the session if it exists."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            finally:
                self.session = None
                
    def __del__(self):
        """Cleanup when object is destroyed."""
        self._close_session()

    SEARCH_MAX = 5
    DETAIL_TIMEOUT = 12
    DEFAULT_TIMEOUT = 10
    WARMUP_TIMEOUT = 8

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active:
            return []

        headers = self._headers_for_locale(locale)
        headers = self._apply_cookies(headers)

        # Warm up session to pick up cookies that sometimes gate search
        try:
            self._get(self.META_URL, headers=headers, timeout=self.WARMUP_TIMEOUT)
        except Exception:
            pass

        # Build primary and fallback search URLs
        primary_url = self._build_search_url(query=query, lang=locale or "en")
        simple_q = "+".join(list(self.get_title_tokens(query, strip_joiners=False)) or [query])
        fallback_url = f"https://www.kobo.com/search?query={simple_q}&fcmedia=Book"

        r = None
        for url in (primary_url, fallback_url):
            try:
                r = self._get(url, headers=headers, timeout=self.DEFAULT_TIMEOUT, allow_redirects=True)
                if r.status_code == 403:
                    continue
                r.raise_for_status()
                break
            except Exception as e:
                log.warning("Kobo search failed for %s: %s", url, e)
                continue  # Try next URL instead of returning immediately
                
        if not r or r.status_code >= 400:
            log.warning("Kobo search failed: no usable response (last status %s)", r.status_code if r else None)
            return []

        soup = BS(r.text, "lxml")
        next_data = self._get_next_data_json(soup)
        # Harvest search-level series hints for fallback (e.g., 'Book 6 -')
        search_series_map = self._extract_search_series_map(soup, next_data)
        

        links = self._extract_result_links(soup)
        links = links[: self.SEARCH_MAX]

        results: List[Tuple[MetaRecord, int]] = []

        def fetch_and_parse(link: str, index: int):
            try:
                rec = self._fetch_detail(link, generic_cover, locale)
                if rec:
                    # Backfill series data from search page if missing
                    slug = self._extract_kobo_id_from_url(link)
                    ser = search_series_map.get(slug)
                    if ser:
                        name, idx = ser
                        if not rec.series:
                            rec.series = name
                        if not rec.series_index:
                            rec.series_index = idx
                    return (rec, index)
            except Exception as ex:
                log.warning("Kobo detail fetch failed for %s: %s", link, ex)
                return None

        if not links:
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futs = {executor.submit(fetch_and_parse, link, i): i for i, link in enumerate(links)}
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=self.DETAIL_TIMEOUT):
                    item = fut.result()
                    if item:
                        results.append(item)
            except concurrent.futures.TimeoutError:
                log.warning("Kobo search detail timeout after %ss", self.DETAIL_TIMEOUT)

        results.sort(key=lambda x: x[1])
        return [x[0] for x in results]

    def _build_search_url(self, query: str, lang: str) -> str:
        lang = str(lang or "en").lower()
        country = "jp" if lang == "ja" else "us"
        path_lang = "ja" if lang == "ja" else "en"
        tokens = list(self.get_title_tokens(query, strip_joiners=False)) or [query]
        q = "+".join(tokens)
        return f"https://www.kobo.com/{country}/{path_lang}/search?query={q}&fcmedia=Book"

    def _headers_for_locale(self, locale: str) -> Dict[str, str]:
        h = dict(self.headers)
        loc = str(locale or "").lower()
        if loc.startswith("ja"):
            h["accept-language"] = "ja-JP,ja;q=0.9"
        else:
            h["accept-language"] = "en-US,en;q=0.9"
        return h

    def _get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: int = None, allow_redirects: bool = True) -> Any:
        """Make HTTP request with rate limiting and proper error handling."""
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT
            
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        session = self._get_session()
        try:
            resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=allow_redirects)
            self._last_request_time = time.time()
            return resp
        except Exception as e:
            self._last_request_time = time.time()
            raise e

    def _extract_result_links(self, soup: BS) -> List[str]:
        # Prefer product links that contain '/ebook/' and avoid audiobooks
        seen = set()
        links: List[str] = []
        for a in soup.select("a[href]"):
            if not isinstance(a, Tag):
                continue
            href = str(a.get("href", ""))
            if not href:
                continue
            if "/ebook/" not in href:
                continue
            if "/audiobook/" in href:
                continue
            # Make absolute
            if href.startswith("/"):
                href = f"https://www.kobo.com{href}"
            if href not in seen:
                seen.add(href)
                links.append(href)
        return links

    def _extract_search_series_map(self, soup: BS, next_data: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, Union[int, float]]]:
        """From the search results page, build a map of product slug -> (series_name, series_index).
        Priority is parsing __NEXT_DATA__ JSON, then fall back to DOM.
        Only captures 'Book' media to avoid audiobooks.
        """
        # 1) Try provided NEXT_DATA JSON
        try:
            j = next_data or self._get_next_data_json(soup)
            if isinstance(j, dict):
                items = (
                    j.get("props", {})
                    .get("pageProps", {})
                    .get("searchResultSSR", {})
                    .get("Items", [])
                )
                out: Dict[str, Tuple[str, Union[int, float]]] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    book = it.get("Book")
                    if not isinstance(book, dict):
                        continue
                    slug = str(book.get("Slug", ""))
                    # Series fields may be absent for standalones
                    sname = str(book.get("SeriesName", "")).strip()
                    snum = book.get("SeriesNumber") or book.get("SeriesNumberFloat")
                    if not (slug and sname and snum):
                        continue
                    idx = self._parse_series_index(snum)
                    if not idx:
                        continue
                    out[slug] = (sname, idx)
                if out:
                    return out
        except Exception as e:
            log.warning("Kobo: Failed to parse NEXT_DATA search series map; falling back to DOM: %s", e)

        # 2) Fallback to DOM card parsing
        out: Dict[str, Tuple[str, Union[int, float]]] = {}
        try:
            # Each card generally has a title link and a dt/dd pair for series
            for card in soup.select(self.CARD_SELECTORS):
                if not isinstance(card, Tag):
                    continue
                a = card.select_one("a[data-testid='title'][href]")
                if not isinstance(a, Tag):
                    continue
                href = a.get("href") or ""
                if not isinstance(href, str):
                    continue
                if "/ebook/" not in href:
                    continue
                # Normalize absolute URL
                if href.startswith("/"):
                    href = f"https://www.kobo.com{href}"
                slug = self._extract_kobo_id_from_url(href)

                # Find the series dt/dd inside this card
                dd = card.select_one(f"dd[data-testid='{self.SERIES_DT_TESTID}']")
                dt = card.select_one(f"dt[data-testid='{self.SERIES_DT_TESTID}']")
                if not (isinstance(dd, Tag) and isinstance(dt, Tag)):
                    continue
                dt_text = dt.get_text(" ", strip=True)
                if not self.BOOK_DT_PREFIX_RE.search(dt_text):
                    continue
                idx = self._parse_series_index(dt_text)
                lbl = dd.select_one("a .link--label") or dd.select_one(".link--label") or dd.select_one("a")
                series_name = lbl.get_text(strip=True) if isinstance(lbl, Tag) else dd.get_text(" ", strip=True)
                if slug and series_name and idx:
                    out[slug] = (series_name, idx)
        except Exception as e:
            log.warning("Kobo: DOM search series map extraction failed: %s", e)
            pass
        return out

    def _fetch_detail(self, url: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        # Data precedence: NEXT_DATA > hidden synopsis > DOM > meta/LD-JSON
        headers = self._headers_for_locale(locale)
        headers = self._apply_cookies(headers)
        r = self._get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BS(r.text, "lxml")
        next_data = self._get_next_data_json(soup)

        # 1) Prefer data from Next.js __NEXT_DATA__ first
        data = self._parse_next_data_detail(soup, url, next_data)
        # 2) Then augment with DOM fallbacks
        # Basic meta/OG fallbacks (image, short description, etc.)
        meta_data = self._parse_meta_fallbacks(soup)
        for k in ("image", "publisher", "publishedDate", "language", "description"):
            if meta_data.get(k) and not data.get(k):
                data[k] = meta_data[k]
        # Published date from DOM if still missing
        if not data.get("publishedDate"):
            dom_pub = self._parse_published_from_dom(soup)
            if dom_pub:
                data["publishedDate"] = dom_pub
        # Publisher from DOM if still missing (eBook Details or dt/dd)
        if not data.get("publisher"):
            dom_publisher = self._parse_publisher_from_dom(soup)
            if dom_publisher:
                data["publisher"] = dom_publisher
        if not data.get("authors"):
            dom_authors = self._parse_authors_from_dom(soup)
            if dom_authors:
                data["authors"] = dom_authors
        # Series precedence: NEXT_DATA already tried inside; augment from DOM only if missing
        if not data.get("series") or not data.get("series_index"):
            dom_series_name, dom_series_index = self._parse_series_from_dom(soup)
            if not data.get("series") and dom_series_name:
                data["series"] = dom_series_name
            if not data.get("series_index") and dom_series_index:
                data["series_index"] = dom_series_index
        # Prefer visible title from DOM if missing or looks like a page title
        dom_title = self._parse_title_from_dom(soup)
        if dom_title:
            prev_title = data.get("title")
            data["title"] = dom_title

        # 3) If still thin, fill from JSON-LD/meta as a last resort
        if not data or (not data.get("title") and not data.get("authors")):
            ld = self._parse_ld_json(soup)
            if ld:
                for k, v in ld.items():
                    data.setdefault(k, v)
                
        # Prefer a longer synopsis from embedded JSON or DOM
        json_desc = self._parse_description_from_embedded_json(soup, next_data)
        if json_desc and len(json_desc) > len(data.get("description", "")):
            data["description"] = json_desc
        # Hidden full synopsis on detail pages
        hidden_desc = self._parse_hidden_full_synopsis(soup)
        if hidden_desc and len(hidden_desc) > len(data.get("description", "")):
            data["description"] = hidden_desc
        # General DOM synopsis as another fallback
        dom_desc = self._parse_description_from_dom(soup)
        if not data.get("description") and dom_desc:
            data["description"] = dom_desc

        title = str(data.get("title", "")).strip()
        authors = data.get("authors", [])
        description = self._clean_description(data.get("description", ""))
        language_code = str(data.get("language", locale or "")).lower()
        cover = self._normalize_cover_url(data.get("image", generic_cover))
        publisher = data.get("publisher", "")
        published = data.get("publishedDate", "")
        series = data.get("series", "")
        series_index = data.get("series_index", 0)
        identifiers: Dict[str, Union[str, int]] = {}
        identifiers["kobo"] = self._extract_kobo_id_from_url(url)

        # Normalize languages to display names like other providers
        languages: List[str] = []
        if language_code:
            try:
                languages = [get_language_name(locale or "en", get_lang3(language_code))]
            except Exception:
                languages = []

        match = MetaRecord(
            id=identifiers.get("kobo") or title,
            title=title,
            authors=authors,
            url=url,
            source=MetaSourceInfo(id=self.__id__, description=self.DESCRIPTION, link=self.META_URL),
        )
        match.cover = cover or generic_cover
        match.description = description
        match.languages = languages
        match.publisher = publisher
        match.publishedDate = published
        match.series = series
        match.series_index = series_index
        match.identifiers = identifiers
        match.tags = []

        # If there is no synopsis, treat as not-a-book and skip
        if not match.description:
            log.debug("Skipping result with no description (likely not a book): %s", url)
            return None

        return match

    def _parse_ld_json(self, soup: BS) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        for s in scripts:
            if not isinstance(s, Tag):
                continue
            try:
                content = s.get_text() or "{}"
                j = json.loads(content)
            except Exception:
                continue

            def extract_from(obj: Dict) -> Optional[Dict]:
                if not isinstance(obj, dict):
                    return None
                types = obj.get("@type")
                types = [types] if isinstance(types, str) else types or []
                # Some Kobo pages wrap the Book as mainEntity or use Product
                if not any(t in ("Book", "Product") for t in types):
                    # If this object has a mainEntity, try extracting from it
                    main = obj.get("mainEntity")
                    if isinstance(main, dict):
                        return extract_from(main)
                    return None

                title = obj.get("name") or obj.get("headline") or ""
                # Authors can be list of dicts, dict, or string
                authors = obj.get("author")
                if isinstance(authors, dict):
                    authors = [authors.get("name", "")] if authors else []
                elif isinstance(authors, list):
                    authors = [a.get("name", "") if isinstance(a, dict) else str(a) for a in authors]
                elif isinstance(authors, str):
                    authors = [authors]
                else:
                    authors = []

                # Description may contain HTML; strip tags
                desc = obj.get("description", "")
                if desc:
                    desc = BS(desc, "lxml").text.strip()

                lang = (obj.get("inLanguage") or "").lower()
                image = obj.get("image") if isinstance(obj.get("image"), str) else obj.get("image", {}).get("url", "")

                publisher = obj.get("publisher", {})
                if isinstance(publisher, dict):
                    publisher = publisher.get("name", "")
                else:
                    publisher = str(publisher) if publisher else ""

                date_published = obj.get("datePublished", "")
                published = self._normalize_date(date_published)

                isbn = obj.get("isbn") or (obj.get("identifier") if isinstance(obj.get("identifier"), str) else None)
                if isbn:
                    isbn = self._validate_isbn(isbn)

                # Series info
                series_name = ""
                series_index = 0
                is_part_of = obj.get("isPartOf") or obj.get("partOfSeries") or obj.get("series")
                if isinstance(is_part_of, dict):
                    series_name = is_part_of.get("name", "")
                    series_index = self._parse_series_index(obj.get("position") or is_part_of.get("position"))
                elif isinstance(is_part_of, list) and is_part_of:
                    first = is_part_of[0]
                    if isinstance(first, dict):
                        series_name = first.get("name", "")
                        series_index = self._parse_series_index(first.get("position"))

                # rating ignored

                out = {
                    "title": title,
                    "authors": [a for a in authors if a],
                    "description": desc,
                    "language": lang,
                    "image": image,
                    "publisher": publisher,
                    "publishedDate": published,
                    "series": series_name,
                    "series_index": series_index,
                }
                # Only accept if it looks like a book
                if out["title"] or out["authors"]:
                    return out
                return None

            # The JSON-LD may be an array, an object, or an object with @graph
            candidates: List[Dict[str, Any]] = []
            if isinstance(j, list):
                for item in j:
                    ext = extract_from(item)
                    if ext:
                        candidates.append(ext)
            elif isinstance(j, dict):
                # If this is a @graph wrapper, iterate its items
                if isinstance(j.get("@graph"), list):
                    for item in j["@graph"]:
                        ext = extract_from(item)
                        if ext:
                            candidates.append(ext)
                else:
                    ext = extract_from(j)
                    if ext:
                        candidates.append(ext)

            # Prefer the first valid candidate
            if candidates:
                return candidates[0]
        return {}

    def _parse_meta_fallbacks(self, soup: BS) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        # Basic OpenGraph fallbacks
        og_title = soup.find("meta", property="og:title")
        if isinstance(og_title, Tag):
            content = og_title.get("content")
            if isinstance(content, str):
                data["title"] = content.strip()
        og_image = soup.find("meta", property="og:image")
        if isinstance(og_image, Tag):
            content = og_image.get("content")
            if isinstance(content, str):
                data["image"] = content.strip()
        # Kobo pages often include description in meta name="description"
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if isinstance(meta_desc, Tag):
            content = meta_desc.get("content")
            if isinstance(content, str):
                data["description"] = content.strip()

        # Attempt to extract authors from visible page nodes as a heuristic
        authors = self._parse_authors_from_dom(soup)
        if authors:
            data["authors"] = authors

        # Extract series details from DOM
        series_name, series_index = self._parse_series_from_dom(soup)
        if series_name:
            data["series"] = series_name
        if series_index:
            data["series_index"] = series_index

        # Language is typically implied by path; leave blank here
        data.setdefault("language", "")
        data.setdefault("publisher", "")
        data.setdefault("publishedDate", "")
        data.setdefault("series", "")
        data.setdefault("series_index", 0)
        return data

    def _parse_authors_from_dom(self, soup: BS) -> List[str]:
        authors: List[str] = []
        # Common Kobo patterns for authors
        for sel in self.AUTHOR_SELECTORS:
            for n in soup.select(sel):
                if not isinstance(n, Tag):
                    continue
                t = n.get_text(strip=True)
                if t and t not in authors:
                    authors.append(t)
        return authors

    def _parse_publisher_from_dom(self, soup: BS) -> str:
        """Extract publisher/imprint from visible DOM on the detail page.
        Prefers an explicit Publisher dt/dd row, then falls back to the eBook Details list.
        """
        try:
            # 1) Look for dt/dd rows with 'publisher'
            for dt in soup.select("dt"):
                if not isinstance(dt, Tag):
                    continue
                label = (dt.get_text(" ", strip=True) or "").lower()
                if "publisher" in label:
                    dd = dt.find_next_sibling("dd")
                    if isinstance(dd, Tag):
                        val = dd.get_text(" ", strip=True)
                        if val:
                            return val

            # 2) Fallback to eBook Details list
            # Try explicit 'Imprint:' first and use its value as publisher if found
            for li in soup.select(".bookitem-secondary-metadata ul li, ul li"):
                if not isinstance(li, Tag):
                    continue
                raw = li.get_text(" ", strip=True) or ""
                low = raw.lower()
                if low.startswith("imprint:"):
                    # Prefer anchor or span content
                    el = li.find("a") or li.find("span")
                    txt = (el.get_text(" ", strip=True) if isinstance(el, Tag) else raw.split(":", 1)[-1]).strip()
                    if txt:
                        return txt

            # 3) If no label present, the first list item is often the publisher name
            # Skip known labeled rows: release date, imprint, book id, language, download options
            for li in soup.select(".bookitem-secondary-metadata ul li"):
                if not isinstance(li, Tag):
                    continue
                raw = (li.get_text(" ", strip=True) or "").strip()
                low = raw.lower()
                if not raw:
                    continue
                if any(x in low for x in ("release date", "imprint:", "book id:", "language:", "download options")):
                    continue
                # Likely the publisher name
                return raw
        except Exception:
            pass
        return ""

    def _parse_series_from_dom(self, soup: BS) -> Tuple[str, int]:
        # Parse the series name and index from dt/dd pairs
        # Example (from search page):
        #   <dt data-testid="series-product-type-and-number">Book 3 -</dt>
        #   <dd data-testid="series-product-type-and-number"> <a>Secret Projects</a>
        series_name = ""
        series_idx = 0  # type: Union[int, float]
        try:
            # Try to limit parsing to the main product container that includes the title
            scope = self._find_series_scope(soup) or soup

            # 1) Strict pairing: dd (with series link) + preceding dt with same data-testid
            title_el = soup.select_one("[data-testid='title'], h1[data-testid='title']")
            candidates: List[Tuple[int, str, Union[int, float]]] = []  # (distance_score, name, index)
            for dd in scope.select(f"dd[data-testid='{self.SERIES_DT_TESTID}']"):
                if not isinstance(dd, Tag):
                    continue
                if not dd.select_one(self.SERIES_LINK_SELECTOR):
                    continue
                dt = dd.find_previous_sibling("dt")
                if not isinstance(dt, Tag):
                    continue
                if dt.get("data-testid") != dd.get("data-testid"):
                    continue
                dt_text = dt.get_text(" ", strip=True)
                # Ignore audiobook rows; prefer only real Book entries
                if not self.BOOK_DT_PREFIX_RE.search(dt_text):
                    continue
                idx = self._parse_series_index(dt_text)
                name_el = dd.select_one("a .link--label") or dd.select_one("a") or dd.select_one(".link--label")
                name_text = name_el.get_text(strip=True) if isinstance(name_el, Tag) else dd.get_text(" ", strip=True)
                if not name_text and not idx:
                    continue
                # Compute a proximity score to the title container to avoid picking from widgets
                dist = 0
                if isinstance(title_el, Tag):
                    dist = 1000
                    for i, anc in enumerate(dd.parents):
                        if not isinstance(anc, Tag):
                            continue
                        try:
                            if isinstance(title_el, Tag) and title_el in getattr(anc, "descendants", []):
                                dist = i
                                break
                        except Exception:
                            pass
                try:
                    val = int(idx) if isinstance(idx, float) and idx.is_integer() else idx
                except Exception:
                    val = idx
                candidates.append((dist, name_text or "", val))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                _, series_name, series_idx = candidates[0]
                if series_name and series_idx:
                    return series_name, int(series_idx)

            # 2) Fallback: any anchor to a series page, try to find an adjacent dt
            for a in scope.select(self.SERIES_LINK_SELECTOR):
                if not isinstance(a, Tag):
                    continue
                # Prefer within same dl block: dd -> dt
                dd = a.find_parent("dd")
                dt = dd.find_previous_sibling("dt") if isinstance(dd, Tag) else None
                idx = 0
                if isinstance(dt, Tag) and dt.get("data-testid") == (dd.get("data-testid") if isinstance(dd, Tag) else None):
                    dt_text = dt.get_text(" ", strip=True)
                    if self.BOOK_DT_PREFIX_RE.search(dt_text):
                        idx = self._parse_series_index(dt_text)
                name_text = a.get_text(strip=True)
                if name_text and not series_name:
                    series_name = name_text
                if idx:
                    series_idx = idx
                if series_name and series_idx:
                    return series_name, int(series_idx)

            # 3) Name-only fallback within scope
            if not series_name:
                a = scope.select_one(f"{self.SERIES_LINK_SELECTOR} .link--label, {self.SERIES_LINK_SELECTOR}")
                if isinstance(a, Tag):
                    series_name = a.get_text(strip=True)
        except Exception:
            pass
        return series_name, int(series_idx)

    def _parse_title_from_dom(self, soup: BS) -> str:
        el = soup.select_one("li.title")
        if isinstance(el, Tag):
            t = el.get_text(" ", strip=True)
            if t:
                return t
        for sel in self.TITLE_SELECTORS:
            el = soup.select_one(sel)
            if isinstance(el, Tag):
                t = el.get_text(" ", strip=True)
                if t:
                    return t
        return ""

    def _clean_description(self, text: str) -> str:
        """Clean and sanitize description text."""
        if not text:
            return ""
        
        t = str(text).strip()
        if not t:
            return ""
            
        # Remove any HTML tags that might remain
        try:
            # Use BeautifulSoup to properly strip HTML
            clean_soup = BS(t, "lxml")
            t = clean_soup.get_text(" ", strip=True)
        except Exception:
            # Fallback: simple HTML tag removal
            t = re.sub(r"<[^>]+>", " ", t)
        
        # Normalize various types of whitespace
        t = t.replace("\u00a0", " ")  # Non-breaking space
        t = t.replace("\u2009", " ")  # Thin space
        t = t.replace("\u200b", "")   # Zero-width space
        t = re.sub(r"\s+", " ", t).strip()
        
        # Unescape common escaped characters
        t = re.sub(r"\\([#@%&*~`])", r"\1", t)
        
        # Remove excessive newlines but preserve paragraph breaks
        t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
        
        # Limit length to prevent extremely long descriptions
        max_length = 5000
        if len(t) > max_length:
            t = t[:max_length].rsplit(" ", 1)[0] + "..."
            
        return t

    def _parse_description_from_dom(self, soup: BS) -> str:
        # Collect candidate description texts from likely containers and pick the longest
        selectors = [
            "[data-full-synopsis]",
            "[data-testid='synopsis']",
            "[data-testid='description']",
            "[data-automation='synopsis']",
            "[data-automation='book-description']",
            "[itemprop='description']",
            ".text-synopsis",
        ]
        texts: List[str] = []
        for sel in selectors:
            for el in soup.select(sel):
                if not isinstance(el, Tag):
                    continue
                t = self._clean_description(el.get_text(" ", strip=True))
                if t and t not in texts:
                    texts.append(t)

        # Heuristic: look for a heading that says "Synopsis" and use nearby content
        if not texts:
            try:
                hdr = None
                for tag in soup.find_all(["h2", "h3", "h4"]):
                    if not isinstance(tag, Tag):
                        continue
                    if "synopsis" in (tag.get_text(" ", strip=True) or "").lower():
                        hdr = tag
                        break
                if isinstance(hdr, Tag):
                    container = hdr.find_next_sibling()
                    limit = 0
                    while isinstance(container, Tag) and limit < 5:
                        t = self._clean_description(container.get_text(" ", strip=True))
                        if t:
                            texts.append(t)
                            break
                        container = container.find_next_sibling()
                        limit += 1
            except Exception:
                pass

        return max(texts, key=len) if texts else ""

    def _parse_published_from_dom(self, soup: BS) -> str:
        """Extract a published/release date from visible detail labels on the page."""
        try:
            # Common detail layout with dt/dd pairs
            for dt in soup.select("dt"):
                if not isinstance(dt, Tag):
                    continue
                label = (dt.get_text(" ", strip=True) or "").lower()
                if any(x in label for x in ("release date", "publication date", "published", "release")):
                    dd = dt.find_next_sibling("dd")
                    if isinstance(dd, Tag):
                        val = dd.get_text(" ", strip=True)
                        if val:
                            norm = self._normalize_date(val)
                            if norm:
                                return norm

            # Kobo detail page often uses a simple list under "eBook Details"
            # Example: <li>Release Date: <span>September 9, 2025</span></li>
            for li in soup.select(".bookitem-secondary-metadata ul li, ul li"):
                if not isinstance(li, Tag):
                    continue
                text = (li.get_text(" ", strip=True) or "").lower()
                if not any(x in text for x in ("release date", "publication date", "published")):
                    continue
                # Prefer explicit span content if present
                span = li.find("span")
                val = ""
                if isinstance(span, Tag):
                    val = span.get_text(" ", strip=True) or ""
                if not val:
                    # Fallback: remove label part before ':'
                    raw = li.get_text(" ", strip=True) or ""
                    parts = raw.split(":", 1)
                    val = parts[1].strip() if len(parts) == 2 else raw
                if val:
                    norm = self._normalize_date(val)
                    if norm:
                        return norm
        except Exception:
            pass
        return ""

    def _parse_hidden_full_synopsis(self, soup: BS) -> str:
        # Specifically extract hidden full synopsis blocks often rendered as display:none
        texts: List[str] = []
        for el in soup.select("[data-full-synopsis]"):
            if not isinstance(el, Tag):
                continue
            # Prefer inner HTML cleaned to preserve intended breaks
            try:
                raw = el.decode_contents() or ""
                if raw:
                    clean = BS(raw, "lxml").text.strip()
                else:
                    clean = el.get_text(" ", strip=True)
            except Exception:
                clean = el.get_text(" ", strip=True)
            clean = self._clean_description(clean)
            if clean:
                texts.append(clean)
        return max(texts, key=len) if texts else ""

    def _parse_description_from_embedded_json(self, soup: BS, next_data: Optional[Dict[str, Any]] = None) -> str:
        # Find the longest plausible description/synopsis in embedded JSON
        best = ""
        keys = ("longdescription", "longsynopsis", "synopsis", "description", "fulldescription", "fullsynopsis")

        def consider(val: Any):
            nonlocal best
            try:
                if isinstance(val, str):
                    s = BS(val, "lxml").text.strip()  # strip HTML
                    s = self._clean_description(s)
                    if len(s) > len(best):
                        best = s
            except Exception:
                pass

        def walk(obj: Any):
            try:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        lk = str(k).lower()
                        if any(kk in lk for kk in keys):
                            consider(v)
                        walk(v)
                elif isinstance(obj, list):
                    for it in obj:
                        walk(it)
            except Exception:
                pass

        # Prefer provided NEXT_DATA JSON to avoid rescanning scripts
        if isinstance(next_data, dict):
            walk(next_data)
        if best:
            return best
        
        for s in soup.find_all("script"):
            if not isinstance(s, Tag):
                continue
            t = (s.get_text() or "").strip()
            if not t:
                continue
            typ = str(s.get("type", "")).lower()
            sid = str(s.get("id", ""))
            if typ == "application/json" or sid == "__NEXT_DATA__" or "description" in t.lower() or "synopsis" in t.lower():
                try:
                    j = json.loads(t)
                    walk(j)
                except Exception:
                    # Attempt to regex match a known description field as a fallback
                    try:
                        m = re.search(r'"(?:long)?(?:synopsis|description)"\s*:\s*"(.*?)"', t, flags=re.I|re.S)
                        if m:
                            candidate = m.group(1)
                            candidate = candidate.encode('utf-8', 'ignore').decode('unicode_escape')
                            candidate = candidate.replace('\\n', ' ').replace('\\t', ' ').strip()
                            candidate = self._clean_description(candidate)
                            if len(candidate) > len(best):
                                best = candidate
                    except Exception:
                        pass
        return best

    def _parse_next_data_detail(self, soup: BS, url: str, next_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract book metadata from Next.js __NEXT_DATA__ on the detail page.
        This prefers structured values from Kobo's app state over HTML/LD-JSON.
        """
        out: Dict[str, Any] = {}
        slug_target = self._extract_kobo_id_from_url(url)

        def assign_if_empty(key: str, value: Any):
            if value is None:
                return
            if key not in out or not out[key]:
                out[key] = value

        def extract_from_book_obj(book: Dict[str, Any]):
            title = book.get("Title") or book.get("Name") or book.get("name")
            if isinstance(title, str):
                assign_if_empty("title", title.strip())

            # Authors
            authors: List[str] = []
            # Primary: ContributorRoles with Role == 'Author'
            roles = book.get("ContributorRoles")
            if isinstance(roles, list):
                for r in roles:
                    if isinstance(r, dict) and str(r.get("Role", "")).lower() == "author":
                        nm = r.get("Name")
                        if isinstance(nm, str) and nm and nm not in authors:
                            authors.append(nm)
            # Secondary: Contributors (string or list)
            if not authors:
                cons = book.get("Contributors")
                if isinstance(cons, str):
                    authors = [cons]
                elif isinstance(cons, list):
                    for c in cons:
                        if isinstance(c, str) and c and c not in authors:
                            authors.append(c)
                        elif isinstance(c, dict):
                            nm = c.get("Name") or c.get("name")
                            if isinstance(nm, str) and nm and nm not in authors:
                                authors.append(nm)
            if authors:
                assign_if_empty("authors", authors)

            # Description (prefer long forms)
            desc = book.get("LongDescription") or book.get("LongSynopsis") or book.get("Synopsis") or book.get("Description")
            if isinstance(desc, str) and desc:
                try:
                    clean = BS(desc, "lxml").text.strip()
                except Exception:
                    clean = desc.strip()
                assign_if_empty("description", self._clean_description(clean))

            # Language
            lang = book.get("Language")
            if isinstance(lang, str):
                assign_if_empty("language", lang.lower())
            loc = book.get("Locale")
            if isinstance(loc, dict):
                lc = loc.get("LanguageCode")
                if isinstance(lc, str) and lc:
                    assign_if_empty("language", lc.lower())

            # Series
            sname = book.get("SeriesName")
            if isinstance(sname, str) and sname.strip():
                assign_if_empty("series", sname.strip())
            snum = book.get("SeriesNumber") or book.get("SeriesNumberFloat")
            if snum is not None:
                idx = self._parse_series_index(snum)
                if idx:
                    assign_if_empty("series_index", idx)

            # Publisher
            pub = book.get("PublisherName") or book.get("Imprint")
            if isinstance(pub, str) and pub:
                assign_if_empty("publisher", pub)

            # Publication date (check several likely keys)
            for key in ("PublicationDate", "PublishedDate", "publishDate", "DatePublished", "ReleaseDate", "OnSaleDate"):
                pd = book.get(key)
                if isinstance(pd, str) and pd:
                    assign_if_empty("publishedDate", self._normalize_date(pd))
                    break

            # Image URL (if any full URL is present)
            img = book.get("ImageUrl") or book.get("Image")
            if isinstance(img, str) and img:
                assign_if_empty("image", img)

        try:
            j = next_data or self._get_next_data_json(soup)
            if not isinstance(j, dict):
                return out

            # First, look for explicit Book entries in search-like structures
            items = (
                j.get("props", {})
                .get("pageProps", {})
                .get("searchResultSSR", {})
                .get("Items", [])
            )
            # Choose the book with matching slug target if present
            best: Optional[Dict[str, Any]] = None
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    book = it.get("Book")
                    if isinstance(book, dict):
                        slug = book.get("Slug")
                        if isinstance(slug, str) and slug.lower() == slug_target.lower():
                            best = book
                            break
                        if best is None:
                            best = book
            if isinstance(best, dict):
                extract_from_book_obj(best)

            # If still missing, walk the entire JSON tree to find a book-like object
            if not out.get("title") or not out.get("series"):
                def walk(node: Any):
                    if isinstance(node, dict):
                        # Heuristic: looks like a book if has Title and either ISBN/PublisherName/Slug
                        if (
                            ("Title" in node or "title" in node)
                            and any(k in node for k in ("ISBN", "PublisherName", "Slug", "SeriesName"))
                        ):
                            extract_from_book_obj(node)
                        for v in node.values():
                            walk(v)
                    elif isinstance(node, list):
                        for v in node:
                            walk(v)
                walk(j)

        except Exception:
            return out

        return out

    def _get_next_data_json(self, soup: BS) -> Optional[Dict[str, Any]]:
        try:
            script = soup.find("script", id="__NEXT_DATA__", attrs={"type": "application/json"})
            if not isinstance(script, Tag):
                return None
            t = script.get_text() or ""
            if not t:
                return None
            return json.loads(t)
        except Exception:
            return None

    def _find_series_scope(self, soup: BS) -> Optional[Tag]:
        """Find a DOM scope near the main title to avoid picking series data from widgets."""
        try:
            title_el = soup.select_one("[data-testid='title'], h1[data-testid='title']")
            if not isinstance(title_el, Tag):
                return None
            for anc in title_el.parents:
                if not isinstance(anc, Tag):
                    continue
                if anc.find("dt", attrs={"data-testid": "series-product-type-and-number"}):
                    return anc
            return None
        except Exception:
            return None

    def _parse_series_index(self, value: Any) -> Union[int, float]:
        """Extract a numeric index from inputs like 3, '3', '3.5', 'Book 3 -', '#3'."""
        if value is None:
            return 0
        # Direct numeric
        if isinstance(value, (int, float)):
            try:
                f = float(value)
                if f < 0:  # Series index should be positive
                    return 0
                return int(f) if f.is_integer() else f
            except (ValueError, OverflowError):
                return 0
        
        s = str(value).strip()
        if not s:
            return 0
            
        # Look for first number with optional decimal
        m = re.search(r"(\d+(?:[\.,]\d+)?)", s)
        if not m:
            return 0
        num = m.group(1).replace(",", ".")
        try:
            f = float(num)
            if f < 0:  # Series index should be positive
                return 0
            return int(f) if f.is_integer() else f
        except (ValueError, OverflowError):
            return 0

    def _normalize_date(self, s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        # Strip time part if present (ISO 8601 like 2025-09-09T00:00:00Z)
        if "T" in s:
            s = s.split("T", 1)[0]
        s = s.rstrip("Zz")
        # Try common date formats (ISO first, then month-name formats)
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m",
            "%Y/%m",
            "%Y",
            "%B %d, %Y",   # e.g., September 9, 2025
            "%b %d, %Y",    # e.g., Sep 9, 2025
            "%B %Y",        # e.g., September 2025
            "%b %Y",        # e.g., Sep 2025
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if fmt == "%Y":
                    return dt.strftime("%Y")
                if fmt in ("%Y-%m", "%Y/%m"):
                    return dt.strftime("%Y-%m")
                if fmt in ("%B %Y", "%b %Y"):
                    return dt.strftime("%Y-%m")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Fallback: extract a 4-digit year if present
        m = re.search(r"(19|20)\d{2}(-\d{2}-\d{2})?", s)
        if m:
            val = m.group(0)
            # If only year captured, return year; else return YYYY-MM-DD
            return val if len(val) == 10 else val[:4]
        return ""

    def _extract_kobo_id_from_url(self, url: str) -> str:
        """Extract Kobo book ID from URL with validation."""
        if not url or not isinstance(url, str):
            return ""
        # Use slug after /ebook/ as an identifier surrogate
        m = re.search(r"/ebook/([^/?#]+)", url)
        return m.group(1) if m else ""

    def _normalize_cover_url(self, url: str, height: int = 1200, width: int = 1200, quality: int = 90) -> str:
        """Normalize Kobo cover URL with size parameters and validation."""
        if not url or not isinstance(url, str):
            return ""
        
        url = url.strip()
        if not url:
            return ""
        
        # Validate URL format
        if not (url.startswith("http://") or url.startswith("https://")):
            return ""
        
        # Validate parameters
        height = max(100, min(height, 2000))  # Reasonable bounds
        width = max(100, min(width, 2000))
        quality = max(10, min(quality, 100))
        
        try:
            # Replace dynamic sizing segments: /H/W/Q/(True|False)
            normalized = re.sub(r"/\d+/\d+/\d+/(True|False)", f"/{height}/{width}/{quality}/False", url)
            # Ensure HTTPS for security
            if normalized.startswith("http://"):
                normalized = normalized.replace("http://", "https://", 1)
            return normalized
        except Exception as e:
            log.debug("Failed to normalize cover URL %s: %s", url, e)
            return url

    def _load_cookie(self) -> Optional[str]:
        """Load and validate Kobo cookies from environment variables."""
        cookie = os.environ.get("CWA_KOBO_COOKIE") or os.environ.get("KOBO_COOKIE")
        if not cookie:
            return None
        
        cookie = cookie.strip()
        if not cookie:
            return None
        
        # Basic validation - should look like cookie format
        if not re.match(r'^[\w\-=;,\s.]+$', cookie):
            log.warning("Invalid cookie format detected, ignoring")
            return None
            
        return cookie

    def _apply_cookies(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Apply cookies to headers and session with proper error handling."""
        cookie_str = self._load_cookie()
        if not cookie_str:
            return headers
            
        new_headers = dict(headers)
        new_headers["Cookie"] = cookie_str
        
        # Try to parse and apply cookies to session
        try:
            sc = SimpleCookie()
            sc.load(cookie_str)
            session = self._get_session()
            
            for name, morsel in sc.items():
                if not name or not morsel.value:
                    continue
                try:
                    # Apply to common Kobo domains
                    for dom in ("www.kobo.com", ".kobo.com"):
                        try:
                            session.cookies.set(name, morsel.value, domain=dom, path="/")
                        except Exception as e:
                            log.debug("Failed to set cookie %s for domain %s: %s", name, dom, e)
                except Exception as e:
                    log.debug("Failed to process cookie %s: %s", name, e)
        except Exception as e:
            log.warning("Failed to parse cookies: %s", e)
            
        return new_headers
        
    def _validate_isbn(self, isbn: str) -> Optional[str]:
        """Validate and clean ISBN format."""
        if not isbn or not isinstance(isbn, str):
            return None
            
        # Clean ISBN: remove hyphens, spaces, and convert to uppercase
        clean_isbn = re.sub(r'[-\s]', '', isbn.strip().upper())
        
        # Check if it's ISBN-10 or ISBN-13
        if len(clean_isbn) == 10:
            # ISBN-10 validation
            if re.match(r'^\d{9}[\dX]$', clean_isbn):
                return clean_isbn
        elif len(clean_isbn) == 13:
            # ISBN-13 validation (should start with 978 or 979)
            if re.match(r'^(978|979)\d{10}$', clean_isbn):
                return clean_isbn
                
        return None
