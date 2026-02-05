# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import abc
import concurrent.futures
import dataclasses
import os
import re
import time
from datetime import datetime
from typing import Generator, Hashable, Iterable, TypeVar

from bs4 import BeautifulSoup as BS

try:
    from curl_cffi import requests as creq  # type: ignore
except ImportError:
    import requests as creq  # Fallback to regular requests if curl-cffi not available
import cps.logger as logger
from cps import constants, isoLanguages

log = logger.create()

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclasses.dataclass
class MetaSourceInfo:
    id: str
    description: str
    link: str


@dataclasses.dataclass
class MetaRecord:
    id: str | int
    title: str
    authors: list[str]
    url: str
    source: MetaSourceInfo
    cover: str = os.path.join(constants.STATIC_DIR, "generic_cover.jpg")
    description: str | None = ""
    series: str | None = None
    series_index: int | float | None = 0
    identifiers: dict[str, str | int] = dataclasses.field(default_factory=dict)
    publisher: str | None = None
    publishedDate: str | None = None
    rating: int | None = 0
    languages: list[str] | None = dataclasses.field(default_factory=list)
    tags: list[str] | None = dataclasses.field(default_factory=list)
    format: str | None = None
    confidence_score: float | None = None
    match_reason: str | None = ""


class Metadata:
    """Abstract base class for metadata sources.

    Attributes:
        __name__ (str): Human-readable name of the metadata source.
        __id__ (str): Unique identifier for the metadata source.
        MAX_SEARCH_RESULTS (int): Maximum number of search results to return.
        MAX_THREADS (int): Maximum number of threads for parallel processing.
        active (bool): Whether this metadata source is active.
        headers (dict): HTTP headers to use for requests.
        session (requests.Session): HTTP session for making requests.
        _last_request_time (float): Timestamp of the last request made.
        _min_request_interval (float): Minimum interval in seconds between requests.
    """

    __name__ = "Generic"
    __id__ = "generic"

    # Maximum number of search results to return from any one provider
    MAX_SEARCH_RESULTS = 5

    active = True

    # Timestamp of the last request made by this metadata source. Used for rate limiting.
    _last_request_time = 0.0

    # Minimum interval in seconds between requests to this metadata source
    _min_request_interval = 0.5

    _thread_pool: concurrent.futures.ThreadPoolExecutor | None = None

    def __init__(self):
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=constants.MAX_THREADS
        )

        # Headers passed to HTTP requests
        # Headers are defined in the constructor because they depend on instance-level language_codes and we may as well
        # just keep it all together here.
        self.headers = {
            "User-Agent": constants.BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": self.accept_language_header(),
        }

        # The session is defined in the constructor because of a quirk of Python: at the class level it's constructed
        # once, when the class is defined, and never touched again. This means that subclasses would share the same
        # session instance, which is not what we want. By defining it in the constructor, each subclass instance gets
        # its own session.
        try:
            # Try curl-cffi with impersonation first
            self.session = creq.Session(impersonate="chrome120")
        except (TypeError, AttributeError):
            # Fallback to regular requests session
            self.session = creq.Session()
        self.session.headers.update(self.headers)

    def accept_language_header(self) -> str:
        """Return the Accept-Language header value for this metadata source.

        This is done as an instance function because some metadata provider regions may have multiple languages with
        different priorities. We assume that the order of language codes returned by language_codes() reflects the
        priority.

        Returns:
            str: Accept-Language header value.
        """
        # TODO: Allow user to configure language preference order?
        return ",".join(
            [
                f"{lang};q={1 - i * 0.1:.1f}" if i else lang
                for i, lang in enumerate(self.language_codes())
            ]
        )

    def language_codes(self) -> list[str]:
        """Return the list of language codes for this metadata source.

        Returns:
            list[str]: List of language codes.
        """
        return ["en-US", "en"]

    def set_status(self, state):
        """Set the active state of this metadata source.

        Args:
            state (bool): True to activate, False to deactivate.
        """
        self.active = state

    @abc.abstractmethod
    def base_url(self) -> str:
        """Return the base URL of the metadata source.

        Returns:
            str: Base URL as a string.
        """
        return ""

    @abc.abstractmethod
    def search(
        self, query: str, generic_cover: str = "", locale: str = "en_US"
    ) -> list[MetaRecord] | None:
        """Search this metadata provider for matching query results.

        Args:
            query (str): The search query.
            generic_cover (str, optional): Path to generic cover image. Defaults to "".

        Returns:
            list[MetaRecord] | None: List of MetaRecord objects or None on failure or no results.
        """
        return None

    @abc.abstractmethod
    def parse_detail_page(
        self, detail_uri: str, generic_cover: str, index: int
    ) -> tuple[MetaRecord, int] | None:
        """Parse a book detail page from the metadata source.

        Args:
            detail_uri (str): The URI of the detail page.
            generic_cover (str): Path to generic cover image.
            index (int): Index of the book in the search results.

        Returns:
            tuple[MetaRecord, int] | None: A tuple of MetaRecord and index, or None on failure.
        """
        return None

    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect the minimum request interval."""
        if self._min_request_interval > 0:
            now = time.time()
            delta = now - self._last_request_time
            if delta < self._min_request_interval:
                sleep_time = self._min_request_interval - delta
                log.debug(
                    f"Time until next request for {self.__name__} is allowed: {sleep_time:.2f}s"
                )
                time.sleep(sleep_time)

    def get_raw(self, url: str, timeout: int = 10, **kwargs) -> bytes | None:
        """Get a URL and return the raw response.

        Args:
            url (str): The URL to fetch.
            timeout (int, optional): Request timeout in seconds. Defaults to 10.
            **kwargs: Additional keyword arguments passed directly to `requests.get()`.
        Returns:
            bytes | None: Raw response bytes or None on failure.
        """
        self._wait_for_rate_limit()

        try:
            r = self.session.get(url, timeout=timeout, **kwargs)
            self._last_request_time = time.time()
            r.raise_for_status()
            return r.content
        except Exception as ex:
            log.error_or_exception(ex)
            return None

    def get(self, url: str, timeout: int = 10, **kwargs) -> BS | None:
        """Get a URL and return the parsed BaeutifulSoup object.

        Args:
            url (str): The URL to fetch.
            timeout (int, optional): Request timeout in seconds. Defaults to 10.
            **kwargs: Additional keyword arguments passed directly to `requests.get()`.

        Returns:
            BS | None: Parsed BeautifulSoup object or None on failure.
        """
        r = self.get_raw(url, timeout=timeout, **kwargs)
        if r is None:
            return None

        # lxml is faster, fall back to html.parser if needed
        try:
            detail_soup = BS(r.decode(), "lxml")
        except Exception:
            detail_soup = BS(r.decode(), "html.parser")

        return detail_soup

    def post(self, url: str, timeout: int = 10, **kwargs) -> BS | dict | None:
        """Post to a URL and return the parsed result. If the Content-Type is JSON return a dict, otherwise return a BeautifulSoup object.

        Args:
            url (str): The URL to post to.
            timeout (int, optional): Request timeout in seconds. Defaults to 10.
            **kwargs: Additional keyword arguments passed directly to `requests.post()`.

        Returns:
            BS | dict | None: Parsed BeautifulSoup object, dict for JSON responses, or None on failure.
        """
        self._wait_for_rate_limit()

        try:
            as_json = kwargs.pop("as_json", False)
            r = self.session.post(url, timeout=timeout, **kwargs)
            self._last_request_time = time.time()
            r.raise_for_status()

            if as_json or self.headers.get("Accept", "").lower() == "application/json":
                return r.json()

            # lxml is faster, fall back to html.parser if needed
            try:
                detail_soup = BS(r.text, "lxml")
            except Exception:
                detail_soup = BS(r.text, "html.parser")

            return detail_soup
        except Exception as ex:
            log.error_or_exception(ex)
            return None

    @property
    def primary_language(self) -> str:
        """Return the primary language code.

        The primary language is constructed by taking the first language code from language_codes and stripping any
        country code. The result is expected to be a valid ISO 639-1 language code. For example, "en-US" becomes "en".

        Returns:
            str: ISO 639-1 language string
        """
        return self.language_codes()[0].split("-", 1)[0]

    def _normalize_date(self, date_str: str) -> str | None:
        """Normalize date strings to YYYY-MM-DD format.

        Args:
            date_str (str): Input date string.

        Returns:
            str | None: Normalized date string or None if parsing fails.
        """
        date_str = date_str.strip()

        if not date_str:
            return None

        # Strip time part if present (ISO 8601 like 2025-09-09T00:00:00Z)
        if "T" in date_str:
            date_str = date_str.split("T", 1)[0]
        # Strip time part if present (like '2025-09-09 00:00:00' or '09 September 2025 00:00:00')
        date_match = re.match(
            r"^(.*?)(\s+\d{1,2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)$", date_str
        )
        if date_match:
            date_str = date_match.group(1).strip()

        # Try common date formats
        for fmt in (
            "%Y-%m-%d",  # e.g., 2025-09-17
            "%Y/%m/%d",  # e.g., 2025/09/17
            "%Y-%m",  # e.g., 2025-09
            "%Y/%m",  # e.g., 2025/09
            "%Y",  # e.g., 2025
            "%B %d, %Y",  # e.g., September 9, 2025
            "%b %d, %Y",  # e.g., Sep 9, 2025
            "%d %B %Y",  # e.g., 9 September 2025
            "%d %b %Y",  # e.g., 9 Sep 2025
            "%B %Y",  # e.g., September 2025
            "%b %Y",  # e.g., Sep 2025
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                if fmt == "%Y":
                    return dt.strftime("%Y")
                if fmt in ("%Y-%m", "%Y/%m"):
                    return dt.strftime("%Y-%m")
                if fmt in ("%B %Y", "%b %Y"):
                    return dt.strftime("%Y-%m")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # Last-ditch fallback: try to extract a 4-digit year or date string
        m = re.search(r"(19|20)\d{2}(-\d{2}-\d{2})?", date_str)
        if m:
            date_val = m.group(0)
            return date_val if len(date_val) == 10 else date_val[:4]

        # No luck
        return None

    def _close_session(self):
        """Properly close the session if it exists."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
            finally:
                self.session = None

    def __del__(self):
        """Cleanup when object is destroyed."""
        self._close_session()

    @staticmethod
    def get_title_tokens(
        title: str, strip_joiners: bool = True
    ) -> Generator[str, None, None]:
        """
        Taken from calibre source code
        It's a simplified (cut out what is unnecessary) version of
        https://github.com/kovidgoyal/calibre/blob/99d85b97918625d172227c8ffb7e0c71794966c0/
        src/calibre/ebooks/metadata/sources/base.py#L363-L367
        (src/calibre/ebooks/metadata/sources/base.py - lines 363-398)
        """
        title_patterns = [
            (re.compile(pat, re.IGNORECASE), repl)
            for pat, repl in [
                # Remove things like: (2010) (Omnibus) etc.
                (
                    r"(?i)[({\[](\d{4}|omnibus|anthology|hardcover|"
                    r"audiobook|audio\scd|paperback|turtleback|"
                    r"mass\s*market|edition|ed\.)[\])}]",
                    "",
                ),
                # Remove any strings that contain the substring edition inside
                # parentheses
                (r"(?i)[({\[].*?(edition|ed.).*?[\]})]", ""),
                # Remove commas used a separators in numbers
                (r"(\d+),(\d+)", r"\1\2"),
                # Remove hyphens only if they have whitespace before them
                (r"(\s-)", " "),
                # Replace other special chars with a space
                (r"""[:,;!@$%^&*(){}.`~"\s\[\]/]《》「」“”""", " "),
            ]
        ]

        for pat, repl in title_patterns:
            title = pat.sub(repl, title)

        tokens = title.split()
        for token in tokens:
            token = token.strip().strip('"').strip("'")
            if token and (
                not strip_joiners or token.lower() not in ("a", "and", "the", "&")
            ):
                yield token

    def get_detail_records(
        self, links: Iterable[str], generic_cover: str
    ) -> list[MetaRecord]:
        """Fetch detailed metadata records in parallel from a list of links.

        Args:
            links (Iterable[str]): List of URLs to fetch metadata from.
            generic_cover (str): Path to generic cover image.

        Returns:
            list[MetaRecord]: List of fetched MetaRecord objects in the order returned by the provider.
        """

        links_list = list(links)
        if len(links_list) == 0:
            return []

        futures = {
            self._thread_pool.submit(self.parse_detail_page, link, generic_cover, index)
            for index, link in enumerate(links_list[: self.MAX_SEARCH_RESULTS])
        }

        try:
            values = list(
                filter(
                    lambda v: v,
                    map(
                        lambda x: x.result(),
                        concurrent.futures.as_completed(futures, timeout=15),
                    ),
                )
            )
        except concurrent.futures.TimeoutError as te:
            log.warning(
                f"Timeout while fetching detail pages from {self.__name__}: {te}"
            )
            return []

        # Sort results by original source index to maintain order for best relevance
        return [x[0] for x in sorted(values, key=lambda t: t[1])]

    def validate_isbn(self, isbn: str) -> str | None:
        """Validate and clean ISBN format."""
        if not isbn or not isinstance(isbn, str):
            return None

        # Clean ISBN: remove hyphens, spaces, and convert to uppercase
        clean_isbn = re.sub(r"[^0-9X]", "", isbn.strip().upper())

        # Check if it's ISBN-10 or ISBN-13
        total = 0
        if len(clean_isbn) == 10:
            for i, ch in enumerate(clean_isbn):
                if i == 9 and ch == "X":
                    val = 10
                elif ch.isdigit():
                    val = int(ch)
                else:
                    return None
                total += val * (10 - i)
            if total % 11 == 0:
                return clean_isbn
        elif len(clean_isbn) == 13:
            if clean_isbn[:3] not in ("978", "979"):
                return None
            for i, ch in enumerate(clean_isbn):
                if not ch.isdigit():
                    return None
                val = int(ch)
                total += val * (1 if i % 2 == 0 else 3)
            if total % 10 == 0:
                return clean_isbn

        return None

    def clean_description(self, text: str, strip_html=False) -> str:
        """Clean and sanitize description text."""
        if not text:
            return ""

        t = str(text).strip()
        if not t:
            return ""

        # Normalize various types of whitespace
        t = t.replace("\u00a0", " ")  # Non-breaking space
        t = t.replace("\u2009", " ")  # Thin space
        t = t.replace("\u200b", "")  # Zero-width space
        t = re.sub(r"[\t ]+", " ", t).strip()

        # Unescape common escaped characters
        t = re.sub(r"\\([#@%&*~`])", r"\1", t)

        # Remove excessive newlines but preserve paragraph breaks
        t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)

        if strip_html:
            # Remove any HTML tags that might remain
            try:
                # Use BeautifulSoup to properly strip HTML
                clean_soup = BS(t, "lxml")
                t = clean_soup.get_text(" ", strip=True)
            except Exception:
                # Fallback: simple HTML tag removal
                t = re.sub(r"<[^>]+>", " ", t)

            # Limit length to prevent extremely long descriptions
            max_length = 5000
            if len(t) > max_length:
                t = t[: max_length - 3].rsplit(" ", 1)[0] + "..."

        return t

    def safe_get(
        self, data: dict[K, V], *keys: K, default: V | None = None
    ) -> V | dict[K, V] | None:
        """Safely get a nested value from a dictionary.

        Args:
            data (dict[str, any]): The dictionary to retrieve the value from.
            *keys (str): Sequence of keys to traverse the nested dictionary.
            default (any|None, optional): Default value to return if any key is missing. Defaults to None.
        Returns:
            any|None: The retrieved value or the default if any key is missing.
        """
        try:
            value: V | dict[K, V] | None = data
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            return value
        except (TypeError, KeyError):
            return default

    def get_language_name(
        self, lang_code: str, locale: str = constants.DEFAULT_LOCALE
    ) -> str:
        """Get the full language display name from a language code.

        Args:
            lang_code (str): ISO 639-1 or ISO 639-3 language code.
            locale (str, optional): Locale for language name.
        Returns:
            str: Full language name or empty string if not found.
        """
        if len(lang_code) < 2 or len(lang_code) > 3:
            return ""

        lang_code = lang_code.lower()
        if len(lang_code) == 2:
            lang_code = isoLanguages.get_lang3(lang_code)

        return isoLanguages.get_language_name(locale, lang_code)
