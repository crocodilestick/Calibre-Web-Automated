# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import re
from typing import override

from bs4 import BeautifulSoup as BS
from bs4.element import NavigableString

try:
    import cchardet  # noqa: F401 optional for better speed
except ImportError:
    pass

from cps import config, constants
import cps.logger as logger
from cps.services.Metadata import Metadata, MetaRecord, MetaSourceInfo
from ..cw_login import current_user

log = logger.create()


class Amazon(Metadata):
    """Metadata provider for Amazon and its country-specific domains."""

    @property
    def __name__(self) -> str:
        if self.amazon_region() == "com":
            return "Amazon"
        return f"Amazon{self.amazon_region().split('.')[-1].capitalize()}"

    @property
    def __id__(self) -> str:
        if self.amazon_region() == "com":
            return "amazon"
        return f"amazon_{self.amazon_region().split('.')[-1]}"

    @override
    def base_url(self) -> str:
        return f"https://www.amazon.{self.amazon_region()}"

    def series_regex(self) -> str:
        """Return the regex to parse series information.

        Must have a named group 'index' for the series number and 'series' for the series name.
        """
        return {
            "co.jp": r"全(?P<total>\d+)巻[の中]第(?P<index>\d+)巻:\s*(?P<series>.+)",
        }.get(self.amazon_region(), r"Book\s+(?P<index>\d+)(?:\s+of\s+\d+)?:\s*(?P<series>.+)")

    def amazon_region(self) -> str:
        """Return the Amazon domain."""
        return getattr(current_user, "amazon_region", None) or getattr(
            config, "amazon_region", constants.AMAZON_REGIONS[0]
        )

    @override
    def language_codes(self) -> list[str]:
        return {
            "com": ["en-US", "en"],
            "co.uk": ["en-GB", "en"],
            "ca": ["en-CA", "en", "fr-CA", "fr"],
            "de": ["de-DE", "de"],
            "fr": ["fr-FR", "fr"],
            "it": ["it-IT", "it"],
            "es": ["es-ES", "es"],
            "co.jp": ["ja-JP", "ja"],
            "com.au": ["en-AU", "en"],
            "com.br": ["pt-BR", "pt"],
            "com.mx": ["es-MX", "es"],
        }.get(self.amazon_region(), ["en-US", "en"])

    def _parse_title(self, container: BS) -> str | None:
        try:
            return container.find("span", attrs={"id": "productTitle"}).get_text(
                strip=True
            )
        except (AttributeError, TypeError) as e:
            log.warning(f"Could not parse title from {self.__name__} page: {e}")
            return None

    def _parse_authors(self, container: BS) -> list[str]:
        try:
            return [
                next(
                    filter(
                        lambda i: i.strip() != "" and not i.startswith("{"),
                        x.find_all(string=True),
                    )
                ).strip()
                for x in container.find_all("span", attrs={"class": "author"})
            ]
        except (AttributeError, TypeError, StopIteration) as e:
            log.warning(f"Could not parse authors from {self.__name__} page: {e}")
            return []

    def _parse_description(self, container: BS) -> str | None:
        try:
            return self.clean_description(
                "<div>"
                + "\n".join(
                    [
                        str(node)
                        for node in container.find(
                            "div", attrs={"data-feature-name": "bookDescription"}
                        )
                        .select_one("div.a-expander-content")
                        .children
                    ]
                )
                + "</div>"
            )
        except (AttributeError, TypeError) as e:
            log.warning(f"Could not parse description from {self.__name__} page: {e}")
            return None

    def _parse_rating(self, container: BS) -> int:
        try:
            return int(
                container.find(attrs={"id": "acrPopover"})["title"]
                .split(" ")[0]
                .split(".")[0]
            )  # first number in string
        except (AttributeError, ValueError, TypeError) as e:
            log.warning(f"Could not parse rating from {self.__name__} page: {e}")
            return 0

    def _parse_asin(self, container: BS) -> str | None:
        try:
            return container.find(
                "input",
                attrs={
                    "type": "hidden",
                    "name": lambda x: x and x.lower() == "asin",
                },
            )["value"]
        except (AttributeError, TypeError) as e:
            log.warning(f"Could not parse ASIN from {self.__name__} page: {e}")
            return None

    def _parse_series_info(self, container: BS) -> tuple[str, int] | None:
        try:
            series_text = str(
                container.find(attrs={"data-feature-name": "seriesBulletWidget"})
                .find("a")
                .get_text(strip=True)
            )
            if series_text:
                # Match patterns like "Book X of Y: Series Title" or "Book X: Series Title"
                series_match = re.search(self.series_regex(), series_text, re.IGNORECASE)
                if series_match:
                    return (
                        series_match.group("series").strip(),
                        int(series_match.group("index").strip()),
                    )
        except (AttributeError, ValueError, TypeError) as e:
            log.warning(f"Could not parse series info from {self.__name__} page: {e}")

        return None

    def _parse_cover(self, container: BS) -> str | None:
        try:
            high_res_re = re.compile(r'"?hiRes"?:\s*"([^"]+)",', re.MULTILINE)
            for script in container.find_all("script"):
                m = high_res_re.search(script.text or "")
                if m:
                    return m.group(1)

            # If we get here, no high-resolution image was found so take the thumbnail
            return container.find(
                "img", attrs={"id": "imgBlkFront", "class": "a-dynamic-image"}
            )["src"]
        except (AttributeError, TypeError) as e:
            log.warning(f"Could not parse cover from {self.__name__} page: {e}")
            return None

    def _parse_publisher(self, container: BS) -> str | None:
        try:
            if self.amazon_region() == "co.jp":
                return (
                    container.find(
                        "div",
                        attrs={"data-rpi-attribute-name": "book_details-publisher"},
                    )
                    .find("div", attrs={"class": "rpi-attribute-value"})
                    .span.get_text(strip=True)
                )
            else:
                detail_items = container.find(
                    attrs={"id": "detailBullets_feature_div"}
                ).ul.children

                for li in detail_items:
                    if isinstance(li, NavigableString):
                        continue

                    label = li.find("span", attrs={"class": "a-text-bold"})
                    if label and label.get_text(strip=True).startswith("Publisher"):
                        publisher_text = label.find_next("span").get_text(strip=True)
                        return publisher_text
        except (AttributeError, TypeError) as e:
            log.warning(f"Could not parse publisher from {self.__name__} page: {e}")

        return None

    def _parse_pubished_date(self, container: BS) -> str | None:
        try:
            pub_date_text = (
                container.find(
                    "div", attrs={"id": "rpi-attribute-book_details-publication_date"}
                )
                .select_one("div.rpi-attribute-value > span")
                .get_text(strip=True)
            )

            return self._normalize_date(pub_date_text)
        except (AttributeError, TypeError) as e:
            log.warning(
                f"Could not parse published date from {self.__name__} page: {e}"
            )
        except ValueError as e:
            log.warning(
                f"Could not normalize published date '{pub_date_text}' from {self.__name__} page: {e}"
            )

        return None

    def parse_detail_page(
        self, detail_uri: str, generic_cover: str | None, index: int
    ) -> tuple[MetaRecord, int] | None:
        # /sspa/ links are not book pages
        if detail_uri.startswith("/sspa/"):
            return None

        # Ensure link starts with / for proper URL construction
        if not detail_uri.startswith("http"):
            if not detail_uri.startswith("/"):
                detail_uri = f"/{detail_uri}"
            detail_uri = f"{self.base_url()}{detail_uri}"
        else:
            detail_uri = detail_uri.replace("http://", "https://")

        log.debug(f"Fetching {self.__name__} detail page: {detail_uri}")

        detail_soup = self.get(detail_uri)
        if detail_soup is None:
            log.warning(f"Could not fetch {self.__name__} detail page: {detail_uri}")
            return None

        container = detail_soup.find("div", attrs={"id": "dp-container"})
        if container is None:
            log.warning(
                f"No detail container found on {self.__name__} page: {detail_uri}"
            )
            return None

        if container.find("input", attrs={"name": "submit.preorder"}) is not None:
            log.debug(f"Skipping {self.__name__} pre-order page: {detail_uri}")
            return None

        title = self._parse_title(container)
        if not title:
            log.warning(f"No title found on {self.__name__} page: {detail_uri}")
            return None

        description = self._parse_description(container)
        if not description:
            log.debug(f"No description found on {self.__name__} page: {detail_uri}")
            return None

        match = MetaRecord(
            title=title,
            authors=self._parse_authors(container),
            description=description,
            rating=self._parse_rating(container),
            source=MetaSourceInfo(
                id=self.__id__, description=self.__name__, link=self.base_url()
            ),
            url=detail_uri,
            publisher=self._parse_publisher(container),
            publishedDate=self._parse_pubished_date(container),
            # This requires the whole page since looking for the high-res cover depends on loading the various script
            # elements on the page.
            cover=self._parse_cover(detail_soup) or generic_cover,
            id=None,
            tags=[],
        )

        asin = self._parse_asin(container)
        if asin:
            match.id = asin
            match.identifiers = {"mobi-asin": asin}
            id_key = (
                "amazon"
                if self.amazon_region() == "com"
                else f"amazon_{self.amazon_region().split('.')[-1]}"
            )
            match.identifiers[id_key] = asin

        series_info = self._parse_series_info(container)
        if series_info:
            match.series, match.series_index = series_info

        return (match, index)

    def parse_search_results(self, search_results: BS) -> set[str]:
        links: set[str] = set()

        for result in search_results.find_all(
            attrs={"data-component-type": "s-search-results"}
        ):
            for a in result.find_all("a", href=lambda x: x and "digital-text" in x):
                # Amazon often appends tracking parameters to URLs, strip them for
                # deduplication. The URL alone is sufficient.
                # TODO: Can we also simplify the URL? Typically there's an ASIN embedded in the URL after '/gp/' or
                # '/dp/'and the URL can be reduced to https://www.amazon.{domain}/dp/{ASIN}, but is that consistent
                # across all Amazon local stores?
                base_url = a["href"].split("?")[0]
                links.add(base_url)

        return links

    @override
    def search(
        self,
        query: str,
        generic_cover: str = "",
        locale: str = constants.DEFAULT_LOCALE,
    ) -> list[MetaRecord] | None:
        if not self.active:
            return None

        q = {
            "unfiltered": "1",
            "sort": "relevanceexprank",
            "search-alias": "stripbooks",
            "i": "digital-text",
            "field-keywords": query,
        }

        search_results_page = self.get(f"{self.base_url()}/s", params=q)
        links_list = self.parse_search_results(search_results_page)

        return self.get_detail_records(links_list, generic_cover)
