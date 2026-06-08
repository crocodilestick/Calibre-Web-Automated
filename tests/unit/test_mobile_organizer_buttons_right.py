# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mobile book-organizer bar: the multi-select + settings buttons stay right-aligned.

On the book-listing pages the organizer bar shows a sort dropdown (left) and a
multi-select toggle + a settings gear (right). The settings menu uses Bootstrap's
``dropdown-menu-right``, so it opens *leftward* from its button.

On phones the bar wraps (``@media (max-width: 480px)``): the sort dropdown takes
the full first row and the button group wraps to its own row. The group was
``justify-content: flex-start`` — so the gear sat near the LEFT edge and its
left-opening menu ran off the left side of the screen (reported: the "Hide shelf
badges on covers" popover was clipped). Right-aligning the group keeps the menu
on screen and matches desktop (where ``space-between`` already pushes the group
right). Verified live at 390px: the open settings menu sits fully within the
viewport (left=123, right=350 on a 390px screen, 0px clipped).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = (REPO_ROOT / "cps" / "static" / "css" / "book_organizer.css").read_text()


def _mobile_media_block() -> str:
    """Return the body of the ``@media (max-width: 480px)`` block via brace
    counting (robust to nested rule braces)."""
    start = CSS.find("@media (max-width: 480px)")
    assert start != -1, "no @media (max-width: 480px) block in book_organizer.css"
    open_brace = CSS.find("{", start)
    depth = 0
    for i in range(open_brace, len(CSS)):
        if CSS[i] == "{":
            depth += 1
        elif CSS[i] == "}":
            depth -= 1
            if depth == 0:
                return CSS[open_brace + 1 : i]
    raise AssertionError("unbalanced braces in @media (max-width: 480px) block")


class TestMobileOrganizerButtonsRightAligned:
    def test_right_group_is_flex_end_on_mobile(self):
        # The only justify-content in the mobile media block is on the
        # .book-organizer-bar-right button group; it must right-align (flex-end),
        # never left-align (flex-start, which clipped the settings dropdown).
        block = _mobile_media_block()
        assert "justify-content: flex-end" in block, (
            "the multi-select + settings group must be right-aligned (flex-end) "
            "when the bar wraps on mobile, so the settings dropdown-menu-right "
            "stays on screen and the layout matches desktop"
        )
        assert "justify-content: flex-start" not in block, (
            "left-aligning the mobile button group (flex-start) made the settings "
            "dropdown open off the left edge of the viewport"
        )
