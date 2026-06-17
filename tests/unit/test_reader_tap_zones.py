"""Source-pin: the web reader turns pages by tapping the left/right half of the
viewport (split down the centre), keeps swipe behind a movement threshold, and
never turns the page while text is selected (the highlight gesture). Task #29.

This is client-side behaviour with no Python entry point, so — like
test_pubdate_datepicker_js_472.py — we pin the shipped JS source. RED on main
(the old handler turned the page on ANY touchend movement: no tap zones, no
threshold, no selection guard); GREEN once the tap-zone handler ships.
"""
import re
from pathlib import Path

EPUB_JS = (
    Path(__file__).resolve().parents[2]
    / "cps" / "static" / "js" / "reading" / "epub.js"
)


def _src():
    return EPUB_JS.read_text(encoding="utf-8")


def test_epub_js_exists():
    assert EPUB_JS.is_file(), f"missing {EPUB_JS}"


def test_tap_zone_splits_viewport_down_the_centre():
    src = _src()
    # A tap maps to a page turn based on which half of the viewport width was hit.
    assert "tappedLeftHalf" in src, "no left/right tap-half decision"
    assert re.search(r"viewportWidth\s*/\s*2", src), "tap zone not split on viewport centre"


def test_swipe_has_a_movement_threshold():
    src = _src()
    assert "SWIPE_MIN_PX" in src, "swipe threshold constant missing"
    # The swipe branch must be gated by the threshold (not fire on any movement).
    assert re.search(r"adx\s*>\s*SWIPE_MIN_PX", src), "swipe not gated by a movement threshold"


def test_tap_is_distinguished_from_swipe_and_long_press():
    src = _src()
    assert "TAP_SLOP_PX" in src, "tap movement-slop constant missing"
    assert "TAP_MAX_MS" in src, "tap duration limit missing (long-press == selection, not a tap)"


def test_selection_suppresses_page_turn():
    src = _src()
    assert "readerHasSelection" in src, "no selection-guard helper"
    # The guard must short-circuit the touchend handler before any page turn.
    assert re.search(r"if\s*\(\s*readerHasSelection\(\)\s*\)\s*\{\s*return", src), \
        "touchend does not return early while a selection is active"


def test_old_thresholdless_swipe_is_gone():
    src = _src()
    # The previous handler compared raw screenX with no threshold; that exact
    # shape must be gone so a jitter or a selection drag no longer turns the page.
    assert "if (touchStart < touchEnd)" not in src, "old thresholdless swipe still present"
    assert "if (touchStart > touchEnd)" not in src, "old thresholdless swipe still present"


def test_rtl_books_still_reverse_direction():
    src = _src()
    # Page-turn direction must still honour right-to-left books in both the tap
    # and swipe branches (regression: the original swipe respected rtl).
    assert "readerIsRtl" in src, "rtl handling dropped"
    assert src.count("rtl ? reader.rendition") >= 3, "rtl branch missing from tap and/or swipe paths"
