"""Source-pin: the Magic Shelf editor uses the available width on mobile. Task #22.

The rule builder was starved of width on phones by generous desktop paddings
(4rem option cards / 2rem rule-group + value containers / 4rem help) with no
mobile override, plus a `width: --webkit-fill-available` typo on the filter
select. Pin the fixes. RED on main; GREEN on branch. (The visual width recovery
itself is verified live with Playwright.)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QB_CSS = ROOT / "cps" / "static" / "css" / "query_builder.css"
EDITOR = ROOT / "cps" / "templates" / "magic_shelf_edit.html"


def test_filter_select_width_typo_fixed():
    css = QB_CSS.read_text(encoding="utf-8")
    assert "--webkit-fill-available" not in css, "broken `width: --webkit-fill-available` still present"


def test_option_cards_extracted_from_inline_padding():
    html = EDITOR.read_text(encoding="utf-8")
    # The three repeated inline 4rem-padding styles were extracted to a class.
    assert 'padding-inline: 4rem; border-radius: 4px;"' not in html, \
        "inline 4rem option-card style still present (should be a class)"
    assert "shelf-option-card" in html, "extracted .shelf-option-card class missing"


def test_mobile_media_tightens_editor_paddings():
    html = EDITOR.read_text(encoding="utf-8")
    assert "max-width: 767px" in html, "no mobile media query"
    assert "Mobile width recovery" in html, "mobile width-recovery block missing"
    # the rule-group + value containers get tight mobile padding so rules fill width
    assert "0.6rem !important" in html, "mobile rule-group/value padding not tightened"
