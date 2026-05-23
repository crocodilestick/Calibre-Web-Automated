# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance test for fork #288 mobile pass — sort dropdown label
no longer truncates the default "Date added, newest first" label.

Evolution: v4.0.125 (pass 4) bumped max-width to 200px which helped
iPhone SE but still truncated on bigger phones (414px) because the
.shelf-actions parent panel constrained the bar to ~324px and the
dropdown side only got ~218px of that. The substantive layout sweep
(post-#306) made the bar flex-wrap on mobile so the sort dropdown
gets the full row width — eliminating the truncation entirely.

This test now pins: in the mobile media query the sort-toggle label
must declare `max-width: none` (since the bar wraps and the
dropdown side is full-width, capping the label is the wrong move
and would re-introduce truncation).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = REPO_ROOT / "cps" / "static" / "css" / "book_organizer.css"


def test_mobile_sort_label_no_max_width_cap_since_bar_wraps():
    """The mobile sort label must not cap max-width to a fixed pixel
    value — the bar wraps so the dropdown gets full row width and any
    cap would re-introduce ellipsis on long sort labels.
    """
    src = CSS.read_text()
    mobile_block = re.search(
        r"@media[^{]*\(max-width:\s*480px\)[^{]*\{(.*?)^\}",
        src, re.DOTALL | re.M,
    )
    assert mobile_block, "mobile media query for sort dropdown not found"
    body = mobile_block.group(1)
    # Inside, find the sort-toggle label rule.
    label_rule = re.search(
        r"\.book-organizer-sort-toggle\s+\.book-organizer-label\s*\{([^}]*)\}",
        body, re.DOTALL,
    )
    assert label_rule, "mobile sort-toggle label rule not found"
    max_width = re.search(r"max-width:\s*(\S+)", label_rule.group(1))
    assert max_width, (
        "expected `max-width: <value>` declaration in the rule (use `none` "
        "now that the bar wraps; using a pixel cap would re-introduce "
        "truncation on long sort labels)"
    )
    val = max_width.group(1).rstrip(";")
    assert val == "none", (
        f"mobile max-width is `{val}` — must be `none` so the label can "
        f"stretch the full row width after the bar flex-wraps. "
        f"Using a pixel cap re-introduces ellipsis on long sort labels."
    )
