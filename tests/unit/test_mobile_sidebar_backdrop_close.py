# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mobile sidebar drawer: tap-outside closes, toggle stays reachable.

The caliBlur theme renders the mobile nav as an off-canvas drawer with a
full-screen ``.sidebar-backdrop`` (z-index 9) while open. Two inherited
gaps bricked phones: the backdrop had NO close handler (the natural
tap-outside gesture did nothing), and the backdrop covered the navbar's
toggle button (the round profile-head icon — the theme's menu button), so
once opened the page was dead until a reload. Operator report: "on mobile
I can't access the sidebar anymore."

Fix: a delegated click handler on the backdrop collapses the drawer, and
``.navbar-header`` gets z-index 10 inside the navbar's stacking context so
the toggle outranks the z-9 backdrop. Verified live with hit-tested taps
(elementFromPoint, not synthetic .click()) at 375px: open → tap-outside
closes; open → toggle visible/tappable → closes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALIBLUR_JS = (REPO_ROOT / "cps" / "static" / "js" / "caliBlur.js").read_text()
OVERRIDE_CSS = (REPO_ROOT / "cps" / "static" / "css" / "caliBlur_override.css").read_text()


class TestBackdropCloseHandler:
    def test_delegated_click_handler_exists(self):
        """Delegated (document-level) because mobileSupport() recreates the
        backdrop on every crossing of the 768px boundary."""
        m = re.search(
            r'\$\(document\)\.on\("click",\s*"\.sidebar-backdrop",',
            CALIBLUR_JS,
        )
        assert m, (
            "caliBlur.js must register a delegated click handler on "
            ".sidebar-backdrop — without it, tap-outside does nothing and "
            "the open drawer bricks the page on phones"
        )

    def test_handler_collapses_the_open_drawer(self):
        handler_zone = CALIBLUR_JS.split('"click", ".sidebar-backdrop"', 1)[1][:200]
        assert '.collapse("hide")' in handler_zone, (
            "the backdrop handler must hide the open .navbar-collapse"
        )
        assert ".navbar-collapse.collapse.in" in handler_zone, (
            "the handler must target the OPEN collapse only"
        )


class TestToggleAboveBackdrop:
    def test_navbar_header_outranks_backdrop_z9(self):
        """The backdrop (z-index 9, same .navbar stacking context) must not
        cover the toggle — .navbar-header needs position + higher z-index."""
        m = re.search(
            r"\.navbar\s*>\s*\.container-fluid\s*>\s*\.navbar-header\s*\{[^}]*z-index:\s*(\d+)",
            OVERRIDE_CSS,
        )
        assert m, "caliBlur_override.css must raise .navbar-header above the backdrop"
        assert int(m.group(1)) > 9, (
            f"z-index {m.group(1)} does not outrank the backdrop's 9"
        )
        block = re.search(
            r"\.navbar\s*>\s*\.container-fluid\s*>\s*\.navbar-header\s*\{[^}]*\}",
            OVERRIDE_CSS,
        ).group(0)
        assert "position" in block, (
            "z-index needs a positioned element to take effect"
        )
