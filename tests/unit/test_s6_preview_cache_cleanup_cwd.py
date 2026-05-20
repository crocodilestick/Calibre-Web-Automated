# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Source-pin that ``cwa-preview-cache-cleanup`` cd's into the app dir
before invoking ``python3 -m cps.services.cover_preview_cache_sweeper``.

Background — fork PR #261 (@ikerios): the s6 longrun
``root/etc/s6-overlay/s6-rc.d/cwa-preview-cache-cleanup/run`` exec'd
``python3 -m cps.services.cover_preview_cache_sweeper`` with no prior
``cd`` into ``/app/calibre-web-automated``. The s6 supervisor execs the
run script with CWD = ``/``; ``python3 -m`` only adds the CURRENT
directory to ``sys.path[0]``, so ``cps`` (located at
``/app/calibre-web-automated/cps/``) was not importable and every sweep
attempt died with ``ModuleNotFoundError: No module named 'cps'``. The
``|| echo …WARNING…`` branch swallowed the failure and the disk-cache
cap turned advisory — the cache grew unbounded on heavily-browsed
libraries.

The fix is one line: ``cd /app/calibre-web-automated`` before the
``while true`` loop. This test pins:

1. The ``cd`` is present at all.
2. It targets the right absolute path (the canonical app dir).
3. It happens BEFORE the ``while true`` loop — a cd inside the loop
   wouldn't fix the cold-start race where the supervisor might restart
   the script with CWD reset.
4. The cd has a guard (``|| { ... exit }``) so a missing app dir
   surfaces as a clear FATAL line instead of looping forever with the
   same opaque ModuleNotFoundError.

Verified live on cwn-local pre-fix (``ModuleNotFoundError``) and
post-fix (``before=… after=… evicted=…`` summary line from
``main()``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = (
    REPO_ROOT
    / "root"
    / "etc"
    / "s6-overlay"
    / "s6-rc.d"
    / "cwa-preview-cache-cleanup"
    / "run"
)


def _read_run_script() -> str:
    assert RUN_SCRIPT.is_file(), (
        f"Expected s6 run script at {RUN_SCRIPT}; the cover-preview "
        f"cache cleanup service must remain registered."
    )
    return RUN_SCRIPT.read_text()


def test_run_script_cd_into_app_dir():
    """The script must `cd /app/calibre-web-automated` so that
    `python3 -m cps.services.<module>` resolves the `cps` package
    against the cwd added to sys.path[0]."""
    src = _read_run_script()
    assert re.search(r"^cd\s+/app/calibre-web-automated\b", src, re.MULTILINE), (
        "root/etc/s6-overlay/s6-rc.d/cwa-preview-cache-cleanup/run must "
        "contain `cd /app/calibre-web-automated` (anchored at start of "
        "line) so `python3 -m cps.services.cover_preview_cache_sweeper` "
        "can import the `cps` package. Without the cd the s6 supervisor "
        "executes the script with CWD=/, the module-spec lookup fails "
        "with ModuleNotFoundError, the sweeper never runs, and the disk "
        "cache cap turns advisory. See PR #261 (@ikerios)."
    )


def test_run_script_cd_precedes_while_loop():
    """The `cd` must happen BEFORE the `while true` loop, not inside
    it. A cd inside the loop would still work for steady-state, but
    a supervisor restart resetting CWD between iterations could race
    with the first sweep — anchoring before the loop is the correct
    shape and matches the pattern used in `svc-calibre-web-automated/run`
    and `cwa-init/run`.
    """
    src = _read_run_script()
    cd_idx = src.find("cd /app/calibre-web-automated")
    while_idx = src.find("while true")
    assert cd_idx >= 0, "cd missing entirely — see test above"
    assert while_idx >= 0, (
        "Expected `while true` in the run script — the sweeper schedule "
        "is implemented as an infinite loop with a sleep between sweeps."
    )
    assert cd_idx < while_idx, (
        f"`cd /app/calibre-web-automated` must appear BEFORE the "
        f"`while true` loop. Got cd at offset {cd_idx}, while at "
        f"{while_idx}. A cd inside the loop wouldn't survive an "
        f"s6 supervisor restart that resets CWD to /."
    )


def test_run_script_cd_has_fatal_guard():
    """The `cd` must have an `||` fallthrough that logs a FATAL line
    and exits non-zero when the app dir is missing. Without the guard,
    a misconfigured image (no /app/calibre-web-automated) would silently
    cd into / and loop forever emitting the same ModuleNotFoundError —
    the exact symptom this PR fixed. A FATAL exit makes the failure
    mode loud and operator-actionable.
    """
    src = _read_run_script()
    # Match either `|| { ... exit ... }` on the same line, or a multi-line
    # block. Be loose about whitespace; require the FATAL banner and an
    # explicit exit.
    cd_line_match = re.search(
        r"^cd\s+/app/calibre-web-automated\s*\|\|\s*\{[^\n]*FATAL[^\n]*exit",
        src,
        re.MULTILINE,
    )
    assert cd_line_match is not None, (
        "The `cd /app/calibre-web-automated` line must include a "
        "`|| { echo \"[cwa-preview-cache-cleanup] FATAL: ...\"; exit 1 }` "
        "guard so a missing app dir surfaces as a clear FATAL log line "
        "and the supervisor stops respawning into the same failure. "
        "Silently looping past the cd would re-create the symptom this "
        "PR fixes."
    )
