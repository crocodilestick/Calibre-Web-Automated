# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the REAL root cause of fork #359.

``config_kobo_sync_magic_shelves`` ships default-False, every Kobo-side
magic-shelf path is gated on it (delivery arm, collections, cache refresh),
and — worse — when it's off, a DeletedTag tombstone is emitted for every
magic shelf the user owns on every sync. Meanwhile the magic-shelf edit UI
happily let users tick the per-shelf "Enable Kobo sync" checkbox, silently
swallowing the intent. @recruiterguy ran this configuration across
v4.0.76 → v4.0.155: five cursor-arithmetic releases were correct but sat
behind a dead flag, and his symptom never changed.

Live reproduction (2026-06-06, cwn-local on main @ e1d36fac2):
  flag=0, magic shelf kobo_sync=1 matching all 19 library books,
  regular shelf with 1 book, fresh device, shelf-only mode
  → sync delivered exactly 1 book, 1 NewTag (regular shelf),
    9 DeletedTags (every magic shelf), 0 magic collections.

The fix is three-pronged; these tests pin each prong:
  1. One-time boot migration enables the global flag where per-shelf
     intent already exists (runs before config load, so same-boot live).
  2. The magic-shelf edit template disables the per-shelf checkbox and
     explains why when the global flag is off (no new silent swallowing).
  3. kobo.py logs swallowed intent at debug level.
"""

import os
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UB_PY = REPO_ROOT / "cps" / "ub.py"
KOBO_PY = REPO_ROOT / "cps" / "kobo.py"
WEB_PY = REPO_ROOT / "cps" / "web.py"
TEMPLATE = REPO_ROOT / "cps" / "templates" / "magic_shelf_edit.html"

MARKER_NAME = "kobo_magic_shelf_intent_v1"


def _make_app_db(path, *, flag_value=0, intent_rows=0, with_flag_column=True):
    """Minimal app.db with just the two tables the migration touches."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE magic_shelf (id INTEGER PRIMARY KEY, name VARCHAR, "
        "user_id INTEGER, kobo_sync BOOLEAN)"
    )
    if with_flag_column:
        cur.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY, "
            "config_kobo_sync_magic_shelves INTEGER)"
        )
        cur.execute(
            "INSERT INTO settings (id, config_kobo_sync_magic_shelves) "
            "VALUES (1, ?)", (flag_value,)
        )
    else:
        cur.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY)")
        cur.execute("INSERT INTO settings (id) VALUES (1)")
    for i in range(intent_rows):
        cur.execute(
            "INSERT INTO magic_shelf (name, user_id, kobo_sync) "
            "VALUES (?, 3, 1)", (f"shelf-{i}",)
        )
    conn.commit()
    conn.close()


def _run_migration(db_path, config_dir, monkeypatch):
    """Invoke migrate_kobo_magic_shelf_intent against a real SQLite file
    with constants.CONFIG_DIR pointed at a temp dir for the marker."""
    from sqlalchemy import create_engine
    from cps import constants as cps_constants
    from cps import ub as cps_ub

    monkeypatch.setattr(cps_constants, "CONFIG_DIR", str(config_dir))
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        cps_ub.migrate_kobo_magic_shelf_intent(engine, None)
    finally:
        engine.dispose()


def _flag(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT config_kobo_sync_magic_shelves FROM settings WHERE id=1"
        ).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.unit
class TestIntentMigration:
    def test_flips_flag_when_per_shelf_intent_exists(self, tmp_path, monkeypatch):
        """The recruiterguy state: flag off, shelves marked kobo_sync=1.
        Migration must enable the global flag."""
        db = tmp_path / "app.db"
        _make_app_db(db, flag_value=0, intent_rows=2)
        _run_migration(db, tmp_path, monkeypatch)
        assert _flag(db) == 1, (
            "per-shelf kobo_sync intent must enable the global flag (#359)"
        )
        assert (tmp_path / ".cwa_migrations" / MARKER_NAME).is_file()

    def test_no_flip_without_intent(self, tmp_path, monkeypatch):
        """Installs with no magic-shelf Kobo intent stay opted out."""
        db = tmp_path / "app.db"
        _make_app_db(db, flag_value=0, intent_rows=0)
        _run_migration(db, tmp_path, monkeypatch)
        assert _flag(db) == 0, "no intent → flag must stay off"
        # marker still written: the decision is made, don't re-evaluate
        assert (tmp_path / ".cwa_migrations" / MARKER_NAME).is_file()

    def test_marker_respects_later_admin_disable(self, tmp_path, monkeypatch):
        """An admin who deliberately disables the flag after the migration
        ran must NOT be re-flipped on subsequent boots."""
        db = tmp_path / "app.db"
        _make_app_db(db, flag_value=0, intent_rows=1)
        _run_migration(db, tmp_path, monkeypatch)
        assert _flag(db) == 1
        # admin disables deliberately
        conn = sqlite3.connect(db)
        conn.execute("UPDATE settings SET config_kobo_sync_magic_shelves=0")
        conn.commit()
        conn.close()
        # next boot
        _run_migration(db, tmp_path, monkeypatch)
        assert _flag(db) == 0, (
            "marker must prevent re-flipping a deliberate admin disable"
        )

    def test_already_enabled_is_untouched_and_marked(self, tmp_path, monkeypatch):
        db = tmp_path / "app.db"
        _make_app_db(db, flag_value=1, intent_rows=3)
        _run_migration(db, tmp_path, monkeypatch)
        assert _flag(db) == 1
        assert (tmp_path / ".cwa_migrations" / MARKER_NAME).is_file()

    def test_marker_unwritable_aborts_flip_then_recovers(self, tmp_path, monkeypatch):
        """Greptile P1 on PR #372: if the marker can't be written, the flag
        flip must NOT commit — otherwise a persistent filesystem problem
        re-overrides a deliberate admin disable on every boot. The flip and
        its never-again guard land together or not at all."""
        db = tmp_path / "app.db"
        _make_app_db(db, flag_value=0, intent_rows=1)
        ro_config = tmp_path / "ro-config"
        ro_config.mkdir()
        ro_config.chmod(0o500)  # .cwa_migrations/ not creatable inside
        try:
            _run_migration(db, ro_config, monkeypatch)  # must not raise
            assert _flag(db) == 0, (
                "flag must NOT flip when the marker is unwritable — "
                "flip + marker land together or not at all"
            )
            assert not (ro_config / ".cwa_migrations").exists()
        finally:
            ro_config.chmod(0o700)
        # Filesystem fixed → next boot applies the flip and the marker.
        _run_migration(db, ro_config, monkeypatch)
        assert _flag(db) == 1
        assert (ro_config / ".cwa_migrations" / MARKER_NAME).is_file()

    def test_missing_column_defers_without_marker(self, tmp_path, monkeypatch):
        """Pre-flag schema (settings column not added yet — config_sql adds
        it after ub migrations on first boot): must not crash, must NOT
        write the marker, so the flip retries next boot."""
        db = tmp_path / "app.db"
        _make_app_db(db, intent_rows=1, with_flag_column=False)
        _run_migration(db, tmp_path, monkeypatch)  # must not raise
        assert not (tmp_path / ".cwa_migrations" / MARKER_NAME).exists(), (
            "marker must not be written when the schema isn't ready — "
            "the migration needs to retry next boot"
        )

    def test_registered_in_migrate_database(self):
        src = UB_PY.read_text(encoding="utf-8")
        body = src.split("def migrate_Database(", 1)[1]
        assert "migrate_kobo_magic_shelf_intent(engine, _session)" in body, (
            "migration must be wired into migrate_Database"
        )


@pytest.mark.unit
class TestUiHonesty:
    """The per-shelf checkbox must not silently swallow intent again."""

    def test_template_gates_checkbox_on_global_flag(self):
        tpl = TEMPLATE.read_text(encoding="utf-8")
        assert "kobo_magic_sync_enabled" in tpl, (
            "magic_shelf_edit.html must consult kobo_magic_sync_enabled"
        )
        # the checkbox itself carries the disabled gate
        for line in tpl.splitlines():
            if 'id="shelf-kobo-sync"' in line:
                assert "disabled" in line and "kobo_magic_sync_enabled" in line, (
                    "the kobo-sync checkbox must be disabled when the global "
                    "flag is off"
                )
                break
        else:
            pytest.fail("shelf-kobo-sync checkbox not found in template")

    def test_template_explains_why_disabled(self):
        tpl = TEMPLATE.read_text(encoding="utf-8")
        assert "Sync Magic Shelves to Kobo" in tpl, (
            "the disabled state must name the exact CWA Settings toggle "
            "the user needs"
        )

    def test_both_render_routes_pass_the_flag(self):
        src = WEB_PY.read_text(encoding="utf-8")
        assert src.count("kobo_magic_sync_enabled=bool(config.config_kobo_sync_magic_shelves)") >= 2, (
            "both magic_shelf_edit.html render calls (create + edit) must "
            "pass kobo_magic_sync_enabled"
        )


@pytest.mark.unit
class TestApiHonesty:
    """Greptile gap 2 on PR #372: the create/edit POST handlers accept
    kobo_sync=True from the JSON body without consulting the global flag —
    a direct API call recreates the silent-swallow state the UI gating
    fixed. The handlers must persist the intent (so enabling the global
    setting later honors it — and so rule edits on previously-marked
    shelves don't get rejected via the disabled-but-checked checkbox) but
    return an explicit warning instead of a silent success."""

    def test_create_handler_warns_on_inert_kobo_intent(self):
        src = WEB_PY.read_text(encoding="utf-8")
        create_body = src.split('@web.route("/magicshelf", methods=["GET", "POST"])', 1)[1]
        create_body = create_body.split('@web.route("/magicshelf/<int:shelf_id>/edit"', 1)[0]
        assert "kobo_sync and not config.config_kobo_sync_magic_shelves" in create_body, (
            "create handler must detect persisted-but-inert kobo intent"
        )
        assert '"warning"' in create_body, (
            "create handler must return a warning for inert kobo intent"
        )

    def test_edit_handler_warns_on_inert_kobo_intent(self):
        src = WEB_PY.read_text(encoding="utf-8")
        edit_body = src.split('@web.route("/magicshelf/<int:shelf_id>/edit"', 1)[1]
        edit_body = edit_body.split('@web.route("/magicshelf/<int:shelf_id>/duplicate"', 1)[0]
        assert "kobo_sync and not config.config_kobo_sync_magic_shelves" in edit_body, (
            "edit handler must detect persisted-but-inert kobo intent"
        )
        assert '"warning"' in edit_body, (
            "edit handler must return a warning for inert kobo intent"
        )

    def test_intent_is_persisted_not_rejected_or_coerced(self):
        """Rejecting would break rule-edits on previously-marked shelves
        (the disabled-but-checked checkbox still posts kobo_sync=true);
        coercing to False would silently erase intent. The shelf keeps the
        value the client sent."""
        src = WEB_PY.read_text(encoding="utf-8")
        # The assignment into the model must remain unconditional.
        assert "kobo_sync=kobo_sync" in src, "create must persist intent as sent"
        assert "shelf.kobo_sync = kobo_sync" in src, "edit must persist intent as sent"


@pytest.mark.unit
class TestSwallowedIntentLog:
    def test_kobo_logs_swallowed_intent_at_debug(self):
        src = KOBO_PY.read_text(encoding="utf-8")
        assert "isEnabledFor(logging.DEBUG)" in src and "#359" in src, (
            "get_magic_shelf_book_ids_for_kobo must debug-log swallowed "
            "per-shelf intent when the global flag is off"
        )
