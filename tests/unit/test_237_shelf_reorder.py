# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #237 (@new-usemame): drag-to-reorder
regular Shelves in the sidebar.

Magic shelves already supported user-ordered display since the
v4.0.39 sort_magic_shelves_for_user work. Regular shelves were
locked to alphabetical (order_by(ub.Shelf.name) in
cps/render_template.py). This issue closes the gap for regular
shelves using the same view_settings storage pattern.

Storage: user.view_settings['shelves'] = {'order': [id, id, ...]}.
Empty / missing keeps alphabetical default. Manual order applies
when the list is non-empty. Sort is stable and tolerant of unknown
or stale IDs in the list (drops them) and newly-added shelves not
yet in the list (appends them at the end, preserving stored prefix).

Endpoint: GET /shelf/reorder renders the drag-list, POST saves
order. Both auth-gated by @user_login_required.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELF_PY = REPO_ROOT / "cps" / "shelf.py"
RENDER_PY = REPO_ROOT / "cps" / "render_template.py"
LAYOUT_HTML = REPO_ROOT / "cps" / "templates" / "layout.html"
REORDER_HTML = REPO_ROOT / "cps" / "templates" / "shelf_reorder.html"


def _shelf_src() -> str:
    return SHELF_PY.read_text()


def _render_src() -> str:
    return RENDER_PY.read_text()


def _layout_src() -> str:
    return LAYOUT_HTML.read_text()


# ---------------------------------------------------------------------------
# normalize_shelf_order: list-validation contract
# ---------------------------------------------------------------------------

def test_normalize_shelf_order_function_exists():
    src = _shelf_src()
    assert re.search(r"def normalize_shelf_order\(", src), (
        "cps/shelf.py must define normalize_shelf_order(order_list, available_ids)"
    )


def test_normalize_shelf_order_behavior():
    """Exec the function body in isolation to avoid the full cps import."""
    src = _shelf_src()
    match = re.search(
        r"(def normalize_shelf_order\(.*?)(?=\n(?:def |@|class ))",
        src, re.DOTALL,
    )
    assert match, "normalize_shelf_order definition not isolated"
    ns: dict = {}
    exec(match.group(1), ns)  # noqa: S102 -- fixture source, not user input
    fn = ns["normalize_shelf_order"]
    assert fn([], []) == []
    assert fn([1, 2, 3], [1, 2, 3]) == [1, 2, 3]
    # Partial stored order: missing shelves appended at the end.
    assert fn([2, 1], [1, 2, 3]) == [2, 1, 3]
    # Stale / unknown IDs in stored order: dropped.
    assert fn([99, 1, 2], [1, 2]) == [1, 2]
    # Duplicates: de-duplicated, first occurrence wins.
    assert fn([1, 1, 2], [1, 2]) == [1, 2]
    # String IDs coerced to int.
    assert fn(["2", "1"], [1, 2]) == [2, 1]
    # None / non-coerceable input: ignored.
    assert fn([None, "abc", 1], [1, 2]) == [1, 2]


# ---------------------------------------------------------------------------
# sort_shelves_for_user: applies the order, defaults to alpha
# ---------------------------------------------------------------------------

def test_sort_shelves_for_user_function_exists():
    src = _shelf_src()
    assert re.search(r"def sort_shelves_for_user\(", src)


def test_sort_shelves_for_user_default_alpha():
    """No view_settings.shelves → case-insensitive alphabetical."""
    src = _shelf_src()
    match = re.search(
        r"(def sort_shelves_for_user\(.*?)(?=\n(?:def |@|class ))",
        src, re.DOTALL,
    )
    assert match
    body = match.group(1)
    assert "view_settings" in body, "must consult user.view_settings"
    assert "'shelves'" in body or '"shelves"' in body
    assert "'order'" in body or '"order"' in body
    assert "casefold" in body, "default sort must be case-insensitive"


def test_sort_shelves_for_user_anon_safe():
    """Anonymous user has view_settings=None per Anonymous.__init__."""
    src = _shelf_src()
    match = re.search(
        r"(def sort_shelves_for_user\(.*?)(?=\n(?:def |@|class ))",
        src, re.DOTALL,
    )
    body = match.group(1)
    safe_pattern = (
        r"getattr\(user,\s*['\"]view_settings['\"],\s*None\)\s*or\s*\{\s*\}"
        r"|user\.view_settings\s+or\s+\{\s*\}"
    )
    assert re.search(safe_pattern, body), (
        "must None-guard view_settings for Anonymous users"
    )


# ---------------------------------------------------------------------------
# /shelf/reorder endpoint
# ---------------------------------------------------------------------------

def test_reorder_route_registered_get_and_post():
    src = _shelf_src()
    assert re.search(
        r'@shelf\.route\(\s*["\']/shelf/reorder["\'].*methods=\[.*?["\']GET["\'].*?["\']POST["\'].*?\]',
        src, re.DOTALL,
    ) or re.search(
        r'@shelf\.route\(\s*["\']/shelf/reorder["\'].*methods=\[.*?["\']POST["\'].*?["\']GET["\'].*?\]',
        src, re.DOTALL,
    ), "GET + POST /shelf/reorder must be registered under the shelf blueprint"


def test_reorder_route_login_gated():
    src = _shelf_src()
    match = re.search(
        r'@shelf\.route\(\s*["\']/shelf/reorder["\'].*?def (\w+)\(',
        src, re.DOTALL,
    )
    assert match, "reorder route handler not found"
    handler_name = match.group(1)
    sig_idx = src.index(f"def {handler_name}(")
    head = src[max(0, sig_idx - 800):sig_idx]
    assert "@user_login_required" in head or "@login_required" in head, (
        f"{handler_name} must be auth-gated"
    )


# ---------------------------------------------------------------------------
# render_template.py applies the sort
# ---------------------------------------------------------------------------

def test_render_template_calls_sort_shelves_for_user():
    src = _render_src()
    assert "sort_shelves_for_user" in src, (
        "render_template.py must import + call sort_shelves_for_user "
        "to apply the user's stored order to g.shelves_access"
    )


# ---------------------------------------------------------------------------
# Sidebar entry for the new page
# ---------------------------------------------------------------------------

def test_sidebar_has_reorder_link():
    src = _layout_src()
    assert "shelf.reorder_shelves" in src or "/shelf/reorder" in src, (
        "layout.html sidebar must link to the reorder endpoint"
    )


# ---------------------------------------------------------------------------
# Template exists with the SortableJS hookup pattern
# ---------------------------------------------------------------------------

def test_reorder_template_exists():
    assert REORDER_HTML.is_file(), "cps/templates/shelf_reorder.html must exist"


def test_reorder_template_uses_sortable():
    src = REORDER_HTML.read_text()
    assert "Sortable" in src, "template must reference SortableJS"
    assert "/shelf/reorder" in src or "shelf.reorder_shelves" in src


# ---------------------------------------------------------------------------
# Order modes (follow-up v4.0.114): parity with magic-shelf modes
# ---------------------------------------------------------------------------

EXPECTED_MODES = {
    'manual',
    'name_asc',
    'name_desc',
    'book_count_desc',
    'book_count_asc',
    'created_desc',
    'created_asc',
    'modified_desc',
    'modified_asc',
}


def test_shelf_order_modes_set_exposed():
    src = _shelf_src()
    assert "SHELF_ORDER_MODES" in src and "DEFAULT_SHELF_ORDER_MODE" in src, (
        "cps/shelf.py must expose SHELF_ORDER_MODES set + DEFAULT_SHELF_ORDER_MODE"
    )
    match = re.search(r"SHELF_ORDER_MODES\s*=\s*\{([^}]*)\}", src, re.DOTALL)
    assert match, "SHELF_ORDER_MODES literal not found"
    block = match.group(1)
    for mode in EXPECTED_MODES:
        assert f"'{mode}'" in block or f'"{mode}"' in block, (
            f"SHELF_ORDER_MODES is missing: {mode}"
        )
    # Default must be valid.
    default_match = re.search(r"DEFAULT_SHELF_ORDER_MODE\s*=\s*['\"]([^'\"]+)['\"]", src)
    assert default_match and default_match.group(1) in EXPECTED_MODES


def test_sort_shelves_for_user_dispatches_on_order_mode():
    """The function body must dispatch on each named mode, not just
    handle 'manual' + alphabetical."""
    src = _shelf_src()
    match = re.search(
        r"(def sort_shelves_for_user\(.*?)(?=\n(?:def |@|class ))",
        src, re.DOTALL,
    )
    body = match.group(1)
    # Each mode constant must appear in the dispatch.
    for mode in ('name_desc', 'book_count_desc', 'book_count_asc',
                 'created_desc', 'created_asc', 'modified_desc', 'modified_asc'):
        assert f"'{mode}'" in body or f'"{mode}"' in body, (
            f"sort_shelves_for_user must dispatch on '{mode}'"
        )


def test_sort_shelves_for_user_book_count_helper_exists():
    """book_count modes need a helper that doesn't crash on detached
    relationships."""
    src = _shelf_src()
    assert re.search(r"def _shelf_book_count\(", src), (
        "cps/shelf.py must expose a helper for the book_count modes"
    )


def test_reorder_route_accepts_order_mode_payload():
    """POST handler must read order_mode from the JSON body, validate
    against SHELF_ORDER_MODES, and persist it into
    view_settings['shelves']['order_mode']."""
    src = _shelf_src()
    # reorder_shelves is the last function in shelf.py — match through EOF.
    match = re.search(
        r"(def reorder_shelves\(.*)",
        src, re.DOTALL,
    )
    assert match, "reorder_shelves definition not found"
    body = match.group(1)
    assert 'order_mode' in body, "POST handler must accept order_mode field"
    assert "SHELF_ORDER_MODES" in body, "POST handler must validate against the set"
    assert "'order_mode'" in body or '"order_mode"' in body, (
        "must persist into view_settings['shelves']['order_mode']"
    )


def test_template_renders_order_mode_picker():
    src = REORDER_HTML.read_text()
    assert "orderModeSelect" in src, "template must include an order-mode <select>"
    assert "order_modes" in src, (
        "template must iterate the order_modes context list (passed by the route)"
    )
    # The route's `order_modes` context list (not the template) is the source
    # of truth for the picker entries — verify the route passes each mode.
    route_match = re.search(
        r"(def reorder_shelves\(.*)", _shelf_src(), re.DOTALL,
    )
    route_body = route_match.group(1)
    for mode in ('name_asc', 'name_desc', 'book_count_desc', 'book_count_asc',
                 'created_desc', 'created_asc', 'modified_desc', 'modified_asc',
                 'manual'):
        assert f"'{mode}'" in route_body or f'"{mode}"' in route_body, (
            f"route must pass {mode} in the order_modes picker list"
        )


def test_template_posts_order_mode_field():
    src = REORDER_HTML.read_text()
    # The XHR body must include order_mode (not just order).
    assert 'order_mode' in src and 'JSON.stringify' in src, (
        "save action must POST {order_mode, order} as JSON"
    )
