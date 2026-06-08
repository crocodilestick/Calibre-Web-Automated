# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mobile caliBlur navbar: the hamburger toggle sits on the LEFT.

The off-canvas navigation drawer slides in from the **left**, but caliBlur floats
the menu toggle to the right (``position: relative; right: 50px`` in
``caliBlur.css``), so on a phone the only menu control was on the opposite side
from where the drawer appears — disconnected. The fork override re-anchors the
toggle to the left (``float: left; right: auto``) and reflows the brand to its
right; the drawer then opens from under the hamburger and the existing
tap-outside-to-close path (fork #382) closes it.

Verified live (caliBlur, 320px + 390px): toggle at the far-left (x=6), brand
reflowed beside it with no overlap of the right-anchored search, drawer slides
from the left, and a tap on the visible scrim closes it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERRIDE_CSS = (REPO_ROOT / "cps" / "static" / "css" / "caliBlur_override.css").read_text()

# `.navbar-toggle {` matches the positioning rules but NOT `.navbar-toggle:before {`
# (the ':before' glyph repaint), because ':' is neither whitespace nor '{'.
_TOGGLE_RULES = re.findall(r"\.navbar-toggle\s*\{([^}]*)\}", OVERRIDE_CSS)


class TestMobileHamburgerLeftPlacement:
    def test_mobile_toggle_floats_left(self):
        float_left_rules = [r for r in _TOGGLE_RULES if "float: left" in r]
        assert float_left_rules, (
            "caliBlur_override.css must float the mobile .navbar-toggle left so the "
            "hamburger sits on the same side as the left-sliding off-canvas drawer"
        )
        assert any("right: auto" in r for r in float_left_rules), (
            "the left-floated toggle must reset caliBlur's right:50px (right: auto) "
            "so it anchors to the left edge, not the right"
        )

    def test_left_placement_is_mobile_scoped(self):
        # The float:left override must live under a max-width:767px media query so
        # the expanded desktop navbar is untouched. Check the float:left toggle
        # rule is preceded by a 767px media open with no intervening close-at-col-0.
        idx = OVERRIDE_CSS.find("float: left")
        assert idx != -1
        head = OVERRIDE_CSS[:idx]
        media_open = head.rfind("max-width: 767px")
        assert media_open != -1, "the hamburger-left override must be inside a max-width:767px media query"
        # no media block closed (newline + '}' at column 0) between the media open and the rule
        assert not re.search(r"\n\}", head[media_open:]), (
            "the float:left toggle rule escaped its mobile media block"
        )
