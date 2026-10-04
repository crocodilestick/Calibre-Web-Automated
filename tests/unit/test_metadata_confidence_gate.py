# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Auto-metadata confidence gate.

Ported from Calibre-Web-NextGen 54ec99033 (NextGen #1197, fixing NextGen issue
#1164 reported by @auspex), by nate (new-usemame).

Reporter (@auspex) dropped an ACSM into the ingest folder; the EPUB carried the
correct title and author, the search ran as ``The Devils Joe Abercrombie``, and
the log then read::

    Successfully applied metadata from Kobo for book: The Heretics

``The Heretics`` is a different, then-unpublished Abercrombie book. Nothing in
the UI or the log flagged the substitution. The book's correct title, author
and description were silently overwritten.

Root cause: ``_select_metadata_result`` gates only on ISBN (NextGen #402). A freshly
ingested EPUB normally has no ISBN, so the ISBN branch is skipped entirely and
the function falls through to ``results[0]`` (whatever the provider happened to
rank first) with no check that the candidate is even the same book.

These tests pin the post-fix contract:

- a candidate whose title does not plausibly match the book's is never applied,
  even when the author agrees and even when it is the provider's first result;
- the *best* candidate is chosen rather than the first, so a correct match
  further down the list wins;
- ordinary title variance (case, punctuation, a leading article, a publisher's
  subtitle) still matches, so the gate does not simply disable auto-fetch;
- when nothing clears the bar the function returns ``None`` and the caller
  applies nothing and moves to the next provider. No metadata beats wrong
  metadata;
- the #402 ISBN priority is preserved unchanged.
"""

from types import SimpleNamespace as NS

import pytest

import cps.metadata_helper as m

pytestmark = pytest.mark.unit


def _cand(title, authors=None, identifiers=None):
    """A provider search result: only the fields the selector reads."""
    return NS(title=title, authors=list(authors or []), identifiers=identifiers or {})


# --- the reporter's exact case ----------------------------------------------

class TestReporterCase:
    def test_the_heretics_is_not_applied_over_the_devils(self):
        """@auspex's trace: first result is a different book by the same author."""
        heretics = _cand("The Heretics", ["Joe Abercrombie"])
        assert m._select_metadata_result(
            [heretics], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is None

    def test_correct_edition_further_down_the_list_wins(self):
        """Selection must consider every candidate, not just results[0]."""
        heretics = _cand("The Heretics", ["Joe Abercrombie"])
        little_hatred = _cand("A Little Hatred", ["Joe Abercrombie"])
        devils = _cand("The Devils", ["Joe Abercrombie"])
        assert m._select_metadata_result(
            [heretics, little_hatred, devils], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is devils

    def test_same_author_does_not_rescue_an_unrelated_title(self):
        """Author agreement lowers the title bar; it must never remove it."""
        assert m._select_metadata_result(
            [_cand("The Blade Itself", ["Joe Abercrombie"])], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is None


# --- the gate must not break ordinary matching -------------------------------

class TestLegitimateMatchesStillApply:
    @pytest.mark.parametrize("candidate_title", [
        "The Devils",
        "the devils",
        "The Devils: A Novel",
        "Devils",
        "The Devils (First Law World)",
    ])
    def test_ordinary_title_variance_matches(self, candidate_title):
        cand = _cand(candidate_title, ["Joe Abercrombie"])
        assert m._select_metadata_result(
            [cand], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is cand

    def test_exact_title_matches_without_author_information(self):
        """A book ingested with no author still auto-fetches on an exact title."""
        cand = _cand("The Devils", [])
        assert m._select_metadata_result(
            [cand], None, book_title="The Devils", book_authors=[],
        ) is cand

    def test_author_initials_still_agree_on_surname(self):
        """Providers routinely differ on how they credit a given name."""
        cand = _cand("The Devils", ["J. Abercrombie"])
        assert m._select_metadata_result(
            [cand], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is cand

    @pytest.mark.parametrize("book_title,candidate_title", [
        ("Harry Potter and the Chamber of Secrets",
         "Harry Potter & the Chamber of Secrets"),
        ("Les Misérables", "Les Miserables"),
    ])
    def test_punctuation_and_diacritic_variance_matches(self, book_title, candidate_title):
        cand = _cand(candidate_title, ["Author Name"])
        assert m._select_metadata_result(
            [cand], None, book_title=book_title, book_authors=["Author Name"],
        ) is cand


# --- series siblings are the dangerous near-miss ------------------------------

class TestSeriesSiblingsAreRejected:
    """Found by measuring scores rather than by a failing test: character
    similarity alone rates "Harry Potter and the Chamber of Secrets" against
    "...and the Goblet of Fire" at 0.78, because series titles share a long
    prefix. Any threshold loose enough to accept real title variance would have
    accepted these, so the gate compares identifying words, not characters."""

    @pytest.mark.parametrize("book_title,candidate_title", [
        ("Harry Potter and the Chamber of Secrets",
         "Harry Potter and the Goblet of Fire"),
        ("Dune", "Dune: Messiah"),
        ("Dune Messiah", "Children of Dune"),
        # Same words, different order, so a different book.
        ("Blood and Iron", "Iron and Blood"),
    ])
    def test_sibling_titles_are_not_applied(self, book_title, candidate_title):
        assert m._select_metadata_result(
            [_cand(candidate_title, ["Same Author"])], None,
            book_title=book_title, book_authors=["Same Author"],
        ) is None


# --- a shared title across different books -----------------------------------

class TestAuthorDisagreementRejects:
    def test_identical_title_by_a_different_author_is_rejected(self):
        """Titles collide across unrelated books; the author breaks the tie."""
        assert m._select_metadata_result(
            [_cand("The Devils", ["Someone Else"])], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is None

    @pytest.mark.parametrize("book_author,candidate_author", [
        # Calibre stores and sorts authors "Last, First"; providers return
        # "First Last". Keying agreement on the final word would make these
        # disagree and reject a correct match for most books in a library.
        ("Stephen King", "King, Stephen"),
        ("King, Stephen", "Stephen King"),
        ("Philip K. Dick", "Dick, Philip K."),
        ("Joe Abercrombie", "J. Abercrombie"),
    ])
    def test_author_name_order_does_not_reject_a_correct_match(
            self, book_author, candidate_author):
        cand = _cand("The Stand", [candidate_author])
        assert m._select_metadata_result(
            [cand], None, book_title="The Stand", book_authors=[book_author],
        ) is cand

    def test_missing_author_information_does_not_reject(self):
        cand = _cand("The Stand", [])
        assert m._select_metadata_result(
            [cand], None, book_title="The Stand", book_authors=["Stephen King"],
        ) is cand

    def test_authors_given_as_a_bare_string_are_not_walked_per_character(self):
        """A str is iterable; iterating it would yield single letters, silently
        emptying the author signal instead of comparing names."""
        assert m._author_name_tokens("Stephen King") == {"stephen", "king"}


# --- degenerate input must not crash or collide ------------------------------

class TestDegenerateInput:
    @pytest.mark.parametrize("book_title,candidate_title", [
        ("The The", "A An Of"),      # everything is a joining word
        ("!!!", "???"),              # nothing survives normalization
        ("and the of", "in on to"),
    ])
    def test_titles_with_no_identifying_words_never_match(self, book_title, candidate_title):
        """Both sides reduce to an empty word tuple; equality on empties would
        make every such pair a perfect match."""
        assert m._select_metadata_result(
            [_cand(candidate_title, ["Same Author"])], None,
            book_title=book_title, book_authors=["Same Author"],
        ) is None

    @pytest.mark.parametrize("left,right", [(None, "X"), ("X", None), (123, "X")])
    def test_non_string_titles_do_not_raise(self, left, right):
        assert m._title_similarity(left, right) == 0.0

    def test_result_without_a_title_attribute_is_not_applied(self):
        class Bare:
            pass
        assert m._select_metadata_result(
            [Bare()], None, book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is None


# --- #402 ISBN priority is preserved ----------------------------------------

class TestISBNPriorityUnchanged:
    def test_isbn_match_still_wins_over_title_score(self):
        right = _cand("The Devils", ["Joe Abercrombie"], {"isbn": "978-0-316-05543-7"})
        wrong = _cand("The Devils", ["Joe Abercrombie"], {"isbn": "111"})
        assert m._select_metadata_result(
            [wrong, right], "9780316055437",
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is right

    def test_legacy_two_argument_call_is_unchanged(self):
        """Existing callers/tests that pass no title keep the old behaviour."""
        first = _cand("Anything", [])
        assert m._select_metadata_result([first, _cand("Other", [])], None) is first


# --- the caller must actually use the gate -----------------------------------

class TestCallerWiresTheGate:
    def test_fetch_passes_title_and_authors_to_the_selector(self):
        """Source-pin: a future edit that drops the arguments silently disables
        the gate (the parameters default to None for back-compat), so pin the
        call site rather than trusting it."""
        import inspect
        src = inspect.getsource(m.fetch_and_apply_metadata)
        assert "book_title=" in src and "book_authors=" in src, (
            "fetch_and_apply_metadata must pass the book's title and authors to "
            "_select_metadata_result or the #1164 confidence gate is inert"
        )

    def test_rejected_candidate_is_not_applied(self, monkeypatch):
        """End of the path: gate rejects -> nothing is written to the book."""
        applied = []
        monkeypatch.setattr(
            m, "_apply_metadata_to_book",
            lambda *a, **k: applied.append(a) or True,
        )
        assert m._select_metadata_result(
            [_cand("The Heretics", ["Joe Abercrombie"])], None,
            book_title="The Devils", book_authors=["Joe Abercrombie"],
        ) is None
        assert applied == []


# --- the log must not report the overwritten title ---------------------------

class TestLogReportsTheBookItSearchedFor:
    def test_success_log_uses_the_pre_apply_title(self):
        """The reporter's log said 'for book: The Heretics' because it read
        book.title *after* the overwrite, hiding which book was affected."""
        import inspect
        src = inspect.getsource(m.fetch_and_apply_metadata)
        apply_at = src.index("_apply_metadata_to_book(book")
        log_at = src.index("Successfully applied metadata from")
        snippet = src[apply_at:log_at]
        assert "book.title" not in src[log_at:log_at + 200], (
            "the success log must report the title captured before "
            "_apply_metadata_to_book mutated it"
        )
        assert snippet is not None
