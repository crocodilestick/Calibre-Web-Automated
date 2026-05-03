# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from lxml.html import fromstring

from cps.metadata_provider.lubimyczytac import LubimyCzytac, LubimyCzytacParser


def test_parse_tags_returns_empty_list_when_book_has_no_tags():
    parser = LubimyCzytacParser(
        root=fromstring("<html><body><section class='container book'></section></body></html>"),
        metadata=LubimyCzytac(),
    )

    assert parser._parse_tags() == []
