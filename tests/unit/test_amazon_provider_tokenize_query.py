# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Source-pin that the Amazon provider tokenizes its query (issue #217).

The first half of the #217 fix made ``Metadata.get_title_tokens`` strip
apostrophe-class characters. But ``cps/metadata_provider/amazon.py`` was
passing the raw ``query`` string directly into Amazon's ``field-keywords``
parameter — so ``Alice's`` still URL-encoded to ``Alice%27s`` against the
one provider sjthespian explicitly named in the report.

These tests pin that the Amazon search method invokes ``get_title_tokens``
on the query before constructing the request params, and that the resulting
``field-keywords`` value never contains a raw apostrophe.
"""

import inspect
import re
from pathlib import Path


def _amazon_source():
    return (Path(__file__).resolve().parents[2] / "cps" / "metadata_provider" / "amazon.py").read_text()


def test_amazon_search_method_invokes_get_title_tokens_on_query():
    """The Amazon search method must call ``self.get_title_tokens(query, ...)``
    before populating ``field-keywords``. Pinning by source so a refactor
    can't silently revert to passing the raw query.
    """
    src = _amazon_source()
    assert "get_title_tokens" in src, (
        "cps/metadata_provider/amazon.py must invoke get_title_tokens on the "
        "incoming query before sending it to Amazon — without this, "
        "apostrophes in the user-typed query reach the URL as %27 and "
        "Amazon's catalog index misses the book. See fork issue #217 "
        "(@sjthespian, `At Winter's End`)."
    )


def test_amazon_search_query_not_raw_query_in_field_keywords():
    """Pin: ``'field-keywords': query`` (the broken form) must NOT appear.

    The fix replaces it with a tokenized variant. If anyone reverts to the
    raw-query form, this test refuses to compile-pass.
    """
    src = _amazon_source()
    assert not re.search(r"'field-keywords'\s*:\s*query\s*,", src), (
        "Amazon provider must not pass the raw query to field-keywords. "
        "Tokenize via get_title_tokens first so apostrophe-class chars are "
        "stripped before URL encoding."
    )


def test_amazon_search_query_is_space_joined_token_stream():
    """Behavior pin: the build expression for ``field-keywords`` joins the
    token stream with a space and falls back to the original query when the
    tokenizer returns an empty list (e.g. all-punctuation queries).
    """
    src = _amazon_source()
    # Match the chosen pattern: "...".join(self.get_title_tokens(query, ...)) or query
    pattern = re.compile(
        r"\"\s\"\.join\(\s*self\.get_title_tokens\(\s*query[^)]*\)\s*\)\s*or\s+query",
    )
    assert pattern.search(src), (
        "Amazon search must build its query via "
        "`\" \".join(self.get_title_tokens(query, strip_joiners=False)) or query` "
        "so the URL-encoded keywords contain no apostrophes and the empty-"
        "tokenizer-result case falls back to the raw query rather than an "
        "empty string. Current source did not match the expected expression."
    )
