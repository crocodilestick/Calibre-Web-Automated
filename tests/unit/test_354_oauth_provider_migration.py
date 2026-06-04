# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #354 — 500 on /admin/config from a partial
oauthProvider schema that ``migrate_oauth_provider_table`` cannot repair.

## Why these tests exist

Reporter @Neuromancien59 (v4.0.144, Debian) hit ``GET /admin/config`` →
HTTP 500. Their startup log shows OAuth init failing with::

    (sqlite3.OperationalError) no such column: oauthProvider.oauth_authorize_url

i.e. their ``oauthProvider`` table has ``oauth_base_url`` but is missing
``oauth_authorize_url`` (and the rest of that group). The boot catch leaves
``oauth_bb.oauthblueprints`` empty; ``config_edit.html`` then does
``provider | selectattr(...) | first`` on an empty sequence and raises
``UndefinedError: No first item, sequence was empty`` → 500.

The root cause is in ``cps.ub.migrate_oauth_provider_table`` (cps/ub.py:1386):

1. **Probe-by-proxy.** The first probe queries only ``oauth_base_url`` as a
   stand-in for its whole 5-column group. A DB that has ``oauth_base_url`` but
   is missing ``oauth_authorize_url`` *passes* the probe, so the group-1 ALTER
   block is skipped and the missing columns are never added. The second group
   has the identical flaw (``metadata_url`` proxies for ``scope`` /
   ``username_mapper`` / ``email_mapper`` / ``login_button``).
2. **All-or-nothing batch** (``_run_ddl_with_retry``): every ALTER in a group
   runs in one transaction; a stray ``duplicate column`` re-raises and rolls
   back the rest.

Net: the migration cannot repair a database in a *partial* column state — the
exact shape an instance upgraded across several releases lands in.

## What these tests pin

Real SQLite engines (not mocks) — the bug is SQL-semantic. After
``migrate_oauth_provider_table`` runs against any starting state, all ten
migration-managed columns must be present and the run must be idempotent.

- ``test_partial_group1_repaired`` and ``test_partial_group2_repaired`` and
  ``test_partial_double_run_idempotent`` are **red on main** (they reproduce
  the reporter's symptom: a column stays missing) and turn green once the
  migration introspects actual columns and adds only the missing ones.
- ``test_all_old_schema_repaired`` and ``test_all_new_schema_noop`` are
  behaviour-preservation pins (green on both main and the fix): the migration
  must still repair an all-old DB and no-op cleanly on an all-new DB.

Parked ahead of the fix per test-driven discipline (red baseline confirmed).
The fix (per-column introspecting migration) lands in the same release that
turns the first three green; see notes/fork-354-oauth-migration-500.md.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from cps import ub

pytestmark = pytest.mark.unit


# The ten columns migrate_oauth_provider_table is responsible for ensuring
# exist (cps/ub.py OAuthProvider model). Base columns created with the table
# itself (id, provider_name, oauth_client_id, oauth_client_secret, active) are
# never migration-managed.
MANAGED_COLUMNS = {
    "oauth_base_url",
    "oauth_authorize_url",
    "oauth_token_url",
    "oauth_userinfo_url",
    "oauth_admin_group",
    "metadata_url",
    "scope",
    "username_mapper",
    "email_mapper",
    "login_button",
}

GROUP1 = [
    "oauth_base_url",
    "oauth_authorize_url",
    "oauth_token_url",
    "oauth_userinfo_url",
    "oauth_admin_group",
]
GROUP2 = ["metadata_url", "scope", "username_mapper", "email_mapper", "login_button"]


def _make_partial_db(extra_columns):
    """Create a temp SQLite DB whose oauthProvider table has the base columns
    plus exactly ``extra_columns`` of the migration-managed set. Returns
    (engine, path). Caller disposes the engine and unlinks the path.
    """
    fd, path = tempfile.mkstemp(suffix="-app.db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    col_defs = [
        "id INTEGER PRIMARY KEY",
        "provider_name VARCHAR",
        "oauth_client_id VARCHAR",
        "oauth_client_secret VARCHAR",
        "active BOOLEAN",
    ]
    for col in extra_columns:
        col_defs.append(f"'{col}' VARCHAR DEFAULT NULL")
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE oauthProvider ({', '.join(col_defs)})"))
    return engine, path


def _columns(engine):
    return {c["name"] for c in sa_inspect(engine).get_columns("oauthProvider")}


def _run_migration(engine):
    """Run the real migration against the engine, mirroring how migrate_Database
    invokes it (a live session bound to the same engine)."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        ub.migrate_oauth_provider_table(engine, session)
    finally:
        session.close()


def _with_db(extra_columns):
    """Build a partial DB, run the migration, return the post-migration column
    set. Cleans up the engine + temp file."""
    engine, path = _make_partial_db(extra_columns)
    try:
        _run_migration(engine)
        return _columns(engine)
    finally:
        engine.dispose()
        os.unlink(path)


def test_partial_group1_repaired():
    """Reporter's exact case: oauth_base_url present, rest of group 1 missing.
    The proxy-probe passes on oauth_base_url and skips the group-1 ALTERs, so
    oauth_authorize_url et al. stay missing → 500. RED on main."""
    cols = _with_db(extra_columns=["oauth_base_url"])
    missing = MANAGED_COLUMNS - cols
    assert not missing, f"migration left managed columns missing: {sorted(missing)}"


def test_partial_group2_repaired():
    """Group 1 fully present + metadata_url present, but scope/username_mapper/
    email_mapper/login_button missing. The second proxy-probe passes on
    metadata_url and skips its ALTERs. RED on main."""
    cols = _with_db(extra_columns=GROUP1 + ["metadata_url"])
    missing = MANAGED_COLUMNS - cols
    assert not missing, f"migration left managed columns missing: {sorted(missing)}"


def test_partial_double_run_idempotent():
    """A partial DB run through the migration twice must end fully repaired and
    must not raise on the second pass (restart idempotency). RED on main (first
    run never repairs group 1, so it stays missing across both runs)."""
    engine, path = _make_partial_db(extra_columns=["oauth_base_url"])
    try:
        _run_migration(engine)
        _run_migration(engine)  # must be a clean no-op, never raise
        missing = MANAGED_COLUMNS - _columns(engine)
        assert not missing, f"migration left managed columns missing: {sorted(missing)}"
    finally:
        engine.dispose()
        os.unlink(path)


def test_all_old_schema_repaired():
    """An all-old DB (none of the ten managed columns present) must be fully
    repaired. Behaviour-preservation pin — green on main and on the fix."""
    cols = _with_db(extra_columns=[])
    missing = MANAGED_COLUMNS - cols
    assert not missing, f"migration left managed columns missing: {sorted(missing)}"


def test_all_new_schema_noop():
    """An all-new DB (all ten present) must survive the migration unchanged and
    without error. Behaviour-preservation pin — green on main and on the fix."""
    cols = _with_db(extra_columns=sorted(MANAGED_COLUMNS))
    assert MANAGED_COLUMNS <= cols


def test_duplicate_column_midloop_does_not_abort_remaining(monkeypatch):
    """A managed column that physically exists but is absent from the
    introspected snapshot makes ``ADD COLUMN`` raise ``duplicate column name``
    mid-loop. The migration must treat that as already-applied and keep adding
    the remaining columns, not abort the loop.

    This is the concurrent-startup race (Greptile P2 on PR #355): two workers
    boot together, both snapshot the same ``existing`` set, one adds a column
    and the other's ALTER then hits ``duplicate column name`` — a non-lock
    ``OperationalError`` that ``_run_ddl_with_retry`` re-raises. Before the
    hardening the exception propagates out of the for-loop and every column
    *after* the racy one stays missing for a full boot cycle (so OAuth init
    keeps failing and ``/admin/config`` keeps 500ing); afterwards the loop
    swallows duplicate-column and continues.

    We reproduce it deterministically: ``oauth_token_url`` (middle of the
    managed list) physically exists, but a wrapper inspector hides it from the
    snapshot, so the loop tries to re-add it and SQLite raises the real
    ``duplicate column name`` error. RED before the fix (the seven columns
    after ``oauth_token_url`` stay missing); GREEN after.
    """
    engine, path = _make_partial_db(
        extra_columns=["oauth_base_url", "oauth_authorize_url", "oauth_token_url"]
    )
    try:
        import sqlalchemy

        real_inspect = sqlalchemy.inspect

        class _StaleInspector:
            """Delegates to the real inspector but drops ``oauth_token_url``
            from the oauthProvider column snapshot — i.e. a stale/racy view in
            which a column the table actually has looks missing."""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def get_columns(self, table_name, *a, **k):
                cols = self._real.get_columns(table_name, *a, **k)
                if table_name == "oauthProvider":
                    return [c for c in cols if c["name"] != "oauth_token_url"]
                return cols

        monkeypatch.setattr(
            sqlalchemy, "inspect", lambda bind: _StaleInspector(real_inspect(bind))
        )
        _run_migration(engine)
        monkeypatch.undo()  # verify the real schema with the real inspector

        missing = MANAGED_COLUMNS - _columns(engine)
        assert not missing, (
            "migration aborted on a duplicate-column ALTER and left managed "
            f"columns missing: {sorted(missing)}"
        )
    finally:
        engine.dispose()
        os.unlink(path)
