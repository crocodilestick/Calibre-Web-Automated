# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #318 — Manual full-scan button must
not be gated on the deferred ingest follow-up marker.

Root cause: ``ingest_batch_follow_up_pending()`` returns True if any of
``cwa_ingest_batch_active``, ``cwa_ingest_batch_dirty``, or
``cwa_ingest_batch_dirty.running`` files exist. The dirty/running
markers signal "the s6 post-batch follow-up (a DB reconnect for the
web process) has not run yet" — NOT "ingest is currently writing
books". A stale dirty marker can persist after a clean ingest
finishes or after an abnormal container shutdown, permanently
blocking the user's manual scan button until the marker is removed
by hand.

The task-level gate at ``cps/tasks/duplicate_scan.py`` already
correctly says: full scan + non-manual + ingest-pending → skip.
Manual triggers are exempt by design. The endpoint-level gate at
``cps/duplicates.py`` (``trigger_scan`` and ``execute_resolution``)
shared the same condition but missed the manual carve-out — so the
user's click was refused even though the underlying queued task
would have run.

Fix: remove the redundant endpoint-level gate. The task-level gate
is the single source of truth.
"""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DUPLICATES_PY = REPO_ROOT / "cps" / "duplicates.py"
DUPLICATE_SCAN_PY = REPO_ROOT / "cps" / "tasks" / "duplicate_scan.py"


def _extract_function_body(source: str, name: str) -> str:
    """Return the source of ``def name(...)`` up to (but not including)
    the next top-level ``def`` / ``class`` declaration at column 0."""
    pattern = rf"^def {re.escape(name)}\(.*?(?=^def |^class |\Z)"
    match = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    assert match is not None, f"function `{name}` not found in source"
    return match.group(0)


@pytest.mark.unit
class TestTriggerScanNotGatedOnFollowUpPending:
    """Pin: the /duplicates/trigger-scan endpoint must NOT check
    ``ingest_batch_follow_up_pending()``. Manual user requests
    always proceed; the task-level gate decides any deferral."""

    @classmethod
    def setup_class(cls):
        cls.src = DUPLICATES_PY.read_text()
        cls.body = _extract_function_body(cls.src, "trigger_scan")

    def test_trigger_scan_does_not_call_followup_pending(self):
        assert "ingest_batch_follow_up_pending" not in self.body, (
            "trigger_scan must not gate on ingest_batch_follow_up_pending(); "
            "that check refused manual scans whenever a stale dirty marker "
            "remained from a prior batch (fork issue #318). The task-level "
            "gate in cps/tasks/duplicate_scan.py handles the only case "
            "where deferral is appropriate (non-manual triggers)."
        )

    def test_trigger_scan_does_not_return_import_in_progress(self):
        assert "Import is in progress" not in self.body, (
            "trigger_scan must not return a 409 'Import is in progress' "
            "response for manual button clicks (fork issue #318)."
        )

    def test_trigger_scan_does_not_return_ingest_in_progress_blocked(self):
        assert "'ingest_in_progress'" not in self.body, (
            "trigger_scan must not return reason=ingest_in_progress; the "
            "endpoint should queue the task and let the task-level gate "
            "decide (it correctly exempts manual triggers)."
        )

    def test_trigger_scan_still_queues_task(self):
        assert "WorkerThread.add" in self.body, (
            "trigger_scan must still queue a TaskDuplicateScan via "
            "WorkerThread.add — the fix removes only the gate, not the "
            "queueing path."
        )

    def test_trigger_scan_still_passes_manual_trigger_type(self):
        body = self.body
        assert ("trigger_type='manual'" in body or
                "trigger_type=\"manual\"" in body), (
            "trigger_scan must still pass trigger_type='manual' so the "
            "task-level gate in TaskDuplicateScan.run() recognizes this as "
            "a manual request and exempts it from the "
            "ingest_batch_follow_up_pending check."
        )


@pytest.mark.unit
class TestExecuteResolutionNotGatedOnFollowUpPending:
    """Pin: the /duplicates/auto-resolve endpoint shares the same root
    cause as trigger_scan; the same fix applies."""

    @classmethod
    def setup_class(cls):
        cls.src = DUPLICATES_PY.read_text()
        cls.body = _extract_function_body(cls.src, "execute_resolution")

    def test_execute_resolution_does_not_call_followup_pending(self):
        assert "ingest_batch_follow_up_pending" not in self.body, (
            "execute_resolution must not gate on "
            "ingest_batch_follow_up_pending() for the same reason as "
            "trigger_scan — the dirty/running markers do not indicate "
            "active ingest work (fork issue #318)."
        )

    def test_execute_resolution_does_not_return_import_in_progress(self):
        assert "Import is in progress" not in self.body, (
            "execute_resolution must not return 'Import is in progress' "
            "for a manual user request (fork issue #318)."
        )


@pytest.mark.unit
class TestTaskLevelGatePreserved:
    """Pin: the task-level gate is the single source of truth and MUST
    still exempt manual triggers. This is the gate that decides whether
    a non-manual full scan (after-import / scheduled) should defer."""

    @classmethod
    def setup_class(cls):
        cls.src = DUPLICATE_SCAN_PY.read_text()

    def test_task_level_gate_still_calls_followup_pending(self):
        assert "ingest_batch_follow_up_pending" in self.src, (
            "the task-level gate must still check "
            "ingest_batch_follow_up_pending — non-manual scans "
            "(after-import / scheduled) defer to it."
        )

    def test_task_level_gate_exempts_manual_triggers(self):
        assert ("trigger_type != 'manual'" in self.src or
                'trigger_type != "manual"' in self.src), (
            "the task-level gate must include `trigger_type != 'manual'` "
            "so manual user requests are exempt from the "
            "ingest-follow-up-pending block. This is now the ONLY gate; "
            "the endpoint-level gate was removed as part of the fix for "
            "fork issue #318."
        )


@pytest.mark.unit
class TestTransientPendingSignalPreserved:
    """Pin: the read-only UI indicator on the duplicates page STILL uses
    ``ingest_batch_follow_up_pending()`` to display the 'transient
    pending' state. This is informational, not behavioral — it's
    correct to keep it."""

    def test_transient_pending_still_uses_followup_pending(self):
        src = DUPLICATES_PY.read_text()
        body = _extract_function_body(
            src, "_duplicate_scan_transiently_pending"
        )
        assert "ingest_batch_follow_up_pending" in body, (
            "_duplicate_scan_transiently_pending is a read-only UI signal "
            "— it must still detect the dirty/running marker to display "
            "the 'scan is transiently pending' indicator on the "
            "duplicates page. The fork-#318 fix removes only the "
            "BEHAVIORAL block, not the indicator."
        )
