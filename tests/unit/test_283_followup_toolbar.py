# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork #283 (@droM4X) follow-up.

After v4.0.112 shipped (contrast + toolbar wrap + dead Link/Image
buttons), reporter @droM4X verified the original fixes and posted a
follow-up with three more issues in the same /table Comments
wysihtml5 dialog:

1. **The first dropdown (formatBlock — H1/H2/H3/Paragraph) takes up
   space without being useful** for the description field. He asked
   for it to be removed too. That frees up toolbar real estate so the
   remaining buttons fit on one row at more widths.

2. **The last two buttons overflow at certain widths.** Those are
   x-editable's Cancel + Submit buttons rendered INLINE with the input
   (`.editable-input` + `.editable-buttons` are inline-block siblings
   in the same row). On narrow popup widths they push past the right
   edge. droM4X asked for the buttons to go UNDER the textarea
   instead.

3. **Button order is reversed**: currently Submit/Cancel (vendor
   default); should be Cancel/Submit per common UX convention.

This module pins the CSS that delivers all three.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_CSS = REPO_ROOT / "cps" / "static" / "css" / "wysihtml5-fork.css"


def _css() -> str:
    return FORK_CSS.read_text()


# ---------------------------------------------------------------------------
# (1) formatBlock dropdown hidden
# ---------------------------------------------------------------------------

def test_toolbar_hides_format_block_dropdown():
    """Like createLink + insertImage already hidden via :has(), the
    formatBlock dropdown (H1/H2/H3/Paragraph) should also be display:
    none on the description-field toolbar."""
    css = _css()
    assert re.search(
        r'li:has\(a\[data-wysihtml5-command="formatBlock"\]\)[^}]*display:\s*none\s*!important',
        css, re.DOTALL,
    ), (
        'formatBlock dropdown <li> must be display: none !important via '
        ':has() selector'
    )


# ---------------------------------------------------------------------------
# (2) Cancel + Submit buttons stack BELOW the textarea
# ---------------------------------------------------------------------------

def test_editable_form_stacks_buttons_below_input_for_wysihtml5():
    """x-editable's `.editableform` puts `.editable-input` and
    `.editable-buttons` as inline-block siblings. For the wysihtml5
    popup (Comments column), we want the form to be a column flex
    container so buttons stack below the input."""
    css = _css()
    # Look for an editable-form rule scoped to wysihtml5 / popover containing
    # a wysihtml5 sandbox or our marker class. Either a direct sibling
    # selector or a :has() check.
    assert re.search(
        r'\.editableform[^{]*:has\(.*wysihtml5.*\)|\.editable-popover\s+\.editableform[^{]*\{[^}]*flex-direction:\s*column',
        css, re.DOTALL,
    ) or re.search(
        r'\.editable-popover[^{]*:has\([^)]*wysihtml5[^)]*\)[^{]*\{[^}]*flex-direction:\s*column',
        css, re.DOTALL,
    ), "form must stack buttons below input via flex-direction: column scoped to wysihtml5 popovers"
    # The editable-input must take full width so the next-row buttons aren't
    # forced into a tight column.
    assert re.search(
        r'\.editable-input[^{]*\{[^}]*width:\s*100%',
        css, re.DOTALL,
    ), ".editable-input must be width: 100% so the popup uses full width"


# ---------------------------------------------------------------------------
# (3) Cancel before Submit (flex order swap)
# ---------------------------------------------------------------------------

def test_editable_button_order_cancel_first_submit_second():
    css = _css()
    # Flex order trick: cancel order: 1; submit order: 2.
    # Or use a different mechanism (margin-left:auto on submit etc).
    assert re.search(
        r'\.editable-cancel[^{]*\{[^}]*order:\s*1',
        css, re.DOTALL,
    ), ".editable-cancel must have order: 1 (renders first)"
    assert re.search(
        r'\.editable-submit[^{]*\{[^}]*order:\s*2',
        css, re.DOTALL,
    ), ".editable-submit must have order: 2 (renders after cancel)"
    # editable-buttons container must use flex so order kicks in.
    assert re.search(
        r'\.editable-buttons[^{]*\{[^}]*display:\s*flex',
        css, re.DOTALL,
    ), ".editable-buttons must be display: flex so the order property applies"
