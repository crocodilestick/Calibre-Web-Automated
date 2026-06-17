"""Source-pin: the web reader suppresses the native context menu (right-click /
long-press) inside the content so the in-app highlight popup is the affordance,
WITHOUT disabling text selection (highlighting needs a live selection). Task #30.

Client-side behaviour with no Python entry point — pinned on the shipped source
like the other reader JS tests. RED on main (no suppression); GREEN on branch.
The iOS text-selection edit menu is a documented platform limit
(notes/2026-06-17-reader-native-menu-DESIGN.md) and is intentionally not asserted.
"""
import re
from pathlib import Path

EPUB_JS = (
    Path(__file__).resolve().parents[2]
    / "cps" / "static" / "js" / "reading" / "epub.js"
)


def _src():
    return EPUB_JS.read_text(encoding="utf-8")


def test_has_suppress_helper():
    assert "suppressReaderNativeMenu" in _src()


def test_contextmenu_is_prevented():
    src = _src()
    assert re.search(r"addEventListener\(\s*['\"]contextmenu['\"]", src), "no contextmenu listener"
    assert "preventDefault" in src


def test_ios_long_press_callout_suppressed():
    assert "-webkit-touch-callout" in _src()


def test_reapplied_on_each_section_render():
    # epub.js swaps the iframe document per spine item — suppression must re-run.
    assert re.search(r"on\(\s*['\"]rendered['\"][\s\S]{0,120}suppressReaderNativeMenu", _src()), \
        "suppression not re-applied on 'rendered'"


def test_does_not_disable_text_selection():
    # The fix must NOT kill selection to remove the menu — highlighting needs it.
    # Guards against a future "iOS fix" that sets user-select:none on content.
    assert "user-select" not in _src(), "epub.js must not disable user-select (breaks highlighting)"
