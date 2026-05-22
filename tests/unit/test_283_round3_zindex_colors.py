# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork #283 round 3 (@droM4X).

After v4.0.125 droM4X verified the previous round's fixes and posted
three more:

1. Popover clipped at top by the fixed navbar on the first ~3 rows of
   the table (placement="top" default + navbar overlap).
2. Asked for auto-flip / "open below" when there's no room above.
3. Button colors should follow Bootstrap convention: primary action
   (Submit) = orange accent, secondary action (Cancel) = muted gray.
   Currently inverted because caliBlur maps btn-default to orange and
   btn-primary to muted dark.

Two fixes:
- `data-editable-placement="bottom"` on the Comments column header
  (and the custom-column wysihtml5 mirror at line ~135) — forces
  popover to open BELOW the cell, eliminating navbar collision.
- Scoped CSS overrides in wysihtml5-fork.css forcing Submit → orange,
  Cancel → muted dark (only inside `.editableform:has(.wysihtml5-sandbox)`
  so other surfaces don't see the theme inversion).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "cps" / "templates" / "book_table.html"
CSS = REPO_ROOT / "cps" / "static" / "css" / "wysihtml5-fork.css"


def test_comments_column_placement_bottom():
    src = TEMPLATE.read_text()
    # Find the comments column <th> definition
    match = re.search(
        r'<th[^>]*\bdata-field="comments"[^>]*>',
        src, re.DOTALL,
    )
    assert match, "comments column <th> not found"
    th = match.group(0)
    assert 'data-editable-placement="bottom"' in th, (
        "comments column must declare data-editable-placement=\"bottom\" "
        "so the popover opens below the cell (avoids navbar clip on top rows)"
    )


def test_custom_column_wysihtml5_placement_bottom():
    """Custom-column wysihtml5 columns must also get the bottom placement."""
    src = TEMPLATE.read_text()
    # Find custom_column TH with editable-type=wysihtml5
    match = re.search(
        r'<th[^>]*\bdata-field="custom_column[^"]*"[^>]*\bdata-editable-type="wysihtml5"[^>]*>',
        src, re.DOTALL,
    )
    assert match, "custom-column wysihtml5 <th> not found"
    th = match.group(0)
    assert 'data-editable-placement="bottom"' in th, (
        "custom-column wysihtml5 columns must also declare "
        "data-editable-placement=\"bottom\""
    )


def test_submit_button_uses_accent_color():
    """Submit button (primary action) must use the CWNG accent color
    inside wysihtml5 popups, overriding caliBlur's btn-primary muted
    dark mapping."""
    css = CSS.read_text()
    # Find the wysihtml5-scoped .editable-submit rule
    assert re.search(
        r'\.editableform:has\(\.wysihtml5-sandbox\)\s+\.editable-submit\s*\{[^}]*background-color:\s*var\(--color-secondary',
        css, re.DOTALL,
    ), ".editable-submit (scoped to wysihtml5) must use var(--color-secondary) for the accent color"


def test_cancel_button_uses_muted_color():
    """Cancel button (secondary) must use a muted dark color inside
    wysihtml5 popups, overriding caliBlur's btn-default orange mapping.
    There are two matching `.editable-cancel` rules in the file (the
    earlier order:1 rule from PR #294 + the new color override) —
    find the one that sets background-color."""
    css = CSS.read_text()
    matches = re.findall(
        r'\.editableform:has\(\.wysihtml5-sandbox\)\s+\.editable-cancel\s*\{([^}]*)\}',
        css, re.DOTALL,
    )
    color_rules = [m for m in matches if "background-color" in m]
    assert color_rules, (
        "no scoped .editable-cancel rule sets background-color — must "
        "override caliBlur's btn-default orange mapping inside wysihtml5 popups"
    )
    body = color_rules[0]
    # Should NOT be the accent variable (that's the orange we want on submit).
    assert "var(--color-secondary" not in body, (
        "cancel must NOT use the accent color — that's the submit color"
    )
