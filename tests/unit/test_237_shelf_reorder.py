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
