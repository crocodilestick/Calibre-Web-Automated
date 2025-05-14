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

# Hardcover api document: https://Hardcover.gamespot.com/api/documentation
from typing import Dict, List, Optional

import requests
from cps import logger
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from cps.isoLanguages import get_language_name
from ..cw_login import current_user
from os import getenv

log = logger.create()

class Hardcover(Metadata):
    __name__ = "Hardcover"
    __id__ = "hardcover"
    DESCRIPTION = "Hardcover Books"
    META_URL = "https://hardcover.app"
    BASE_URL = "https://api.hardcover.app/v1/graphql"
    SEARCH_QUERY = """query Search($query: String!) {
        search(query: $query, query_type: "Book", per_page: 50) {
            results
        }
    }
    """
    EDITION_QUERY = """query getEditions($query: Int!) {
        books(
            where: { id: { _eq: $query } }
            order_by: { users_read_count: desc_nulls_last }
        ) {
            title
            slug
            id
            
            book_series {
                series {
                    name
                }
                position
            }
            rating
            editions(
                where: {
                    _or: [{ reading_format_id: { _neq: 2 } }, { edition_format: { _is_null: true } }]
                }
                order_by: [{ reading_format_id: desc_nulls_last },{users_count: desc_nulls_last }]
            ) {
                id
                isbn_13
                isbn_10
                title
                reading_format_id
                contributions {
                    author {
                        name
                    }
                }
                image {
                    url
                }
                language {
                    code3
                }
                publisher {
                    name
                }
                release_date
                
            }
            description
            cached_tags(path: "Genre")
        }
    }
    """
    HEADERS = {
        "Content-Type": "application/json",
    }
    FORMATS = ["","Physical Book","","","E-Book"] # Map reading_format_id to text equivelant.

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        val = list()
        if self.active:
            try:
                token = current_user.hardcover_token or getenv("HARDCOVER_TOKEN")
                if not token:
                    self.set_status(False)
                    raise Exception("Hardcover token not set for user, and no global token provided.")
                edition_seach = query.split(":")[0] == "hardcover-id"
                Hardcover.HEADERS["Authorization"] = "Bearer %s" % token.replace("Bearer ","")
                result = requests.post(
                    Hardcover.BASE_URL,
                    json={
                        "query":Hardcover.SEARCH_QUERY if not edition_seach else Hardcover.EDITION_QUERY,
                        "variables":{"query":query if not edition_seach else query.split(":")[1]}
                    },
                    headers=Hardcover.HEADERS,
                )
                result.raise_for_status()
            except Exception as e:
                log.warning(e)
                return None
            if edition_seach:
                result = result.json()["data"]["books"][0]
                val = self._parse_edition_results(result=result, generic_cover=generic_cover, locale=locale)
            else:
                for result in result.json()["data"]["search"]["results"]["hits"]:
                    match = self._parse_title_result(
                        result=result, generic_cover=generic_cover, locale=locale
                    )
                    val.append(match)
        return val
    
    def _parse_title_result(
        self, result: Dict, generic_cover: str, locale: str
    ) -> MetaRecord:
        series = result["document"].get("featured_series",{}).get("series_name", "")
        series_index = result["document"].get("featured_series",{}).get("position", "")
        match = MetaRecord(
            id=result["document"].get("id",""),
            title=result["document"].get("title",""),
            authors=result["document"].get("author_names", []),
            url=self._parse_title_url(result, ""),
            source=MetaSourceInfo(
                id=self.__id__,
                description=Hardcover.DESCRIPTION,
                link=Hardcover.META_URL,
            ),
            series=series,
        )
        match.cover = result["document"]["image"].get("url", generic_cover)
        
        match.description = result["document"].get("description","")
        match.publishedDate = result["document"].get(
            "release_date", "")
        match.series_index = series_index
        match.tags = result["document"].get("genres",[])
        match.identifiers = {
            "hardcover-id": match.id,
            "hardcover-slug": result["document"].get("slug", "")
        }
        return match

    def _parse_edition_results(
        self, result: Dict, generic_cover: str, locale: str
    ) -> MetaRecord:
        editions = list()
        id = result.get("id","")
        for edition in result["editions"]:
            match = MetaRecord(    
                id=id,
                title=edition.get("title",""),       
                authors=self._parse_edition_authors(edition,[]),
                url=self._parse_edition_url(result, edition, ""),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=Hardcover.DESCRIPTION,
                    link=Hardcover.META_URL,
                ),
                series=(result.get("book_series") or [{}])[0].get("series",{}).get("name", ""),
            )
            match.cover = (edition.get("image") or {}).get("url", generic_cover)
            match.description = result.get("description","")
            match.publisher = (edition.get("publisher") or {}).get("name","")
            match.publishedDate = edition.get("release_date", "")
            match.series_index = (result.get("book_series") or [{}])[0].get("position", "")
            match.tags = self._parse_tags(result,[])
            match.languages = self._parse_languages(edition,locale)
            match.identifiers = {
                "hardcover-id": id,
                "hardcover-slug": result.get("slug", ""),
                "hardcover-edition": edition.get("id",""),
                "isbn": (edition.get("isbn_13",edition.get("isbn_10")) or "")
            }
            isbn = edition.get("isbn_13",edition.get("isbn_10"))
            if isbn:
                match.identifiers["isbn"] = isbn
            match.format = Hardcover.FORMATS[edition.get("reading_format_id",0)]
            editions.append(match)
        return editions
    
    @staticmethod
    def _parse_title_url(result: Dict, url: str) -> str:
        hardcover_slug = result["document"].get("slug", "")
        if hardcover_slug:
            return f"https://hardcover.app/books/{hardcover_slug}"
        return url

    @staticmethod
    def _parse_edition_url(result: Dict, edition: Dict, url: str) -> str:
        edition = edition.get("id", "")
        slug = result.get("slug","")
        if edition:
            return f"https://hardcover.app/books/{slug}/editions/{edition}"
        return url
    
    @staticmethod
    def _parse_edition_authors(edition: Dict, authors: List[str]) -> List[str]:
        try:
            return [author["author"]["name"] for author in edition.get("contributions",[]) if "author" in author and "name" in author["author"]]
        except Exception as e:
            log.warning(e)
            return authors

    @staticmethod
    def _parse_tags(result: Dict, tags: List[str]) -> List[str]:
        try:
            return [item["tag"] for item in result["cached_tags"] if "tag" in item]
        except Exception as e:
            log.warning(e)
            return tags
        
    @staticmethod
    def _parse_languages(edition: Dict, locale: str) -> List[str]:
        language_iso = (edition.get("language") or {}).get("code3","")
        languages = (
            [get_language_name(locale, language_iso)]
            if language_iso
            else []
        )
        return languages