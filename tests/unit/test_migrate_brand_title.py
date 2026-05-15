# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pin the brand-title migration shipped with v4.0.60+.

The v4.0.60 rebrand changed the *default* for fresh installs to
``Calibre-Web NextGen`` but left existing rows alone. Maggie's install
was still showing ``Calibre-Web`` in the browser tab after the upgrade
because her ``settings`` row predated the default change. This migration
fixes that for everyone migrating from stock calibre-web (default
``Calibre-Web``) or from CWA (default ``Calibre-Web Automated``) while
leaving anyone who picked a custom title (``Maggie's Library``,
``Coundou Family Library``, etc.) untouched.

Behavior under test:
- ``should_migrate`` matches the two legacy defaults regardless of
  hyphenation or case ("calibre web", "CALIBRE-WEB AUTOMATED", etc.)
- Empty / whitespace / None are treated as legacy (same as old default).
- Any custom or already-rebranded title is left alone.
- ``migrate`` writes the new value and is idempotent on a second run.
"""

import os
import sqlite3
import tempfile

import pytest


# Import directly from the scripts/ folder. The Docker image puts
# scripts/ on disk at /app/calibre-web-automated/scripts/; in CI the
# repo root is the working dir, so we add it to sys.path explicitly.
import sys
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))

import migrate_brand_title as mod  # noqa: E402


# --- helpers ----------------------------------------------------------

def _make_db(tmp_path: str, title) -> str:
    """Create a minimal sqlite app.db with one settings row.

    ``title`` may be a string, None, or ``...`` to skip the row entirely
    (simulating a never-initialized DB).
    """
    db_path = os.path.join(tmp_path, "app.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY, "
            "config_calibre_web_title TEXT)"
        )
        if title is not Ellipsis:
            conn.execute(
                "INSERT INTO settings (id, config_calibre_web_title) VALUES (1, ?)",
                (title,),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _read_title(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT config_calibre_web_title FROM settings LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# --- should_migrate ---------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "Calibre-Web",
        "calibre-web",
        "CALIBRE-WEB",
        "Calibre Web",
        "calibreweb",
        "  Calibre-Web  ",
        "Calibre-Web Automated",
        "calibre-web automated",
        "CALIBRE WEB AUTOMATED",
        "calibrewebautomated",
        None,
        "",
        "   ",
    ],
)
def test_should_migrate_recognizes_legacy(title):
    assert mod.should_migrate(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "Calibre-Web NextGen",          # already on new brand
        "calibre-web nextgen",
        "Maggie's Library",
        "Coundou Family Library",
        "CWA",                          # acronym alone is not the legacy default
        "Calibre-Web Automated v2",     # customized suffix
        "My Calibre-Web",               # customized prefix
        "Calibre-Web - Family",         # customized suffix
        "NextGen",
    ],
)
def test_should_migrate_preserves_custom(title):
    assert mod.should_migrate(title) is False


# --- migrate (end-to-end on real sqlite db) ---------------------------

def test_migrate_rewrites_legacy_calibre_web(tmp_path):
    db = _make_db(str(tmp_path), "Calibre-Web")
    updated, previous = mod.migrate(db)
    assert updated is True
    assert previous == "Calibre-Web"
    assert _read_title(db) == "Calibre-Web NextGen"


def test_migrate_rewrites_legacy_calibre_web_automated(tmp_path):
    db = _make_db(str(tmp_path), "Calibre-Web Automated")
    updated, previous = mod.migrate(db)
    assert updated is True
    assert previous == "Calibre-Web Automated"
    assert _read_title(db) == "Calibre-Web NextGen"


def test_migrate_preserves_custom_title(tmp_path):
    db = _make_db(str(tmp_path), "Maggie's Library")
    updated, previous = mod.migrate(db)
    assert updated is False
    assert previous == "Maggie's Library"
    assert _read_title(db) == "Maggie's Library"


def test_migrate_noop_when_already_on_new_brand(tmp_path):
    db = _make_db(str(tmp_path), "Calibre-Web NextGen")
    updated, previous = mod.migrate(db)
    assert updated is False
    assert previous == "Calibre-Web NextGen"
    assert _read_title(db) == "Calibre-Web NextGen"


def test_migrate_handles_null_title(tmp_path):
    db = _make_db(str(tmp_path), None)
    updated, previous = mod.migrate(db)
    assert updated is True
    assert previous is None
    assert _read_title(db) == "Calibre-Web NextGen"


def test_migrate_empty_settings_table_is_safe(tmp_path):
    db = _make_db(str(tmp_path), Ellipsis)  # no row inserted
    updated, previous = mod.migrate(db)
    assert updated is False
    assert previous is None
    # And the table is still empty after.
    conn = sqlite3.connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_migrate_is_idempotent(tmp_path):
    db = _make_db(str(tmp_path), "Calibre-Web")
    updated1, _ = mod.migrate(db)
    updated2, previous2 = mod.migrate(db)
    assert updated1 is True
    assert updated2 is False
    assert previous2 == "Calibre-Web NextGen"
    assert _read_title(db) == "Calibre-Web NextGen"


# --- CLI entrypoint ---------------------------------------------------

def test_cli_returns_zero_and_prints_on_update(tmp_path, capsys):
    db = _make_db(str(tmp_path), "Calibre-Web")
    rc = mod.main([db])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Updated config_calibre_web_title" in captured.out
    assert "Calibre-Web NextGen" in captured.out
    assert _read_title(db) == "Calibre-Web NextGen"


def test_cli_returns_zero_and_prints_on_noop(tmp_path, capsys):
    db = _make_db(str(tmp_path), "Maggie's Library")
    rc = mod.main([db])
    captured = capsys.readouterr()
    assert rc == 0
    assert "No change" in captured.out
    assert _read_title(db) == "Maggie's Library"


def test_cli_returns_one_on_sqlite_error(tmp_path, capsys):
    missing = os.path.join(str(tmp_path), "does-not-exist.db")
    # Force sqlite to fail by pointing at a path it can't even create
    # the table-scan against (no file, table missing). Open it once to
    # ensure the file exists but the table does NOT, so the SELECT
    # raises OperationalError which is sqlite3.Error.
    sqlite3.connect(missing).close()
    rc = mod.main([missing])
    captured = capsys.readouterr()
    assert rc == 1
    assert "sqlite error" in captured.out
