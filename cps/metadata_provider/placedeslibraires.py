# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import re
from typing import List, Optional

from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from cps.services.bookshop_metadata import (
    BookshopSession, SchemaOrgBook, fetch_in_order, isbn_from_query, language_names
)

log = logger.create()


class PlaceDesLibraires(Metadata):
    __name__ = "Place des Libraires"
    __id__ = "placedeslibraires"
    DESCRIPTION = "Place des Libraires"
    META_URL = "https://www.placedeslibraires.fr/"
    BASE_URL = "https://www.placedeslibraires.fr"
    SEARCH_URL = "https://www.placedeslibraires.fr/listeliv.php"
    BOOK_LINK = r'href="(?:https://www\.placedeslibraires\.fr)?(/livre/97[89]\d{10}-[^"]*)"'
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
            log.info(f"No Place des Libraires results found for query: {query}")
            return []
        return fetch_in_order(
            lambda link: self._parse_book(link, generic_cover, locale), links, PlaceDesLibraires.MAX_RESULTS
        )

    def search_links(self, query: str) -> List[str]:
        response = self.bookshop.get_search(
            PlaceDesLibraires.SEARCH_URL, params={"base": "allbooks", "mots_recherche": query}
        )
        if response is None:
            return []
        return list(dict.fromkeys(re.findall(PlaceDesLibraires.BOOK_LINK, response.text)))

    def _parse_book(self, link: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        response = self.bookshop.get_page(PlaceDesLibraires.BASE_URL + link)
        book = SchemaOrgBook.from_html(response.text) if response is not None else None
        if book is None:
            return None
        match = book.to_record(
            MetaSourceInfo(
                id=self.__id__,
                description=PlaceDesLibraires.DESCRIPTION,
                link=PlaceDesLibraires.META_URL,
            ),
            response.url,
            generic_cover,
            locale,
        )
        match.cover = re.sub(r"_1_75\.jpg$", "_1_m.jpg", match.cover)
        match.languages = match.languages or language_names(["fre"], locale)
        match.publisher = match.publisher or book.data.get("Publisher", "") or (book.data.get("brand") or {}).get("name", "")
        return match
