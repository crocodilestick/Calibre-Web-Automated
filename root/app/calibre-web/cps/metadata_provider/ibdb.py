# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2021 OzzieIsaacs
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

# Google Books api document: https://developers.google.com/books/docs/v1/using
from typing import Dict, List, Optional
from urllib.parse import quote
from datetime import datetime

import requests

from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

log = logger.create()


class IBDb(Metadata):
    __name__ = "IBDb"
    __id__ = "ibdb"
    DESCRIPTION = "Internet Book Database"
    META_URL = "https://ibdb.dev/"
    BOOK_URL = "https://ibdb.dev/book/"
    SEARCH_URL = "https://ibdb.dev/search?q="

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        val = list()
        if self.active:

            title_tokens = list(self.get_title_tokens(query, strip_joiners=False))
            if title_tokens:
                tokens = [quote(t.encode("utf-8")) for t in title_tokens]
                query = "+".join(tokens)
            try:
                results = requests.get(IBDb.SEARCH_URL + query)
                results.raise_for_status()
            except Exception as e:
                log.warning(e)
                return []
            for result in results.json().get("books", []):
                val.append(
                    self._parse_search_result(
                        result=result, generic_cover=generic_cover, locale=locale
                    )
                )
        return val

    def _parse_search_result(
        self, result: Dict, generic_cover: str, locale: str
    ) -> MetaRecord:
        match = MetaRecord(
            id=result["id"],
            title=result["title"],
            authors= self._parse_authors(result=result),
            url=IBDb.BOOK_URL + result["id"],
            source=MetaSourceInfo(
                id=self.__id__,
                description=IBDb.DESCRIPTION,
                link=IBDb.META_URL,
            ),
        )

        match.cover = self._parse_cover(result=result, generic_cover=generic_cover)
        match.description = result.get("synopsis", "")
        match.languages = self._parse_languages(result=result, locale=locale)
        match.publisher = result.get("publisher", "")
        try:
            datetime.strptime(result.get("publishedDate", ""), "%Y-%m-%d")
            match.publishedDate = result.get("publishedDate", "")
        except ValueError:
            match.publishedDate = ""
        match.rating = 0
        match.series, match.series_index = "", 1
        match.tags = []

        match.identifiers = {"ibdb": match.id, "isbn": result.get("isbn13", "")}
        return match

    @staticmethod
    def _parse_authors(result: Dict) -> List[str]:
        if (result.get("authors")):
            return [author.get("name", "-no-name-") for author in result.get("authors", [])]
        return []

    @staticmethod
    def _parse_cover(result: Dict, generic_cover: str) -> str:
        if result.get("image"):
            return result["image"]["url"]

        return generic_cover

    @staticmethod
    def _parse_languages(result: Dict, locale: str) -> List[str]:
        language_iso2 = result.get("language", "")
        languages = (
            [get_language_name(locale, get_lang3(language_iso2))]
            if language_iso2
            else []
        )
        return languages
