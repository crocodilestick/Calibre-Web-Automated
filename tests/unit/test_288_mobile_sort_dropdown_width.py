# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance test for fork #288 mobile pass 4 — sort dropdown label
no longer truncates the default "Date added, newest first" label to
"DATE A..." at iPhone SE 375px width.

Root cause: book_organizer.css's mobile media query (max-width:480px)
capped `.book-organizer-sort-toggle .book-organizer-label` at
`max-width: 140px`. With caliBlur's `text-transform: uppercase`, the
default label ("Date added, newest first") needs ~190px to render
without ellipsis. Bumping to 200px fits the label.

Pin: the mobile max-width must be ≥200px so the common default label
isn't aggressively truncated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = REPO_ROOT / "cps" / "static" / "css" / "book_organizer.css"


def test_mobile_sort_label_max_width_fits_default_label():
    """The mobile media query rule for the sort label must allow the
    default 'Date added, newest first' label (~190px uppercase) to fit
    without ellipsis."""
    src = CSS.read_text()
    # Find the mobile (max-width:480px) rule for the sort label.
    mobile_block = re.search(
        r"@media[^{]*\(max-width:\s*480px\)[^{]*\{(.*?)^\}",
        src, re.DOTALL | re.M,
    )
    assert mobile_block, "mobile media query for sort dropdown not found"
    body = mobile_block.group(1)
    # Inside, find the sort-toggle label rule.
    label_rule = re.search(
        r"\.book-organizer-sort-toggle\s+\.book-organizer-label\s*\{[^}]*max-width:\s*(\d+)px",
        body, re.DOTALL,
    )
    assert label_rule, "mobile sort-toggle label max-width rule not found"
    px = int(label_rule.group(1))
    assert px >= 200, (
        f"mobile max-width is {px}px — must be ≥200px so the default "
        f"sort label 'Date added, newest first' fits without ellipsis"
    )
