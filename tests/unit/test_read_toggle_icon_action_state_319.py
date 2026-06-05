# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #319 read-toggle icon standardization.

@droM4X (2026-05-28) on the #319 thread:

> The new icons are good, but it would be better if they were consistent.
> The unchecked icon is fine, but instead of the glyphicon-ok, it should
> use glyphicon-check / glyphicon-unchecked consistently.
>
> I would swap the two icons so they represent the action that will
> happen when clicked, matching the label text, instead of the current
> [state-showing behavior].

Two changes pinned here:

1. **Consistent matched pair.** The read toggle was using
   ``glyphicon-ok`` (a heavy checkmark) paired with
   ``glyphicon-unchecked`` (an empty checkbox). Different visual
   languages. Standardize on ``glyphicon-check`` (checkbox checked) +
   ``glyphicon-unchecked`` (checkbox empty) — both are checkbox-shaped
   so the toggle reads as a single coherent control.

2. **Show ACTION on interactive button, STATE on passive badge.** On
   the detail-page toggle button:
     - `entry.read_status == False` (book is unread) → show
       ``glyphicon-check`` (the icon for "click to make checked / mark
       as read"). The button label says "Mark As Read".
     - `entry.read_status == True` (book is read) → show
       ``glyphicon-unchecked`` (the icon for "click to make unchecked /
       mark as unread"). Label says "Mark As Unread".
   The icon visually previews the action the click will perform. On
   the passive badges (index grid card, cover overlay) the icon shows
   STATE — a check means "read" — because there's no action context.

Sweep: detail.html (button + JS), index.html (passive grid badge),
image.html (passive cover badge), caliBlur.js (caliBlur theme's badge
update + button success state).
"""

import pathlib
import re

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DETAIL_HTML = REPO_ROOT / "cps" / "templates" / "detail.html"
INDEX_HTML = REPO_ROOT / "cps" / "templates" / "index.html"
IMAGE_HTML = REPO_ROOT / "cps" / "templates" / "image.html"
CALIBLUR_JS = REPO_ROOT / "cps" / "static" / "js" / "caliBlur.js"


@pytest.fixture(scope="module")
def detail_html() -> str:
    return DETAIL_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def image_html() -> str:
    return IMAGE_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def caliblur_js() -> str:
    return CALIBLUR_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Detail-page button — shows ACTION (the state the click will produce).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetailButtonShowsAction:
    def test_read_icon_uses_check_unchecked_matched_pair(self, detail_html: str):
        """Pin the glyphicon-check / glyphicon-unchecked pair on the
        read-icon span (consistent checkbox-shaped icons)."""
        m = re.search(
            r'id=["\']read-icon["\'][^>]*class=(["\'])(.+?)\1',
            detail_html,
            re.DOTALL,
        )
        assert m, "read-icon span not found in detail.html"
        klass = m.group(2)
        assert "glyphicon-check" in klass, (
            "read-icon must use glyphicon-check (checkbox checked) — the "
            "matched pair with glyphicon-unchecked. droM4X #319: "
            "'instead of the glyphicon-ok, it should use glyphicon-check'."
        )
        assert "glyphicon-unchecked" in klass, (
            "read-icon must use glyphicon-unchecked (empty checkbox) "
            "for the other state."
        )
        # The OLD glyphicon-ok must be gone from this span (it's still
        # fine to use elsewhere — custom-column bool true, send-button
        # success — but not for the read-toggle).
        assert "glyphicon-ok" not in klass, (
            "read-icon must NOT use glyphicon-ok any more — droM4X #319 "
            "pushback asked for the matched glyphicon-check pair instead."
        )

    def test_read_icon_shows_action_not_state(self, detail_html: str):
        """When the book is READ, the icon must show
        ``glyphicon-unchecked`` (the action: 'click to mark unread').
        When the book is UNREAD, the icon must show ``glyphicon-check``
        (the action: 'click to mark read'). The icon visually previews
        what the click will do, matching the button's label text."""
        m = re.search(
            r'id=["\']read-icon["\'][^>]*class=(["\'])(.+?)\1',
            detail_html,
            re.DOTALL,
        )
        assert m, "read-icon span not found"
        klass = m.group(2)
        # The Jinja conditional should be:
        # entry.read_status and 'glyphicon-unchecked' or 'glyphicon-check'
        # OR equivalent forms that map True→unchecked, False→check.
        # Pin the inverted-mapping by looking for the read_status-True
        # arm choosing 'unchecked'.
        assert re.search(
            r"read_status\s+and\s+['\"]glyphicon-unchecked['\"]",
            klass,
        ) or re.search(
            r"if\s+entry\.read_status\s*%}\s*glyphicon-unchecked",
            detail_html,
        ), (
            "When entry.read_status is True (book is READ), read-icon "
            "must show glyphicon-unchecked — the action is 'mark unread'. "
            "droM4X #319: 'they should represent the action that will "
            "happen when clicked'. Got class string: " + repr(klass)
        )
        # Defensive: the False arm should pick glyphicon-check (the
        # action 'mark read'). Combined with the True→unchecked above,
        # this pins the full inversion.
        assert re.search(
            r"or\s+['\"]glyphicon-check['\"]",
            klass,
        ), (
            "When entry.read_status is False (book is UNREAD), read-icon "
            "must show glyphicon-check — the action is 'mark read'."
        )

    def test_toggle_read_js_handler_uses_check_unchecked(self, detail_html: str):
        """The JS handler must toggle the matched pair too — otherwise
        clicking goes glyphicon-check → glyphicon-ok and the visual
        breaks on the first click."""
        m = re.search(
            r'\$\("#toggle-read-btn"\).on\("click".*?\}\);\s*\n',
            detail_html,
            re.DOTALL,
        )
        assert m, "toggle-read-btn click handler not found"
        body = m.group(0)
        assert "glyphicon-check" in body, (
            "toggle-read-btn handler must toggleClass('glyphicon-check', ...) "
            "to match the template's new icon. Without this the icon "
            "drifts to glyphicon-ok on first click."
        )
        assert "glyphicon-unchecked" in body, (
            "toggle-read-btn handler must toggleClass('glyphicon-unchecked', ...) "
            "to match the template."
        )
        # The OLD glyphicon-ok must be gone from this handler block.
        assert "glyphicon-ok" not in body, (
            "toggle-read-btn handler must NOT reference glyphicon-ok — "
            "it'll override the template's glyphicon-check on click."
        )


# ---------------------------------------------------------------------------
# Passive state badges — show STATE (check means "this book is read").
# Both the static template render and the caliBlur theme's JS-injected
# variant must use the same glyphicon-check.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPassiveBadgesUseGlyphiconCheck:
    def test_index_grid_read_badge_uses_glyphicon_check(self, index_html: str):
        """The read badge on the index grid card is purely passive — it
        shows up only when the book is read. Use glyphicon-check (not
        glyphicon-ok) to match the detail-page toggle's visual
        language."""
        assert "badge read glyphicon glyphicon-check" in index_html, (
            "index.html grid card's read badge must use 'glyphicon-check' "
            "(matched-pair with the detail page). Old 'glyphicon-ok' "
            "leaves the grid inconsistent with the toggle."
        )
        assert "badge read glyphicon glyphicon-ok" not in index_html, (
            "index.html grid card read badge must NOT use 'glyphicon-ok' "
            "any more — that's the old inconsistent icon."
        )

    def test_cover_overlay_read_badge_uses_glyphicon_check(self, image_html: str):
        """image.html's cover overlay badge (rendered into list / grid /
        author / search pages via the cover macro) needs the same
        treatment."""
        assert "cover-badge cover-badge-read" in image_html, (
            "Sanity check — cover-badge-read must still exist (pre-fix)."
        )
        assert 'glyphicon glyphicon-check"' in image_html, (
            "image.html cover-badge-read must use glyphicon-check to "
            "match the rest of the read-status UI. Old glyphicon-ok "
            "leaves the cover badge inconsistent."
        )

    def test_caliblur_theme_badge_uses_glyphicon_check(self, caliblur_js: str):
        """caliBlur.js dynamically renders the read badge after the
        toggle AJAX. It must use glyphicon-check too — otherwise users
        on the caliBlur theme see glyphicon-ok come back the first time
        they click."""
        # The badge insertion: `<span class="badge read glyphicon glyphicon-check">`
        assert 'badge read glyphicon glyphicon-check' in caliblur_js, (
            "caliBlur.js read-badge insertion must use glyphicon-check "
            "(consistent with index.html). Old glyphicon-ok diverges "
            "from the rest of the icon set."
        )
        # Defensive: the OLD class string must not still be present in
        # the badge-insertion lines.
        assert 'badge read glyphicon glyphicon-ok' not in caliblur_js, (
            "caliBlur.js read-badge insertion must NOT use glyphicon-ok "
            "any more — that's the old inconsistent icon."
        )
