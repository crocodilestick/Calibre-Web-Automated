# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from bs4 import BeautifulSoup as BS
from lxml import etree

from cps.metadata_provider.amazon_fr import AmazonFr
from cps.metadata_provider.bnf import BnF, UnimarcRecordParser
from cps.metadata_provider.leslibraires import LesLibraires, LesLibrairesParser
from cps.services.Metadata import MetaSourceInfo
from cps.services.bookshop_metadata import (
    SchemaOrgBook, isbn13_to_isbn10, isbn_from_query, parse_french_date
)

SOURCE = MetaSourceInfo(id="test", description="Test", link="")


def test_isbn_from_query_accepts_prefix_and_dashes():
    assert isbn_from_query("isbn: 978-2-266-32048-1") == "9782266320481"
    assert isbn_from_query("Dune Frank Herbert") is None


def test_isbn13_to_isbn10_only_for_978():
    assert isbn13_to_isbn10("9782266320481") == "2266320483"
    assert isbn13_to_isbn10("9791092982770") is None


def test_parse_french_date():
    assert parse_french_date("26 août 2021") == "2021-08-26"
    assert parse_french_date("1er janvier 2020") == "2020-01-01"
    assert parse_french_date("29/05/2013") == "2013-05-29"
    assert parse_french_date("Pocket, 2022") == "2022-01-01"


def test_schema_org_book_from_html_to_record():
    page = """<script type="application/ld+json">{"@type": "Book", "name": "Dune Tome 2 : Le Messie de Dune",
    "author": [{"name": "Frank Herbert"}], "publisher": {"name": "Pocket"}, "datePublished": "2021-08-26",
    "isbn": "9782266320498", "image": "https://example.org/cover.jpg", "inLanguage": "fr",
    "aggregateRating": {"ratingValue": "4.6"}}</script>"""

    match = SchemaOrgBook.from_html(page).to_record(SOURCE, "https://example.org/book", "generic.svg", "en")

    assert match.title == "Dune Tome 2 : Le Messie de Dune"
    assert match.authors == ["Frank Herbert"]
    assert match.publisher == "Pocket"
    assert match.publishedDate == "2021-08-26"
    assert match.identifiers == {"isbn": "9782266320498"}
    assert match.cover == "https://example.org/cover.jpg"
    assert match.rating == 5
    assert match.languages == ["French"]
    assert (match.series, match.series_index) == ("Dune", 2.0)


def test_schema_org_book_ignores_other_types():
    assert SchemaOrgBook.from_html('<script type="application/ld+json">{"@type": "Organization"}</script>') is None


def test_amazon_fr_asin_from_links():
    assert AmazonFr._asin_from_link("https://www.amazon.fr/Myst%C3%A8res/dp/B0D78D8NB5/ref=sr_1_1") == "B0D78D8NB5"
    assert AmazonFr._asin_from_link("b0cxkgkxrk") == "B0CXKGKXRK"
    assert AmazonFr._asin_from_link("Dune Frank Herbert") is None


def test_bnf_unimarc_record():
    record = etree.fromstring("""<mxc:record xmlns:mxc="info:lc/xmlns/marcxchange-v2">
      <mxc:controlfield tag="003">http://catalogue.bnf.fr/ark:/12148/cb46958734r</mxc:controlfield>
      <mxc:datafield tag="010"><mxc:subfield code="a">978-2-266-32048-1</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="101"><mxc:subfield code="a">fre</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="200"><mxc:subfield code="a">Dune</mxc:subfield><mxc:subfield code="e">roman</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="214"><mxc:subfield code="c">Pocket</mxc:subfield><mxc:subfield code="d">DL 2022</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="461"><mxc:subfield code="t">Le cycle de Dune</mxc:subfield><mxc:subfield code="v">1</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="700"><mxc:subfield code="a">Herbert</mxc:subfield><mxc:subfield code="b">Frank</mxc:subfield></mxc:datafield>
      <mxc:datafield tag="702"><mxc:subfield code="a">Demuth</mxc:subfield><mxc:subfield code="b">Michel</mxc:subfield><mxc:subfield code="4">730</mxc:subfield></mxc:datafield>
    </mxc:record>""")

    match = UnimarcRecordParser(record, BnF()).parse("generic.svg", "en")

    assert match.title == "Dune : roman"
    assert match.authors == ["Frank Herbert"]
    assert match.publisher == "Pocket"
    assert match.publishedDate == "2022-01-01"
    assert match.identifiers == {"isbn": "9782266320481", "bnf": "cb46958734r"}
    assert match.languages == ["French"]
    assert (match.series, match.series_index) == ("Le cycle de Dune", 1.0)


def test_leslibraires_series_title():
    soup = BS("""<h1 itemprop="name"><a href="/serie/dune">Dune</a> 6 - La maison des mères</h1>
    <span itemprop="author">Frank Herbert</span><span itemprop="publisher">Robert Laffont</span>
    <span itemprop="datePublished">2 septembre 2021</span><span itemprop="isbn">978-2-221-25234-5</span>
    <img src="//abc.b-cdn.net/cover.jpg">""", "html.parser")

    match = LesLibrairesParser(soup, LesLibraires()).parse("https://example.org/livre", "generic.svg", "en")

    assert match.title == "La maison des mères"
    assert (match.series, match.series_index) == ("Dune", 6.0)
    assert match.publishedDate == "2021-09-02"
    assert match.identifiers == {"isbn": "9782221252345"}
    assert match.cover == "https://abc.b-cdn.net/cover.jpg"
