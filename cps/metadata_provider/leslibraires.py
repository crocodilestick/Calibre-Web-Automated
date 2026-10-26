# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import re
from typing import List, Optional

from bs4 import BeautifulSoup as BS

from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from cps.services.bookshop_metadata import (
    BookshopSession, fetch_in_order, isbn_from_query, language_names, parse_french_date
)

log = logger.create()


class LesLibraires(Metadata):
    __name__ = "Leslibraires.fr"
    __id__ = "leslibraires"
    DESCRIPTION = "Leslibraires.fr"
    META_URL = "https://www.leslibraires.fr/"
    BASE_URL = "https://www.leslibraires.fr"
    SEARCH_URL = "https://www.leslibraires.fr/recherche/"
    BOOK_LINK = r'href="(/livre/\d+-[^"]+)"'
    COVER_HOST = "b-cdn.net"
    MAX_RESULTS = 5
    bookshop = BookshopSession()

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active or not query:
            return []
        self.bookshop.reset()
        isbn = isbn_from_query(query)
        links = [f"/livre/{isbn}"] if isbn else self.search_links(query)
        if not links:
            log.info(f"No Leslibraires.fr results found for query: {query}")
            return []
        return fetch_in_order(
            lambda link: self._parse_book(link, generic_cover, locale), links, LesLibraires.MAX_RESULTS
        )

    def search_links(self, query: str) -> List[str]:
        response = self.bookshop.get_search(LesLibraires.SEARCH_URL, params={"q": query})
        if response is None:
            return []
        return list(dict.fromkeys(re.findall(LesLibraires.BOOK_LINK, response.text)))

    def _parse_book(self, link: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        response = self.bookshop.get_page(LesLibraires.BASE_URL + link)
        if response is None:
            return None
        try:
            soup = BS(response.text, "lxml")
        except Exception:
            soup = BS(response.text, "html.parser")
        return LesLibrairesParser(soup, self).parse(response.url, generic_cover, locale)


class LesLibrairesParser:
    def __init__(self, soup: BS, metadata: LesLibraires):
        self.soup = soup
        self.metadata = metadata

    def parse(self, url: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        title = self._parse_property("name")
        if not title:
            return None
        series, series_index, title = self._parse_series(title)
        isbn = re.sub(r"\D", "", self._parse_property("isbn")) or self._parse_property("gtin13")
        match = MetaRecord(
            id=isbn,
            title=title,
            authors=self._parse_authors(),
            url=url,
            source=MetaSourceInfo(
                id=self.metadata.__id__,
                description=LesLibraires.DESCRIPTION,
                link=LesLibraires.META_URL,
            ),
        )
        description = self.soup.find(attrs={"itemprop": "description"})
        match.description = str(description) if description else ""
        match.cover = self._parse_cover() or generic_cover
        match.publisher = self._parse_property("publisher")
        match.publishedDate = parse_french_date(self._parse_property("datePublished"))
        match.identifiers = {"isbn": isbn} if isbn else {}
        match.languages = language_names([self._parse_property("inLanguage")], locale)
        match.series, match.series_index = series, series_index
        return match

    def _parse_property(self, name: str) -> str:
        element = self.soup.find(attrs={"itemprop": name})
        if element is None:
            return ""
        return (element.get("content") or element.get_text(" ", strip=True)).strip()

    def _parse_authors(self) -> List[str]:
        authors = list()
        for element in self.soup.find_all(attrs={"itemprop": "author"}):
            name = (element.get("content") or element.get_text(" ", strip=True)).strip()
            if name and name not in authors:
                authors.append(name)
        return authors

    def _parse_series(self, title: str):
        heading = self.soup.find(attrs={"itemprop": "name"})
        series_link = heading.find("a") if heading else None
        if not series_link:
            return None, 0, title
        series = series_link.get_text(" ", strip=True)
        rest = heading.get_text(" ", strip=True)[len(series):]
        match = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*-\s*(.+)", rest)
        if not match:
            return None, 0, title
        return series, float(match.group(1).replace(",", ".")), match.group(2).strip()

    def _parse_cover(self) -> str:
        for image in self.soup.find_all("img"):
            src = image.get("src") or image.get("data-src") or ""
            if LesLibraires.COVER_HOST in src:
                return "https:" + src if src.startswith("//") else src
        return ""
