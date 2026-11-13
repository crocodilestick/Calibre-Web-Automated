# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import concurrent.futures
import re
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

# Amazon stores selectable in the CWA settings (metadata_amazon_domain), with
# the Accept-Language header sent to each one. Japan has its own provider (amazonjp).
AMAZON_DOMAINS = {
    "com": "en-US,en;q=0.9",
    "co.uk": "en-GB,en;q=0.9",
    "ca": "en-CA,en;q=0.9,fr-CA;q=0.8",
    "com.au": "en-AU,en;q=0.9",
    "in": "en-IN,en;q=0.9",
    "de": "de-DE,de;q=0.9,en;q=0.5",
    "fr": "fr-FR,fr;q=0.9,en;q=0.5",
    "it": "it-IT,it;q=0.9,en;q=0.5",
    "es": "es-ES,es;q=0.9,en;q=0.5",
    "nl": "nl-NL,nl;q=0.9,en;q=0.5",
    "com.br": "pt-BR,pt;q=0.9,en;q=0.5",
    "com.mx": "es-MX,es;q=0.9,en;q=0.5",
}
DEFAULT_AMAZON_DOMAIN = "com"

# "Book 2 of 5: Series", "Libro 2 di 5: Serie", "Buch 2 von 5: Reihe", "Tome 2 sur 5 : Série"...
SERIES_RE = re.compile(
    r'(?:Book|Libro|Buch|Band|Tome|Livre|Boek|Deel|Livro)\s+(\d+)'
    r'(?:\s+(?:of|di|de|von|aus|sur|van|do)\s+\d+)?\s*:\s*(.+)',
    re.IGNORECASE,
)


def normalize_amazon_domain(value) -> str:
    """Return a supported Amazon domain suffix ("com", "it", "co.uk"...), defaulting to amazon.com."""
    value = str(value or "").strip().lower()
    for prefix in ("https://", "http://", "www.", "amazon."):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = value.strip("/")
    return value if value in AMAZON_DOMAINS else DEFAULT_AMAZON_DOMAIN


def get_amazon_domain() -> str:
    """Read the configured Amazon store from the CWA settings."""
    try:
        from scripts.cwa_db import CWA_DB  # imported here to avoid circular imports
        return normalize_amazon_domain(CWA_DB().cwa_settings.get("metadata_amazon_domain"))
    except Exception as e:
        log.debug(f"Could not read metadata_amazon_domain, using amazon.{DEFAULT_AMAZON_DOMAIN}: {e}")
        return DEFAULT_AMAZON_DOMAIN


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
        domain = get_amazon_domain()
        store_url = f"https://www.amazon.{domain}"
        request_headers = {"Accept-Language": AMAZON_DOMAINS[domain]}

        def inner(link, index) -> [dict, int]:
            if link.startswith("/sspa/") or link.startswith(("http://", "https://")):
                return []  # sponsored/ad links are not book pages

            # Ensure link starts with / for proper URL construction
            if not link.startswith('/'):
                link = f"/{link}"

            try:
                r = self.session.get(f"{store_url}{link}", headers=request_headers, timeout=10)
                r.raise_for_status()
            except Exception as ex:
                log.warning(ex)
                return []
            
            # Try lxml first (faster), fallback to html.parser if needed
            try:
                long_soup = BS(r.text, "lxml")
            except Exception:
                long_soup = BS(r.text, "html.parser")
            
            soup2 = long_soup.find("div", attrs={"id": "dp-container"})
            if soup2 is None:
                return []
            if soup2.find("input", attrs={"name": "submit.preorder"}) is not None:
                log.debug(f"Skipping pre-order page: {store_url}{link}")
                return []  # pre-order page, ignore
            try:
                match = MetaRecord(
                    title = "",
                    authors = [],
                    source=MetaSourceInfo(
                        id=self.__id__,
                        description="Amazon Books",
                        link=f"https://amazon.{domain}/"
                    ),
                    url = f"{store_url}{link}",
                    #the more searches the slower, these are too hard to find in reasonable time or might not even exist
                    publisher= "",  # very unreliable
                    publishedDate= "",  # very unreliable
                    id = None,  # ?
                    tags = []  # dont exist on amazon
                )

                try:
                    desc_div = soup2.find("div", attrs={"data-feature-name": "bookDescription"})
                    if desc_div and desc_div.div and desc_div.div.div:
                        match.description = "<div>" + \
                            "\n".join([
                                str(node) for node in desc_div.div.div.children
                            ]) + \
                            "</div>"
                    else:
                        return []  # if there is no description it is not a book and therefore should be ignored
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
                    match.authors = []
                try:
                    match.rating = int(
                        soup2.find(attrs={"id": "acrPopover"})["title"].split(" ")[0].split(".")[
                            0])  # first number in string
                except (AttributeError, ValueError, TypeError):
                    match.rating = 0
                try:
                    asin = soup2.find("input", attrs={"type": "hidden", "name": lambda x: x and x.lower()=="asin"})["value"]
                    match.identifiers = {"amazon": asin, "mobi-asin": asin}
                except (AttributeError, TypeError):
                    match.identifiers = {}
                try:
                    series_link = soup2.find(attrs={"data-feature-name": "seriesBulletWidget"})
                    if series_link:
                        series_text = series_link.find("a")
                        if series_text:
                            series_str = str(series_text.text).strip()
                            # Match patterns like "Book X of Y: Series Title" or "Book X: Series Title"
                            series_match = SERIES_RE.search(series_str)
                            if series_match:
                                match.series_index = int(series_match.group(1))
                                match.series = series_match.group(2).strip()
                            else:
                                match.series = None
                                match.series_index = None
                        else:
                            match.series = None
                            match.series_index = None
                    else:
                        match.series = None
                        match.series_index = None
                except (AttributeError, ValueError, TypeError):
                    match.series = None
                    match.series_index = None
                try:
                    cover_src = ""
                    # Look for the high-res cover image first
                    high_res_re = re.compile(r'"hiRes":"([^"]+)","thumb"')
                    for script in soup2.find_all("script"):
                        m = high_res_re.search(script.text or "")
                        if m:
                            cover_src = m.group(1)
                            break
                    if not cover_src:
                        # Fallback to the standard image
                        cover_src = soup2.find("img", attrs={"class": "a-dynamic-image"})["src"]
                    match.cover = cover_src
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
                'sort': 'relevanceexprank',
                'search-alias': 'stripbooks',
                'i': 'digital-text',
                'field-keywords': query,
            }

            try:
                results = self.session.get(
                    f"{store_url}/s",
                    params=q,
                    headers=request_headers,
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
                    # Amazon often appends tracking parameters to URLs, strip them for
                    # deduplication. The URL alone is sufficient.
                    base_url = a["href"].split("?")[0]
                    if base_url not in links_list:
                        links_list.append(base_url)
            if len(links_list) == 0:
                log.info(f"No amazon.{domain} search results found for query: {query}")
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
