# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-pins for the web-reader highlight popup i18n bridge.

The create/edit popup is built in JS (cps/static/js/reading/annotations.js), so
its user-facing strings can't be wrapped with Jinja `_()` directly. The reader
convention (every other string in read.html) is: the template emits translated
text and the JS consumes it. These pins lock that bridge so a refactor can't
silently re-hardcode English into the popup:

- read.html must expose `annotationsI18n` on `window.calibre`, every value
  wrapped in `_()` so pybabel extracts it and locales translate it.
- annotations.js must read from `window.calibre.annotationsI18n` and must not
  carry bare hardcoded UI strings on the popup buttons.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READ_HTML = ROOT / "cps" / "templates" / "read.html"
ANN_JS = ROOT / "cps" / "static" / "js" / "reading" / "annotations.js"

# keys the JS reads via t(<key>, <fallback>) / colorLabel
EXPECTED_KEYS = ["save", "cancel", "del", "note", "addNote", "selectWithin", "noAnnotations"]
EXPECTED_COLORS = ["yellow", "red", "green", "blue"]


def test_read_html_exposes_annotationsI18n_object():
    html = READ_HTML.read_text(encoding="utf-8")
    assert "annotationsI18n" in html, "read.html must expose window.calibre.annotationsI18n"
    block = html[html.index("annotationsI18n"):html.index("annotationsI18n") + 700]
    for key in EXPECTED_KEYS:
        assert re.search(rf"\b{key}\s*:", block), f"annotationsI18n missing key '{key}'"
    for color in EXPECTED_COLORS:
        assert re.search(rf"\b{color}\s*:", block), f"annotationsI18n.colors missing '{color}'"


def test_read_html_wraps_every_popup_string_in_gettext():
    """Every exposed string must go through _() so pybabel extracts it."""
    html = READ_HTML.read_text(encoding="utf-8")
    block = html[html.index("annotationsI18n"):html.index("annotationsI18n") + 700]
    # one _() per key + 4 colours = 11 translatable strings in the block
    assert block.count("_(") >= 11, (
        f"expected >=11 _() wrapped strings in the annotationsI18n block, found {block.count('_(')}"
    )
    # reuse, don't duplicate: the empty-state string must match the existing msgid
    assert "_('No annotations on this book yet.')" in html


def test_annotations_js_reads_the_bridge_not_hardcoded_english():
    js = ANN_JS.read_text(encoding="utf-8")
    assert "window.calibre && window.calibre.annotationsI18n" in js, (
        "annotations.js must read strings from window.calibre.annotationsI18n"
    )
    assert "function t(" in js and "function colorLabel(" in js
    # the popup buttons must be set via t(...), never a bare literal
    for bad in ('textContent = "Save"', 'textContent = "Cancel"',
                'textContent = "Delete"', 'placeholder = "Note"',
                'placeholder = "Add a note (optional)"'):
        assert bad not in js, f"annotations.js still hardcodes a popup string: {bad}"


def test_every_js_fallback_has_a_matching_bridge_key():
    """t("key", "Fallback") calls must use keys the template actually provides,
    so a typo can't make a string permanently fall back to English."""
    js = ANN_JS.read_text(encoding="utf-8")
    html = READ_HTML.read_text(encoding="utf-8")
    block = html[html.index("annotationsI18n"):html.index("annotationsI18n") + 700]
    for key in re.findall(r'\bt\("([a-zA-Z]+)"', js):
        assert re.search(rf"\b{key}\s*:", block), (
            f"annotations.js calls t('{key}', ...) but read.html exposes no such key"
        )
