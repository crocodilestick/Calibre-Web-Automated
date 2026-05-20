# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Backport of CWA PR #1330 (@I-Would-Like-To-Report-A-Bug-Please):
defensive handling of missing/null fields in metadata-search results.

Symptom: metadata-search modal would crash silently when a provider
returned valid results with missing `tags`, `authors`, or `identifiers`
fields. The user saw "no results" even though the backend response was
fine — JS exploded on `book.tags.length` / `book.authors.join(...)` /
`Object.keys(book.identifiers)`.

Root cause: provider contracts were inconsistent
- amazon / amazonjp set `authors = ""` (string) instead of `[]` on
  parse failure
- lubimyczytac returned `None` from `_parse_tags` when a book had no
  tags
- frontend assumed arrays for `book.tags`, `book.authors`, and a dict
  for `book.identifiers`.

These tests source-pin the contracts post-fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text()


def test_amazon_uses_empty_list_for_authors_default():
    """amazon.py's `match = MetaRecord(authors = ...)` must default to
    [] (not ""). Without this the JS join(\" & \") at book_edit.html:364
    crashes on `''.join is not a function` for amazon results that
    failed author extraction."""
    src = _read("cps/metadata_provider/amazon.py")
    assert 'authors = ""' not in src, (
        "amazon.py still has `authors = \"\"` — must be `authors = []` "
        "so the JS frontend can call `.join()` without crashing. "
        "See CWA PR #1330."
    )
    # Pin the corrected forms — both the MetaRecord constructor + the
    # except-branch fallback.
    matches = re.findall(r"authors\s*=\s*\[\]", src)
    assert len(matches) >= 2, (
        f"Expected at least 2 `authors = []` occurrences in amazon.py "
        f"(constructor + except-fallback). Got {len(matches)}."
    )


def test_amazonjp_uses_empty_list_for_authors_default():
    src = _read("cps/metadata_provider/amazonjp.py")
    assert 'authors = ""' not in src, (
        "amazonjp.py still has `authors = \"\"` — must be `authors = []`."
    )
    assert "authors = []" in src


def test_lubimyczytac_parse_tags_returns_empty_list_not_none():
    """`_parse_tags` must return `[]` for books with no tags, never
    None. Returning None made the metadata modal explode on
    `book.tags.length` for valid lubimyczytac results — that was the
    original report on CWA #1330."""
    src = _read("cps/metadata_provider/lubimyczytac.py")
    # The function body must end with `return []`, not `return None`.
    match = re.search(
        r"def _parse_tags\(self\)[^:]*:.*?(?=def \w)",
        src,
        re.DOTALL,
    )
    assert match, "Could not locate _parse_tags function body"
    body = match.group(0)
    assert "return []" in body, (
        f"_parse_tags must return [] for the empty-tags path. Body: {body!r}"
    )
    assert "return None" not in body, (
        f"_parse_tags must not return None. Body: {body!r}"
    )


def test_get_meta_js_defends_against_undefined_array():
    """`$.each(book[attribute_name], ...)` must be guarded so a
    provider that returns `null` for an array field doesn't crash the
    de-duplication step."""
    src = _read("cps/static/js/get_meta.js")
    assert re.search(
        r"\$\.each\(book\[attribute_name\]\s*\|\|\s*\[\]\s*,",
        src,
    ), (
        "get_meta.js must guard `$.each(book[attribute_name] || [], ...)` "
        "so a provider returning null for an array field doesn't crash "
        "the de-dup loop. See CWA PR #1330."
    )


def test_get_meta_js_defends_against_undefined_identifiers():
    """`Object.keys(book.identifiers)` crashes when identifiers is
    undefined — guard with `|| {}`."""
    src = _read("cps/static/js/get_meta.js")
    assert re.search(
        r"Object\.keys\(book\.identifiers\s*\|\|\s*\{\s*\}\s*\)",
        src,
    ), (
        "get_meta.js must guard `Object.keys(book.identifiers || {})` "
        "so a provider returning undefined identifiers doesn't crash "
        "the identifiers selector. See CWA PR #1330."
    )


def test_book_edit_template_guards_authors_join():
    """The modal template's `book.authors.join(\" & \")` must be
    guarded with `|| []` so a provider that didn't populate authors
    renders the row blank rather than crashing the whole modal."""
    src = _read("cps/templates/book_edit.html")
    assert "(book.authors || []).join" in src, (
        "book_edit.html must guard `(book.authors || []).join(\" & \")` "
        "so providers that don't populate authors render an empty cell "
        "instead of crashing the modal. See CWA PR #1330."
    )


def test_book_edit_template_guards_tags_length_check():
    """The `<% if (book.tags.length !== 0) %>` check must be guarded
    with `book.tags &&` so a null `tags` field doesn't throw."""
    src = _read("cps/templates/book_edit.html")
    assert "book.tags && book.tags.length" in src, (
        "book_edit.html must guard `book.tags && book.tags.length !== 0` "
        "so a null tags field doesn't crash the template. See CWA #1330."
    )


def test_book_edit_template_guards_identifiers_keys_check():
    """`Object.keys(book.identifiers).length` similarly needs a
    `book.identifiers &&` short-circuit."""
    src = _read("cps/templates/book_edit.html")
    assert "book.identifiers && Object.keys(book.identifiers)" in src, (
        "book_edit.html must guard `book.identifiers && "
        "Object.keys(book.identifiers).length` so missing identifiers "
        "don't crash the template. See CWA PR #1330."
    )
