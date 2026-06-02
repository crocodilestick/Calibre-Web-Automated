# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression test for fork #352 (@SethMilliken).

Symptom: PR #161 (drag-and-drop book merge) shipped with `draggable="true"`
set on the whole `.book` grid card. On Safari/WebKit (the reporter's browser,
also the household's) a `draggable="true"` ancestor suppresses native text
selection of its descendants, so users can't select the title/author text in
the grid. The same script also ran on the book detail page (`<body data-page="book">`),
adding a pointless drag source to the cover there.

Browser repro (cwn-local, 2026-06-01T22:09Z): all 4 grid `.book` cards carried
`draggable="true"` and the title's ancestor chain hit the draggable card —
confirms the selection block.

Root cause (cps/static/js/drag-drop-merge.js):
  * `BOOK_SELECTOR = ".book"` matches both grid cards and the lone `.book`
    that exists in the detail template, so init runs on both surfaces.
  * `enableDrag(bookEl)` sets `draggable="true"` on the whole `.book` card.

Fix:
  A. Move the drag SOURCE off the whole card and onto the `.cover` element,
     so the title/author text in `.meta` stays selectable. Drop target stays
     the whole card (you can drop the source cover onto any part of the
     target card).
  B. Tighten the selector to `.book.session` so the script only initialises
     on the grid (the index/search/author/shelf templates render the card
     with both `book` and `session` classes; the detail page does not).

These pins are deliberately at the source level — the JS is delivered as a
static asset, so a pytest hitting Flask wouldn't catch a regression. The
behavioural proof lives in the Playwright run in the PR; this guard catches
a future refactor that re-broadens the selector or re-binds drag at the card
level.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "cps" / "static" / "js" / "drag-drop-merge.js"


@pytest.fixture(scope="module")
def js_src() -> str:
    assert JS_PATH.exists(), f"missing {JS_PATH}"
    return JS_PATH.read_text(encoding="utf-8")


@pytest.mark.unit
class TestDragMergeTextSelectionRegression:
    def test_book_selector_scoped_to_grid_session_class(self, js_src):
        """Fix B: the selector must NOT match the lone `.book` element on the
        book detail template. Tightening to `.book.session` excludes detail
        (grid cards always carry both classes; detail doesn't carry `session`)."""
        m = re.search(r'(?:^|\s)var\s+BOOK_SELECTOR\s*=\s*"([^"]+)"\s*;', js_src, re.MULTILINE)
        assert m is not None, "could not find BOOK_SELECTOR declaration"
        sel = m.group(1)
        assert sel != ".book", (
            "BOOK_SELECTOR is still bare '.book' — that matches the lone "
            "`.book` on the detail template and runs drag-merge init there "
            "(#352 complaint #2). Tighten to '.book.session' to scope it "
            "to the grid."
        )
        assert "session" in sel, (
            f"BOOK_SELECTOR must restrict to grid cards (which carry the "
            f"`session` class). Got: {sel!r}"
        )

    def test_drag_source_is_cover_not_whole_card(self, js_src):
        """Fix A: `draggable="true"` must NOT be set on the `.book` card —
        Safari/WebKit suppresses text selection of any descendant of a
        draggable ancestor. Move the drag source to `.cover` so the title
        and author text in `.meta` stay selectable (#352 complaint #1)."""
        # Match the full enableDrag body, anchored on the 2-space-indented
        # closing brace so an inner `if (cover) { ... }` block doesn't
        # truncate the capture.
        m = re.search(
            r"function\s+enableDrag\s*\([^)]*\)\s*\{(.*?)\n  \}\s*\n",
            js_src,
            re.DOTALL,
        )
        assert m is not None, "could not find enableDrag function body"
        body = m.group(1)

        # The card itself must not be made draggable.
        assert not re.search(
            r'bookEl\.setAttribute\(\s*["\']draggable["\']\s*,\s*["\']true["\']\s*\)',
            body,
        ), (
            "enableDrag still sets `draggable=\"true\"` on the whole .book "
            "card (#352): Safari suppresses text selection of any "
            "descendant of a draggable ancestor. Move the drag source onto "
            "the cover element instead."
        )

        # And the cover-scoped drag source must be wired in.
        assert re.search(
            r'\.setAttribute\(\s*["\']draggable["\']\s*,\s*["\']true["\']\s*\)',
            body,
        ), (
            "enableDrag should set draggable=true on the cover element — "
            "the title/author text stays selectable, but the cover is still "
            "a valid drag source."
        )
        assert "cover" in body.lower() or "COVER" in body, (
            "enableDrag must reference the cover element to scope the drag "
            "source there (e.g. querySelector('.cover'))."
        )

    def test_dragstart_and_dragend_bound_on_cover_not_card(self, js_src):
        """The dragstart/dragend events fire from where draggable is set;
        binding them on the card is dead weight after the move, and binding
        them on the card again would re-introduce the symptom."""
        # Match the full enableDrag body, anchored on the 2-space-indented
        # closing brace so an inner `if (cover) { ... }` block doesn't
        # truncate the capture.
        m = re.search(
            r"function\s+enableDrag\s*\([^)]*\)\s*\{(.*?)\n  \}\s*\n",
            js_src,
            re.DOTALL,
        )
        assert m is not None
        body = m.group(1)
        assert not re.search(
            r'bookEl\.addEventListener\(\s*["\']dragstart["\']', body,
        ), (
            "dragstart must NOT be bound on the .book card after #352 — "
            "the card is no longer the drag source. Bind dragstart on the "
            "cover element."
        )

    def test_drop_target_still_whole_card(self, js_src):
        """The drop TARGET stays the whole card so the user can drop the
        source cover onto any part of the target (cover + meta area).
        Without this, dropping onto title/author text would be a no-op."""
        # Match the full enableDrag body, anchored on the 2-space-indented
        # closing brace so an inner `if (cover) { ... }` block doesn't
        # truncate the capture.
        m = re.search(
            r"function\s+enableDrag\s*\([^)]*\)\s*\{(.*?)\n  \}\s*\n",
            js_src,
            re.DOTALL,
        )
        assert m is not None
        body = m.group(1)
        assert re.search(
            r'bookEl\.addEventListener\(\s*["\']drop["\']', body,
        ), (
            "drop listener must remain bound on the whole .book card so the "
            "card stays a full drop target."
        )
