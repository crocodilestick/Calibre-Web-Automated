from bs4 import BeautifulSoup
from cps import logger
from cps.isoLanguages import get_lang3, get_language_name
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata
from typing import List, Optional
from urllib.parse import quote
import concurrent.futures
import json
import random
import re
import requests

log = logger.create()


class DatabazeKnih(Metadata):
    __name__ = "Databáze Knih"
    __id__ = "databazeknih"
    DESCRIPTION = "Databáze Knih"
    META_URL = "https://www.databazeknih.cz/"
    SEARCH_URL = "https://www.databazeknih.cz/search"
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:90.0) Gecko/20100101 Firefox/90.0",
        "Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0",
        "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.77 Mobile Safari/537.36"
    ]

    def get_headers(self):
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
        }

    def search(
        self, query: str, generic_cover: str = "", locale: str = "en"
    ) -> Optional[List[MetaRecord]]:
        """
        Search databazeknih.cz for books matching the query using Google search, then scrape metadata for each result.
        """

        def search_links(query: str) -> list:
            url = f"{self.SEARCH_URL}?q={quote(query)}"
            headers = self.get_headers()

            try:
                response = requests.post(url, headers=headers, timeout=10)
                response.raise_for_status()
            except requests.RequestException as e:
                print("Request failed:", e)
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            links = []
            for result in soup.select("a"):
                href = result['href']
                if href and '/prehled-knihy/' in href:
                    links.append(href)

            return list(set(links))

        def parse_title(script_tag, soup):
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'name' in json_data:
                        return json_data['name']
                except json.JSONDecodeError:
                    pass
            # Fallback to parsing title from the page
            return ''.join(soup.find('h1').find_all(text=True, recursive=False)).strip()

        def parse_authors(script_tag, soup):
            authors = []
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'author' in json_data:
                        authors = [author['name'] for author in json_data['author']] if isinstance(
                            json_data['author'], list) else [json_data['author']['name']]
                except json.JSONDecodeError:
                    pass
            if len(authors) > 0:
                return authors
            # Fallback to parsing authors from the page
            for author in soup.select("a[href*='/autori/']"):
                author_name = author.get_text(strip=True)
                if author_name:
                    authors.append(author_name)
            return list(set(authors))

        def parse_description(script_tag, soup):
            description_tag = soup.find('p', class_='new2 odtop')
            if description_tag:
                for hidden in description_tag.select('.show_hide_more'):
                    hidden.decompose()
                return description_tag.get_text(separator=' ', strip=True)
            # Fallback to parsing description script tag (Not whole)
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'description' in json_data:
                        return json_data['description']
                except json.JSONDecodeError:
                    pass

        def parse_series(soup):
            series_tag = soup.select_one("a[href*='/serie/']")
            if series_tag:
                return series_tag.get_text(strip=True)
            return None

        def parse_series_index(soup):
            series_tag = soup.select_one("a[href*='/serie/']")
            if series_tag and 'href' in series_tag.attrs:
                parent = series_tag.find_parent()
                if parent:
                    next_sibling = parent.find_next_sibling()
                    if next_sibling:
                        series_index = re.search(
                            r'\d+', next_sibling.get_text(strip=True))
                        if series_index:
                            return int(series_index.group())
            return 0

        def parse_publisher(script_tag):
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'publisher' in json_data:
                        return json_data['publisher'][0]['name'] if isinstance(json_data['publisher'], list) else json_data['publisher']
                except json.JSONDecodeError:
                    pass
            return None

        def parse_tags(soup):
            tags = []
            for tag in soup.select("a[href*='/stitky/']"):
                tag_name = tag.get_text(strip=True)
                if tag_name:
                    tags.append(tag_name)
            return tags

        def parse_rating(script_tag, soup):
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'aggregateRating' in json_data:
                        return int(float(json_data['aggregateRating']['ratingValue']))
                except json.JSONDecodeError:
                    pass
            # Fallback to parsing rating from the page
            rating_tag = soup.select_one("a[href*='/hodnoceni-knihy/']")
            if rating_tag:
                rating_text = rating_tag.get_text(strip=True)
                match = re.search(r'\d+', rating_text)
                if match:
                    return int(match.group()) // 20
            return 0

        def parse_language(script_tag):
            if script_tag:
                try:
                    json_data = json.loads(script_tag.string)
                    if isinstance(json_data, dict) and 'inLanguage' in json_data:
                        return [get_language_name(locale, get_lang3(json_data['inLanguage']))]
                except json.JSONDecodeError:
                    pass
            return []

        def parse_cover(soup):
            cover_tag = soup.find(id='icover_mid')
            if cover_tag and cover_tag.img and cover_tag.img.has_attr('src'):
                return cover_tag.img['src']
            return generic_cover

        def extract_isbn(soup):
            scripts = soup.select('script')
            for script in scripts:
                if 'window.dataLayer' in script.text:
                    match = re.search(r"isbn:\s*'([^']+)'", script.text)
                    if match:
                        return match.group(1)
            return None

        def extract_data(url: str) -> Optional[MetaRecord]:
            url = f"{self.META_URL}{url.lstrip('/')}"
            headers = self.get_headers()

            try:
                response = requests.post(url, headers=headers, timeout=10)
                response.raise_for_status()
            except requests.RequestException as e:
                print("Request failed:", e)
                return []

            soup = BeautifulSoup(response.text, "lxml")
            script_tag = soup.find('script', type='application/ld+json')

            title = parse_title(script_tag, soup)
            authors = parse_authors(script_tag, soup)
            description = parse_description(script_tag, soup)
            series = parse_series(soup)
            series_index = parse_series_index(soup)
            tags = parse_tags(soup)
            cover = parse_cover(soup)
            rating = parse_rating(script_tag, soup)
            publisher = parse_publisher(script_tag)
            publishedDate = None
            language = parse_language(script_tag)

            match = re.search(r'/prehled-knihy/[^/]+-(\d+)', url)
            if match:
                dk_id = match.group(1)
            else:
                dk_id = None

            # identifiers
            link = url.split('/')[-1]
            isbn = extract_isbn(soup)

            identifiers = {}
            if isbn:
                identifiers['isbn'] = isbn
            if link:
                identifiers['databazeknih'] = link

            if not title or not authors:
                return None

            record = MetaRecord(
                id=dk_id,
                title=title,
                authors=authors,
                url=url,
                source=MetaSourceInfo(
                    id=self.__id__,
                    description=self.DESCRIPTION,
                    link=self.META_URL
                ),
                cover=cover,
                description=description,
                series=series,
                series_index=series_index,
                identifiers=identifiers,
                publisher=publisher,
                publishedDate=publishedDate,
                rating=rating,
                languages=language,
                tags=tags,
            )
            return record

        if not self.active:
            return []

        links = search_links(query)
        if not links:
            return []

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = {executor.submit(extract_data, link): link for link in links}
            for fut in concurrent.futures.as_completed(futs):
                rec = fut.result()
                if rec:
                    results.append(rec)
        return results if results else []
