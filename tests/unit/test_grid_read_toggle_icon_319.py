# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression: the caliBlur grid/listing hover read-toggle must use the
glyphicon-check / glyphicon-unchecked matched pair, not the eye glyph.

Fork #319 (droM4X, 2026-06-12 follow-up): v4.0.150 standardized the
detail-page read toggle on the check/unchecked action pair, but the
cover-hover "Toggle Read Status" button in listing views still showed
glyphicon-eye-open — the visibility glyph, which is exactly the
read-vs-hide icon confusion #319 was opened about. The icon must show
the ACTION the click performs: unread book -> glyphicon-check ("mark as
read"), read book -> glyphicon-unchecked ("mark as unread").
"""

from pathlib import Path

import pytest

CALIBLUR_JS = (
    Path(__file__).resolve().parents[2] / "cps" / "static" / "js" / "caliBlur.js"
)


@pytest.mark.unit
class TestGridReadToggleIcon:
    def _src(self):
        return CALIBLUR_JS.read_text(encoding="utf-8")

    def test_no_eye_glyph_anywhere(self):
        # The read toggle was the only consumer of the eye glyph; it must
        # not come back on any of the three states (rest, success, error).
        assert "glyphicon-eye-open" not in self._src()

    def test_construction_uses_action_pair_from_read_state(self):
        src = self._src()
        assert "linkIsRead ? 'glyphicon-unchecked' : 'glyphicon-check'" in src
        assert "linkIsRead ? 'Mark As Unread' : 'Mark As Read'" in src

    def test_success_handler_rests_on_next_action_icon(self):
        src = self._src()
        assert "nowRead ? 'glyphicon-unchecked' : 'glyphicon-check'" in src
        assert "nowRead ? 'Mark As Unread' : 'Mark As Read'" in src

    def test_error_handler_restores_unchanged_state_icon(self):
        src = self._src()
        assert (
            "isCurrentlyRead ? 'glyphicon-unchecked' : 'glyphicon-check'" in src
        )
