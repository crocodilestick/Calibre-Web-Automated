# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import concurrent.futures
import json
import re
from typing import Callable, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo

log = logger.create()

FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}
BIBLIOGRAPHIC_LANGUAGES = {"fre": "fra", "ger": "deu", "dut": "nld"}


def isbn_from_query(query: str) -> Optional[str]:
    query = re.sub(r"^isbn:\s*", "", query.strip(), flags=re.IGNORECASE)
    digits = re.sub(r"[\s-]", "", query)
    if re.fullmatch(r"97[89]\d{10}|\d{9}[\dXx]", digits):
        return digits.upper()
    return None


def isbn13_to_isbn10(isbn: str) -> Optional[str]:
    if len(isbn) == 10:
        return isbn
    if not isbn.startswith("978"):
        return None
    core = isbn[3:12]
    check = (11 - sum((10 - i) * int(d) for i, d in enumerate(core)) % 11) % 11
    return core + ("X" if check == 10 else str(check))


def parse_french_date(text: str) -> str:
    text = (text or "").strip().lower()
    match = re.search(r"(\d{1,2})(?:er)?\s+([a-zéû]+)\s+(\d{4})", text)
    if match and match.group(2) in FRENCH_MONTHS:
        return f"{match.group(3)}-{FRENCH_MONTHS[match.group(2)]:02d}-{int(match.group(1)):02d}"
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    match = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", text)
    return f"{match.group(1)}-01-01" if match else ""


def language_names(codes: List[str], locale: str) -> List[str]:
    names = list()
    for code in codes:
        code = (code or "").strip().lower()
        code = BIBLIOGRAPHIC_LANGUAGES.get(code, get_lang3(code) if len(code) == 2 else code)
        name = get_language_name(locale, code) if code else ""
        if name and name != "Unknown" and name not in names:
            names.append(name)
    return names


class BookshopSession:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    SEARCH_TIMEOUT = 5
    PAGE_TIMEOUT = 6

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or BookshopSession.HEADERS)
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=0)))

    def reset(self):
        self.session.close()

    def get(self, url: str, timeout: int, **kwargs) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response
        except Exception as e:
            log.warning(e)
            return None

    def get_search(self, url: str, **kwargs) -> Optional[requests.Response]:
        return self.get(url, BookshopSession.SEARCH_TIMEOUT, **kwargs)

    def get_page(self, url: str, **kwargs) -> Optional[requests.Response]:
        return self.get(url, BookshopSession.PAGE_TIMEOUT, **kwargs)


def fetch_in_order(
    parse: Callable[[str], Optional[MetaRecord]], links: List[str], max_results: int, timeout: int = 15
) -> List[MetaRecord]:
    val = list()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_results) as executor:
        fut = {executor.submit(parse, link): index for index, link in enumerate(links[:max_results])}
        try:
            for future in concurrent.futures.as_completed(fut, timeout=timeout):
                match = future.result()
                if match:
                    val.append((fut[future], match))
        except concurrent.futures.TimeoutError:
            log.warning("Bookshop search timeout after %s seconds", timeout)
    return [match for _, match in sorted(val, key=lambda x: x[0])]


class SchemaOrgBook:
    def __init__(self, data: Dict):
        self.data = data

    @classmethod
    def from_html(cls, page: str) -> Optional["SchemaOrgBook"]:
        for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict):
                    continue
                types = item.get("@type")
                if "Book" in (types if isinstance(types, list) else [types]) and item.get("name"):
                    return cls(item)
        return None

    @staticmethod
    def _names(value) -> List[str]:
        names = list()
        for item in value if isinstance(value, list) else [value]:
            name = item.get("name", "") if isinstance(item, dict) else str(item or "")
            if name.strip() and name.strip() not in names:
                names.append(name.strip())
        return names

    def to_record(self, source: MetaSourceInfo, url: str, generic_cover: str, locale: str) -> MetaRecord:
        isbn = str(self.data.get("isbn") or "")
        match = MetaRecord(
            id=isbn,
            title=self.data["name"].strip(),
            authors=self._names(self.data.get("author") or []),
            url=self.data.get("url") or url,
            source=source,
        )
        image = self.data.get("image")
        image = image[0] if isinstance(image, list) and image else image
        match.cover = (image.get("url") if isinstance(image, dict) else image) or generic_cover
        match.description = self.data.get("description", "")
        match.publisher = (self._names(self.data.get("publisher") or []) or [""])[0]
        match.publishedDate = parse_french_date(str(self.data.get("datePublished") or ""))
        match.identifiers = {"isbn": isbn} if isbn else {}
        try:
            match.rating = int(round(float((self.data.get("aggregateRating") or {}).get("ratingValue") or 0)))
        except (TypeError, ValueError):
            match.rating = 0
        languages = self.data.get("inLanguage") or []
        match.languages = language_names(languages if isinstance(languages, list) else [languages], locale)
        genres = self.data.get("genre") or []
        match.tags = [g for g in (genres if isinstance(genres, list) else [genres]) if "langue" not in g.lower()]
        match.series, match.series_index = SchemaOrgBook.parse_series(match.title)
        return match

    @staticmethod
    def parse_series(title: str):
        match = re.search(
            r"^(.*?)\s*[-–:,(]?\s*\b(?:tome|t\.|volume|vol\.)\s*(\d+(?:[.,]\d+)?)\b", title, re.IGNORECASE
        )
        if not match or not match.group(1).strip(" -–:,("):
            return None, 0
        return match.group(1).strip(" -–:,("), float(match.group(2).replace(",", "."))
