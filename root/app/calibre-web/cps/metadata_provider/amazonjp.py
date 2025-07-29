# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2025 quarz12, Hobogrammer
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
import cps.logger as logger
import concurrent.futures
import re
import requests

from bs4 import BeautifulSoup as BS
from datetime import datetime
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from operator import itemgetter
from typing import List, Optional

log = logger.create()

class AmazonJp(Metadata):
    __name__ = "AmazonJp"
    __id__ = "amazonjp"
    headers = {'upgrade-insecure-requests': '1',
               'user-agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
               'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8',
               'Sec-Fetch-Site': 'same-origin',
               'Sec-Fetch-Mode': 'navigate',
               'Sec-Fetch-User': '?1',
               'Sec-Fetch-Dest': 'document',
               'Upgrade-Insecure-Requests': '1',
               'Alt-Used' : 'www.amazon.co.jp',
               'Priority' : 'u=0, i',
               'accept-encoding': 'gzip, deflate, br, zstd',
               'accept-language': 'ja-JP,ja;q=0.9'}
    session = requests.Session()
    session.headers=headers

    def search(
        self, query: str, generic_cover: str = "", locale: str = "ja"
    ) -> Optional[List[MetaRecord]]:
        def inner(link, index) -> [dict, int]:
            with self.session as session:
                try:
                    r = session.get(f"https://www.amazon.co.jp/{link}")
                    r.raise_for_status()
                except Exception as ex:
                    log.warning(ex)
                    return []
                long_soup = BS(r.text, "lxml")
                soup2 = long_soup.find("div", attrs={"cel_widget_id": "dpx-ppd_csm_instrumentation_wrapper"})
                if soup2 is None:
                    return []
                try:
                    match = MetaRecord(
                        title = "",
                        authors = "",
                        source=MetaSourceInfo(
                            id=self.__id__,
                            description="Amazon Japan",
                            link="https://amazon.co.jp/"
                        ),
                        url = f"https://www.amazon.co.jp{link}",
                        id = None,
                        tags = []  # N/A
                    )

                    match.description = self._parse_description(soup2)

                    # If there is no description the result is not a book and should be ignored
                    if not match.description:
                        return []

                    match.authors = self._parse_authors(soup2)
                    match.cover = self._parse_cover(soup2, generic_cover)
                    match.identifiers = self._parse_identifiers(soup2)
                    match.publishedDate = self._parse_published_date(soup2)
                    match.publisher = self._parse_publisher(soup2)
                    match.rating = self._parse_rating(soup2)
                    match.series, match.series_index = self._parse_series_name_and_index(soup2)
                    match.title = self._parse_title(soup2)

                    return match, index
                except Exception as e:
                    log.error_or_exception(e)
                    return []

        val = list()
        if self.active:
            try:
                results = self.session.get(
                    f"https://www.amazon.co.jp/s?k={query.replace(' ', '+')}&i=digital-text&sprefix={query.replace(' ', '+')}"
                    f"%2Cdigital-text&ref=nb_sb_noss",
                    headers=self.headers)
                results.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log.error_or_exception(e)
                return []
            except Exception as e:
                log.warning(e)
                return []
            soup = BS(results.text, 'html.parser')
            links_list = [next(filter(lambda i: "digital-text" in i["href"], x.findAll("a")))["href"] for x in
                          soup.findAll("div", attrs={"data-component-type": "s-search-result"})]
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                fut = {executor.submit(inner, link, index) for index, link in enumerate(links_list[:10])}
                val = list(map(lambda x : x.result(), concurrent.futures.as_completed(fut)))
        result = list(filter(lambda x: x, val))
        return [x[0] for x in sorted(result, key=itemgetter(1))] #sort by amazons listing order for best relevance

    def _parse_authors(self, result) -> str:
        try:
            return [next(
                filter(lambda i: i != " " and i != "\n" and not i.startswith("{"),
                       x.findAll(string=True))).strip()
                            for x in result.findAll("span", attrs={"class": "author"})]
        except (AttributeError, TypeError, StopIteration):
            return ""

    def _parse_cover(self, result, generic_cover) -> str:
        try:
            cover_url = result.find("img", attrs={"id": "landingImage", "class": "a-dynamic-image"})["data-old-hires"]
            if not cover_url: # Fallback in case there is no hi-res cover
                cover_url = result.find("img", attrs={"id": "landingImage"})["src"]
            
            # Remove Amazon's dynamic sizing from url to get full sized image
            # ex: 1234._SX466_SY466_.jpg -> 1234.jpg
            return re.sub(r'(\._.*_\.)', '.', cover_url)
        except (AttributeError, TypeError):
            return generic_cover

    def _parse_description(self, result) -> Optional[str]:
        try:
            return "\n".join(
                result.find("div", attrs={"data-feature-name": "bookDescription"}).stripped_strings)\
                        .replace("\xa0"," ")[:-9].strip().strip("\n")
        except (AttributeError, TypeError):
            return ""

    def _parse_identifiers(self, result) -> dict:
        try:
            amazon_jp = result.find("div", attrs={"id": "averageCustomerReviews"})["data-asin"].strip()
            if amazon_jp:
                return {"amazon_jp": amazon_jp}

            return {}
        except (AttributeError, TypeError):
            return {}

    def _parse_published_date(self, result) -> str:
        try:
            published_date = result.find("div", attrs={"data-rpi-attribute-name": "book_details-publication_date"})\
                        .find("div", attrs={"class": "rpi-attribute-value"}).span.text.strip()
            return datetime.strptime(published_date, '%Y/%m/%d').strftime('%Y-%m-%d')
        except (AttributeError, TypeError):
            return ""

    def _parse_publisher(self, result) -> str:
        try:
            return result.find("div", attrs={"data-rpi-attribute-name": "book_details-publisher"})\
                        .find("div", attrs={"class": "rpi-attribute-value"}).span.text.strip()
        except (AttributeError, TypeError):
            return ""

    def _parse_rating(self, result) -> int:
        try:
            return int(round(float(result.find("div", attrs={"id": "averageCustomerReviews"}).a.span.text)))
        except (AttributeError, ValueError):
            return 0

    def _parse_series_name_and_index(self, result) -> tuple[str, int]:
        try:
            series_link = result.find("div", attrs={"id": "seriesBulletWidget_feature_div"}).a
            if series_link:
                series_string = series_link.contents[0]
                expression_match = re.search(r'全(?P<total>\d+)巻[の中]第(?P<index>\d+)巻:\s*(?P<series>.+)', series_string.strip())
                if expression_match:
                    series = expression_match.group('series').strip()
                    series_index = int(expression_match.group('index'))
                    return series, series_index
            else:
                return "", 0
        except (AttributeError, TypeError, ValueError):
            return "", 0

    def _parse_title(self, result) -> str:
        try:
            return result.find("span", attrs={"id": "productTitle"}).text
        except (AttributeError, TypeError):
           return ""
