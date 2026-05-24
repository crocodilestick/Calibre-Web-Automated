# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for two mobile bugs the operator caught on a real
iPhone that did NOT reproduce on localhost (Chromium or headless WebKit):

1. **Book titles overlapping the cover above them.** Root cause: the
   home grid uses isotope masonry (`main.js` ~line 424,
   `layoutMode: fitRowsCentered`), which absolutely-positions each
   `.book` card from its measured height at document-ready. On a cold
   mobile-Safari load the web font (Open Sans) arrives AFTER isotope
   lays out, so cards are measured with fallback-font metrics; when the
   real font swaps in, multi-line titles reflow taller but the absolute
   positions are stale → titles overlap covers. There was no relayout
   on `document.fonts.ready`, and phones never fire `window.resize`, so
   it never self-corrected. Localhost serves the font instantly so the
   race never lost there.

   Two-part fix:
   - `main.js`: relayout isotope on `document.fonts.ready` + `window
     load` (remeasure once the real font is active).
   - `fork-mobile-cards.css`: reserve a deterministic 2-line title
     height (`min-height: 2.5em`) so every card is a CONSTANT height
     regardless of title length or font-load timing — isotope then
     can't mis-measure in the first place.

2. **Pagination prev/next arrow vertically misaligned** with the page
   number buttons. Root cause: caliBlur sizes the arrow `<a>` +
   `:before` glyph with desktop dimensions (`line-height: 60px;
   padding: 20px 25px; height: 60px`) tuned for its 60px-tall desktop
   pagination bar; against ~33px mobile page buttons the arrow centered
   ~9px low. Fix: mobile flex-row pagination with `align-items: center`
   + collapse the arrow box to match button height.

Proven in actual WebKit with the font response delayed 4s (forcing the
fallback-metrics layout): 0 overlaps + uniform 285px card heights both
during the delay and after the font + relayout settle.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MOBILE_CARDS = REPO_ROOT / "cps" / "static" / "css" / "fork-mobile-cards.css"
MAIN_JS = REPO_ROOT / "cps" / "static" / "js" / "main.js"


def _mobile_block(src: str, bp: int) -> str:
    m = re.search(
        rf"@media[^{{]*\(max-width:\s*{bp}px\)[^{{]*\{{(.*?)^\}}",
        src, re.DOTALL | re.M,
    )
    assert m, f"no @media (max-width:{bp}px) block found"
    return m.group(1)


# --- Bug 1: isotope / web-font race ---------------------------------------

def test_main_js_relayouts_isotope_on_fonts_ready():
    """main.js must relayout the discover isotope grid after the web
    font loads, or a cold mobile load lays out with fallback-font
    metrics + never corrects."""
    src = MAIN_JS.read_text()
    assert "document.fonts.ready" in src, (
        "main.js must hook document.fonts.ready to relayout isotope after "
        "the web font swaps in (masonry + webfont race fix)"
    )
    # Must actually call isotope('layout') in that path.
    assert re.search(
        r"document\.fonts\.ready\.then\(\s*relayoutDiscoverIsotope",
        src,
    ), "document.fonts.ready must call the isotope relayout helper"
    # The helper body spans nested braces (a jQuery filter fn), so just
    # assert the function exists AND an isotope('layout') call appears
    # after its declaration.
    decl = src.index("function relayoutDiscoverIsotope")
    assert re.search(
        r"isotope\(\s*[\"']layout[\"']\s*\)",
        src[decl:decl + 400],
    ), "relayoutDiscoverIsotope must call isotope('layout')"


def test_main_js_relayouts_on_window_load():
    """Belt-and-suspenders: also relayout on window load for any late
    settling content."""
    src = MAIN_JS.read_text()
    assert re.search(
        r"\$\(window\)\.on\(\s*[\"']load[\"']\s*,\s*relayoutDiscoverIsotope",
        src,
    ), "must relayout isotope on window load"


def test_title_has_deterministic_two_line_height_on_mobile():
    """The title must reserve a fixed 2-line height on mobile so card
    heights are constant — isotope cannot mis-place a constant-height
    card when the font swaps in. Without this the overlap can recur if
    the relayout is ever missed."""
    block = _mobile_block(MOBILE_CARDS.read_text(), 767)
    m = re.search(
        r"\.container-fluid \.book \.meta \.title\s*\{[^}]*min-height:\s*([\d.]+)(em|px)",
        block, re.DOTALL,
    )
    assert m, ".book .meta .title must declare a min-height on mobile (reserve 2 lines)"
    val, unit = float(m.group(1)), m.group(2)
    # 2 lines at line-height 1.25 = 2.5em; accept >= 2.4em or >= 33px.
    if unit == "em":
        assert val >= 2.4, f"min-height {val}em too small to reserve 2 lines"
    else:
        assert val >= 33, f"min-height {val}px too small to reserve 2 lines"


# --- Bug 2: pagination arrow alignment ------------------------------------

def test_pagination_is_flex_aligned_on_mobile():
    """Pagination must be a vertically-centered flex row on mobile so the
    prev/next arrow centers with the page-number buttons."""
    block = _mobile_block(MOBILE_CARDS.read_text(), 767)
    m = re.search(r"\.pagination\s*\{([^}]*)\}", block, re.DOTALL)
    assert m, "no .pagination rule in mobile block"
    body = m.group(1)
    assert "display: flex" in body, ".pagination must be display:flex on mobile"
    assert "align-items: center" in body, ".pagination must align-items:center"


def test_pagination_arrow_box_collapsed_on_mobile():
    """The arrow <a> + :before must drop caliBlur's desktop 60px line-height
    / 20px padding so it matches the ~33px page buttons."""
    block = _mobile_block(MOBILE_CARDS.read_text(), 767)
    # The arrow link rule must set line-height:1 + height:auto.
    assert re.search(
        r"\.page-next > a,\s*[^{]*\.page-previous > a\s*\{[^}]*line-height:\s*1\s*!important",
        block, re.DOTALL,
    ), "arrow <a> must reset line-height to 1 on mobile"
    # The :before glyph must drop the big padding + negative margin.
    assert re.search(
        r"\.page-next > a:before,\s*[^{]*\.page-previous > a:before\s*\{[^}]*margin-right:\s*0\s*!important",
        block, re.DOTALL,
    ), "arrow :before must reset margin-right to 0 on mobile"
