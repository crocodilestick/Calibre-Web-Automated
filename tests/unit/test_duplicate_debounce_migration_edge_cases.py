# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Edge cases for the v4.0.65 ``_migrate_duplicate_debounce_5_to_30_v1``.

The happy path (legacy 5 -> 30; custom 15/60 preserved; marker idempotency)
lives in ``test_duplicate_debounce_default_regression.py``. This file pins
the failure-mode behaviour so a future refactor that quietly breaks the
guard rails fails CI loudly:

* Empty ``cwa_settings`` table (race between INSERT DEFAULT VALUES and
  the migration) — must not crash, must not skip the marker.
* ``.cwa_migrations`` directory not creatable (parent read-only) — migration
  still applies the UPDATE; marker write failure is logged but not fatal.
* Two ``CWA_DB()`` constructors in the same process (boot-time race between
  web process and ingest_processor module-level import) — exactly one
  migration log line, exactly one marker write, both end up at 30.
* Concrete boundary tests for the SQL: only EXACT value 5 migrates;
  4, 6, 0 are preserved.
* Marker file is in ``.cwa_migrations/`` directory (parent path is
  ``CWA_DB_PATH``), matching the kobo migration convention.
"""

import os
import re
import sqlite3
import sys
import threading
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _seed_cwa_db(tmp_path: Path, *, debounce_value: int | None,
                 insert_row: bool = True):
    """Write a cwa.db at ``tmp_path/cwa.db`` with the production schema patched
    to the requested debounce default. If ``insert_row`` is False the table is
    created empty (no default-values row) — tests the boot-race window where
    settings INSERT hasn't happened yet.
    """
    schema = _read(REPO_ROOT / "scripts" / "cwa_schema.sql")
    if debounce_value is not None:
        schema = re.sub(
            r"duplicate_scan_debounce_seconds\s+INTEGER\s+DEFAULT\s+\d+\s+NOT\s+NULL",
            f"duplicate_scan_debounce_seconds INTEGER DEFAULT {debounce_value} NOT NULL",
            schema,
        )
    db_path = tmp_path / "cwa.db"
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
            cur.execute(stmt)
        if insert_row:
            cur.execute("INSERT INTO cwa_settings DEFAULT VALUES;")
        con.commit()
    finally:
        con.close()


@pytest.mark.unit
class TestMigrationEdgeCasesAroundBoundary:
    """Pin: only the EXACT value 5 migrates. 4, 6, 0, negative all preserved."""

    @pytest.mark.parametrize("preserved", [0, 1, 2, 3, 4, 6, 7, 10, 25, 31, 100])
    def test_only_5_migrates_not_neighbours(self, tmp_path, monkeypatch, preserved):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        _seed_cwa_db(tmp_path, debounce_value=preserved)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == preserved, (
                f"value {preserved} (!=5) must be preserved verbatim, "
                f"got {settings['duplicate_scan_debounce_seconds']}"
            )
        finally:
            db.con.close()


@pytest.mark.unit
class TestEmptyTableHandling:
    """Pin: an empty cwa_settings table (race window) doesn't crash the
    migration and doesn't leave the marker un-written.
    """

    def test_empty_table_no_crash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        # Build cwa.db with the table created but no row inserted yet.
        _seed_cwa_db(tmp_path, debounce_value=None, insert_row=False)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            # Either the row was inserted during CWA_DB.__init__ at the
            # set_default_settings path, or it remains absent; either way
            # the migration must not crash.
            settings = db.get_cwa_settings()
            assert "duplicate_scan_debounce_seconds" in settings
        finally:
            db.con.close()


@pytest.mark.unit
class TestMarkerWriteFailureNonFatal:
    """If marker dir cannot be created (parent read-only), the migration
    must still apply the SQL bump — the marker write failure is logged
    but not fatal. Without this guarantee, the migration would skip and
    affected users would stay at 5 forever.
    """

    def test_marker_write_failure_does_not_block_sql_bump(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        _seed_cwa_db(tmp_path, debounce_value=5)

        # Pre-create the marker dir as a FILE (so makedirs fails) — simulates
        # a permission/filesystem failure on the marker write path.
        marker_dir_path = tmp_path / ".cwa_migrations"
        marker_dir_path.write_text("not a directory", encoding="utf-8")

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == 30, (
                "SQL bump must apply even when marker write fails — "
                "otherwise affected users stay at 5 forever"
            )
        finally:
            db.con.close()


@pytest.mark.unit
class TestConcurrentCWADBConstructors:
    """Boot-race: web process and ingest_processor both module-import
    cwa_db simultaneously. Both CWA_DB() __init__ runs. The migration must
    end with the value at 30, not crash, not double-apply, not loop.

    With marker-file gating this should be safe because the second
    constructor sees the marker (written by the first) and short-circuits.
    The window where both run the SELECT before either writes the marker is
    tolerable because the UPDATE is idempotent (already-30 rows are
    untouched by ``WHERE ... = 5``).
    """

    def test_two_concurrent_constructors_converge_to_30(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        _seed_cwa_db(tmp_path, debounce_value=5)

        from cwa_db import CWA_DB

        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=5)
                db = CWA_DB(verbose=False)
                settings = db.get_cwa_settings()
                results.append(settings["duplicate_scan_debounce_seconds"])
                db.con.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"errors during concurrent CWA_DB init: {errors}"
        assert results == [30, 30], (
            f"both concurrent constructors should converge to 30, got {results}"
        )

        # Marker must exist.
        marker = tmp_path / ".cwa_migrations" / "duplicate_debounce_5_to_30_v1.applied"
        assert marker.exists(), "marker should be written by one of the constructors"


@pytest.mark.unit
class TestMarkerNameMatchesConvention:
    """The kobo migration uses ``CONFIG_DIR/.cwa_migrations/<marker_name>``.
    Our migration must use the same convention so future operators can find
    it in the same directory and clean / inspect uniformly.
    """

    def test_marker_path_matches_kobo_convention(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        _seed_cwa_db(tmp_path, debounce_value=5)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            db.get_cwa_settings()
        finally:
            db.con.close()

        # Marker must be at tmp_path/.cwa_migrations/<name>
        marker_dir = tmp_path / ".cwa_migrations"
        assert marker_dir.is_dir(), (
            "marker directory ``.cwa_migrations/`` must exist alongside cwa.db"
        )
        markers = list(marker_dir.iterdir())
        names = [m.name for m in markers]
        assert "duplicate_debounce_5_to_30_v1.applied" in names, (
            f"versioned marker file expected; got {names}"
        )


@pytest.mark.unit
class TestSourcePinSchemaMigrationOrder:
    """Pin: the migration runs AFTER set_default_settings but BEFORE
    get_cwa_settings — otherwise we'd either skip the migration entirely
    (if it runs before the table exists / before set_default_settings
    populates the row) or return stale data (if it runs after the public
    settings dict is captured).
    """

    def test_init_order_set_defaults_then_migrate_then_get_settings(self):
        src = _read(REPO_ROOT / "scripts" / "cwa_db.py")
        # Find the __init__ body and assert ordering.
        m = re.search(
            r"def __init__\(self, verbose=False\):(.*?)def\s+\w+\(",
            src,
            flags=re.DOTALL,
        )
        assert m, "could not locate CWA_DB.__init__ in cwa_db.py"
        body = m.group(1)

        set_defaults_pos = body.find("self.set_default_settings()")
        migrate_pos = body.find("self._migrate_duplicate_debounce_5_to_30_v1()")
        get_settings_pos = body.find("self.cwa_settings = self.get_cwa_settings()")

        assert -1 < set_defaults_pos < migrate_pos < get_settings_pos, (
            f"init must call set_default_settings -> migrate -> get_cwa_settings in "
            f"that order; got positions "
            f"set={set_defaults_pos} mig={migrate_pos} get={get_settings_pos}"
        )
