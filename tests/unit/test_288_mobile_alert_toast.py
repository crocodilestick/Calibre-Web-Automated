# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork #288 mobile pass 2 (login form).

caliBlur.css positions every `.alert` as a fixed-bottom toast
(`position: fixed; bottom: 20px`). On narrow viewports this collides
with form buttons stacked at the bottom of the visible area — most
visibly the "Wrong Username or Password" toast overlapping the
"LOG IN WITH MAGIC LINK" button on /login.

Fix: scoped media query (<=767px) that flips toast positioning to
`top: 80px; bottom: auto` so toasts float above page content rather
than on top of bottom-of-form controls.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MOBILE_CSS = REPO_ROOT / "cps" / "static" / "css" / "mobile-alert-toast-position.css"
LAYOUT_HTML = REPO_ROOT / "cps" / "templates" / "layout.html"


def test_mobile_alert_css_file_exists():
    assert MOBILE_CSS.is_file(), (
        "cps/static/css/mobile-alert-toast-position.css must exist"
    )


def test_mobile_alert_css_targets_mobile_breakpoint():
    src = MOBILE_CSS.read_text()
    # Bootstrap 3 'sm' breakpoint upper bound is 767px.
    assert re.search(
        r"@media[^{]*\(max-width:\s*767px\)",
        src,
    ), "rule must be scoped to (max-width: 767px)"


def test_mobile_alert_css_flips_toast_to_top():
    src = MOBILE_CSS.read_text()
    assert re.search(
        r"\.alert\s*\{[^}]*top:\s*\d+px\s*!important",
        src, re.DOTALL,
    ), ".alert media-scoped rule must set explicit top position with !important"
    assert re.search(
        r"\.alert\s*\{[^}]*bottom:\s*auto\s*!important",
        src, re.DOTALL,
    ), ".alert media-scoped rule must set bottom: auto !important to override caliBlur"


def test_layout_loads_mobile_alert_css():
    src = LAYOUT_HTML.read_text()
    assert "mobile-alert-toast-position.css" in src, (
        "layout.html must include the mobile-alert-toast-position.css <link>"
    )
