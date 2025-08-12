# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

# Version from AutoCaliWeb - Optimized by - gelbphoenix & UsamaFoad

# Hardcover api document: https://Hardcover.gamespot.com/api/documentation
from typing import Dict, List, Optional

import requests
from cps import logger, config, constants
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
        "User-Agent": constants.USER_AGENT,
    }
    FORMATS = ["","Physical Book","","","E-Book"] # Map reading_format_id to text equivelant.

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        val = list()
        if self.active:
            try:
                token = (current_user.hardcover_token or config.config_hardcover_api_token or getenv("HARDCOVER_TOKEN"))
                if not token:
                    self.set_status(False)
                    raise Exception("Hardcover token not set for user, and no global token provided.")
                edition_search = query.split(":")[0] == "hardcover-id"
                Hardcover.HEADERS["Authorization"] = "Bearer %s" % token.replace("Bearer ","")
                result = requests.post(
                    Hardcover.BASE_URL,
                    json={
                        "query":Hardcover.SEARCH_QUERY if not edition_search else Hardcover.EDITION_QUERY,
                        "variables":{"query":query if not edition_search else query.split(":")[1]}
                    },
                    headers=Hardcover.HEADERS,
                )
                result.raise_for_status()
                response_data = result.json()
                
                # Check for GraphQL errors  
                if "errors" in response_data:  
                    log.error(f"GraphQL errors: {response_data['errors']}")  
                    return []
                    
                # Validate response structure  
                if "data" not in response_data:  
                    log.warning("Invalid response structure: missing 'data' field")  
                    return []  

            except requests.exceptions.RequestException as e:  
                log.warning(f"HTTP request failed: {e}")  
                return []  
            except ValueError as e:  
                log.warning(f"JSON parsing failed: {e}")  
                return []  
            except Exception as e:
                log.warning(f"Unexpected error: {e}")
                return [] # Return empty list instead of None

            # Process results with error handling
            try:
                if edition_search:
                    books_data = self._safe_get(response_data, "data", "books", default=[])
                    if books_data:
                        result = books_data[0]
                        val = self._parse_edition_results(result=result, generic_cover=generic_cover, locale=locale)
                else:
                    search_results = self._safe_get(response_data, "data", "search", "results", "hits", default=[])
                    for result in search_results:
                        match = self._parse_title_result(
                            result=result, generic_cover=generic_cover, locale=locale
                        )
                        if match:  # Only add valid results
                            val.append(match)
            except Exception as e:
                log.warning(f"Error processing results: {e}")
                return []

        return val

    def _parse_title_result(
        self, result: Dict, generic_cover: str, locale: str
    ) -> Optional[MetaRecord]:
        try:
            document = self._safe_get(result, "document", default={})
            if not document:
                return None

            series_info = self._safe_get(document, "featured_series", default={})
            series = self._safe_get(series_info, "series_name", default="")
            series_index = self._safe_get(series_info, "position", default="")

            match = MetaRecord(
                id=self._safe_get(document, "id", default=""),
                title=self._safe_get(document, "title", default=""),
                authors=self._safe_get(document, "author_names", default=[]),
                url=self._parse_title_url(result, ""),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=Hardcover.DESCRIPTION,
                    link=Hardcover.META_URL,
                ),
                series=series,
            )

            # Safe cover image access
            image_data = self._safe_get(document, "image", default={})
            match.cover = self._safe_get(image_data, "url", default=generic_cover)

            match.description = self._safe_get(document, "description", default="")
            match.publishedDate = self._safe_get(document, "release_date", default="")
            match.series_index = series_index
            match.tags = self._safe_get(document, "genres", default=[])
            match.identifiers = {
                "hardcover-id": match.id,
                "hardcover-slug": self._safe_get(document, "slug", default="")
            }
            return match
        except Exception as e:
            log.warning(f"Error parsing title result: {e}")
            return None

    def _parse_edition_results(
        self, result: Dict, generic_cover: str, locale: str
    ) -> List[MetaRecord]:
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
        # Use safe access instead of direct dictionary access  
        document = result.get("document", {})  
        hardcover_slug = document.get("slug", "")  
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
            contributions = edition.get("contributions", [])
            if not isinstance(contributions, list):
                return authors

            result = []
            for contrib in contributions:
                if isinstance(contrib, dict) and "author" in contrib:
                    author_data = contrib["author"]
                    if isinstance(author_data, dict) and "name" in author_data:
                        result.append(author_data["name"])
            return result if result else authors
        except Exception as e:
            log.warning(f"Error parsing edition authors: {e}")
            return authors

    @staticmethod
    def _parse_tags(result: Dict, tags: List[str]) -> List[str]:
        try:
            cached_tags = result.get("cached_tags", [])
            if not isinstance(cached_tags, list):
                return tags

            result_tags = []
            for item in cached_tags:
                if isinstance(item, dict) and "tag" in item and item["tag"]:
                    result_tags.append(item["tag"])
            return result_tags if result_tags else tags
        except Exception as e:
            log.warning(f"Error parsing tags: {e}")
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

    @staticmethod
    def _safe_get(data, *keys, default=None):
        """Safely get nested dictionary values"""
        try:
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return default
            return data
        except (TypeError, KeyError):
            return default