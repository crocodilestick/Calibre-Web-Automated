# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import re
from os import getenv
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup as BS

from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from cps.services.bookshop_metadata import (
    BookshopSession, fetch_in_order, isbn13_to_isbn10, isbn_from_query, language_names, parse_french_date
)

log = logger.create()


class AmazonFr(Metadata):
    __name__ = "Amazon.fr"
    __id__ = "amazon_fr"
    DESCRIPTION = "Amazon.fr"
    META_URL = "https://www.amazon.fr/"
    BOOK_URL = "https://www.amazon.fr/dp/"
    SEARCH_URL = "https://www.amazon.fr/s"
    FALLBACK_SEARCH_URL = "https://www.placedeslibraires.fr/listeliv.php"
    GOOGLE_SEARCH_URL = "https://www.googleapis.com/books/v1/volumes"
    API_KEY_ENV = "GOOGLE_BOOKS_API_KEY"
    ASIN_LINK = r"/(?:dp|gp/product|gp/aw/d)/([0-9A-Z]{10})"
    SHORT_LINK = r"https?://(?:www\.)?(?:amzn\.(?:eu|to)|a\.co)/\S+"
    PAGE_END_MARKER = 'id="detailBullets_feature_div"'
    MAX_PAGE_SIZE = 1500000
    MAX_RESULTS = 4
    bookshop = BookshopSession()

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active or not query:
            return []
        self.bookshop.reset()
        asins = self._prepare_query(query)
        if not asins:
            log.info(f"No Amazon.fr results found for query: {query}")
            return []
        return fetch_in_order(lambda asin: self._parse_book(asin, generic_cover, locale), asins, AmazonFr.MAX_RESULTS)

    def _prepare_query(self, query: str) -> List[str]:
        asin = self._asin_from_link(query) or self._asin_from_link(self._resolve_short_link(query))
        if asin:
            return [asin]
        isbn = isbn_from_query(query)
        if isbn and isbn13_to_isbn10(isbn):
            return [isbn13_to_isbn10(isbn)]
        if isbn:
            query = self._title_from_isbn(isbn)
            if not query:
                return []
        return self.search_asins(query) or self.search_fallback_asins(query)

    @staticmethod
    def _asin_from_link(query: str) -> Optional[str]:
        match = re.search(AmazonFr.ASIN_LINK, query) or re.fullmatch(r"\s*(B0[0-9A-Z]{8})\s*", query.upper())
        return match.group(1) if match else None

    def _resolve_short_link(self, query: str) -> str:
        match = re.search(AmazonFr.SHORT_LINK, query)
        if not match:
            return ""
        try:
            with self.bookshop.session.get(match.group(0), allow_redirects=False, timeout=8, stream=True) as r:
                return r.headers.get("Location", "")
        except Exception as e:
            log.warning(e)
            return ""

    def _title_from_isbn(self, isbn: str) -> str:
        api_key = getenv(AmazonFr.API_KEY_ENV)
        if not api_key:
            return ""
        try:
            response = self.bookshop.session.get(
                AmazonFr.GOOGLE_SEARCH_URL, params={"q": f"isbn:{isbn}", "key": api_key}, timeout=8
            )
            response.raise_for_status()
            info = (response.json().get("items") or [{}])[0].get("volumeInfo", {})
        except Exception as e:
            log.warning("Google Books lookup failed: %s", type(e).__name__)
            return ""
        return " ".join([info.get("title", "")] + (info.get("authors") or [])[:1]).strip()

    def search_asins(self, query: str) -> List[str]:
        response = self.bookshop.get_search(AmazonFr.SEARCH_URL, params={"k": query, "i": "stripbooks"})
        if response is None or response.status_code != 200 or response.headers.get("x-amzn-waf-action"):
            return []
        return list(dict.fromkeys(re.findall(r'data-asin="([0-9A-Z]{10})"', response.text)))

    def search_fallback_asins(self, query: str) -> List[str]:
        response = self.bookshop.get_search(
            AmazonFr.FALLBACK_SEARCH_URL, params={"base": "allbooks", "mots_recherche": query}
        )
        if response is None:
            return []
        asins = [isbn13_to_isbn10(isbn) for isbn in re.findall(r"/livre/(97[89]\d{10})-", response.text)]
        return list(dict.fromkeys(asin for asin in asins if asin))

    def _parse_book(self, asin: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        page = self._fetch_product_page(AmazonFr.BOOK_URL + asin)
        if not page:
            return None
        try:
            soup = BS(page, "lxml")
        except Exception:
            soup = BS(page, "html.parser")
        if soup.find(id="dp-container") is None:
            return None
        return AmazonFrParser(soup, self).parse(asin, generic_cover, locale)

    def _fetch_product_page(self, url: str) -> str:
        page, end = "", -1
        try:
            with self.bookshop.session.get(url, timeout=BookshopSession.PAGE_TIMEOUT, stream=True) as r:
                if r.status_code == 404:
                    return ""
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                for chunk in r.iter_content(chunk_size=65536, decode_unicode=True):
                    page += chunk
                    if end < 0 and AmazonFr.PAGE_END_MARKER in page:
                        end = len(page) + 65536
                    if 0 <= end <= len(page) or len(page) > AmazonFr.MAX_PAGE_SIZE:
                        break
        except Exception as e:
            log.warning(e)
            return ""
        start = page.find('id="dp-container"')
        return page[page.rfind("<", 0, start):] if start > 0 else ""


class AmazonFrParser:
    LANGUAGES = {
        "français": "fre", "anglais": "eng", "allemand": "ger", "espagnol": "spa",
        "italien": "ita", "néerlandais": "dut", "portugais": "por", "japonais": "jpn",
    }

    def __init__(self, soup: BS, metadata: AmazonFr):
        self.soup = soup
        self.metadata = metadata

    def parse(self, asin: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        title = self._parse_title()
        if not title:
            return None
        details = self._parse_details()
        match = MetaRecord(
            id=asin,
            title=title,
            authors=self._parse_authors(),
            url=AmazonFr.BOOK_URL + asin,
            source=MetaSourceInfo(id=self.metadata.__id__, description=AmazonFr.DESCRIPTION, link=AmazonFr.META_URL),
        )
        match.cover = self._parse_cover() or generic_cover
        match.description = self._parse_description()
        match.publisher = details.get("éditeur", "").split(";")[0].split("(")[0].strip()
        match.publishedDate = parse_french_date(details.get("date de publication", "") or details.get("éditeur", ""))
        match.identifiers = {"amazon_fr": asin}
        isbn = re.sub(r"\D", "", details.get("isbn-13", ""))
        if isbn:
            match.identifiers["isbn"] = isbn
        language = AmazonFrParser.LANGUAGES.get(details.get("langue", "").lower())
        match.languages = language_names([language], locale) if language else []
        match.rating = self._parse_rating()
        match.series, match.series_index = self._parse_series(title)
        return match

    def _parse_title(self) -> str:
        element = self.soup.find(id="productTitle")
        if element is None:
            return ""
        return re.sub(r"\s*\(\d+\)$", "", element.get_text(strip=True))

    def _parse_details(self) -> Dict[str, str]:
        details = dict()
        for item in self.soup.select("#detailBullets_feature_div li"):
            spans = item.select("span.a-list-item > span")
            if len(spans) >= 2:
                key = re.sub(r"[\u200e\u200f:\s]+", " ", spans[0].get_text()).strip().lower()
                details[key] = re.sub(r"[\u200e\u200f]", "", spans[1].get_text()).strip()
        for element in self.soup.select("[id^=rpi-attribute-book_details-]"):
            value = element.select_one(".rpi-attribute-value")
            if value:
                details.setdefault("rpi-" + element["id"].replace("rpi-attribute-book_details-", ""),
                                   value.get_text(" ", strip=True))
        details.setdefault("éditeur", details.get("rpi-publisher", ""))
        details.setdefault("date de publication", details.get("rpi-publication_date", ""))
        details.setdefault("isbn-13", details.get("rpi-isbn13", ""))
        return details

    def _parse_authors(self) -> List[str]:
        authors, contributors = list(), list()
        for element in self.soup.select("#bylineInfo .author"):
            name = element.find("a")
            name = name.get_text(strip=True) if name else ""
            role = element.select_one(".contribution")
            role = role.get_text(strip=True).lower() if role else ""
            if name:
                (authors if not role or "auteur" in role or "author" in role else contributors).append(name)
        return authors or contributors

    def _parse_description(self) -> str:
        element = self.soup.find(attrs={"data-feature-name": "bookDescription"})
        if element is None:
            return ""
        content = element.select_one(".a-expander-content") or element
        return "<div>" + "".join(str(node) for node in content.children) + "</div>"

    def _parse_cover(self) -> str:
        match = re.search(r'"hiRes":"(https://[^"]+)"', str(self.soup))
        if match:
            return match.group(1)
        image = self.soup.find(id="landingImage") or self.soup.find(id="imgBlkFront")
        return (image.get("data-old-hires") or image.get("src") or "") if image else ""

    def _parse_rating(self) -> int:
        try:
            return int(float(self.soup.find(id="acrPopover")["title"].split(" ")[0].replace(",", ".")) + 0.5)
        except (AttributeError, TypeError, ValueError, KeyError):
            return 0

    def _parse_series(self, title: str) -> Tuple[Optional[str], float]:
        series, index = None, None
        element = self.soup.select_one("#rpi-attribute-book_details-series")
        if element:
            value = element.select_one(".rpi-attribute-value")
            series = value.get_text(" ", strip=True) if value else None
            number = re.search(r"(?:Livre|Tome)\s+(\d+(?:[.,]\d+)?)\s+sur", element.get_text(" ", strip=True))
            if number:
                index = float(number.group(1).replace(",", "."))
        number = re.search(
            r"^(.*?)\s*[-–:,(]?\s*\b(?:tome|t\.|volume|vol\.)\s*(\d+(?:[.,]\d+)?)\b", title, re.IGNORECASE
        )
        if number:
            series = series or number.group(1).strip(" -–:,(") or None
            index = index if index is not None else float(number.group(2).replace(",", "."))
        if not series:
            return None, 0
        return series, index if index is not None else 1
