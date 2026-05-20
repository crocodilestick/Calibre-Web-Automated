# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for fork #205 — Cover Settings cog button wiring.

Reporter @goatdancer4000-sudo, +1 from @droM4X, +1 from @Onkeyuk:
the cog icon on the book-organizer bar opens a dropdown menu whose
single item ("Cover Settings") does nothing when clicked. Users want
a way to hide the shelf badges that overlay book covers — the badges
get noisy when a book is in several shelves.

Fix wires the cog menu to a per-user "Hide shelf badges on covers"
toggle backed by ``user.view_settings.cover.hide_shelf_badges`` (no
DB migration — JSON column). When set, ``<body>`` carries
``cover-hide-shelf-badges`` and CSS hides ``.cover-badge-shelf`` and
``.cover-badge-shelf-extra-pill`` (the Read badge stays — it's not a
shelf badge).

These tests pin the load-bearing invariants at the source level so a
future refactor can't silently re-introduce the no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

LAYOUT = REPO_ROOT / "cps" / "templates" / "layout.html"
ORGANIZER_TMPL = REPO_ROOT / "cps" / "templates" / "_book_organizer.html"
ORGANIZER_JS = REPO_ROOT / "cps" / "static" / "js" / "book_organizer.js"
ORGANIZER_CSS = REPO_ROOT / "cps" / "static" / "css" / "book_organizer.css"
WEB = REPO_ROOT / "cps" / "web.py"


def test_layout_emits_cover_hide_shelf_badges_body_class():
    """Layout must emit `cover-hide-shelf-badges` on `<body>` when the
    user's view_settings has `cover.hide_shelf_badges` set."""
    src = LAYOUT.read_text()
    assert "cover-hide-shelf-badges" in src, (
        "cps/templates/layout.html must conditionally add the "
        "`cover-hide-shelf-badges` class to <body> based on the user's "
        "view_settings. See fork issue #205."
    )
    # Pin the read of the view property — not just the class literal.
    assert re.search(
        r"get_view_property\([\'\"]cover[\'\"]\s*,\s*[\'\"]hide_shelf_badges[\'\"]\)",
        src,
    ), (
        "Layout must call current_user.get_view_property('cover', "
        "'hide_shelf_badges') so the body class reflects the persisted "
        "user setting."
    )


def test_organizer_menu_has_toggle_item_not_no_op_link():
    """The cog dropdown must contain the toggle-hide-shelf-badges action
    with `role="menuitemcheckbox"` — the original `cover-settings`
    no-op link is replaced by the real toggle."""
    src = ORGANIZER_TMPL.read_text()
    assert 'data-organizer-action="toggle-hide-shelf-badges"' in src, (
        "cps/templates/_book_organizer.html must include a menu item "
        "with data-organizer-action=\"toggle-hide-shelf-badges\" so the "
        "cog button does something. See fork #205."
    )
    assert 'role="menuitemcheckbox"' in src, (
        "The toggle menu item must use role=\"menuitemcheckbox\" so "
        "screen readers announce it as a toggle, not a plain menu item."
    )
    # The aria-checked state must be wired to the persisted setting.
    assert re.search(
        r"aria-checked=[\"']\{\{\s*[\'\"]true[\'\"]\s+if\s+_cover_hide_shelf_badges",
        src,
    ), (
        "aria-checked on the toggle must be derived from "
        "_cover_hide_shelf_badges (read from view_settings)."
    )


def test_organizer_js_handles_toggle_action():
    """The JS dispatcher must handle the new action and call the
    persistence helper. The original no-op branch is preserved for
    backward compatibility with the legacy `cover-settings` action
    string but must not be the new wiring."""
    src = ORGANIZER_JS.read_text()
    assert 'action === "toggle-hide-shelf-badges"' in src, (
        "cps/static/js/book_organizer.js must branch on the "
        "`toggle-hide-shelf-badges` action so the cog menu item actually "
        "does something. See fork #205."
    )
    assert "toggleHideShelfBadges" in src, (
        "The handler function `toggleHideShelfBadges` must exist."
    )
    # The persistence call: POST /ajax/view with cover.hide_shelf_badges.
    assert re.search(
        r"postJson\(\s*[\"']/ajax/view[\"']\s*,\s*\{\s*cover:\s*\{\s*hide_shelf_badges:",
        src,
    ), (
        "toggleHideShelfBadges must POST /ajax/view with payload "
        "{cover: {hide_shelf_badges: <bool>}} to persist via the "
        "existing user.set_view_property infrastructure (no new route)."
    )


def test_organizer_js_revert_on_persist_failure():
    """If the AJAX persist fails, the UI must revert — both the body
    class and the aria-checked state — so storage stays in sync with
    what the user sees. Without this, a network blip leaves the user
    with badges hidden on screen but the next page load brings them
    back, which is confusing."""
    src = ORGANIZER_JS.read_text()
    fn_match = re.search(
        r"function toggleHideShelfBadges[\s\S]+?\n  \}\n",
        src,
    )
    assert fn_match, "toggleHideShelfBadges function block not found"
    fn_body = fn_match.group(0)
    assert ".catch(" in fn_body, (
        "toggleHideShelfBadges must register a .catch handler so a "
        "failed persist reverts the optimistic UI change."
    )
    # The catch must revert at least the body class.
    assert "classList.remove" in fn_body and "classList.add" in fn_body, (
        "The revert branch must un-do the body class toggle."
    )


def test_css_hides_shelf_badges_when_body_class_set():
    """CSS must scope `display: none` on `.cover-badge-shelf` and
    `.cover-badge-shelf-extra-pill` to the body class. The Read badge
    (`.cover-badge-read`) MUST NOT be hidden — the toggle is scoped to
    shelf badges only."""
    src = ORGANIZER_CSS.read_text()
    rule = re.search(
        r"body\.cover-hide-shelf-badges[^{]*\{[^}]*display:\s*none",
        src,
    )
    assert rule, (
        "cps/static/css/book_organizer.css must include a "
        "`body.cover-hide-shelf-badges ... { display: none }` rule so "
        "the shelf badges hide when the toggle is on."
    )
    # The rule must cover both shelf-badge variants.
    region = src[rule.start():rule.end() + 200]
    assert "cover-badge-shelf" in region, (
        "The CSS rule must scope to `.cover-badge-shelf` (the per-shelf "
        "badge variant)."
    )
    # The Read badge must NOT be hidden by the rule — it's not a shelf badge.
    # Loose check: the selector list must not contain `.cover-badge-read`.
    bad = re.search(
        r"body\.cover-hide-shelf-badges[^{]*\.cover-badge-read\b",
        src,
    )
    assert bad is None, (
        "The `body.cover-hide-shelf-badges` rule must NOT target "
        ".cover-badge-read — the toggle is scoped to shelf badges only."
    )


def test_ajax_view_endpoint_already_handles_arbitrary_keys():
    """The toggle reuses the existing /ajax/view endpoint that accepts
    `{element: {param: value}}`. Pin that the endpoint is still the
    generic shape — if a refactor narrows it to specific keys, the
    cover.hide_shelf_badges write path silently breaks."""
    src = WEB.read_text()
    # The endpoint must exist.
    assert "/ajax/view" in src, "cps/web.py must register /ajax/view route"
    # It must iterate elements + params generically. Loose pin on the
    # iteration pattern.
    assert re.search(
        r"for\s+element\s+in\s+to_save[\s\S]+?for\s+param\s+in\s+to_save\[element\][\s\S]+?set_view_property",
        src,
    ), (
        "/ajax/view must iterate {element: {param: value}} payloads "
        "generically and delegate to set_view_property. A narrowed "
        "endpoint would break the cover.hide_shelf_badges write path."
    )
