# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backport of janeczku/calibre-web#3370 (@ryan-c-scott) — section
progress indicator in the web EPUB reader.

Upstream shows ``XX%`` (book progress only); this backport extends to
``XX% (YY% in book)`` — section progress alongside total. Adapted to
our split ``epub-progress.js`` architecture (the upstream PR inlined
the logic in ``epub.js``; ours splits progress handling out).

These tests source-pin the JS-side contract:

1. ``calculateSectionProgress`` function defined in epub-progress.js.
2. The locationchange handler formats the dual-progress string when
   ``calculateSectionProgress`` returns a number, falls back to the
   book-only single-number when it returns null (before
   ``locations.generate()`` resolves).
3. The CW #3370 anchor comment is present so a future refactor knows
   the rationale and the upstream link.
4. The localStorage save still passes the BOOK percentage (single
   number, contract preserved across upgrades — section% would change
   the saved-state shape and break older sessions).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
EPUB_PROGRESS_JS = REPO_ROOT / "cps" / "static" / "js" / "reading" / "epub-progress.js"


def _source() -> str:
    return EPUB_PROGRESS_JS.read_text()


def test_calculate_section_progress_function_defined():
    """The helper must be defined as a top-level function so it's
    callable from the locationchange handler."""
    src = _source()
    assert re.search(
        r"^function calculateSectionProgress\(\)\s*\{",
        src,
        re.MULTILINE,
    ), (
        "epub-progress.js must define `function calculateSectionProgress()` "
        "so the locationchange handler can call it. See janeczku/calibre-web#3370."
    )


def test_section_progress_uses_spine_get_and_cfi_base():
    """The algorithm walks the spine for the current location's `index`
    and slices `book.locations._locations` by `cfiBase`. Source-pin
    both calls so a future refactor doesn't silently switch to a
    different (less accurate) computation."""
    src = _source()
    body_match = re.search(
        r"function calculateSectionProgress\(\)\s*\{(?P<body>.*?)\n\}\n",
        src,
        re.DOTALL,
    )
    assert body_match, "Could not locate calculateSectionProgress body"
    body = body_match.group("body")
    # Note: upstream PR uses `reader.book.spine.get(...)` because it runs
    # inside epub.js where `reader.book === epub`. Our adapter uses the
    # `epub` global directly — `reader.book.locations._locations` stays
    # empty in our split-file setup. Accept either form so a future
    # refactor that consolidates files doesn't trip the source-pin.
    assert ("epub.spine.get(" in body) or ("reader.book.spine.get(" in body), (
        "calculateSectionProgress must resolve the current section via "
        "`spine.get(loc.start.index)` on either the `epub` global "
        "(our adapter) or `reader.book` (upstream PR shape). See CW #3370."
    )
    assert "cfiBase" in body, (
        "calculateSectionProgress must slice the locations list by the "
        "spine item's `cfiBase` to identify the section's start/end CFIs."
    )
    assert "percentageFromCfi" in body, (
        "calculateSectionProgress must use `book.locations.percentageFromCfi` "
        "to map CFIs to numeric percentages."
    )


def test_section_progress_handles_findlast_fallback():
    """findLast is ES2023 (Safari 15.4+); the implementation must
    provide a manual reverse-iteration fallback for older runtimes.
    Defense-in-depth: even though our reader UI targets modern
    browsers, the fallback prevents a hard ReferenceError on
    older clients."""
    src = _source()
    body_match = re.search(
        r"function calculateSectionProgress\(\)\s*\{(?P<body>.*?)\n\}\n",
        src,
        re.DOTALL,
    )
    body = body_match.group("body")
    assert "findLast" in body, (
        "calculateSectionProgress must use Array.prototype.findLast as "
        "the fast path (per upstream PR)."
    )
    assert "typeof" in body and "findLast" in body, (
        "calculateSectionProgress must gate `findLast` behind a `typeof` "
        "check and provide a manual reverse-iteration fallback for "
        "older runtimes that lack the ES2023 method."
    )


def test_locationchange_handler_emits_dual_progress_string():
    """The handler must format `XX% (YY% in book)` when the section
    helper returns a number, and fall back to `XX%` (book-only) when
    it returns null (early calls before locations.generate() resolves)."""
    src = _source()
    handler_match = re.search(
        r"window\.addEventListener\(['\"]locationchange['\"].*?\}\);",
        src,
        re.DOTALL,
    )
    assert handler_match, "Could not locate locationchange handler"
    body = handler_match.group(0)
    assert "calculateSectionProgress" in body, (
        "locationchange handler must call calculateSectionProgress() "
        "to drive the section-progress portion of the display."
    )
    assert "in book" in body, (
        "locationchange handler must format `XX% (YY% in book)` per "
        "ryan-c-scott's design in CW #3370."
    )
    # Fall-back path: when sectionPct is null, plain `XX%` book-only.
    assert re.search(r"newPos\s*\+\s*['\"]%['\"]", body), (
        "locationchange handler must preserve the `newPos+\"%\"` "
        "book-only fallback for the early-call case where section "
        "computation isn't ready."
    )


def test_localstorage_save_preserves_book_percentage_shape():
    """The localStorage save value must remain a single book-percentage
    integer. Switching to a composite shape would break older sessions
    whose saved progress is `parseInt`-readable. The dual display is
    a UI-only change."""
    src = _source()
    handler_match = re.search(
        r"window\.addEventListener\(['\"]locationchange['\"].*?\}\);",
        src,
        re.DOTALL,
    )
    body = handler_match.group(0)
    # The localStorage set must use `newPos` (the book percentage)
    # directly — no concatenation with section%.
    save_match = re.search(
        r"localStorage\.setItem\([^,]+,\s*([^)]+)\)",
        body,
    )
    assert save_match, "Could not find localStorage.setItem in handler"
    value_arg = save_match.group(1).strip()
    assert value_arg == "newPos", (
        f"localStorage save must pass `newPos` (book percentage) verbatim — "
        f"changing this shape would break saved-progress reads on next page "
        f"load. Got: {value_arg!r}. See CW #3370 backport notes."
    )


def test_cw_3370_anchor_comment_present():
    """A search anchor in the file lets future code archaeology find
    why we have this composite display + why the localStorage save
    intentionally stayed single-value."""
    src = _source()
    assert "CW #3370" in src or "calibre-web#3370" in src, (
        "epub-progress.js must reference CW #3370 (the upstream PR) so a "
        "future refactor can find the rationale for the dual-progress "
        "display + the localStorage compatibility decision."
    )
