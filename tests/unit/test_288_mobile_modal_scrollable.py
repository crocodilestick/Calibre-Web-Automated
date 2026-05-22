# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork #288 mobile pass 3.

Bootstrap 3 modals don't have a scrollable-body class. On narrow
viewports the Send-to-eReader email-select modal on `/book/<id>`
renders tall enough that the Send/Cancel buttons fall below the
visible viewport — iPhone SE users physically can't tap Send without
page-scrolling.

Fix: media query scoped to <=767px that caps `.modal-body` to 50vh
with internal `overflow-y: auto`. Modal header + footer stay pinned;
body scrolls between them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = REPO_ROOT / "cps" / "static" / "css" / "mobile-modal-scrollable-body.css"
LAYOUT = REPO_ROOT / "cps" / "templates" / "layout.html"


def test_mobile_modal_css_exists():
    assert CSS.is_file()


def test_modal_body_capped_with_scroll_on_mobile():
    src = CSS.read_text()
    # Media query scoped to Bootstrap SM breakpoint.
    assert re.search(r"@media[^{]*\(max-width:\s*767px\)", src)
    # modal-body must get max-height and overflow-y: auto.
    assert re.search(
        r"\.modal-body\s*\{[^}]*max-height:\s*\d+\w+", src, re.DOTALL,
    ), ".modal-body must set max-height"
    assert re.search(
        r"\.modal-body\s*\{[^}]*overflow-y:\s*auto", src, re.DOTALL,
    ), ".modal-body must set overflow-y: auto so it scrolls internally"


def test_modal_dialog_top_offset_tightened_on_mobile():
    """Tightening .modal-dialog margin-top recovers visible viewport."""
    src = CSS.read_text()
    assert re.search(
        r"\.modal-dialog\s*\{[^}]*margin-top:\s*\d+\w+", src, re.DOTALL,
    ), ".modal-dialog must set a smaller margin-top on mobile"


def test_layout_loads_mobile_modal_css():
    src = LAYOUT.read_text()
    assert "mobile-modal-scrollable-body.css" in src, (
        "layout.html must include the <link> for mobile-modal-scrollable-body.css"
    )
