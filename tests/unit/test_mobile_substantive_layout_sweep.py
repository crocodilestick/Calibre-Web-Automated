# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for the substantive mobile layout sweep.

Operator screenshot at iPhone 14 (414px) on production v4.0.127
revealed that earlier mobile passes (v4.0.119–v4.0.125) were too
micro-targeted at iPhone SE 375px and didn't actually solve the
visible problems on real-world phones:

1. Sort dropdown 'DATE ADDED, NEWES...' still truncated because the
   .shelf-actions parent panel constrains the bar to ~324px
   regardless of viewport width — the dropdown side only got 218px
   of that.
2. Book card titles single-line + ellipsis at ~180px card width:
   '(ebook - german) Niet...' instead of two readable lines.
3. .alert.alert-info.alert-cwa banner (duplicate-scan-setup etc.)
   uses position:fixed bottom:20px left:50% width:50% which becomes
   a floating overlay on top of book content at narrow viewports.

Three scoped fixes:

(a) book_organizer.css mobile block: flex-wrap on the bar so the
    sort dropdown gets a full row, action icons stack below.
(b) fork-mobile-cards.css: 2-line wrap on book titles + authors
    with !important to overcome caliBlur's `white-space:nowrap
    !important` on the same selectors.
(c) Same file: alert-cwa banner re-anchored top:64px full-width on
    mobile (still position:fixed) so it doesn't block book content.

Desktop verified at 1280x800: bar single-row, titles single-line
ellipsis, banner bottom-center 50%-width — all preserved.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOK_ORGANIZER = REPO_ROOT / "cps" / "static" / "css" / "book_organizer.css"
MOBILE_CARDS = REPO_ROOT / "cps" / "static" / "css" / "fork-mobile-cards.css"
LAYOUT = REPO_ROOT / "cps" / "templates" / "layout.html"


def _mobile_block(src: str, breakpoint_px: int) -> str | None:
    """Extract the body of `@media (max-width: <N>px)` if present."""
    match = re.search(
        rf"@media[^{{]*\(max-width:\s*{breakpoint_px}px\)[^{{]*\{{(.*?)^\}}",
        src, re.DOTALL | re.M,
    )
    return match.group(1) if match else None


def test_mobile_cards_css_exists():
    assert MOBILE_CARDS.is_file()


def test_layout_loads_mobile_cards_css():
    assert "fork-mobile-cards.css" in LAYOUT.read_text(), (
        "layout.html must include the <link> for fork-mobile-cards.css"
    )


def test_book_organizer_bar_wraps_on_mobile():
    """The mobile bar must use flex-wrap so the sort dropdown gets a
    full row and the icons stack below."""
    src = BOOK_ORGANIZER.read_text()
    block = _mobile_block(src, 480)
    assert block, "mobile media query (max-width:480px) not found in book_organizer.css"
    assert re.search(r"\.book-organizer-bar\s*\{[^}]*flex-wrap:\s*wrap", block, re.DOTALL), (
        ".book-organizer-bar must declare flex-wrap: wrap on mobile so the "
        "sort dropdown can claim a full row when icons don't fit alongside"
    )


def test_book_organizer_bar_children_full_width_on_mobile():
    """Once the bar wraps, left + right children must take full row width."""
    src = BOOK_ORGANIZER.read_text()
    block = _mobile_block(src, 480)
    assert re.search(
        r"\.book-organizer-bar-(?:left|right)[^{]*\{[^}]*flex:\s*1\s+1\s+100%",
        block, re.DOTALL,
    ), "bar-left/right must declare flex:1 1 100% so each child takes a full row"


def test_book_card_title_wraps_to_two_lines_on_mobile():
    """Book card titles must override caliBlur's nowrap to wrap to 2 lines."""
    src = MOBILE_CARDS.read_text()
    block = _mobile_block(src, 767)
    assert block, "mobile media query (max-width:767px) not found in fork-mobile-cards.css"
    # Must override white-space + apply line-clamp 2, both with !important
    # to overcome caliBlur's `white-space: nowrap !important`.
    assert re.search(
        r"\.book \.meta \.title[^{]*\{[^}]*white-space:\s*normal\s*!important",
        block, re.DOTALL,
    ), ".book .meta .title must set white-space: normal !important"
    assert re.search(
        r"-webkit-line-clamp:\s*2\s*!important",
        block,
    ), "must declare -webkit-line-clamp: 2 !important"


def test_alert_cwa_banner_repositioned_top_on_mobile():
    """The persistent .alert-cwa banner must move from caliBlur's
    fixed-bottom-50%-width treatment to a top-anchored full-width
    banner on mobile, so it doesn't overlap book grid content."""
    src = MOBILE_CARDS.read_text()
    block = _mobile_block(src, 767)
    # Selectors must cover both info + danger variants.
    assert re.search(
        r"\.alert-(?:info|danger)\.alert-cwa", block,
    ), "must scope rule to .alert-info.alert-cwa + .alert-danger.alert-cwa"
    # Must move top down from auto + clear bottom.
    assert re.search(r"top:\s*\d+px\s*!important", block), (
        "must set explicit top: Npx (below navbar)"
    )
    assert re.search(r"bottom:\s*auto\s*!important", block), (
        "must clear bottom: auto to override caliBlur's fixed-bottom positioning"
    )
    # Must clear caliBlur's width:50% so banner spans full width.
    assert re.search(r"width:\s*auto\s*!important", block), (
        "must override caliBlur's width: 50% to span full mobile width"
    )
