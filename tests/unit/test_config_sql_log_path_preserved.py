# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #312 — Tier 1: stop force-resetting
`config_logfile` to `/dev/stdout`.

Background: `cps/config_sql.py` carried a startup block that, on every
settings load, force-set `config_logfile = /dev/stdout` with a comment
"enforce unified logging for Docker deployments." It also auto-saved
that value back to `app.db` so the in-UI editor in admin →
Configuration showed a stale stdout value the user couldn't change.

That broke the admin → View Logs page (which reads from disk) AND
broke the Download Debug Package zip (whose log slot ended up empty).

The new contract:

* the force-reset block must not exist in source
* a one-time migration auto-promotes legacy `/dev/stdout` saved values
  to the default file path so existing installs start writing a file
  they can actually view
* an explicit user choice of `/dev/stdout` is honored if present
  alongside a sentinel marking explicit user intent

This is a source-pinned test — we read `cps/config_sql.py` and confirm
the dangerous source pattern is gone. That's the cheapest way to keep
the regression from sneaking back via a "fix unified logging" PR.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SQL_PY = REPO_ROOT / "cps" / "config_sql.py"


@pytest.mark.unit
def test_no_force_reset_of_config_logfile_to_stdout():
    """The exact pattern that broke the admin log viewer must not return."""
    source = CONFIG_SQL_PY.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"""self\.config_logfile\s*=\s*logger\.LOG_TO_STDOUT\s*\n"""
        r"""\s*s\.config_logfile\s*=\s*logger\.LOG_TO_STDOUT""",
        re.MULTILINE,
    )
    assert not forbidden.search(source), (
        "cps/config_sql.py contains the force-reset-to-stdout block that "
        "permanently blanked the admin → View Logs page. See fork issue "
        "#312 for the user-visible symptom."
    )


@pytest.mark.unit
def test_migration_helper_exists_and_is_callable():
    """A migration must move legacy `/dev/stdout` (set by the old enforce
    block) back to the default file path so the admin viewer has data
    again on first boot after upgrade."""
    from cps import config_sql
    assert hasattr(config_sql, "_migrate_legacy_stdout_logfile"), (
        "Expected a `_migrate_legacy_stdout_logfile` helper on cps.config_sql "
        "that translates the legacy auto-set stdout value to the file default."
    )


@pytest.mark.unit
def test_migration_helper_swaps_legacy_stdout_to_empty_default():
    from cps import config_sql, logger

    class _Row:
        config_logfile = logger.LOG_TO_STDOUT

    row = _Row()
    changed = config_sql._migrate_legacy_stdout_logfile(row)
    assert changed is True, "migration must report it changed the row"
    assert row.config_logfile == "", (
        f"legacy /dev/stdout should migrate to '' (the empty default → "
        f"DEFAULT_LOG_FILE), got {row.config_logfile!r}"
    )


@pytest.mark.unit
def test_migration_helper_leaves_user_chosen_paths_alone():
    from cps import config_sql

    class _Row:
        config_logfile = "/config/my-custom.log"

    row = _Row()
    changed = config_sql._migrate_legacy_stdout_logfile(row)
    assert changed is False, "must not touch a user-chosen path"
    assert row.config_logfile == "/config/my-custom.log"


@pytest.mark.unit
def test_migration_helper_leaves_empty_default_alone():
    from cps import config_sql

    class _Row:
        config_logfile = ""

    row = _Row()
    changed = config_sql._migrate_legacy_stdout_logfile(row)
    assert changed is False, "no-op on already-default rows"
    assert row.config_logfile == ""
