# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests: the _cwa_ensure_db_session before_request hook
logged per-request DEBUG lines ("Found N total magic shelves...",
"Hiding system shelf template '...'", "Hiding public shelf '...'",
"Filtered to N visible...") on EVERY authenticated request, flooding
docker logs whenever the log level is DEBUG and a UI tab is polling
(fork #445, upstream CWA #1060). Fixed by routing one merged message
through _log_magic_shelf_counts, deduped per user per filter-snapshot
change (same pattern as _AUTHOR_SORT_DRIFT_WARNED, fork #108). The
orphaned-system-shelf WARNING is likewise deduped per (user, shelf).
cps.log is patched directly; caplog is flaky with cps's handlers.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

CPS_INIT = Path(__file__).resolve().parents[2] / "cps" / "__init__.py"


@pytest.mark.unit
class TestMagicShelfDebugLogDedup:
    def test_unconditional_per_request_debug_lines_removed(self):
        src = CPS_INIT.read_text()
        assert "magic shelves for user {current_user.id} before filtering" not in src
        assert "Filtered to {len(filtered_shelves)} visible magic shelves" not in src
        # The per-shelf "Hiding ..." lines fired on every request too (#445).
        assert 'log.debug(f"Hiding system shelf template' not in src
        assert 'log.debug(f"Hiding public shelf' not in src

    def test_steady_state_polling_logs_once(self):
        import cps
        cps._MAGIC_SHELF_COUNTS_LOGGED.clear()
        with patch.object(cps, "log", MagicMock(spec=logging.Logger)) as fake_log:
            for _ in range(50):  # user 3, 5 shelves visible, polled every ~3s
                cps._log_magic_shelf_counts(3, 5, 5)
        assert fake_log.debug.call_count == 1
        assert cps._MAGIC_SHELF_COUNTS_LOGGED == {3: (5, 5, (), ())}

    def test_count_change_logs_exactly_once_more(self):
        import cps
        cps._MAGIC_SHELF_COUNTS_LOGGED.clear()
        with patch.object(cps, "log", MagicMock(spec=logging.Logger)) as fake_log:
            for _ in range(10):
                cps._log_magic_shelf_counts(3, 5, 5)
            for _ in range(10):
                cps._log_magic_shelf_counts(3, 5, 4)  # one shelf hidden
        assert fake_log.debug.call_count == 2
        assert cps._MAGIC_SHELF_COUNTS_LOGGED == {3: (5, 4, (), ())}

    def test_per_user_isolation(self):
        import cps
        cps._MAGIC_SHELF_COUNTS_LOGGED.clear()
        with patch.object(cps, "log", MagicMock(spec=logging.Logger)) as fake_log:
            for uid in (3, 7, 3, 7):
                cps._log_magic_shelf_counts(uid, 5, 5)
        assert fake_log.debug.call_count == 2
        assert cps._MAGIC_SHELF_COUNTS_LOGGED == {3: (5, 5, (), ()), 7: (5, 5, (), ())}

    def test_hidden_shelves_polling_logs_once(self):
        # The reporter's exact scenario (#445): 6 shelves, 4 hidden system
        # templates, polled every ~3s — six DEBUG lines per request pre-fix.
        import cps
        cps._MAGIC_SHELF_COUNTS_LOGGED.clear()
        hidden = ["recently_added", "highly_rated", "yet_to_read",
                  "recent_publications"]
        with patch.object(cps, "log", MagicMock(spec=logging.Logger)) as fake_log:
            for _ in range(50):
                cps._log_magic_shelf_counts(3, 6, 2, hidden, [])
        assert fake_log.debug.call_count == 1
        msg = fake_log.debug.call_args[0][0]
        assert "6 total magic shelves" in msg
        assert "2 visible" in msg
        assert "hidden system templates: recently_added" in msg

    def test_hidden_set_change_logs_again(self):
        import cps
        cps._MAGIC_SHELF_COUNTS_LOGGED.clear()
        with patch.object(cps, "log", MagicMock(spec=logging.Logger)) as fake_log:
            for _ in range(10):
                cps._log_magic_shelf_counts(3, 6, 4, ["recently_added"], ["'Public' (ID: 9)"])
            for _ in range(10):  # user un-hides one template, hides another
                cps._log_magic_shelf_counts(3, 6, 4, ["highly_rated"], ["'Public' (ID: 9)"])
        assert fake_log.debug.call_count == 2
        msg = fake_log.debug.call_args[0][0]
        assert "hidden system templates: highly_rated" in msg
        assert "hidden public shelves: 'Public' (ID: 9)" in msg

    def test_orphaned_system_shelf_warning_deduped(self):
        # The "doesn't match any current template" WARNING also fired per
        # request (worse: visible at default log level). Source-pin that it
        # is now guarded by _ORPHANED_SYSTEM_SHELF_WARNED.
        import cps
        src = CPS_INIT.read_text()
        assert "_ORPHANED_SYSTEM_SHELF_WARNED" in src
        guard = src.index("not in _ORPHANED_SYSTEM_SHELF_WARNED")
        warn = src.index("doesn't match any current template")
        assert guard < warn, "orphan WARNING must be inside the dedup guard"
        assert isinstance(cps._ORPHANED_SYSTEM_SHELF_WARNED, set)
