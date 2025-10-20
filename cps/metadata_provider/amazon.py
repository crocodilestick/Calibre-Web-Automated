# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import concurrent.futures
import requests
from bs4 import BeautifulSoup as BS  # requirement
from typing import List, Optional

try:
    import cchardet #optional for better speed
except ImportError:
    pass

from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
import cps.logger as logger

#from time import time
from operator import itemgetter
log = logger.create()


class Amazon(Metadata):
    __name__ = "Amazon"
    __id__ = "amazon"
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
    }
    session = requests.Session()
    session.headers=headers

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        def inner(link, index) -> [dict, int]:
            try:
                r = self.session.get(f"https://www.amazon.com{link}", timeout=10)
                r.raise_for_status()
            except Exception as ex:
                log.warning(ex)
                return []
            long_soup = BS(r.text, "html.parser")  #~4sec :/
            soup2 = long_soup.find("div", attrs={"id": "dp-container"})
            if soup2 is None:
                return []
            try:
                match = MetaRecord(
                    title = "",
                    authors = "",
                    source=MetaSourceInfo(
                        id=self.__id__,
                        description="Amazon Books",
                        link="https://amazon.com/"
                    ),
                    url = f"https://www.amazon.com{link}",
                    #the more searches the slower, these are too hard to find in reasonable time or might not even exist
                    publisher= "",  # very unreliable
                    publishedDate= "",  # very unreliable
                    id = None,  # ?
                    tags = []  # dont exist on amazon
                )

                try:
                    match.description = "\n".join(
                        soup2.find("div", attrs={"data-feature-name": "bookDescription"}).stripped_strings)\
                                            .replace("\xa0"," ")[:-9].strip().strip("\n")
                except (AttributeError, TypeError):
                    return []  # if there is no description it is not a book and therefore should be ignored
                try:
                    match.title = soup2.find("span", attrs={"id": "productTitle"}).text
                except (AttributeError, TypeError):
                    match.title = ""
                try:
                    match.authors = [next(
                        filter(lambda i: i != " " and i != "\n" and not i.startswith("{"),
                                x.findAll(string=True))).strip()
                                    for x in soup2.findAll("span", attrs={"class": "author"})]
                except (AttributeError, TypeError, StopIteration):
                    match.authors = ""
                try:
                    match.rating = int(
                        soup2.find("span", class_="a-icon-alt").text.split(" ")[0].split(".")[
                            0])  # first number in string
                except (AttributeError, ValueError):
                    match.rating = 0
                try:
                    match.cover = soup2.find("img", attrs={"class": "a-dynamic-image"})["src"]
                except (AttributeError, TypeError):
                    match.cover = ""
                return match, index
            except Exception as e:
                log.error_or_exception(e)
                return []

        val = list()
        if self.active:
            q = {
                'unfiltered': '1',
                's': 'relevanceexprank',
                'i': 'digital-text',
                'k': query,
            }

            try:
                results = self.session.get(
                    "https://www.amazon.com/s",
                    params=q,
                    # headers=self.headers,
                    timeout=10,
                )
                results.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log.error_or_exception(e)
                return []
            except Exception as e:
                log.warning(e)
                return []
            soup = BS(results.text, 'html.parser')
            links_list = []
            for result in soup.find_all(attrs={"data-component-type": "s-search-results"}):
                for a in result.find_all("a", href=lambda x: x and "digital-text" in x):
                    if a["href"] not in links_list:
                        links_list.append(a["href"])
            if len(links_list) == 0:
                return []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                fut = {executor.submit(inner, link, index) for index, link in enumerate(links_list[:3])}
                try:
                    val = list(map(lambda x : x.result(), concurrent.futures.as_completed(fut, timeout=15)))
                except concurrent.futures.TimeoutError:
                    log.warning("Amazon search timeout after 15 seconds")
                    val = []
        result = list(filter(lambda x: x, val))
        return [x[0] for x in sorted(result, key=itemgetter(1))] #sort by amazons listing order for best relevance
