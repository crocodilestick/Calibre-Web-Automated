"""
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

# Version from AutoCaliWeb - Optimized by - gelbphoenix & UsamaFoad

# Hardcover api document: https://Hardcover.gamespot.com/api/documentation
"""
from typing import Dict, List, Optional, Union

import requests
from os import getenv

# Try importing from full app; if unavailable (CLI), use light fallbacks
try:  # pragma: no cover - normal app path
    from cps import logger, config, constants  # type: ignore
    from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata  # type: ignore
    from cps.isoLanguages import get_language_name  # type: ignore
    from ..cw_login import current_user  # type: ignore
except Exception:  # pragma: no cover - CLI/testing path
    import logging as _logging
    from dataclasses import dataclass, field

    class _FallbackLogger:
        @staticmethod
        def create():
            _log = _logging.getLogger("hardcover")
            if not _log.handlers:
                _h = _logging.StreamHandler()
                _h.setFormatter(_logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
                _log.addHandler(_h)
                _log.setLevel(_logging.INFO)
            return _log

    logger = _FallbackLogger()  # type: ignore

    class _FallbackConfig:
        config_hardcover_token: Optional[str] = None

    config = _FallbackConfig()  # type: ignore

    class _FallbackConstants:
        USER_AGENT = "Calibre-Web-Automated/HardcoverTest"

    constants = _FallbackConstants()  # type: ignore

    # Minimal stand-ins for CLI runs
    @dataclass
    class MetaSourceInfo:  # type: ignore
        id: str
        description: str
        link: str

    @dataclass
    class MetaRecord:  # type: ignore
        id: Union[str, int]
        title: str
        authors: List[str]
        url: str
        source: MetaSourceInfo
        cover: str = ""
        description: Optional[str] = ""
        series: Optional[str] = None
        series_index: Optional[Union[int, float]] = 0
        identifiers: Dict[str, Union[str, int]] = field(default_factory=dict)
        publisher: Optional[str] = None
        publishedDate: Optional[str] = None
        rating: Optional[int] = 0
        languages: Optional[List[str]] = field(default_factory=list)
        tags: Optional[List[str]] = field(default_factory=list)
        format: Optional[str] = None

    class Metadata:  # type: ignore
        def __init__(self):
            self.active = True

        def set_status(self, state):
            self.active = state

    def get_language_name(locale: str, code3: str) -> str:  # type: ignore
        return code3 or ""

    class _DummyUser:
        hardcover_token: Optional[str] = None

    current_user = _DummyUser()  # type: ignore

log = logger.create()


class Hardcover(Metadata):
    __name__ = "Hardcover"
    __id__ = "hardcover"
    DESCRIPTION = "Hardcover"
    META_URL = "https://hardcover.app/"
    BASE_URL = "https://api.hardcover.app/v1/graphql"
    HEADERS = {
        "Content-Type": "application/json",
        "User-Agent": constants.USER_AGENT,
    }
    # reading_format_id mapping (indices observed in API). Leave blanks for unknowns to keep indices aligned.
    FORMATS = ["", "Physical Book", "", "", "E-Book"]

    # Results is a scalar JSON string; we decode client-side.
    SEARCH_QUERY = (
        "query SearchBooks($query: String!) { "
        "search(query: $query, query_type: \"Book\", per_page: 50) { results } "
        "}"
    )

    EDITION_QUERY = (
        "query BookEditions($query: Int!) { "
        "books(where: {id: {_eq: $query}}) { "
        "  id slug description "
        "  book_series { position series { name } } "
        "  cached_tags(path: \"Genre\") "
        "  editions { "
        "    id title release_date isbn_13 isbn_10 reading_format_id "
        "    image { url } "
        "    language { code3 } "
        "    publisher { name } "
        "    contributions { author { name } } "
        "  } "
        "} }"
    )

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        val: List[MetaRecord] = []
        if not self.active:
            return val

        token = (
            getattr(current_user, "hardcover_token", None)
            or getattr(config, "config_hardcover_token", None)
            or getenv("HARDCOVER_TOKEN")
        )
        if not token:
            log.warning("Hardcover token missing; set a user token or global token to enable results.")
            return []

        try:
            edition_search = query.split(":")[0] == "hardcover-id"
            Hardcover.HEADERS["Authorization"] = "Bearer %s" % token.replace("Bearer ", "")
            resp = requests.post(
                Hardcover.BASE_URL,
                json={
                    "query": Hardcover.EDITION_QUERY if edition_search else Hardcover.SEARCH_QUERY,
                    "variables": {"query": int(query.split(":")[1]) if edition_search else query},
                },
                headers=Hardcover.HEADERS,
            )
            resp.raise_for_status()
            response_data = resp.json()

            if "errors" in response_data:
                log.error(f"GraphQL errors: {response_data['errors']}")
                return []
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
            return []

        try:
            if edition_search:
                books_data = self._safe_get(response_data, "data", "books", default=[])
                if books_data:
                    book = books_data[0]
                    val = self._parse_edition_results(result=book, generic_cover=generic_cover, locale=locale)
            else:
                raw_results = self._safe_get(response_data, "data", "search", "results", default=[])
                if isinstance(raw_results, str):
                    import json as _json
                    try:
                        parsed = _json.loads(raw_results)
                    except Exception:
                        parsed = []
                else:
                    parsed = raw_results

                for hit in self._safe_get(parsed, "hits", default=[]):
                    match = self._parse_title_result(result=hit, generic_cover=generic_cover, locale=locale)
                    if match:
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
            series = self._safe_get(document, "featured_series", "series", "name", default="")
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

            image_data = self._safe_get(document, "image", default={})
            match.cover = self._safe_get(image_data, "url", default=generic_cover)

            match.description = self._safe_get(document, "description", default="")
            match.publishedDate = self._safe_get(document, "release_date", default="")
            match.series_index = series_index
            match.tags = self._safe_get(document, "genres", default=[])
            match.identifiers = {
                "hardcover-id": match.id,
                "hardcover-slug": self._safe_get(document, "slug", default=""),
            }
            return match
        except Exception as e:
            log.warning(f"Error parsing title result: {e}")
            return None

    def _parse_edition_results(
        self, result: Dict, generic_cover: str, locale: str
    ) -> List[MetaRecord]:
        editions: List[MetaRecord] = []
        book_id = result.get("id", "")
        for edition in result.get("editions", []) or []:
            match = MetaRecord(
                id=book_id,
                title=edition.get("title", ""),
                authors=self._parse_edition_authors(edition, []),
                url=self._parse_edition_url(result, edition, ""),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=Hardcover.DESCRIPTION,
                    link=Hardcover.META_URL,
                ),
                series=(result.get("book_series") or [{}])[0].get("series", {}).get("name", ""),
            )
            match.cover = (edition.get("image") or {}).get("url", generic_cover)
            match.description = result.get("description", "")
            match.publisher = (edition.get("publisher") or {}).get("name", "")
            match.publishedDate = edition.get("release_date", "")
            match.series_index = (result.get("book_series") or [{}])[0].get("position", "")
            match.tags = self._parse_tags(result, [])
            match.languages = self._parse_languages(edition, locale)
            match.identifiers = {
                "hardcover-id": book_id,
                "hardcover-slug": result.get("slug", ""),
                "hardcover-edition": edition.get("id", ""),
            }
            isbn = edition.get("isbn_13", edition.get("isbn_10"))
            if isbn:
                match.identifiers["isbn"] = isbn
            rf_id = edition.get("reading_format_id")
            if isinstance(rf_id, int) and 0 <= rf_id < len(Hardcover.FORMATS):
                match.format = Hardcover.FORMATS[rf_id]
            else:
                match.format = ""
            editions.append(match)
        return editions

    @staticmethod
    def _parse_title_url(result: Dict, url: str) -> str:
        document = result.get("document", {})
        hardcover_slug = document.get("slug", "")
        if hardcover_slug:
            return f"https://hardcover.app/books/{hardcover_slug}"
        return url

    @staticmethod
    def _parse_edition_url(result: Dict, edition: Dict, url: str) -> str:
        edition_id = edition.get("id", "")
        slug = result.get("slug", "")
        if edition_id:
            return f"https://hardcover.app/books/{slug}/editions/{edition_id}"
        return url

    @staticmethod
    def _parse_edition_authors(edition: Dict, authors: List[str]) -> List[str]:
        try:
            contributions = edition.get("contributions", [])
            if not isinstance(contributions, list):
                return authors
            result_authors: List[str] = []
            for contrib in contributions:
                if isinstance(contrib, dict) and "author" in contrib:
                    author_data = contrib.get("author")
                    if isinstance(author_data, dict) and "name" in author_data:
                        result_authors.append(author_data["name"])
            return result_authors if result_authors else authors
        except Exception as e:
            log.warning(f"Error parsing edition authors: {e}")
            return authors

    @staticmethod
    def _parse_tags(result: Dict, tags: List[str]) -> List[str]:
        try:
            cached_tags = result.get("cached_tags", [])
            # Hardcover GraphQL now returns cached_tags as a scalar JSON value (!json)
            # It may be:
            # - a list of dicts: [{"tag": "..."}] (old shape)
            # - a list of strings: ["..."] (possible shape)
            # - a JSON-encoded string: "[\"...\"]" (defensive handling)
            # - a single string: "..."
            parsed: List[str] = []
            # If it's a string, try to json-decode, otherwise treat as single tag
            if isinstance(cached_tags, str):
                try:
                    import json as _json
                    decoded = _json.loads(cached_tags)
                    cached_tags = decoded
                except Exception:
                    cached_tags = [cached_tags] if cached_tags else []

            if isinstance(cached_tags, list):
                for item in cached_tags:
                    if isinstance(item, dict):
                        val = item.get("tag") or item.get("name")
                        if val:
                            parsed.append(str(val))
                    elif isinstance(item, str):
                        if item:
                            parsed.append(item)
            elif isinstance(cached_tags, dict):
                # Some backends might return an object; try common keys
                val = cached_tags.get("tag") or cached_tags.get("name")
                if isinstance(val, str) and val:
                    parsed.append(val)

            return parsed if parsed else tags
        except Exception as e:
            log.warning(f"Error parsing tags: {e}")
            return tags

    @staticmethod
    def _parse_languages(edition: Dict, locale: str) -> List[str]:
        language_iso = (edition.get("language") or {}).get("code3", "")
        languages = [get_language_name(locale, language_iso)] if language_iso else []
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


if __name__ == "__main__":
    # Lightweight CLI for manual testing of Hardcover searches
    import argparse
    import json
    try:
        from dataclasses import asdict, is_dataclass
    except Exception:  # pragma: no cover
        asdict = None
        is_dataclass = None

    parser = argparse.ArgumentParser(description="Test Hardcover metadata provider")
    parser.add_argument("query", help="Search text or 'hardcover-id:ID' to fetch editions")
    parser.add_argument("--token", dest="token", help="Hardcover API token (or set HARDCOVER_TOKEN)")
    parser.add_argument("--locale", default="en", help="Locale for language names (default: en)")
    parser.add_argument("--cover", dest="generic_cover", default="", help="Generic cover URL fallback")
    args = parser.parse_args()

    token = args.token or getenv("HARDCOVER_TOKEN")
    if token:
        try:
            setattr(config, "config_hardcover_token", token)
        except Exception:
            pass

    class _DummyUser:
        hardcover_token = None

    try:
        globals()["current_user"] = _DummyUser()
    except Exception:
        pass

    provider = Hardcover()
    results = provider.search(args.query, generic_cover=args.generic_cover, locale=args.locale) or []

    def _to_dict(obj):
        try:
            if is_dataclass and is_dataclass(obj):
                return asdict(obj)
        except Exception:
            pass
        if isinstance(obj, (list, tuple)):
            return [_to_dict(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj

    print(json.dumps([_to_dict(r) for r in results], ensure_ascii=False, indent=2))