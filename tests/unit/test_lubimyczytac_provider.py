# -*- coding: utf-8 -*-
# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from lxml.html import fromstring

from cps.metadata_provider.lubimyczytac import LubimyCzytac, LubimyCzytacParser


def parser_from_html(html):
    return LubimyCzytacParser(root=fromstring(html), metadata=LubimyCzytac())


def test_parse_tags_returns_empty_list_when_book_has_no_tags():
    parser = parser_from_html("<html><body><section class='container book'></section></body></html>")

    assert parser._parse_tags() == []


def test_parse_description_prefers_current_book_description_over_truncated_meta():
    parser = parser_from_html(
        """
        <html>
          <head>
            <meta property="og:description" content="Short truncated description..." />
          </head>
          <body>
            <section class="container book">
              <div id="book-description" class="book__description text-collapse">
                Full publisher description.<br><br>
                Second paragraph with the actual plot.
              </div>
            </section>
          </body>
        </html>
        """
    )

    description = parser._parse_description()

    assert "Full publisher description" in description
    assert "Second paragraph with the actual plot" in description
    assert "Short truncated description" not in description


def test_parse_description_keeps_hash_leader_as_paragraph_text():
    parser = parser_from_html(
        """
        <html>
          <body>
            <section class="container book">
              <div id="book-description" class="book__description">
                #1 na liście bestsellerów „New York Timesa”<br><br>
                Drugi akapit opisu.
              </div>
            </section>
          </body>
        </html>
        """
    )

    description = parser._parse_description()

    assert "<h1" not in description
    assert "#1 na liście bestseller" in description
    assert "Drugi akapit opisu" in description


def test_parse_publisher_supports_current_book_header_markup():
    parser = parser_from_html(
        """
        <html>
          <body>
            <section class="container book">
              <span class="book__txt d-none d-lg-inline-block mt-2">
                Wydawnictwo:
                <a href="https://lubimyczytac.pl/wydawnictwo/7576/proszynski-i-s-ka">
                  Prószyński i S-ka
                </a>
              </span>
            </section>
          </body>
        </html>
        """
    )

    assert parser._parse_publisher() == "Prószyński i S-ka"


def test_parse_from_summary_uses_book_jsonld_when_other_jsonld_precedes_it():
    parser = parser_from_html(
        """
        <html>
          <head>
            <script type="application/ld+json">
              {"@context":"https://schema.org","@type":"Organization","name":"Lubimyczytac"}
            </script>
            <script type="application/ld+json">
              {"@context":"https://schema.org","@type":"Book","datePublished":"2017-04-11","numberOfPages":608}
            </script>
          </head>
          <body>
            <section class="container book"></section>
          </body>
        </html>
        """
    )

    assert parser._parse_from_summary("datePublished") == "2017-04-11"
    assert parser._parse_from_summary("numberOfPages") == "608"
