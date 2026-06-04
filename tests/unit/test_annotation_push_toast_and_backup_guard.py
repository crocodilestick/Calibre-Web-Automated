# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for two greptile P1 findings on PR #349 (annotation bridge).

Both live in the KOReader Lua plugin, which CI can't execute, so — like the
other `test_kosync_plugin_*` suites — these pattern-pin the load-bearing call
sites against the Lua source. A regression that reverts either fix trips a test.

1. Push-failure must not report success. The `push_annotations` callback in
   main.lua used to ignore its `ok` argument and always show the "N to device,
   M to server" toast, so a 401/503/unreachable push looked identical to a clean
   sync. The callback must branch on the callback's success flag and surface a
   distinct "Server push failed" message on failure.

2. The device backup must be once-per-session. `applyToDevice` used to call
   `backup()` unconditionally on every invocation, writing a fresh full-size
   `.cwn-bak-*` copy of KoboReader.sqlite each time and filling /mnt/onboard.
   A module-level guard must snapshot only on the first successful backup of a
   KOReader run.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "koreader" / "plugins" / "cwasync.koplugin"
MAIN_LUA = PLUGIN_DIR / "main.lua"
PROVIDER_LUA = PLUGIN_DIR / "kobo_sqlite_provider.lua"


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def test_push_callback_binds_success_flag():
    # The callback's first parameter must be a usable name, not the discarded
    # `_ok2` it was before — otherwise the branch below can't gate on it.
    body = _read(MAIN_LUA)
    assert "function(_ok2, _body2)" not in body, (
        "push_annotations callback must not discard its success flag as `_ok2`"
    )
    assert "function(ok2, _body2)" in body, (
        "push_annotations callback must bind its success flag as `ok2`"
    )


def test_push_callback_branches_on_success():
    body = _read(MAIN_LUA)
    # The success toast must be gated behind an `if ok2 then`, with a distinct
    # failure message in the else arm. Pin both so a revert to the always-success
    # shape trips the test.
    assert re.search(r"if\s+ok2\s+then", body), (
        "push callback must gate the success toast behind `if ok2 then`"
    )
    assert '_("Highlights synced: %1 to device. Server push failed.")' in body, (
        "push callback must show a distinct message when the server push fails"
    )


def test_apply_to_device_has_session_backup_guard():
    body = _read(PROVIDER_LUA)
    # A module-level flag must exist and gate the backup call.
    assert re.search(r"local\s+_backed_up\s*=\s*false", body), (
        "kobo_sqlite_provider.lua must declare a module-level `_backed_up` flag"
    )
    # The backup() call must be inside an `if not _backed_up` guard, and the flag
    # must only be set when the backup actually succeeded (so a failed backup
    # retries on the next call rather than disabling backups for the session).
    guard = re.search(
        r"if\s+not\s+_backed_up\s+then\s+"
        r"if\s+KoboSqliteProvider\.backup\(\)\s+then\s+"
        r"_backed_up\s*=\s*true",
        body,
    )
    assert guard, (
        "applyToDevice must back up only when not already backed up this session, "
        "setting _backed_up = true only on a successful backup()"
    )


def test_apply_to_device_does_not_back_up_unconditionally():
    body = _read(PROVIDER_LUA)
    # Pin the absence of the old unguarded call: a bare `KoboSqliteProvider.backup()`
    # statement on its own line (not inside the success-gated guard) would
    # reintroduce the unbounded-backup bug.
    for line in body.splitlines():
        stripped = line.strip()
        assert stripped != "KoboSqliteProvider.backup()", (
            "applyToDevice must not call backup() unconditionally — it must be "
            "guarded by `if not _backed_up`"
        )
