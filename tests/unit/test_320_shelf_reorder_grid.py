# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #320 (@SpookyUSAF, design seconded by @droM4X): the shelf reorder
screen is a responsive cover grid with save-on-drop — no more vertical list
at 10% browser zoom, no Save button to forget.

Design decisions pinned here:
- The reorder stays on its own page rather than live-dragging in the shelf
  view: the shelf grid's existing cover-drag is the destructive book MERGE,
  and disambiguating drop-on (merge) from drop-between (reorder) by pixels
  would put a data-destroying action one mis-drop away — worst on touch.
- Touch uses long-press-to-lift (Sortable delayOnTouchOnly) so plain swipes
  scroll the page.
- Keyboard: covers are focusable; arrow keys move them; an aria-live status
  line announces positions and doubles as the error/retry control.
- POST accepts JSON {"order": [...]} normalized via normalize_shelf_order —
  unknown ids dropped, duplicates collapsed, missing books keep their
  relative order at the end. The legacy form shape (which raised KeyError →
  500 on a stale page) is still accepted, tolerantly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELF_PY = (REPO_ROOT / "cps" / "shelf.py").read_text()
ORDER_HTML = (REPO_ROOT / "cps" / "templates" / "shelf_order.html").read_text()
ORDER_JS = (REPO_ROOT / "cps" / "static" / "js" / "shelforder.js").read_text()


def _isolated(*func_names):
    """Exec the named module-level functions from shelf.py in isolation
    (the cps import chain isn't needed for pure helpers)."""
    ns: dict = {}
    for name in func_names:
        match = re.search(
            r"(def %s\(.*?)(?=\ndef |\n@|\nclass )" % re.escape(name),
            SHELF_PY, re.DOTALL,
        )
        assert match, f"{name} not found in cps/shelf.py"
        exec(match.group(1), ns)  # noqa: S102 - fixture source, not user input
    return ns


# --------------------------------------------------- position computation

class TestComputeShelfPositions:
    def _fn(self):
        return _isolated("normalize_shelf_order", "compute_shelf_positions")[
            "compute_shelf_positions"]

    def test_full_permutation(self):
        fn = self._fn()
        assert fn([30, 10, 20], [10, 20, 30]) == {30: 1, 10: 2, 20: 3}

    def test_stale_payload_missing_books_keep_relative_order_at_end(self):
        """A book added to the shelf after page load must keep a position
        (the legacy handler 500'd here)."""
        fn = self._fn()
        assert fn([20, 10], [10, 20, 30, 40]) == {20: 1, 10: 2, 30: 3, 40: 4}

    def test_unknown_ids_dropped_duplicates_collapse(self):
        fn = self._fn()
        assert fn([99, 20, 20, "junk", 10], [10, 20]) == {20: 1, 10: 2}

    def test_string_ids_coerced(self):
        fn = self._fn()
        assert fn(["2", "1"], [1, 2]) == {2: 1, 1: 2}

    def test_empty_payload_keeps_current_order(self):
        fn = self._fn()
        assert fn([], [5, 6, 7]) == {5: 1, 6: 2, 7: 3}


# ----------------------------------------------- behavioral: apply + save

class TestReorderPersistence:
    @pytest.fixture
    def ub_session(self):
        from cps import ub
        engine = create_engine("sqlite:///:memory:", future=True)
        ub.Base.metadata.create_all(engine)
        s = sessionmaker(bind=engine, future=True)()
        original = ub.session
        ub.session = s
        try:
            yield s
        finally:
            ub.session = original
            s.close()

    def test_route_apply_block_renumbers_sequentially(self, ub_session):
        """Replicates the route's apply block against a real session: the
        JSON order [30, 10, 20] must persist as orders 1..3."""
        from cps import ub
        from sqlalchemy import func  # noqa: F401  (parity with route imports)
        shelf = ub.Shelf(name="R", is_public=0, user_id=1)
        shelf.id = 9
        ub_session.add(shelf)
        for bid, order in ((10, 1), (20, 2), (30, 3)):
            shelf.books.append(ub.BookShelf(shelf=9, book_id=bid, order=order))
        ub_session.commit()

        fns = _isolated("normalize_shelf_order", "compute_shelf_positions")
        books_in_shelf = (ub_session.query(ub.BookShelf)
                          .filter(ub.BookShelf.shelf == 9)
                          .order_by(ub.BookShelf.order.asc()).all())
        available = [e.book_id for e in books_in_shelf]
        positions = fns["compute_shelf_positions"]([30, 10, 20], available)
        for entry in books_in_shelf:
            entry.order = positions[entry.book_id]
        ub_session.commit()

        rows = (ub_session.query(ub.BookShelf).filter(ub.BookShelf.shelf == 9)
                .order_by(ub.BookShelf.order).all())
        assert [(r.book_id, r.order) for r in rows] == [(30, 1), (10, 2), (20, 3)]


# ------------------------------------------------------------ source pins

class TestRouteContract:
    def _body(self):
        return SHELF_PY.split("def order_shelf", 1)[1].split("\n@shelf.route", 1)[0]

    def test_json_payload_accepted_and_normalized(self):
        body = self._body()
        assert "request.is_json" in body
        assert "get_json(silent=True)" in body, "malformed JSON must not 500"
        assert "compute_shelf_positions" in body

    def test_legacy_form_path_is_tolerant(self):
        """The old handler did to_save[str(book.book_id)] — KeyError → 500
        when the shelf changed between page load and save."""
        body = self._body()
        assert "to_save[str(" not in body, "raw dict indexing of form keys is the 500 bug"
        assert "to_save.get(" in body

    def test_edit_permission_denial_returns_403_json_for_fetch(self):
        body = self._body()
        assert "403" in body, "the grid's fetch needs a JSON 403, not a redirect"


class TestTemplateContract:
    def test_grid_uses_responsive_book_card_classes(self):
        assert 'id="reorder-grid"' in ORDER_HTML
        assert "col-xs-6" in ORDER_HTML, (
            "cards must use the responsive column classes of the regular "
            "cover grid — the vertical list at 10%% zoom was the complaint"
        )
        assert "display-flex" in ORDER_HTML

    def test_no_save_button(self):
        assert 'id="ChangeOrder"' not in ORDER_HTML, (
            "saving is automatic on every change; a Save button reintroduces "
            "the forget-to-save failure mode"
        )
        assert "sendData(" not in ORDER_HTML

    def test_accessibility_wiring(self):
        assert 'aria-live="polite"' in ORDER_HTML
        assert 'tabindex="0"' in ORDER_HTML
        assert 'role="list"' in ORDER_HTML

    def test_grid_not_wrapped_in_discover_isotope_selector(self):
        """main.js initializes isotope on every `.discover .row` containing
        .book cards. Isotope absolutely-positions cards from its own item
        model, which desyncs from Sortable's DOM moves — a resize or font
        load snaps covers back to the pre-drag picture while the DB holds
        the new order. The reorder page must NOT match that selector."""
        assert 'class="discover"' not in ORDER_HTML, (
            "shelf_order.html must not use class=discover — isotope would "
            "capture the reorder grid and fight Sortable"
        )

    def test_status_line_carries_translated_strings(self):
        for attr in ("data-saving-text", "data-saved-text", "data-error-text",
                     "data-moved-text"):
            assert attr in ORDER_HTML, f"status line must carry {attr}"


class TestJsContract:
    def test_touch_uses_long_press(self):
        assert "delayOnTouchOnly: true" in ORDER_JS, (
            "without delayOnTouchOnly a plain swipe grabs a cover instead of "
            "scrolling the page"
        )

    def test_keyboard_handler_moves_cards(self):
        assert "ArrowLeft" in ORDER_JS and "ArrowRight" in ORDER_JS
        assert "insertBefore" in ORDER_JS

    def test_persist_is_json_with_csrf(self):
        assert "X-CSRFToken" in ORDER_JS
        assert "JSON.stringify({order: currentOrder()})" in ORDER_JS

    def test_failure_surfaces_with_retry(self):
        assert "reorder-error" in ORDER_JS
        assert "catch" in ORDER_JS
