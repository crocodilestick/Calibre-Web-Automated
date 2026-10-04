# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Wrong-book records that auto metadata fetch applied on a real CWA ingest.

Each case is a provider record that was written over a correctly named book
(the file and its folder were right, only the database record changed). The
titles are public books; the candidate records are the ones the providers
returned first.
"""

from types import SimpleNamespace as NS

import pytest

import cps.metadata_helper as m

pytestmark = pytest.mark.unit


def _cand(title, authors=None, identifiers=None):
    return NS(title=title, authors=list(authors or []), identifiers=identifiers or {})


WRONG_BOOK_CASES = [
    # (book title, book authors, candidate title, candidate authors)
    ("The Selfish Gene", ["Richard Dawkins"],
     "Summary of The Selfish Gene 40th Anniversary Edition by Richard Dawkins",
     ["Readtrepreneur Publishing"]),
    ("Outgrowing God", ["Richard Dawkins"],
     "SUMMARY: Outgrowing God (UNOFFICIAL SUMMARY)",
     ["Powerful Insights"]),
    ("Flights of Fancy", ["Richard Dawkins"],
     "Summary of Richard Dawkins's Flights of Fancy",
     ["Irb Media"]),
    ("Outgrowing God", ["Richard Dawkins"],
     "Outgrowing God? A Beginner's Guide to Richard Dawkins and the God Debate",
     ["Peter S. Williams"]),
    ("The Ancestor's Tale", ["Richard Dawkins"],
     "Books By Richard Dawkins: The Selfish Gene, The God Delusion, The Blind Watchmaker",
     ["Books LLC"]),
    ("Start With Why", ["Simon Sinek"],
     "Start With Why By Simon Sinek ,The $100 Startup By Chris Guillebeau 2 Books Collection Set",
     ["Simon Sinek", "Chris Guillebeau"]),
    # A James Patterson novel got the authors of an Immortal Hulk comic record.
    ("Cross", ["James Patterson"],
     "Immortal Hulk #35",
     ["Al Ewing", "Alex Ross"]),
]


class TestWrongBookRecordsAreRejected:
    @pytest.mark.parametrize("book_title,book_authors,cand_title,cand_authors", WRONG_BOOK_CASES)
    def test_record_for_a_different_book_is_not_applied(
            self, book_title, book_authors, cand_title, cand_authors):
        assert m._select_metadata_result(
            [_cand(cand_title, cand_authors)], None,
            book_title=book_title, book_authors=book_authors,
        ) is None

    def test_real_book_wins_over_a_summary_ranked_first(self):
        summary = _cand("Summary of Richard Dawkins's Flights of Fancy", ["Irb Media"])
        real = _cand("Flights of Fancy", ["Richard Dawkins"])
        assert m._select_metadata_result(
            [summary, real], None,
            book_title="Flights of Fancy", book_authors=["Richard Dawkins"],
        ) is real
