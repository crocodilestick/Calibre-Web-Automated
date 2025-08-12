# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

# Version from AutoCaliWeb - Created by - UsamaFoad & gelbphoenix

import re
import datetime
from typing import List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import requests
from lxml import etree

from cps import logger, constants
from cps.services.Metadata import MetaRecord, MetaSourceInfo, Metadata

from cps import isoLanguages
from flask_babel import get_locale

log = logger.create()


class DNB(Metadata):
    __name__ = "Deutsche Nationalbibliothek"
    __id__ = "dnb"

    # Configuration defaults from original plugin
    cfg_guess_series = True
    cfg_append_edition_to_title = False
    cfg_fetch_subjects = 2  # Both GND and non-GND subjects
    cfg_skip_series_starting_with_publishers_name = True
    cfg_unwanted_series_names = [
        r'^Roman$', r'^Science-fiction$', r'^\[Ariadne\]$', r'^Ariadne$', r'^atb$', r'^BvT$',
        r'^Bastei L', r'^bb$', r'^Beck Paperback', r'^Beck\-.*berater', r'^Beck\'sche Reihe',
        r'^Bibliothek Suhrkamp$', r'^BLT$', r'^DLV-Taschenbuch$', r'^Edition Suhrkamp$',
        r'^Edition Lingen Stiftung$', r'^Edition C', r'^Edition Metzgenstein$', r'^ETB$', r'^dtv',
        r'^Ein Goldmann', r'^Oettinger-Taschenbuch$', r'^Haymon-Taschenbuch$', r'^Mira Taschenbuch$',
        r'^Suhrkamp-Taschenbuch$', r'^Bastei-L', r'^Hey$', r'^btb$', r'^bt-Kinder', r'^Ravensburger',
        r'^Sammlung Luchterhand$', r'^blanvalet$', r'^KiWi$', r'^Piper$', r'^C.H. Beck', r'^Rororo',
        r'^Goldmann$', r'^Moewig$', r'^Fischer Klassik$', r'^hey! shorties$', r'^Ullstein',
        r'^Unionsverlag', r'^Ariadne-Krimi', r'^C.-Bertelsmann', r'^Phantastische Bibliothek$',
        r'^Beck Paperback$', r'^Beck\'sche Reihe$', r'^Knaur', r'^Volk-und-Welt', r'^Allgemeine',
        r'^Premium', r'^Horror-Bibliothek$'
    ]

    MAXIMUMRECORDS = 10
    QUERYURL = 'https://services.dnb.de/sru/dnb?version=1.1&maximumRecords=%s&operation=searchRetrieve&recordSchema=MARC21-xml&query=%s'
    COVERURL = 'https://portal.dnb.de/opac/mvb/cover?isbn=%s'

    def search(self, query: str, generic_cover: str = "", locale: str = "en") -> Optional[List[MetaRecord]]:
        try:
            if not self.active:
                return None

            val = []

            # Parse query for special identifiers
            idn = None
            isbn = None
            title = None
            authors = []

            # Check if query contains special identifiers
            if query.startswith('dnb-idn:'):
                idn = query.replace('dnb-idn:', '').strip()
            elif query.startswith('isbn:'):
                isbn = query.replace('isbn:', '').strip()
            else:
                # Treat as title/author search
                title = query

            # Create query variations
            queries = self._create_query_variations(idn, isbn, authors, title)

            for query_str in queries:
                try:
                    results = self._execute_query(query_str)
                    if not results:
                        continue

                    log.info("Parsing DNB records")

                    for record in results:
                        book_data = self._parse_marc21_record(record)
                        if book_data:
                            meta_record = self._create_meta_record(book_data, generic_cover)
                            if meta_record:
                                val.append(meta_record)

                    # Stop on first successful query
                    if val:
                        break

                except Exception as e:
                    log.warning(f"DNB search error: {e}")
                    continue

            return val if val else [] # None
            pass
        except Exception as e:
            log.error(f"DNB search failed for query '{query}': {e}")
            return [] # None  # Return None instead of letting exception propagate

    def _create_query_variations(self, idn=None, isbn=None, authors=None, title=None):
        """Create SRU query variations with increasing fuzziness"""
        if authors is None:
            authors = []

        queries = []

        if idn:
            queries.append(f'num={idn}')
        elif isbn:
            queries.append(f'num={isbn}')
        else:
            if title:
                # Basic title search - preserve spaces
                title_tokens = list(self.get_title_tokens(title, strip_joiners=False))
                if title_tokens:
                    query_title = " ".join(title_tokens)
                    queries.append(f'tit="{query_title}"')

                # German joiner removal for fuzzy matching
                german_tokens = self._strip_german_joiners(
                    list(self.get_title_tokens(title, strip_joiners=True))
                )
                if german_tokens and german_tokens != title_tokens:
                    query_title = " ".join(german_tokens)
                    queries.append(f'tit="{query_title}"')

        # Add filters to exclude non-book materials
        filtered_queries = []
        for q in queries:
            filtered_q = f'{q} NOT (mat=film OR mat=music OR mat=microfiches OR cod=tt)'
            filtered_queries.append(filtered_q)

        return filtered_queries

    def _execute_query(self, query, timeout=30):
        """Query DNB SRU API"""
        headers = {  
            'User-Agent': constants.USER_AGENT,  
            'Accept': 'application/xml, text/xml',  
            'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',  
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }  

        log.info(f'DNB Query: {query}')

        query_url = self.QUERYURL % (self.MAXIMUMRECORDS, quote(query))
        log.info(f'DNB Query URL: {query_url}')

        try:
            response = requests.get(query_url, headers=headers, timeout=timeout)
            response.raise_for_status()

            xml_data = etree.XML(response.content)
            num_records = xml_data.xpath("./zs:numberOfRecords",
                                       namespaces={"zs": "http://www.loc.gov/zing/srw/"})[0].text.strip()
            log.info(f'DNB found {num_records} records')

            if int(num_records) == 0:
                return []  # Return empty list, not None

            return xml_data.xpath("./zs:records/zs:record/zs:recordData/marc21:record",
                                namespaces={'marc21': 'http://www.loc.gov/MARC21/slim',
                                          "zs": "http://www.loc.gov/zing/srw/"})
        except Exception as e:
            log.error(f'DNB query error: {e}')
            return []  # Return empty list, not None

    def _parse_marc21_record(self, record):
        """Parse MARC21 XML record into book data"""
        ns = {'marc21': 'http://www.loc.gov/MARC21/slim'}

        book = {
            'series': None,
            'series_index': None,
            'pubdate': None,
            'languages': [],
            'title': None,
            'authors': [],
            'comments': None,
            'idn': None,
            'urn': None,
            'isbn': None,
            'ddc': [],
            'subjects_gnd': [],
            'subjects_non_gnd': [],
            'publisher_name': None,
            'publisher_location': None,
        }

        # Skip audio/video content
        try:
            mediatype = record.xpath("./marc21:datafield[@tag='336']/marc21:subfield[@code='a']", namespaces=ns)[0].text.strip().lower()
            if mediatype in ('gesprochenes wort'):
                return None
        except (IndexError, AttributeError):
            pass

        try:
            mediatype = record.xpath("./marc21:datafield[@tag='337']/marc21:subfield[@code='a']", namespaces=ns)[0].text.strip().lower()
            if mediatype in ('audio', 'video'):
                return None
        except (IndexError, AttributeError):
            pass

        # Extract IDN
        try:
            book['idn'] = record.xpath("./marc21:datafield[@tag='016']/marc21:subfield[@code='a']", namespaces=ns)[0].text.strip()
        except (IndexError, AttributeError):
            pass

        # Extract title from field 245
        self._extract_title_and_series(record, book, ns)

        # Extract authors from fields 100/700
        self._extract_authors(record, book, ns)

        # Extract publisher info from field 264
        self._extract_publisher_info(record, book, ns)

        # Extract ISBN from field 020
        self._extract_isbn(record, book, ns)

        # Extract subjects
        self._extract_subjects(record, book, ns)

        # Extract languages from field 041
        self._extract_languages(record, book, ns)

        # Extract comments from field 856
        self._extract_comments(record, book, ns)

        # Apply series guessing if enabled
        if self.cfg_guess_series and (not book['series'] or not book['series_index']):
            self._guess_series_from_title(book)

        return book

    def _extract_title_and_series(self, record, book, ns):
        """Extract title and series from MARC21 field 245"""
        for field in record.xpath("./marc21:datafield[@tag='245']", namespaces=ns):
            title_parts = []

            # Get main title (subfield a)
            code_a = []
            for i in field.xpath("./marc21:subfield[@code='a']", namespaces=ns):
                code_a.append(i.text.strip())

            # Get part numbers (subfield n)
            code_n = []
            for i in field.xpath("./marc21:subfield[@code='n']", namespaces=ns):
                match = re.search(r"(\d+([,\.]\d+)?)", i.text.strip())
                if match:
                    code_n.append(match.group(1))

            # Get part names (subfield p)
            code_p = []
            for i in field.xpath("./marc21:subfield[@code='p']", namespaces=ns):
                code_p.append(i.text.strip())

            title_parts = code_a

            # Handle series extraction
            if code_a and code_n:
                if code_p:
                    title_parts = [code_p[-1]]

                # Build series name
                series_parts = [code_a[0]]
                for i in range(0, min(len(code_p), len(code_n)) - 1):
                    series_parts.append(code_p[i])

                for i in range(0, min(len(series_parts), len(code_n) - 1)):
                    series_parts[i] += ' ' + code_n[i]

                book['series'] = ' - '.join(series_parts)
                book['series'] = self._clean_series(book['series'], book['publisher_name'])

                if code_n:
                    book['series_index'] = code_n[-1]

            # Add subtitle (subfield b)
            try:
                subtitle = field.xpath("./marc21:subfield[@code='b']", namespaces=ns)[0].text.strip()
                title_parts.append(subtitle)
            except (IndexError, AttributeError):
                pass

            book['title'] = " : ".join(title_parts)
            book['title'] = self._clean_title(book['title'])

    def _extract_authors(self, record, book, ns):
        """Extract authors from MARC21 fields 100/700"""
        # Primary authors (field 100)
        for i in record.xpath("./marc21:datafield[@tag='100']/marc21:subfield[@code='4' and text()='aut']/../marc21:subfield[@code='a']", namespaces=ns):
            name = re.sub(r" \[.*\]$", "", i.text.strip())
            book['authors'].append(name)

        # Secondary authors (field 700)
        for i in record.xpath("./marc21:datafield[@tag='700']/marc21:subfield[@code='4' and text()='aut']/../marc21:subfield[@code='a']", namespaces=ns):
            name = re.sub(r" \[.*\]$", "", i.text.strip())
            book['authors'].append(name)

        # If no authors found, use all involved persons
        if not book['authors']:
            for i in record.xpath("./marc21:datafield[@tag='700']/marc21:subfield[@code='a']", namespaces=ns):
                name = re.sub(r" \[.*\]$", "", i.text.strip())
                book['authors'].append(name)

    def _extract_publisher_info(self, record, book, ns):
        """Extract publisher information from MARC21 field 264"""
        for field in record.xpath("./marc21:datafield[@tag='264']", namespaces=ns):
            # Publisher location (subfield a)
            if not book['publisher_location']:
                location_parts = []
                for i in field.xpath("./marc21:subfield[@code='a']", namespaces=ns):
                    location_parts.append(i.text.strip())
                if location_parts:
                    book['publisher_location'] = ' '.join(location_parts).strip('[]')

            # Publisher name (subfield b)
            if not book['publisher_name']:
                try:
                    book['publisher_name'] = field.xpath("./marc21:subfield[@code='b']", namespaces=ns)[0].text.strip()
                except (IndexError, AttributeError):
                    pass

            # Publication date (subfield c)
            if not book['pubdate']:
                try:
                    pubdate = field.xpath("./marc21:subfield[@code='c']", namespaces=ns)[0].text.strip()
                    match = re.search(r"(\d{4})", pubdate)
                    if match:
                        year = match.group(1)
                        book['pubdate'] = datetime.datetime(int(year), 1, 1, 12, 30, 0)
                except (IndexError, AttributeError):
                    pass

    def _extract_isbn(self, record, book, ns):
        """Extract ISBN from MARC21 field 020"""
        for i in record.xpath("./marc21:datafield[@tag='020']/marc21:subfield[@code='a']", namespaces=ns):
            try:
                isbn_regex = r"(?:ISBN(?:-1[03])?:? )?(?=[-0-9 ]{17}|[-0-9X ]{13}|[0-9X]{10})(?:97[89][- ]?)?[0-9]{1,5}[- ]?(?:[0-9]+[- ]?){2}[0-9X]"
                match = re.search(isbn_regex, i.text.strip())
                if match:
                    isbn = match.group()
                    book['isbn'] = isbn.replace('-', '')
                    break
            except AttributeError:
                pass

    def _extract_subjects(self, record, book, ns):
        """Extract subjects from MARC21 fields"""
        # GND subjects from field 689
        for i in record.xpath("./marc21:datafield[@tag='689']/marc21:subfield[@code='a']", namespaces=ns):
            book['subjects_gnd'].append(i.text.strip())

        # GND subjects from fields 600-655
        for f in range(600, 656):
            for i in record.xpath(f"./marc21:datafield[@tag='{f}']/marc21:subfield[@code='2' and text()='gnd']/../marc21:subfield[@code='a']", namespaces=ns):
                if not i.text.startswith("("):
                    book['subjects_gnd'].append(i.text.strip())

        # Non-GND subjects from fields 600-655
        for f in range(600, 656):
            for i in record.xpath(f"./marc21:datafield[@tag='{f}']/marc21:subfield[@code='a']", namespaces=ns):
                if not i.text.startswith("(") and len(i.text) >= 2:
                    book['subjects_non_gnd'].extend(re.split(',|;', self._remove_sorting_characters(i.text)))

    # def _extract_languages(self, record, book, ns):
        # """Extract languages from MARC21 field 041"""
        # for i in record.xpath("./marc21:datafield[@tag='041']/marc21:subfield[@code='a']", namespaces=ns):
            # lang_code = self._iso639_2b_as_iso639_3(i.text.strip())
            # book['languages'].append(lang_code)

    def _extract_languages(self, record, book, ns):
        """Extract languages from MARC21 field 041"""
        raw_languages = []
        for i in record.xpath("./marc21:datafield[@tag='041']/marc21:subfield[@code='a']", namespaces=ns):
            lang_code = i.text.strip()
            # Convert 'ger' to 'deu' for consistency
            if lang_code == 'ger':
                lang_code = 'deu'

            # Convert ISO code to English language name
            language_name = isoLanguages.get_language_name(get_locale(), lang_code)
            if language_name != "Unknown":
                raw_languages.append(language_name)
                #log.info(f"Converted {lang_code} to {language_name}")
            else:
                log.warning(f"Unknown language code from DNB: {lang_code}")

        book['languages'] = raw_languages

    def _extract_comments(self, record, book, ns):
        """Extract comments from MARC21 field 856"""
        for url_elem in record.xpath("./marc21:datafield[@tag='856']/marc21:subfield[@code='u']", namespaces=ns):
            url = url_elem.text.strip()
            if url.startswith("http://deposit.dnb.de/") or url.startswith("https://deposit.dnb.de/"):
                try:
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    comments_text = response.text
                    if 'Zugriff derzeit nicht möglich' in comments_text:
                        continue

                    # Clean up comments
                    comments_text = re.sub(
                        r'(\s|<br>|<p>|\n)*Angaben aus der Verlagsmeldung(\s|<br>|<p>|\n)*(<h3>.*?</h3>)*(\s|<br>|<p>|\n)*',
                        '', comments_text, flags=re.IGNORECASE)
                    book['comments'] = comments_text
                    break
                except Exception:
                    continue

    def _extract_edition(self, record, book, ns):
        """Extract edition from MARC21 field 250"""
        try:
            book['edition'] = record.xpath("./marc21:datafield[@tag='250']/marc21:subfield[@code='a']", namespaces=ns)[0].text.strip()
        except (IndexError, AttributeError):
            pass

    def _get_cover_url(self, book_data, generic_cover):
        if not book_data.get('isbn'):
            return generic_cover

        cover_url = self.COVERURL % book_data['isbn']

        try:
            # Test the actual response from DNB
            response = requests.head(cover_url, timeout=10)
            #log.info(f"DNB cover response status: {response.status_code}")
            #log.info(f"DNB cover content-type: {response.headers.get('content-type')}")

            if response.status_code == 200:
                return cover_url
        except Exception as e:
            log.error(f"DNB cover test failed: {e}")

        return generic_cover

    def _extract_image_url_from_html(self, html_content, original_url):
        """Extract actual image URL from DNB's HTML wrapper"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            img_tag = soup.find('img')
            if img_tag and img_tag.get('src'):
                img_src = img_tag['src']
                # If it's a relative URL, make it absolute
                if img_src.startswith('/'):
                    from urllib.parse import urljoin
                    return urljoin(original_url, img_src)
                elif img_src.startswith('http'):
                    return img_src
                else:
                    # If it's the same URL, we have a problem
                    if img_src == original_url:
                        return None
                    return img_src
        except Exception as e:
            log.error(f"Failed to extract image URL from HTML: {e}")
        return None

    def _get_validated_cover_url(self, book_data, generic_cover):
        """Get and validate DNB cover URL, handling HTML responses"""
        if not book_data.get('isbn'):
            return generic_cover

        cover_url = self.COVERURL % book_data['isbn']

        try:
            response = requests.get(cover_url, timeout=10)
            response.raise_for_status()

            content_type = response.headers.get('content-type').lower()
            #content_type = content_type.split(';')[0].strip() # Test remove charset=utf-8

            #log.info(f"DNB cover response content-type: {content_type}")

            # Clean content-type by removing charset and other parameters
            main_content_type = content_type.split(';')[0].strip()

            # Check if it's a valid image type
            if main_content_type in ('image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/bmp'):
                # Modify the response headers to remove charset
                response.headers['content-type'] = main_content_type
                #log.info("Test: _get_validated_cover_url: if main_content_type")
                #log.info(cover_url)
                #log.info(response.headers['content-type'])
                return cover_url
            elif 'text/html' in content_type:
                # Handle HTML wrapper case as before
                log.info("main_content_type: text/html")
                # Verify the response actually contains image data
                if len(response.content) > 0 and response.content[:4] in [b'\xff\xd8\xff', b'\x89PNG']:
                    log.info("response.content>0 and ..etc")
                    actual_image_url = self._extract_image_url_from_html(response.text, cover_url)
                    if actual_image_url and actual_image_url != cover_url:
                        log.info(actual_image_url)
                        return actual_image_url

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                log.info(f"DNB cover not found for ISBN: {book_data.get('isbn')}")
            else:
                log.error(f"DNB cover validation failed: {e}")
        except Exception as e:
            log.error(f"DNB cover validation failed: {e}")

        return generic_cover

    def _create_meta_record(self, book_data, generic_cover):
        """Create MetaRecord from parsed book data"""
        if not book_data.get('title') or not book_data.get('authors'):
            return None

        # Apply edition to title if configured
        title = book_data['title']
        if self.cfg_append_edition_to_title and book_data.get('edition'):
            title = f"{title} : {book_data['edition']}"

        # Clean author names
        authors = [self._remove_sorting_characters(author) for author in book_data['authors']]
        authors = [re.sub(r"^(.+), (.+)$", r"\2 \1", author) for author in authors]

        # Get validated cover URL
        cover_url = self._get_validated_cover_url(book_data, generic_cover)
        # log.info(cover_url)

        # Build publisher string
        publisher_parts = []
        if book_data.get('publisher_location'):
            publisher_parts.append(book_data['publisher_location'])
        if book_data.get('publisher_name'):
            publisher_parts.append(self._remove_sorting_characters(book_data['publisher_name']))
        publisher = " ; ".join(publisher_parts) if publisher_parts else ""

        # Select subjects based on configuration
        tags = []
        if self.cfg_fetch_subjects == 0:  # Only GND
            tags = self._uniq(book_data['subjects_gnd'])
        elif self.cfg_fetch_subjects == 1:  # GND if available, else non-GND
            tags = self._uniq(book_data['subjects_gnd']) if book_data['subjects_gnd'] else self._uniq(book_data['subjects_non_gnd'])
        elif self.cfg_fetch_subjects == 2:  # Both GND and non-GND
            tags = self._uniq(book_data['subjects_gnd'] + book_data['subjects_non_gnd'])
        elif self.cfg_fetch_subjects == 3:  # Non-GND if available, else GND
            tags = self._uniq(book_data['subjects_non_gnd']) if book_data['subjects_non_gnd'] else self._uniq(book_data['subjects_gnd'])
        elif self.cfg_fetch_subjects == 4:  # Only non-GND
            tags = self._uniq(book_data['subjects_non_gnd'])
        # cfg_fetch_subjects == 5: No subjects

        # Build identifiers
        identifiers = {}
        if book_data.get('idn'):
            identifiers['dnb-idn'] = book_data['idn']
        if book_data.get('isbn'):
            identifiers['isbn'] = book_data['isbn']
        if book_data.get('urn'):
            identifiers['urn'] = book_data['urn']
        if book_data.get('ddc'):
            identifiers['ddc'] = ",".join(book_data['ddc'])

        # Get cover URL
        # cover_url = generic_cover
        # if book_data.get('isbn'):
        #    cover_url = self.COVERURL % book_data['isbn']

        return MetaRecord(
            id=book_data.get('idn', ''),
            title=self._remove_sorting_characters(title),
            authors=authors,
            url=f"https://portal.dnb.de/opac.htm?method=simpleSearch&query={book_data.get('idn', '')}",
            source=MetaSourceInfo(
                id=self.__id__,
                description=self.__name__,
                link="https://portal.dnb.de/",
            ),
            cover=cover_url,
            description=book_data.get('comments', ''),
            series=self._remove_sorting_characters(book_data.get('series', '')) if book_data.get('series') else None,
            series_index=float(book_data.get('series_index', 0)) if book_data.get('series_index') else None,
            identifiers=identifiers,
            publisher=publisher,
            publishedDate=book_data['pubdate'].strftime('%Y-%m-%d') if book_data.get('pubdate') else None,
            languages=book_data.get('languages', []),
            tags=tags,
        )

    # Helper functions adapted from original plugin
    def _remove_sorting_characters(self, text):
        """Remove sorting word markers"""
        if text:
            return ''.join([c for c in text if ord(c) != 152 and ord(c) != 156])
        return None

    def _clean_title(self, title):
        """Clean up title"""
        if title:
            # Remove name of translator from title
            match = re.search(r'^(.+) [/:] [Aa]us dem .+? von(\s\w+)+$', self._remove_sorting_characters(title))
            if match:
                title = match.group(1)
        return title

    def _clean_series(self, series, publisher_name):
        """Clean up series"""
        if not series:
            return None

        # Series must contain at least one character
        if not re.search(r'\S', series):
            return None

        # Remove sorting word markers
        series = self._remove_sorting_characters(series)

        # Skip series starting with publisher name if configured
        if self.cfg_skip_series_starting_with_publishers_name and publisher_name:
            if publisher_name.lower() == series.lower():
                return None

            match = re.search(r'^(\w\w\w\w+)', self._remove_sorting_characters(publisher_name))
            if match:
                pubcompany = match.group(1)
                if re.search(r'^\W*' + pubcompany, series, flags=re.IGNORECASE):
                    return None

        # Check against unwanted series patterns
        for pattern in self.cfg_unwanted_series_names:
            try:
                if re.search(pattern, series, flags=re.IGNORECASE):
                    return None
            except:
                pass

        return series

    def _strip_german_joiners(self, wordlist):
        """Remove German joiners from list of words"""
        tokens = []
        for word in wordlist:
            if word.lower() not in ('ein', 'eine', 'einer', 'der', 'die', 'das', 'und', 'oder'):
                tokens.append(word)
        return tokens

    def _guess_series_from_title(self, book):
        """Try to extract Series and Series Index from a book's title"""
        if not book.get('title'):
            return

        title = book['title']
        parts = re.split("[:]", self._remove_sorting_characters(title))

        if len(parts) == 2:
            # Make sure only one part contains digits
            if bool(re.search(r"\d", parts[0])) != bool(re.search(r"\d", parts[1])):
                if bool(re.search(r"\d", parts[0])):
                    indexpart = parts[0]
                    textpart = parts[1]
                else:
                    indexpart = parts[1]
                    textpart = parts[0]

                # Clean textpart
                match = re.match(r"^[\s\-–—:]*(.+?)[\s\-–—:]*$", textpart)
                if match:
                    textpart = match.group(1)

                # Extract series and index
                match = re.match(
                    r"^\s*(\S\D*?[a-zA-Z]\D*?)\W[\(\/\.,\s\-–—:]*(?:#|Reihe|Nr\.|Heft|Volume|Vol\.?|Episode|Bd\.|Sammelband|[B|b]and|Part|Kapitel|[Tt]eil|Folge)[,\-–—:\s#\(]*(\d+[\.,]?\d*)[\)\s\-–—:]*$",
                    indexpart)
                if match:
                    series = match.group(1)
                    series_index = match.group(2)

                    series = self._clean_series(series, book.get('publisher_name'))
                    if series and series_index:
                        book['series'] = series
                        book['series_index'] = series_index
                        book['title'] = textpart

    def _iso639_2b_as_iso639_3(self, lang):
        """Convert ISO 639-2/B to ISO 639-3"""
        mapping = {
            'ger': 'deu', 'fre': 'fra', 'dut': 'nld', 'chi': 'zho',
            'cze': 'ces', 'gre': 'ell', 'ice': 'isl', 'rum': 'ron',
        }
        """Convert ISO 639-2/B to ISO 639-1"""
        # mapping = {
            # 'ger': 'de', 'fre': 'fr', 'dut': 'nl', 'chi': 'zh',
            # 'cz': 'cs', 'gre': 'el', 'ice': 'is', 'rum': 'ro',
        # }

        return mapping.get(lang.lower(), lang)

    def _uniq(self, list_with_duplicates):
        """Remove duplicates from a list while preserving order"""
        unique_list = []
        for item in list_with_duplicates:
            if item not in unique_list:
                unique_list.append(item)
        return unique_list
