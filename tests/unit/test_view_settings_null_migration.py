# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the User.view_settings NULL → {} startup
migration.

## Why this migration exists

`view_settings` is declared `Column(JSON, default={})` in cps/ub.py.
SQLAlchemy's `default=` only applies on INSERT through the ORM; rows
imported from older schemas (pre-2025-01-14 when this column was added
upstream by demitrix), or inserted by raw SQL / external admin tools,
can land with the column NULL. Any user with NULL view_settings hits:

    File "cps/ub.py", line 235, in get_view_property
        if not self.view_settings.get(page):
               ^^^^^^^^^^^^^^^^^^^^^^
    AttributeError: 'NoneType' object has no attribute 'get'

…which 500s every page that consults view_settings: `/`,
`/book/<id>` (via layout.html cover-settings cog), `/table`, etc.
Effectively a per-user lockout from the web UI.

PR #281 proposed `vs = self.view_settings or {}` guards inside
get_view_property / set_view_property. That was closed because no
production user (teenyverse) currently has NULL view_settings — the
fix looked speculative. During fork #276 work I reproduced the exact
crash by manually setting `view_settings=NULL` on a test user.

The chosen long-term shape: a one-time startup migration that
normalizes NULL → '{}' for every existing user. That eliminates the
failure class entirely instead of putting per-call guards everywhere.
Idempotent (the UPDATE matches zero rows on subsequent runs), wired
into the existing cps.ub.migrate_Database orchestrator.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
UB_PY = REPO_ROOT / "cps" / "ub.py"


def _ub_src() -> str:
    return UB_PY.read_text()


def test_migration_function_defined():
    """A migrate_user_view_settings_null function must exist in cps/ub.py."""
    src = _ub_src()
    assert re.search(
        r"def migrate_user_view_settings_null\(engine,\s*_session\):",
        src,
    ), (
        "cps/ub.py must define migrate_user_view_settings_null(engine, _session) "
        "matching the existing migration-function signature"
    )


def test_migration_uses_idempotent_update():
    """The migration must be a single UPDATE that matches only NULL rows.
    Idempotent: zero rows match on the second invocation."""
    src = _ub_src()
    match = re.search(
        r"def migrate_user_view_settings_null\([^)]*\):.*?(?=\n(?:def \w|class \w))",
        src, re.DOTALL,
    )
    assert match, "migration function body not isolatable"
    body = match.group(0)
    # Must target the user table.
    assert "user" in body.lower(), "must target the user table"
    # Must target the view_settings column.
    assert "view_settings" in body, "must target the view_settings column"
    # Must match only NULL rows (idempotency).
    assert re.search(r"view_settings\s+IS\s+NULL", body, re.IGNORECASE), (
        "WHERE clause must filter to view_settings IS NULL (idempotent on re-run)"
    )
    # Must set to '{}' literal (empty JSON object).
    assert re.search(r"view_settings\s*=\s*['\"]\{\}['\"]", body) or "'{}'" in body, (
        "SET clause must normalize to '{}' (empty JSON object literal)"
    )


def test_migration_logs_rowcount():
    """The migration must log the number of rows normalized so operators
    can see in container logs whether legacy NULL rows existed."""
    src = _ub_src()
    match = re.search(
        r"def migrate_user_view_settings_null\([^)]*\):.*?(?=\n(?:def \w|class \w))",
        src, re.DOTALL,
    )
    body = match.group(0)
    assert "rowcount" in body, (
        "migration must read .rowcount from the UPDATE result + log it"
    )
    assert "log." in body or "log_" in body, "must call into the logger"


def test_migration_wired_into_orchestrator():
    """migrate_Database must call the new migration alongside the existing
    user-table migrations."""
    src = _ub_src()
    match = re.search(
        r"def migrate_Database\(_session\):(.*?)(?=\n(?:def \w|class \w))",
        src, re.DOTALL,
    )
    assert match, "migrate_Database orchestrator not found"
    orchestrator = match.group(1)
    assert "migrate_user_view_settings_null(" in orchestrator, (
        "migrate_Database must call migrate_user_view_settings_null(engine, _session) "
        "in the orchestrator block alongside migrate_user_table etc."
    )


def test_migration_rolls_back_on_failure():
    """If the UPDATE raises (e.g. DB locked), the migration must rollback
    so it doesn't leave a half-committed transaction."""
    src = _ub_src()
    match = re.search(
        r"def migrate_user_view_settings_null\([^)]*\):.*?(?=\n(?:def \w|class \w))",
        src, re.DOTALL,
    )
    body = match.group(0)
    assert "rollback" in body, (
        "migration must rollback on exception to avoid half-committed transactions"
    )


def test_anonymous_init_uses_empty_dict_not_none():
    """Belt-and-suspenders: cps/ub.py Anonymous.__init__ used to set
    self.view_settings = None. Even though loadSettings() overwrites it
    from the DB row immediately after, the migration above ensures that
    DB row's view_settings is {} (never NULL). Set the initial value to
    {} as well for symmetry — any future code that races between __init__
    and loadSettings won't see a NoneType."""
    src = _ub_src()
    match = re.search(
        r"class Anonymous\([^)]*\):.*?def __init__\(self\):(.*?)def loadSettings",
        src, re.DOTALL,
    )
    assert match, "Anonymous.__init__ not found"
    init_body = match.group(1)
    # The assignment line should be view_settings = {} not None.
    assert re.search(
        r"self\.view_settings\s*=\s*\{\s*\}",
        init_body,
    ), (
        "Anonymous.__init__ should set self.view_settings = {} (not None) for "
        "defense-in-depth — the DB migration is the primary fix"
    )
