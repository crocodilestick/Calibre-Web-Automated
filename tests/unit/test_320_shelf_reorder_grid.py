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
REORDER_CSS = (REPO_ROOT / "cps" / "static" / "css" / "shelf_reorder.css").read_text()
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


class TestDisplayFollowup320:
    """v4.0.157 follow-up: @droM4X + @SpookyUSAF confirmed the reorder feature
    works but reported two display defects on the default theme — covers render
    near-natural size ("large icon style ... not needed here") and the Back
    button sits too far left with no spacing above it. The default theme caps
    covers only via `.container-fluid .book .cover { height: 225px }`; on this
    fork-new page that box can render uncapped, so covers blow past the normal
    grid size. Both fixes are theme-independent and live in the template's own
    scoped <style> + markup."""

    def test_cover_sizing_externalised_and_self_contained(self):
        # The reorder styles must be an EXTERNAL stylesheet, not an inline
        # <style>: a strict reverse-proxy CSP can strip inline blocks, leaving
        # the cover cap unapplied and covers oversized. @SpookyUSAF still saw
        # oversized covers on v4.0.158 even though the inline rule was in the
        # release — the inline block wasn't reaching their render.
        assert "css/shelf_reorder.css" in ORDER_HTML, (
            "shelf_order.html must link the external shelf_reorder.css"
        )
        _html_no_comments = re.sub(r"\{#.*?#\}", "", ORDER_HTML, flags=re.S)
        assert "<style" not in _html_no_comments, (
            "reorder styles must not live in an inline <style> (CSP-fragile, #320)"
        )
        # The cover sizing must be SELF-CONTAINED — fit inside a 150x225 box
        # regardless of theme or cover orientation, not reliant on caliBlur's
        # width:150 or the default theme's box (which don't always reach this
        # fork-new grid that deliberately avoids .discover/isotope).
        m = re.search(
            r"#reorder-grid\s+\.reorder-item\s+\.cover\s+img\s*\{([^}]*)\}",
            REORDER_CSS,
        )
        assert m, "shelf_reorder.css must size the reorder cover image"
        rule = m.group(1)
        assert "max-width: 150px" in rule and "!important" in rule, (
            "cover must be width-capped to 150px (self-contained), so it stays a "
            "thumbnail even where no theme width rule applies (#320, @SpookyUSAF)"
        )
        assert "max-height: 225px" in rule, "cover must be height-capped to 225px"

    def test_back_button_has_gutter_and_spacing(self):
        # Back button must sit inside a grid column so it inherits the same
        # left gutter as the cover columns on every theme (a bare sibling
        # lands 15px off on caliBlur), and the wrapper must carry top spacing.
        back_idx = ORDER_HTML.find('id="shelf_back"')
        assert back_idx != -1, "shelf_order.html must keep the Back button"
        wrapper = ORDER_HTML[max(0, back_idx - 250):back_idx]
        assert "reorder-back-row" in wrapper and "col-" in wrapper, (
            "the Back button must be wrapped in a grid row/column so it aligns "
            "under the first cover on both themes (#320 follow-up, @droM4X)"
        )
        assert re.search(r"\.reorder-back-row\s*\{[^}]*margin-top", REORDER_CSS), (
            "the Back button row must carry top margin (in shelf_reorder.css) so "
            "it doesn't butt against the cover grid above it"
        )


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
