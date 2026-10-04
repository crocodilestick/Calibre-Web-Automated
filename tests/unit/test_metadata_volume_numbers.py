# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Neighbouring volumes must not pass the auto-metadata title check, and a book
whose only author is Calibre's "Unknown" placeholder must still be matchable."""

from types import SimpleNamespace as NS

import pytest

import cps.metadata_helper as m

pytestmark = pytest.mark.unit


def _cand(title, authors=None):
    return NS(title=title, authors=list(authors or []), identifiers={})


NEIGHBOURING_VOLUMES = [
    ("One Piece, Vol. 12", "One Piece, Vol. 13", "Eiichiro Oda"),
    ("Saga, Volume 1", "Saga, Volume 2", "Brian K. Vaughan"),
    ("The Walking Dead, Vol. 11", "The Walking Dead, Vol. 12", "Robert Kirkman"),
    ("Harry Potter and the Deathly Hallows, Part 1",
     "Harry Potter and the Deathly Hallows, Part 2", "J.K. Rowling"),
    ("Some Series, Book One", "Some Series, Book Two", "An Author"),
    ("Some Series, Part I", "Some Series, Part II", "An Author"),
]


class TestVolumeNumbers:
    @pytest.mark.parametrize("book,cand,author", NEIGHBOURING_VOLUMES)
    def test_neighbouring_volume_is_rejected(self, book, cand, author):
        assert m._select_metadata_result(
            [_cand(cand, [author])], None,
            book_title=book, book_authors=[author],
        ) is None

    @pytest.mark.parametrize("book,cand,author", NEIGHBOURING_VOLUMES)
    def test_right_volume_wins_over_neighbour_ranked_first(self, book, cand, author):
        right = _cand(book, [author])
        assert m._select_metadata_result(
            [_cand(cand, [author]), right], None,
            book_title=book, book_authors=[author],
        ) is right

    def test_same_volume_written_differently_still_matches(self):
        for book, cand in (
            ("One Piece, Vol. 12", "One Piece Vol 12"),
            ("Some Series, Part II", "Some Series Part II"),
        ):
            result = _cand(cand, ["An Author"])
            assert m._select_metadata_result(
                [result], None, book_title=book, book_authors=["An Author"],
            ) is result

    def test_ordinary_number_words_are_not_volumes(self):
        # "one" and "i" outside a volume marker are just words.
        assert m._title_numbers("One Hundred Years of Solitude") == set()
        assert m._title_numbers("Lord of the Rings") == set()


class TestUnknownAuthorPlaceholder:
    def test_unknown_placeholder_book_matches_on_title(self):
        result = _cand("Cross", ["James Patterson"])
        placeholder = NS(name="Unknown")
        assert m._select_metadata_result(
            [result], None, book_title="Cross", book_authors=[placeholder],
        ) is result

    def test_unknown_placeholder_keeps_title_strictness(self):
        assert m._select_metadata_result(
            [_cand("Cross Fire", ["James Patterson"])], None,
            book_title="Cross", book_authors=[NS(name="Unknown")],
        ) is None

    def test_unknown_placeholder_does_not_weaken_volume_check(self):
        assert m._select_metadata_result(
            [_cand("Saga, Volume 2", ["Brian K. Vaughan"])], None,
            book_title="Saga, Volume 1", book_authors=[NS(name="Unknown")],
        ) is None

    def test_real_author_mismatch_is_still_rejected(self):
        assert m._select_metadata_result(
            [_cand("Cross", ["Al Ewing"])], None,
            book_title="Cross", book_authors=[NS(name="James Patterson")],
        ) is None


class TestOrdinalsAndYearsAreNotVolumes:
    def test_ordinal_in_an_edition_name_is_not_a_volume_number(self):
        # "60th" is not a bare number, so it adds nothing to the number set
        assert m._title_numbers("Fahrenheit 451: 60th Anniversary Edition") == {451}
        assert not m._volume_numbers_conflict(
            "Fahrenheit 451", "Fahrenheit 451: 60th Anniversary Edition")

    def test_hyphenated_number_title_still_matches_itself(self):
        assert m._title_similarity(
            "Catch-22", "Catch-22 (50th Anniversary Edition)") == 1.0

    def test_a_year_in_a_title_still_tells_volumes_apart(self):
        assert m._volume_numbers_conflict(
            "The Best American Short Stories 2019",
            "The Best American Short Stories 2020")
