# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace

from cps.db import CalibreDB


class FakeCalibreDB:
    def ensure_session(self):
        pass


def author(author_id, name, sort):
    return SimpleNamespace(id=author_id, name=name, sort=sort)


def test_order_authors_uses_linked_authors_without_querying_database():
    first = author(1, "Jane Alpha", "Alpha, Jane")
    second = author(2, "Bob Beta", "Beta, Bob")
    book = SimpleNamespace(
        id=10,
        author_sort="Beta, Bob & Alpha, Jane",
        authors=[first, second],
    )

    result = CalibreDB.order_authors(FakeCalibreDB(), [book], list_return=False)

    assert result == [second, first]


def test_order_authors_tolerates_stale_author_sort_and_none_authors():
    linked = author(1, "Jane Alpha", "Alpha, Jane")
    book = SimpleNamespace(
        id=11,
        author_sort="Missing, Author & Alpha, Jane",
        authors=[None, linked],
    )

    entries = CalibreDB.order_authors(FakeCalibreDB(), [book], list_return=True)

    assert entries == [book]
    assert book.ordered_authors == [linked]


def test_order_authors_falls_back_to_linked_authors_when_sort_is_missing():
    linked = author(1, "Jane Alpha", "Alpha, Jane")
    book = SimpleNamespace(
        id=12,
        author_sort=None,
        authors=[linked],
    )

    entries = CalibreDB.order_authors(FakeCalibreDB(), [book], list_return=True)

    assert entries == [book]
    assert book.ordered_authors == [linked]
