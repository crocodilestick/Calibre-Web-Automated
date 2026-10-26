# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import re
from typing import List, Optional

from lxml import etree

from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from cps.services.bookshop_metadata import BookshopSession, isbn_from_query, language_names

log = logger.create()


class BnF(Metadata):
    __name__ = "BnF (Bibliothèque nationale de France)"
    __id__ = "bnf"
    DESCRIPTION = "BnF (Bibliothèque nationale de France)"
    META_URL = "https://catalogue.bnf.fr/"
    SEARCH_URL = "https://catalogue.bnf.fr/api/SRU"
    NAMESPACES = {"mxc": "info:lc/xmlns/marcxchange-v2"}
    MAX_RESULTS = 5
    bookshop = BookshopSession({"User-Agent": "Calibre-Web-Automated metadata (BnF SRU)"})

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        if not self.active or not query:
            return []
        self.bookshop.reset()
        cql = self._prepare_query(query)
        if not cql:
            return []
        response = self.bookshop.get_search(
            BnF.SEARCH_URL,
            params={
                "version": "1.2",
                "operation": "searchRetrieve",
                "query": cql,
                "recordSchema": "unimarcxchange",
                "maximumRecords": BnF.MAX_RESULTS,
            },
        )
        if response is None:
            return []
        try:
            root = etree.fromstring(response.content)
        except etree.XMLSyntaxError as e:
            log.warning(e)
            return []
        val = list()
        for record in root.iterfind(".//mxc:record", BnF.NAMESPACES):
            match = UnimarcRecordParser(record, self).parse(generic_cover, locale)
            if match:
                val.append(match)
        if not val:
            log.info(f"No BnF results found for query: {query}")
        return val

    def _prepare_query(self, query: str) -> str:
        isbn = isbn_from_query(query)
        if isbn:
            return f'bib.isbn adj "{isbn}"'
        words = " ".join(self.get_title_tokens(query, strip_joiners=False)).replace('"', "")
        return f'bib.anywhere all "{words}" and bib.doctype any "a"' if words else ""


class UnimarcRecordParser:
    AUTHOR_FIELDS = ("700", "701", "702")
    AUTHOR_ROLES = ("070", "440")

    def __init__(self, record, metadata: BnF):
        self.record = record
        self.metadata = metadata

    def parse(self, generic_cover: str, locale: str) -> Optional[MetaRecord]:
        title = self._parse_title()
        if not title:
            return None
        ark = (self.record.findtext("mxc:controlfield[@tag='003']", "", BnF.NAMESPACES) or "").strip()
        match = MetaRecord(
            id=ark.rsplit("/", 1)[-1] if ark else "",
            title=title,
            authors=self._parse_authors(),
            url=ark or BnF.META_URL,
            source=MetaSourceInfo(id=self.metadata.__id__, description=BnF.DESCRIPTION, link=BnF.META_URL),
        )
        summaries = self._subfields("330", "a")
        match.cover = generic_cover
        match.description = "<p>" + "</p><p>".join(summaries) + "</p>" if summaries else ""
        match.publisher = (self._subfields("210", "c") + self._subfields("214", "c") + [""])[0]
        match.publishedDate = self._parse_date()
        match.identifiers = self._parse_identifiers(match.id)
        match.tags = list(dict.fromkeys(self._subfields("606", "a")))[:10]
        match.languages = language_names(self._subfields("101", "a")[:1], locale)
        match.series, match.series_index = self._parse_series()
        return match

    def _subfields(self, tag: str, code: str) -> List[str]:
        return [
            element.text.strip()
            for element in self.record.iterfind(
                f"mxc:datafield[@tag='{tag}']/mxc:subfield[@code='{code}']", BnF.NAMESPACES
            )
            if element.text and element.text.strip()
        ]

    def _parse_title(self) -> str:
        titles = self._subfields("200", "a")
        if not titles:
            return ""
        title = titles[0]
        part = self._subfields("200", "h") + self._subfields("200", "i")
        if part:
            title = f"{title}. {' '.join(part)}"
        subtitles = self._subfields("200", "e")
        if subtitles:
            title = f"{title} : {subtitles[0]}"
        return title

    def _parse_authors(self) -> List[str]:
        authors = list()
        for field in self.record.iterfind("mxc:datafield", BnF.NAMESPACES):
            tag = field.get("tag")
            if tag not in UnimarcRecordParser.AUTHOR_FIELDS:
                continue
            codes = {s.get("code"): (s.text or "").strip() for s in field.iterfind("mxc:subfield", BnF.NAMESPACES)}
            if tag != "700" and codes.get("4", "070") not in UnimarcRecordParser.AUTHOR_ROLES:
                continue
            name = " ".join(x for x in (codes.get("b"), codes.get("a")) if x)
            if name and name not in authors:
                authors.append(name)
        return authors or self._subfields("200", "f")[:1]

    def _parse_date(self) -> str:
        date = (self._subfields("210", "d") + self._subfields("214", "d") + [""])[0]
        year = re.search(r"\d{4}", date)
        return f"{year.group(0)}-01-01" if year else ""

    def _parse_identifiers(self, ark_id: str) -> dict:
        identifiers = dict()
        isbns = [re.sub(r"[^\dX]", "", isbn) for isbn in self._subfields("010", "a")]
        if isbns and isbns[0]:
            identifiers["isbn"] = isbns[0]
        if ark_id:
            identifiers["bnf"] = ark_id
        return identifiers

    def _parse_series(self):
        series = self._subfields("461", "t")
        if not series:
            return None, 0
        number = re.search(r"\d+(?:[.,]\d+)?", (self._subfields("461", "v") + [""])[0])
        return series[0].rstrip(" .;,"), float(number.group(0).replace(",", ".")) if number else 1
