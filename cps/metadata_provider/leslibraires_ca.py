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
from cps.services.bookshop_metadata import BookshopSession, SchemaOrgBook, fetch_in_order, isbn_from_query

log = logger.create()


class LesLibrairesCa(Metadata):
    __name__ = "Leslibraires.ca"
    __id__ = "leslibraires_ca"
    DESCRIPTION = "Leslibraires.ca"
    META_URL = "https://www.leslibraires.ca/"
    BOOK_URL = "https://www.leslibraires.ca/livres/"
    SEARCH_URL = "https://app.leslibraires.ca/api/v1/books"
    COVER_URLS = (
        "https://images.epagine.fr/{suffix}/{isbn}_1_m.jpg",
        "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false",
    )
    MIN_COVER_SIZE = 4000
    MAX_RESULTS = 5
    bookshop = BookshopSession()

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active or not query:
            return []
        self.bookshop.reset()
        isbn = isbn_from_query(query)
        isbns = [isbn] if isbn and len(isbn) == 13 else self.search_isbns(query)
        if not isbns:
            log.info(f"No Leslibraires.ca results found for query: {query}")
            return []
        return fetch_in_order(
            lambda book_isbn: self._parse_book(book_isbn, generic_cover, locale), isbns, LesLibrairesCa.MAX_RESULTS
        )

    def search_isbns(self, query: str) -> List[str]:
        response = self.bookshop.get_search(LesLibrairesCa.SEARCH_URL, params={"query": query})
        if response is None:
            return []
        try:
            books = response.json().get("data") or []
        except ValueError:
            return []
        isbns = [str(book.get("isbn") or "") for book in books]
        return list(dict.fromkeys(isbn for isbn in isbns if re.fullmatch(r"97[89]\d{10}", isbn)))

    def _parse_book(self, isbn: str, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        response = self.bookshop.get_page(LesLibrairesCa.BOOK_URL + isbn)
        book = SchemaOrgBook.from_html(response.text) if response is not None else None
        if book is None:
            return None
        match = book.to_record(
            MetaSourceInfo(id=self.__id__, description=LesLibrairesCa.DESCRIPTION, link=LesLibrairesCa.META_URL),
            response.url,
            generic_cover,
            locale,
        )
        match.identifiers = {"isbn": match.id or isbn}
        match.cover = self._parse_cover(match.id or isbn) or generic_cover
        return match

    def _parse_cover(self, isbn: str) -> str:
        for template in LesLibrairesCa.COVER_URLS:
            url = template.format(suffix=isbn[-3:], isbn=isbn)
            try:
                response = self.bookshop.session.head(url, timeout=5, allow_redirects=True)
            except Exception:
                continue
            if (
                response.status_code == 200
                and response.headers.get("Content-Type", "").startswith("image/jpeg")
                and int(response.headers.get("Content-Length") or LesLibrairesCa.MIN_COVER_SIZE + 1)
                > LesLibrairesCa.MIN_COVER_SIZE
            ):
                return url
        return ""
