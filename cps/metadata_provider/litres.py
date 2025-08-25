# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
import re
import requests
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

log = logger.create()


class Litres(Metadata):
    __name__ = "Litres"
    __id__ = "litres"
    DESCRIPTION = "LitRes"
    META_URL = "https://www.litres.ru"
    BOOK_URL = "https://www.litres.ru"
    API_URL = "https://api.litres.ru/foundation/api/search"
    API_ARTS_URL = "https://api.litres.ru/foundation/api/arts/{}"
    DEFAULT_LIMIT = 7
    TIMEOUT = 20
    DEFAULT_TYPES = [
        "text_book",
        "audiobook",
        "podcast",
        "podcast_episode",
        "webtoon",
    ]

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Calibre-Web-Litres-Provider/2.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        })

    def config(self, settings: Dict) -> None:
        self.active = settings.get(self.__id__, "True") == "True"
        log.info("Litres provider configured, active: %s", self.active)

    @staticmethod
    def setup() -> None:
        log.info("Litres provider initialized")

    def name(self) -> str:
        return self.__name__

    def id(self) -> str:
        return self.__id__

    def search(
            self,
            query: str,
            generic_cover: str = "",
            locale: Any = "ru"
    ) -> Optional[List[MetaRecord]]:
        if not self.active:
            log.info("Litres provider inactive, skipping search")
            return []

        log.info("Searching Litres for: %s", query)

        locale_str = self._locale_to_string(locale)

        params = {
            "q": query.strip(),
            "limit": self.DEFAULT_LIMIT,
            "show_unavailable": "true",
            "types": self.DEFAULT_TYPES
        }

        headers = {
            "ui-language-code": locale_str,
        }

        try:
            response = self.session.get(
                self.API_URL,
                params=params,
                headers=headers,
                timeout=self.TIMEOUT
            )

            log.debug("Litres API request URL: %s", response.url)
            log.debug("Litres API response status: %s", response.status_code)

            if response.status_code != 200:
                log.warning("Litres API returned status: %s", response.status_code)
                try:
                    error_data = response.json()
                    log.warning("Litres API error details: %s", error_data)
                except:
                    log.warning("Litres API error response: %s", response.text[:200])
                return []

            data = response.json()
            items = self._extract_items(data)

            if not items:
                log.debug("No items found in Litres response")
                return []

            results = []
            for item in items:
                if meta_record := self._process_item(item, generic_cover, locale_str):
                    results.append(meta_record)
                    if len(results) >= self.DEFAULT_LIMIT:
                        break

            log.info("Litres search found %d results", len(results))
            return results

        except requests.exceptions.Timeout:
            log.error("Litres API request timed out")
        except requests.exceptions.RequestException as e:
            log.error("Litres API request failed: %s", e)
        except json.JSONDecodeError:
            log.error("Failed to decode JSON from Litres API response")
        except Exception as e:
            log.exception("Unexpected error in Litres search: %s", e)

        return []

    @staticmethod
    def _locale_to_string(locale: Any) -> str:
        if isinstance(locale, str):
            return locale
        try:
            if hasattr(locale, 'language'):
                return locale.language
            return str(locale)
        except (AttributeError, TypeError):
            return 'ru'

    def _extract_items(self, data: Dict) -> List[Dict]:
        items = []
        try:
            payload_data = data.get("payload", {}).get("data")
            if isinstance(payload_data, list):
                for el in payload_data:
                    inst = el.get("instance") if isinstance(el, dict) else None
                    if inst and isinstance(inst, dict):
                        items.append(inst)
            else:
                items = self._find_items_in_payload(data)
        except Exception as e:
            log.debug("Error extracting items using original method: %s", e)
            items = self._find_items_in_payload(data)

        log.debug("Found %d items in response", len(items))
        return items

    @staticmethod
    def _find_items_in_payload(payload: Dict) -> List[Dict]:
        if isinstance(payload, dict):
            for key in ("payload", "data", "items", "results", "content", "docs", "books"):
                v = payload.get(key)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    if isinstance(v[0], dict) and "instance" in v[0]:
                        out = []
                        for el in v:
                            if isinstance(el, dict) and "instance" in el and isinstance(el["instance"], dict):
                                out.append(el["instance"])
                        if out:
                            return out
                    return v
            for k, v in payload.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
        if isinstance(payload, list):
            return payload
        return []

    def _process_item(
            self,
            item: Dict,
            generic_cover: str,
            locale: str
    ) -> Optional[MetaRecord]:
        try:
            item_id = item.get("id") or item.get("uuid") or item.get("instanceId")
            if not item_id:
                log.debug("Skipping item without ID")
                return None

            detailed_data = self._get_detailed_info(item_id, locale)

            title = self._get_title(item, detailed_data)
            if not title:
                log.debug("Skipping item without title")
                return None

            meta_record = MetaRecord(
                id=str(item_id),
                title=title,
                authors=self._get_authors(item, detailed_data),
                url=self._get_url(item),
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=self.DESCRIPTION,
                    link=self.META_URL
                )
            )

            meta_record.cover = self._get_cover(item, generic_cover)
            meta_record.description = self._get_description(item, detailed_data)
            meta_record.languages = self._get_languages(item, locale)
            meta_record.publisher = self._get_publisher(item)
            meta_record.publishedDate = self._get_published_date(item)
            meta_record.rating = self._get_rating(item, detailed_data)
            meta_record.identifiers = self._get_identifiers(item, detailed_data)
            meta_record.tags = self._get_tags(detailed_data)

            log.debug("Processed Litres item: %s by %s", meta_record.title, meta_record.authors)
            return meta_record

        except Exception as e:
            log.exception("Error processing Litres item %s: %s", item.get("id"), e)
            return None

    def _get_detailed_info(self, item_id: str, locale: str) -> Dict:
        try:
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8",
                "ui-language-code": locale,
                "User-Agent": "Calibre-Web-Litres-Provider/2.0",
            }

            response = self.session.get(
                self.API_ARTS_URL.format(item_id),
                headers=headers,
                timeout=self.TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("payload", {}).get("data", {})
            else:
                log.debug("Detailed info request failed for %s: %s", item_id, response.status_code)

        except Exception as e:
            log.debug("Failed to get detailed info for %s: %s", item_id, e)

        return {}

    @staticmethod
    def _get_title(item: Dict, detailed_data: Dict) -> str:
        title =  (
                item.get("title")
                or detailed_data.get("title")
                or item.get("name")
                or ""
        ).strip()

        formats = ['pdf', 'epub']
        pattern = r'\s*\([^)]*(' + '|'.join(formats) + ')[^)]*\)'

        title =  re.sub(pattern, '', title, flags=re.IGNORECASE)
        return title

    @staticmethod
    def _get_authors(item: Dict, detailed_data: Dict) -> List[str]:
        authors = []

        for p in item.get("persons") or []:
            try:
                role = (p.get("role") or "").lower()
                name = p.get("full_name") or p.get("fullName") or p.get("name")
                if not name:
                    continue
                if role in ("author", "автор", ""):
                    authors.append(name)
            except Exception:
                continue

        if not authors and detailed_data.get("persons"):
            for p in detailed_data.get("persons"):
                try:
                    role = (p.get("role") or "").lower()
                    name = p.get("full_name") or p.get("fullName") or p.get("name")
                    if not name:
                        continue
                    if role in ("author", "автор", ""):
                        authors.append(name)
                except Exception:
                    continue

        return authors or []

    def _get_url(self, item: Dict) -> str:
        rel_url = item.get("url") or item.get("uri") or ""
        return urljoin(self.META_URL, rel_url) if rel_url else self.BOOK_URL

    def _get_cover(self, item: Dict, generic_cover: str) -> str:
        cover_rel = item.get("cover_url") or item.get("image") or item.get("thumbnail") or ""
        cover_candidate = urljoin(self.META_URL, cover_rel) if cover_rel else ""
        return cover_candidate or generic_cover

    @staticmethod
    def _get_description(item: Dict, detailed_data: Dict) -> str:
        if detailed_data.get("html_annotation"):
            raw_html = detailed_data.get("html_annotation")
        else:
            raw_html = item.get("annotation") or item.get("description") or item.get("lead") or ""

        description = raw_html or ""

        patterns =  [
            r'<p\b[^>]*>(?:(?!</p>).)*?(?:покупк|скачать|загрузить|предоставляется|формат|epub|pdf|fb2|mobi)(?:(?!</p>).)*?</p>',
            r'<p><br/></p>'
        ]

        for pattern in patterns:
            description = re.sub(pattern, '', description, flags=re.IGNORECASE | re.DOTALL)

        return description

    @staticmethod
    def _get_languages(item: Dict, locale: str) -> List[str]:
        lang = item.get("language_code") or item.get("language") or item.get("inLanguage") or "ru"
        try:
            return [get_language_name(locale, get_lang3(lang))]
        except Exception:
            return [lang] if lang else []

    @staticmethod
    def _get_publisher(item: Dict) -> str:
        return item.get("publisher") or ""

    @staticmethod
    def _get_published_date(item: Dict) -> str:
        published_date = ""
        for dkey in ("date_written_at", "first_published_at", "release_date", "last_released_at", "available_from"):
            if item.get(dkey):
                s = str(item.get(dkey))
                m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
                if m:
                    published_date = m.group(1)
                else:
                    m2 = re.search(r"(\d{4})", s)
                    if m2:
                        published_date = m2.group(1)
                if published_date:
                    break
        return published_date

    @staticmethod
    def _get_rating(item: Dict, detailed_data: Dict) -> int:
        try:
            if detailed_data.get("livelib_rated_avg") is not None:
                rating = int(detailed_data.get("livelib_rated_avg"))
            else:
                rating_obj = item.get("rating") or {}
                rating = int(
                    rating_obj.get("rated_avg") or rating_obj.get("avg") or rating_obj.get("ratingValue") or 0)
        except Exception:
            rating = 0
        return rating

    def _get_identifiers(self, item: Dict, detailed_data: Dict) -> Dict[str, str]:
        identifiers = {}
        isbn = item.get("isbn") or item.get("bookIsbn") or item.get("isbn13") or item.get("isbn_13")
        if isbn:
            identifiers["isbn"] = str(isbn).replace("-", "")

        if "isbn" not in identifiers:
            text_search = " ".join(filter(None, [
                item.get("title") or "",
                item.get("annotation") or "",
                item.get("description") or "",
                " ".join(self._get_authors(item, detailed_data))
            ]))
            m = re.search(r"\b(?:ISBN(?:-13)?:?\s*)?([0-9\-]{10,17})\b", text_search, re.IGNORECASE)
            if m:
                identifiers["isbn"] = m.group(1).replace("-", "")

        item_id = item.get("id") or item.get("uuid") or item.get("instanceId")
        if item_id:
            identifiers["litres"] = str(item_id)

        return identifiers

    @staticmethod
    def _get_tags(detailed_data: Dict) -> List[str]:
        tag_list = []
        for tag in detailed_data.get("tags", []):
            name = tag.get("name")
            if name:
                tag_list.append(name)
        return tag_list or []