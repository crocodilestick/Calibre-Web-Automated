# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pin the two CI mitigations for the xdist worker-IPC hang documented
in notes/xdist-worker-ipc-hang-followup-2026-05-21.md.

The hang ate roughly one in three CI runs across the v4.0.110–v4.0.121
window: pytest-xdist's master would wait forever for a worker that's
between assignments, with no currently-executing test for
pytest-timeout to interrupt; only the step-level 10-minute kill
caught it.

Two complementary mitigations:

1. **Push trigger scoped to `[main, dev]`**, NOT `['**']`. Previously a
   fork branch push fired BOTH the `push` event AND the `pull_request`
   event for the same SHA → two parallel Test Suite runs competing for
   the same xdist resources. Halves the surface for the hang.

2. **`--dist=loadfile`** pins every test in a file to a single xdist
   worker, eliminating the work-stealing race. Fewer worker handoffs
   = fewer races.

Both must stay. If a future refactor drops either, these tests fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


def _yaml() -> str:
    return WORKFLOW.read_text()


def test_push_trigger_scoped_to_main_dev_only():
    """The `push:` trigger must NOT use `branches: ['**']` (which is the
    dual-trigger surface). Must be `branches: [main, dev]`."""
    src = _yaml()
    # Find the push: trigger's branches list.
    match = re.search(
        r"push:\s*\n(?:\s*#[^\n]*\n)*\s*branches:\s*\[([^\]]+)\]",
        src,
    )
    assert match, "could not locate push.branches in tests.yml"
    branches = [b.strip().strip("'\"") for b in match.group(1).split(",")]
    assert "**" not in branches, (
        "push.branches must NOT include '**' — that re-introduces the "
        "dual-trigger CI surface for fork branches that doubles the xdist "
        "worker-IPC hang rate. See notes/xdist-worker-ipc-hang-followup-2026-05-21.md"
    )
    assert "main" in branches, "push trigger must still fire on main"


def test_pytest_invocation_pins_dist_loadfile():
    """The Fast Tests pytest invocation must include `--dist=loadfile`
    to eliminate work-stealing races between xdist workers."""
    src = _yaml()
    # The relevant pytest call lives under the fast-tests job.
    assert re.search(
        r"pytest -m \"smoke or unit\"[^&]*--dist=loadfile",
        src, re.DOTALL,
    ), (
        "Fast Tests pytest invocation must include `--dist=loadfile` — "
        "eliminates the xdist work-stealing race that hangs fast-tests "
        "runs at the step-level timeout. See "
        "notes/xdist-worker-ipc-hang-followup-2026-05-21.md"
    )


def test_pytest_invocation_still_has_pytest_timeout():
    """Belt-and-suspenders: `--timeout=120 --timeout-method=thread` must
    stay alongside `--dist=loadfile`. They cover different failure
    modes (per-test hang vs worker-IPC hang)."""
    src = _yaml()
    assert "--timeout=120" in src, "must keep --timeout=120 (per-test hang gate)"
    assert "--timeout-method=thread" in src, "must keep --timeout-method=thread"
