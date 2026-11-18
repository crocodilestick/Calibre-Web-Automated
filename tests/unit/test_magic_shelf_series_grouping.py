# -*- coding: utf-8 -*-
# Calibre-Web Automated â€“ fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit coverage for Magic Shelf's series-card presentation data."""

from types import SimpleNamespace

import pytest

from cps import magic_shelf


pytestmark = pytest.mark.unit


def _book(book_id, *series):
    return SimpleNamespace(id=book_id, series=list(series))


def _series(series_id, name):
    return SimpleNamespace(id=series_id, name=name)


def test_series_groups_keep_only_matching_books_and_first_cover(monkeypatch):
    dune = _series(1, 'Dune')
    expanse = _series(2, 'The Expanse')
    first_dune_book = _book(10, dune)
    matching_books = [
        first_dune_book,
        _book(11, dune),
        _book(12, expanse),
        _book(13),
        _book(14),
    ]
    monkeypatch.setattr(magic_shelf, 'get_books_for_magic_shelf',
                        lambda *args, **kwargs: (matching_books, len(matching_books)))

    groups, total = magic_shelf.get_series_groups_for_magic_shelf(42)

    assert total == 3
    assert [(group['series_id'], group['count']) for group in groups] == [(1, 2), (2, 1), (None, 2)]
    assert groups[0]['book'] is first_dune_book


@pytest.mark.parametrize(
    ('sort_param', 'expected_names'),
    [
        ('abc', ['Alpha', 'Zulu', 'Unseriesed']),
        ('zyx', ['Zulu', 'Alpha', 'Unseriesed']),
    ],
)
def test_series_groups_sort_named_series_but_keep_unseriesed_last(monkeypatch, sort_param, expected_names):
    alpha = _series(1, 'Alpha')
    zulu = _series(2, 'Zulu')
    matching_books = [_book(10, zulu), _book(11), _book(12, alpha)]
    monkeypatch.setattr(magic_shelf, 'get_books_for_magic_shelf',
                        lambda *args, **kwargs: (matching_books, len(matching_books)))

    groups, total = magic_shelf.get_series_groups_for_magic_shelf(42, sort_param=sort_param)

    assert total == 3
    assert [group['name'] for group in groups] == expected_names


def test_series_group_pagination_applies_to_groups_not_books(monkeypatch):
    matching_books = [_book(book_id, _series(book_id, 'Series {}'.format(book_id)))
                      for book_id in range(1, 5)]
    monkeypatch.setattr(magic_shelf, 'get_books_for_magic_shelf',
                        lambda *args, **kwargs: (matching_books, len(matching_books)))

    groups, total = magic_shelf.get_series_groups_for_magic_shelf(42, page=2, page_size=2)

    assert total == 4
    assert [group['series_id'] for group in groups] == [3, 4]

