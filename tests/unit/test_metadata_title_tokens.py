# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for the metadata-search title tokenizer (issue #217).

Reporter (@sjthespian) observed that `At Winter's End` returns no metadata-
provider results while `At Winters End` finds the book on first search.
Root cause: `Metadata.get_title_tokens` doesn't normalize the apostrophe,
so providers URL-encode it as `%27`, which catalog indexes that store the
apostrophe-free form don't match.

These tests pin the desired post-fix behaviour: apostrophe-class characters
(ASCII + curly + modifier-letter + backtick + acute-accent) are stripped
during tokenization so the user-typed query maps onto the form most
catalogs actually index.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_metadata_module():
    """Import cps.services.Metadata in isolation (no Flask app boot)."""
    cps_pkg = sys.modules.get("cps")
    if cps_pkg is None:
        cps_pkg = types.ModuleType("cps")
        cps_pkg.__path__ = [str(REPO_ROOT / "cps")]
        sys.modules["cps"] = cps_pkg

    constants = sys.modules.get("cps.constants") or types.ModuleType("cps.constants")
    if not hasattr(constants, "STATIC_DIR"):
        constants.STATIC_DIR = str(REPO_ROOT / "cps" / "static")
    sys.modules["cps.constants"] = constants
    cps_pkg.constants = constants

    spec = importlib.util.spec_from_file_location(
        "cps.services.Metadata",
        REPO_ROOT / "cps" / "services" / "Metadata.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def Metadata():
    return _load_metadata_module().Metadata


def _tokenize(Metadata, title, strip_joiners=False):
    return list(Metadata.get_title_tokens(title, strip_joiners=strip_joiners))


class TestApostropheNormalization:
    """Issue #217 — apostrophes must not produce tokens that catalogs miss."""

    def test_ascii_apostrophe_interior_is_stripped(self, Metadata):
        # Reporter's exact case: `At Winter's End` must tokenize the same
        # way `At Winters End` does, so providers send the form catalogs
        # actually index.
        assert _tokenize(Metadata, "At Winter's End") == ["At", "Winters", "End"]

    def test_ascii_apostrophe_equals_apostrophe_free_form(self, Metadata):
        # The whole point of the fix — both spellings collapse to the same
        # token stream. If this ever drifts, the bug is back.
        with_apos = _tokenize(Metadata, "At Winter's End")
        without = _tokenize(Metadata, "At Winters End")
        assert with_apos == without

    def test_single_word_apostrophe(self, Metadata):
        assert _tokenize(Metadata, "O'Reilly") == ["OReilly"]

    def test_contraction_apostrophe(self, Metadata):
        assert _tokenize(Metadata, "Don't Look Back") == ["Dont", "Look", "Back"]

    def test_possessive_apostrophe(self, Metadata):
        assert _tokenize(Metadata, "Tom's Diner") == ["Toms", "Diner"]

    def test_curly_right_single_quotation_mark_is_stripped(self, Metadata):
        # U+2019 — what word-processors auto-insert. Users copy-paste from
        # store listings and end up with curly apostrophes in the search
        # box; we must treat them the same as ASCII.
        assert _tokenize(Metadata, "At Winter’s End") == ["At", "Winters", "End"]

    def test_curly_left_single_quotation_mark_is_stripped(self, Metadata):
        # U+2018 — less common but appears in some typographic sources.
        assert _tokenize(Metadata, "At Winter‘s End") == ["At", "Winters", "End"]

    def test_modifier_letter_apostrophe_is_stripped(self, Metadata):
        # U+02BC — Hawaiian okina and other linguistic uses.
        assert _tokenize(Metadata, "Hawaiʼi") == ["Hawaii"]

    def test_backtick_used_as_apostrophe_is_stripped(self, Metadata):
        # Some keyboards/layouts produce ` instead of ' for apostrophe.
        assert _tokenize(Metadata, "Don`t Stop") == ["Dont", "Stop"]

    def test_acute_accent_used_as_apostrophe_is_stripped(self, Metadata):
        # U+00B4 — sometimes typed instead of an apostrophe.
        assert _tokenize(Metadata, "L´Etranger") == ["LEtranger"]


class TestExistingBehaviourPreserved:
    """Regression guards — the apostrophe fix must not break anything else."""

    def test_plain_title_unchanged(self, Metadata):
        assert _tokenize(Metadata, "The Great Gatsby") == ["The", "Great", "Gatsby"]

    def test_strip_joiners_still_drops_a_and_the(self, Metadata):
        # When strip_joiners=True the joiner removal applies AFTER the
        # apostrophe strip, so it still works on canonical tokens.
        assert _tokenize(Metadata, "The Great Gatsby", strip_joiners=True) == [
            "Great", "Gatsby",
        ]

    def test_year_in_parentheses_is_still_removed(self, Metadata):
        # Pre-existing behaviour from the upstream Calibre tokenizer.
        assert _tokenize(Metadata, "Some Book (2010)") == ["Some", "Book"]

    def test_special_chars_still_become_spaces(self, Metadata):
        # The colon/semicolon/etc. char class is unchanged.
        assert _tokenize(Metadata, "Title: Subtitle; Part") == [
            "Title", "Subtitle", "Part",
        ]

    def test_double_quote_outer_wrapper_still_stripped(self, Metadata):
        # `.strip('"')` on each token still works.
        assert _tokenize(Metadata, '"Quoted" Title') == ["Quoted", "Title"]

    def test_apostrophe_only_token_drops_to_empty(self, Metadata):
        # If someone types just an apostrophe, no tokens come out (rather
        # than an empty string masquerading as a token).
        assert _tokenize(Metadata, "'") == []
        assert _tokenize(Metadata, "’") == []

    def test_leading_and_trailing_apostrophes_handled(self, Metadata):
        # Pre-existing `.strip("'")` covered outer ASCII apostrophes; the
        # new normalization covers them more uniformly, plus interior ones.
        assert _tokenize(Metadata, "'leading'") == ["leading"]
        assert _tokenize(Metadata, "trailing'") == ["trailing"]

    def test_unicode_cjk_quotes_still_normalized(self, Metadata):
        # The existing char class includes 《》「」“” — apostrophe fix
        # must not displace that handling.
        assert _tokenize(Metadata, "《Title》Text") == ["Title", "Text"]


class TestUrlEncodingDownstream:
    """The fix's purpose is to make URL-encoded queries match catalog indexes."""

    def test_query_url_for_winters_end_has_no_percent27(self, Metadata):
        from urllib.parse import quote

        tokens = _tokenize(Metadata, "At Winter's End")
        url_q = "+".join(quote(t.encode("utf-8")) for t in tokens)
        assert "%27" not in url_q, (
            f"URL-encoded query still contains %27 (apostrophe): {url_q!r}. "
            "Catalog indexes that store the apostrophe-free form will miss this query."
        )
        assert url_q == "At+Winters+End"
