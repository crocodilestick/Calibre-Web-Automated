# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pin the duplicate_scan_debounce_seconds default at 30.

CWA upstream commit fe60df7b (2026-01-29) lowered this default from 30 -> 5 to
make duplicate-detection notifications surface faster after multi-book ingest.
For users with large libraries (10k+ books) the 5s default produces stacking
SQL prefilter queries that contend for the GIL with concurrent SQLAlchemy
session-init paths (which call create_function() to register title_sort/lower
UDFs), surfacing as Web UI 504s under sustained ingest. Reported as the
underlying cause behind fork issue #134 by @kanjieater (CWA #1256 reporter)
and identified as the regression vector by @navels in CWA #1256.

The fork reverts the default to 30 in five mirrored sites - schema literal,
three Python fallbacks (web process, editbooks, ingest processor), and the
Jinja fallback - plus a clamp floor of 10 that prevents users from
re-introducing the regression via the admin UI.

These tests pin all five sites + the clamp + the one-time settings migration
that bumps legacy installs (where the user value is the regression default 5)
to the new safe default 30.
"""

import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSchemaDefault:
    """Pin the SQL schema literal to 30."""

    def test_schema_sets_debounce_default_30(self):
        schema = _read(REPO_ROOT / "scripts" / "cwa_schema.sql")
        match = re.search(
            r"duplicate_scan_debounce_seconds\s+INTEGER\s+DEFAULT\s+(\d+)\s+NOT\s+NULL",
            schema,
            flags=re.IGNORECASE,
        )
        assert match is not None, (
            "duplicate_scan_debounce_seconds column not found in cwa_schema.sql"
        )
        assert match.group(1) == "30", (
            f"schema default is {match.group(1)}, expected 30 - the v4.0.46-era"
            f" regression default of 5 must not return"
        )


@pytest.mark.unit
class TestPythonFallbacks:
    """Pin every Python-side fallback that consumes duplicate_scan_debounce_seconds."""

    def _grep_fallback_calls(self, source: str) -> list[str]:
        """Return list of literal default values from cwa_settings.get(...) calls."""
        pattern = (
            r"cwa_settings\.get\(\s*['\"]duplicate_scan_debounce_seconds['\"]\s*,\s*(\d+)"
        )
        return re.findall(pattern, source)

    def test_cwa_functions_fallback_30(self):
        path = REPO_ROOT / "cps" / "cwa_functions.py"
        values = self._grep_fallback_calls(_read(path))
        assert values, "no duplicate_scan_debounce_seconds fallback found in cwa_functions.py"
        for v in values:
            assert v == "30", (
                f"cwa_functions.py has fallback default {v}, expected 30"
            )

    def test_editbooks_fallback_30(self):
        path = REPO_ROOT / "cps" / "editbooks.py"
        values = self._grep_fallback_calls(_read(path))
        assert values, "no duplicate_scan_debounce_seconds fallback found in editbooks.py"
        for v in values:
            assert v == "30", (
                f"editbooks.py has fallback default {v}, expected 30"
            )

    def test_ingest_processor_fallback_30(self):
        """ingest_processor.py is a separate short-lived process - its fallback
        is independent of cwa_functions.py (the web process). Both must agree.
        """
        path = REPO_ROOT / "scripts" / "ingest_processor.py"
        values = self._grep_fallback_calls(_read(path))
        assert values, (
            "no duplicate_scan_debounce_seconds fallback found in ingest_processor.py"
        )
        for v in values:
            assert v == "30", (
                f"ingest_processor.py has fallback default {v}, expected 30"
            )

    def test_template_fallback_30(self):
        path = REPO_ROOT / "cps" / "templates" / "cwa_settings.html"
        values = self._grep_fallback_calls(_read(path))
        assert values, (
            "no duplicate_scan_debounce_seconds fallback found in cwa_settings.html"
        )
        for v in values:
            assert v == "30", (
                f"cwa_settings.html has fallback default {v}, expected 30"
            )


@pytest.mark.unit
class TestClampFloor:
    """Pin the runtime lower-bound clamp at 10 - even if a user types 5, they get 10."""

    def test_cwa_functions_clamp_floor_10(self):
        src = _read(REPO_ROOT / "cps" / "cwa_functions.py")
        match = re.search(
            r"delay_seconds\s*=\s*max\(\s*(\d+)\s*,\s*min\(\s*600\s*,\s*delay_seconds\s*\)\s*\)",
            src,
        )
        assert match is not None, (
            "duplicate-scan delay clamp not found in cwa_functions.py"
        )
        assert match.group(1) == "10", (
            f"clamp floor is {match.group(1)}, expected 10 - protects users from"
            f" re-introducing the regression via the admin UI"
        )

    def test_editbooks_clamp_floor_10(self):
        src = _read(REPO_ROOT / "cps" / "editbooks.py")
        match = re.search(
            r"delay_seconds\s*=\s*max\(\s*(\d+)\s*,\s*min\(\s*600\s*,\s*delay_seconds\s*\)\s*\)",
            src,
        )
        assert match is not None, "duplicate-scan delay clamp not found in editbooks.py"
        assert match.group(1) == "10"

    def test_ingest_processor_clamp_floor_10(self):
        src = _read(REPO_ROOT / "scripts" / "ingest_processor.py")
        match = re.search(
            r"delay_seconds\s*=\s*max\(\s*(\d+)\s*,\s*min\(\s*600\s*,\s*delay_seconds\s*\)\s*\)",
            src,
        )
        assert match is not None, (
            "duplicate-scan delay clamp not found in ingest_processor.py"
        )
        assert match.group(1) == "10"


@pytest.mark.unit
class TestCWAFreshInstallDefault:
    """Behavioural: fresh CWA_DB install must report debounce=30 in settings dict."""

    def test_fresh_install_debounce_is_30(self, temp_cwa_db):
        settings = temp_cwa_db.get_cwa_settings()
        assert "duplicate_scan_debounce_seconds" in settings, (
            "duplicate_scan_debounce_seconds missing from CWA settings"
        )
        assert settings["duplicate_scan_debounce_seconds"] == 30, (
            f"fresh install debounce is {settings['duplicate_scan_debounce_seconds']}, expected 30"
        )


@pytest.mark.unit
class TestLegacyValueMigration:
    """Behavioural: existing installs with the regression default 5 get bumped to 30 once."""

    def _make_legacy_cwa_db(self, tmp_path, debounce_value: int):
        """Build a cwa.db with debounce already at ``debounce_value`` AND no
        migration marker, mimicking an install that ran on the v4.0.46-era
        schema default of 5 (or any prior customized value).
        """
        db_path = tmp_path / "cwa.db"
        schema = _read(REPO_ROOT / "scripts" / "cwa_schema.sql")
        legacy_schema = re.sub(
            r"duplicate_scan_debounce_seconds\s+INTEGER\s+DEFAULT\s+\d+\s+NOT\s+NULL",
            f"duplicate_scan_debounce_seconds INTEGER DEFAULT {debounce_value} NOT NULL",
            schema,
        )
        con = sqlite3.connect(str(db_path))
        try:
            cur = con.cursor()
            for stmt in [s.strip() for s in legacy_schema.split(";") if s.strip()]:
                cur.execute(stmt)
            cur.execute("INSERT INTO cwa_settings DEFAULT VALUES;")
            con.commit()
        finally:
            con.close()

    def test_legacy_5_migrates_to_30(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        self._make_legacy_cwa_db(tmp_path, 5)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == 30, (
                f"legacy 5 should migrate to 30, got {settings['duplicate_scan_debounce_seconds']}"
            )
        finally:
            db.con.close()

        marker = tmp_path / ".cwa_migrations" / "duplicate_debounce_5_to_30_v1.applied"
        assert marker.exists(), "migration marker should be written after one-time bump"

    def test_legacy_custom_60_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        self._make_legacy_cwa_db(tmp_path, 60)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == 60, (
                f"user-customized 60 must be preserved, got"
                f" {settings['duplicate_scan_debounce_seconds']}"
            )
        finally:
            db.con.close()

    def test_legacy_custom_15_preserved(self, tmp_path, monkeypatch):
        """A user who picked 15 explicitly (anything != 5) must not be touched."""
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        self._make_legacy_cwa_db(tmp_path, 15)

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == 15
        finally:
            db.con.close()

    def test_migration_idempotent_marker_short_circuits(self, tmp_path, monkeypatch):
        """If the marker already exists, a user-set value of 5 stays at 5
        (we don't re-migrate someone who manually set it back).
        """
        monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
        self._make_legacy_cwa_db(tmp_path, 5)

        marker = tmp_path / ".cwa_migrations" / "duplicate_debounce_5_to_30_v1.applied"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("pre-existing marker", encoding="utf-8")

        from cwa_db import CWA_DB

        db = CWA_DB(verbose=False)
        try:
            settings = db.get_cwa_settings()
            assert settings["duplicate_scan_debounce_seconds"] == 5, (
                "if marker already exists, do not re-migrate - user may have"
                " manually set 5 again after the first migration ran"
            )
        finally:
            db.con.close()
