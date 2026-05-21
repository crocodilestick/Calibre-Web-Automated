# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #283 (@droM4X): UI bugs in the
Books List (`/table`) bulk editor's Comments wysihtml5 dialog.

Three bugs (all reproduced on cwn-local v4.0.111):

1. **Light gray text on white background.** The wysihtml5 sandbox
   copies the surrounding page's computed `color` (rgb(245, 245, 245)
   from the CWNG dark theme) into the iframe body's inline style.
   The iframe body background is forced to white. Result: nearly
   unreadable text once the user types something.

2. **Toolbar overflows the dialog.** Vendor lib uses `float: left` on
   toolbar items; when the toolbar runs out of horizontal room the
   wrap stacks items vertically with awkward whitespace.

3. **Insert Link / Upload Image buttons are dead.** They DO open
   their modals on click — but the modals are tagged with Bootstrap 2's
   `modal hide fade` class set. Bootstrap 3+ (which CWNG uses) treats
   `hide` as `display: none !important`, so the modal never becomes
   visible. The metadata editor doesn't render links or accept image
   uploads anyway, so the buttons are vestigial.

These tests pin the three fix surfaces so a future refactor can't
silently regress them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_IFRAME = REPO_ROOT / "cps" / "static" / "css" / "wysihtml5-fork-iframe.css"
CSS_FORK = REPO_ROOT / "cps" / "static" / "css" / "wysihtml5-fork.css"
BOOK_TABLE = REPO_ROOT / "cps" / "templates" / "book_table.html"


def _iframe_css() -> str:
    return CSS_IFRAME.read_text()


def _fork_css() -> str:
    return CSS_FORK.read_text()


def _template() -> str:
    return BOOK_TABLE.read_text()


# ---------------------------------------------------------------------------
# Bug #1 — iframe body color override
# ---------------------------------------------------------------------------

def test_iframe_css_file_exists():
    assert CSS_IFRAME.is_file(), (
        "cps/static/css/wysihtml5-fork-iframe.css must exist; it's the "
        "stylesheet wysihtml5 loads INTO the editor's sandbox iframe to "
        "override the gray-on-white color inherited from the dark theme."
    )


def test_iframe_css_forces_dark_text_on_white():
    """Body must be readable: dark text, white background, both with
    !important so the wysihtml5 inline-style copy can't override."""
    css = _iframe_css()
    assert re.search(
        r"body\.wysihtml5-editor\s*\{[^}]*?color:\s*#3\d{2}\s*!important",
        css, re.DOTALL,
    ), "body.wysihtml5-editor must set color: #3?? !important"
    assert re.search(
        r"body\.wysihtml5-editor\s*\{[^}]*?background-color:\s*#fff(?:fff)?\s*!important",
        css, re.DOTALL | re.I,
    ), "body.wysihtml5-editor must set background-color: #ffffff !important"


def test_iframe_css_preserves_placeholder_dim():
    """Placeholder text should stay visibly dim (vendor convention),
    not inherit our forced dark color."""
    css = _iframe_css()
    assert re.search(
        r"body\.wysihtml5-editor\.placeholder\s*\{[^}]*color:\s*#a9a9a9\s*!important",
        css, re.DOTALL,
    ), "placeholder rule must keep #a9a9a9 with !important"


# ---------------------------------------------------------------------------
# Bug #2 — toolbar wraps cleanly
# ---------------------------------------------------------------------------

def test_fork_css_file_exists():
    assert CSS_FORK.is_file()


def test_toolbar_uses_flex_wrap_not_float():
    """Replace vendor's `float: left` wrap with flexbox so wrapped rows
    stay aligned with consistent gaps."""
    css = _fork_css()
    assert re.search(
        r"ul\.wysihtml5-toolbar\s*\{[^}]*display:\s*flex",
        css, re.DOTALL,
    ), "ul.wysihtml5-toolbar must set display: flex"
    assert re.search(
        r"ul\.wysihtml5-toolbar\s*\{[^}]*flex-wrap:\s*wrap",
        css, re.DOTALL,
    ), "ul.wysihtml5-toolbar must set flex-wrap: wrap"
    # Vendor uses `float: left` on > li; we must explicitly cancel it.
    assert re.search(
        r"ul\.wysihtml5-toolbar\s*>\s*li\s*\{[^}]*float:\s*none",
        css, re.DOTALL,
    ), "ul.wysihtml5-toolbar > li must set float: none to override vendor"


# ---------------------------------------------------------------------------
# Bug #3 — dead Insert Link / Upload Image buttons removed
# ---------------------------------------------------------------------------

def test_toolbar_hides_createlink_button():
    css = _fork_css()
    assert re.search(
        r'li:has\(a\[data-wysihtml5-command="createLink"\]\)[^}]*display:\s*none\s*!important',
        css, re.DOTALL,
    ), 'createLink button li must be display: none !important via :has()'


def test_toolbar_hides_insertimage_button():
    css = _fork_css()
    assert re.search(
        r'li:has\(a\[data-wysihtml5-command="insertImage"\]\)[^}]*display:\s*none\s*!important',
        css, re.DOTALL,
    ), 'insertImage button li must be display: none !important via :has()'


# ---------------------------------------------------------------------------
# Template wiring
# ---------------------------------------------------------------------------

def test_template_loads_fork_toolbar_css():
    """book_table.html must include wysihtml5-fork.css AFTER the vendor
    bootstrap-wysihtml5 css so our overrides win on specificity ties."""
    src = _template()
    vendor_pos = src.find("bootstrap-wysihtml5-0.0.3.css")
    fork_pos = src.find("wysihtml5-fork.css")
    assert vendor_pos != -1, "vendor bootstrap-wysihtml5 css must be loaded"
    assert fork_pos != -1, "fork-#283 wysihtml5-fork.css must be loaded"
    assert fork_pos > vendor_pos, (
        "wysihtml5-fork.css must be loaded AFTER vendor css so cascade wins"
    )


def test_template_injects_iframe_stylesheet_via_xeditable_defaults():
    """The script block must configure x-editable's wysihtml5 plugin to
    load wysihtml5-fork-iframe.css INTO the editor iframe via the
    `stylesheets` option."""
    src = _template()
    assert "$.fn.editabletypes.wysihtml5" in src, (
        "must reference $.fn.editabletypes.wysihtml5 to set defaults"
    )
    assert "stylesheets" in src, "must pass `stylesheets` option to wysihtml5"
    assert "wysihtml5-fork-iframe.css" in src, (
        "must reference the fork iframe stylesheet"
    )


def test_template_iframe_inject_runs_before_table_js():
    """The defaults-override must run BEFORE table.js, since table.js
    renders the editable column definitions on its very first init pass."""
    src = _template()
    inject_pos = src.find("$.fn.editabletypes.wysihtml5")
    table_js_pos = src.find("js/table.js")
    assert inject_pos != -1 and table_js_pos != -1
    assert inject_pos < table_js_pos, (
        "iframe-stylesheet inject must run before table.js loads/renders"
    )


def test_template_iframe_inject_runs_after_wysihtml5_xeditable_plugin():
    """The x-editable wysihtml5 plugin (wysihtml5-0.0.3.js) defines
    $.fn.editabletypes.wysihtml5. The inject must run AFTER that file
    loads, otherwise the namespace doesn't exist yet."""
    src = _template()
    plugin_pos = src.find("js/libs/wysihtml5-0.0.3.js")
    inject_pos = src.find("$.fn.editabletypes.wysihtml5")
    assert plugin_pos != -1 and inject_pos != -1
    assert plugin_pos < inject_pos, (
        "x-editable wysihtml5 plugin script must load before the inject"
    )
