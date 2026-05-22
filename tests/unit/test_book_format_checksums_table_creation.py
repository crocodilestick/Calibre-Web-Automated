# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #219 — "Missing database table on fresh installation".

Symptom: on a fresh install (and on upgrades), the ``book_format_checksums``
table is never created in ``metadata.db``. Every ingested book then logs
``ERROR ... Failed to store checksum for book N: no such table:
book_format_checksums`` because three callers in ``scripts/`` (ingest_processor,
cover_enforcer, kindle_epub_fixer) write checksums on every ingest without
checking whether KOReader sync is enabled.

Root cause has two parts:

1. **Schema is treated as a feature toggle.** ``cps/db.py`` and ``cps/ub.py``
   gate ``ensure_calibre_db_tables`` / ``ensure_app_db_tables`` on
   ``is_koreader_sync_enabled()``. The table is a schema invariant, not a
   feature toggle — it must always exist so writers (and the user's later
   feature-flip to enable sync) work without ordering hazards.

2. **Three sibling writers are unguarded.** ``helper.py`` was fixed by PR #94
   (v4.0.28) to gate its checksum write on ``is_koreader_sync_enabled()``, but
   the same pattern was never applied to ``ingest_processor.py``,
   ``cover_enforcer.py``, or ``kindle_epub_fixer.py``. Those three still fire
   unconditionally on every ingest, wasting MD5 CPU when sync is off.

The fix applies both parts:

- Drop the ``is_koreader_sync_enabled()`` gate from the ``ensure_*`` callers
  so the table always exists.
- Add the ``is_koreader_sync_enabled()`` gate to the three sibling writers so
  they match the v4.0.28 pattern from PR #94.

These tests pin both halves of the fix so a future refactor can't accidentally
re-introduce the original gate-mismatch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Part 1 — schema-invariant fix (gate removed from ensure_* callers)
# ---------------------------------------------------------------------------


class TestCpsDbAlwaysEnsuresCalibreTables:
    """``cps/db.py`` must call ``ensure_calibre_db_tables`` unconditionally on
    startup (modulo the safety checks for db_writable + NETWORK_SHARE_MODE)."""

    DB_FILE = REPO_ROOT / "cps" / "db.py"

    def _read(self) -> str:
        return self.DB_FILE.read_text(encoding="utf-8")

    def test_ensure_calibre_db_tables_call_is_present(self):
        src = self._read()
        assert "ensure_calibre_db_tables(" in src

    def test_ensure_calibre_db_tables_is_not_gated_on_koreader_setting(self):
        # The gate is the bug. Removing it is the fix.
        src = self._read()
        call_idx = src.find("ensure_calibre_db_tables(conn)")
        assert call_idx != -1, (
            "Expected 'ensure_calibre_db_tables(conn)' call in cps/db.py"
        )

        # Look at the ~400-char window before the call. The original gate had
        # 'is_koreader_sync_enabled()' immediately preceding the call inside
        # the if-condition. The fix removes that.
        window_start = max(0, call_idx - 400)
        window = src[window_start:call_idx]
        assert "is_koreader_sync_enabled" not in window, (
            "cps/db.py must not gate ensure_calibre_db_tables on "
            "is_koreader_sync_enabled() — the table is a schema invariant. "
            "See fork issue #219."
        )


class TestCpsUbAlwaysEnsuresAppTables:
    """``cps/ub.py`` must call ``ensure_app_db_tables`` unconditionally at the
    end of ``migrate_Database``. Same reasoning: schema invariant."""

    UB_FILE = REPO_ROOT / "cps" / "ub.py"

    def _read(self) -> str:
        return self.UB_FILE.read_text(encoding="utf-8")

    def test_ensure_app_db_tables_call_is_present(self):
        src = self._read()
        assert "ensure_app_db_tables(" in src

    def test_ensure_app_db_tables_is_not_gated_on_koreader_setting(self):
        src = self._read()
        call_idx = src.find("ensure_app_db_tables(engine.raw_connection())")
        assert call_idx != -1, (
            "Expected 'ensure_app_db_tables(engine.raw_connection())' call "
            "in cps/ub.py"
        )
        window_start = max(0, call_idx - 400)
        window = src[window_start:call_idx]
        assert "is_koreader_sync_enabled" not in window, (
            "cps/ub.py must not gate ensure_app_db_tables on "
            "is_koreader_sync_enabled() — the table is a schema invariant. "
            "See fork issue #219."
        )


# ---------------------------------------------------------------------------
# Part 2 — match PR #94 (v4.0.28) gating pattern at sibling write paths
# ---------------------------------------------------------------------------


class _ScriptWriteGuardCase:
    """Source-pin shared assertions for the three unguarded write paths."""

    SCRIPT_PATH: Path = None  # type: ignore[assignment]
    CALL_NEEDLE: str = ""

    def _read(self) -> str:
        return self.SCRIPT_PATH.read_text(encoding="utf-8")

    def test_call_site_is_present(self):
        src = self._read()
        assert self.CALL_NEEDLE in src, (
            f"Expected {self.CALL_NEEDLE!r} in {self.SCRIPT_PATH.name}; "
            "the test target moved or got renamed."
        )

    def test_call_site_is_gated_on_is_koreader_sync_enabled(self):
        # Match the v4.0.28 / PR #94 pattern: the call must be wrapped in
        # `if is_koreader_sync_enabled():` so disabled-sync instances skip
        # the MD5 work entirely (and avoid noisy "no such table" errors on
        # any future code path that hasn't yet been migrated). Window is
        # generous (2500 chars) because the gate may live near the top of
        # the enclosing function while the call is several blocks later.
        src = self._read()
        call_idx = src.find(self.CALL_NEEDLE)
        assert call_idx != -1
        window_start = max(0, call_idx - 2500)
        window = src[window_start:call_idx]
        assert "is_koreader_sync_enabled" in window, (
            f"{self.SCRIPT_PATH.name}: {self.CALL_NEEDLE!r} must be gated on "
            "is_koreader_sync_enabled() — see fork issue #219 + PR #94."
        )


class TestIngestProcessorGatesGenerateBookChecksums(_ScriptWriteGuardCase):
    SCRIPT_PATH = REPO_ROOT / "scripts" / "ingest_processor.py"
    CALL_NEEDLE = "self.generate_book_checksums("


class TestCoverEnforcerGatesChecksumRecalc(_ScriptWriteGuardCase):
    SCRIPT_PATH = REPO_ROOT / "scripts" / "cover_enforcer.py"
    # The call site we care about is the body of
    # `_recalculate_checksum_after_modification`, which imports + calls
    # `store_checksum`. Gating must happen either at the body's top
    # (preferred) or at every caller. Source-pin by checking that
    # `store_checksum(` is preceded by an `is_koreader_sync_enabled()`
    # reference in the same file.
    CALL_NEEDLE = "store_checksum("


class TestKindleEpubFixerGatesChecksumRecalc(_ScriptWriteGuardCase):
    SCRIPT_PATH = REPO_ROOT / "scripts" / "kindle_epub_fixer.py"
    CALL_NEEDLE = "store_checksum("


# ---------------------------------------------------------------------------
# Part 3 — behavioral test: real SQLite, real ensure_* call
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreChecksumWorksAfterUnconditionalEnsure:
    """End-to-end micro-test: a fresh DB + unconditional ensure_* call +
    store_checksum should write a row, not crash with 'no such table'.
    This is the user-visible symptom from #219, rendered as a test."""

    def test_store_checksum_after_ensure_calibre_db_tables(self, tmp_path):
        # Stand up a metadata.db-shaped sqlite (just the `books` table is
        # needed for the foreign key).
        #
        # IMPORTANT: explicit conn.close() in a try/finally. Without it,
        # the sqlite3 connection survives past the test function and gets
        # cleaned up later — and that cleanup can deadlock on the C-level
        # sqlite mutex during pytest-xdist worker IPC handoff. The hang
        # was traced to this test in v4.0.121 CI runs (sometimes passes
        # immediately, sometimes hangs ~9 minutes until the step-level
        # kill fires). See notes/xdist-worker-ipc-hang-followup-2026-05-21.md.
        db_path = tmp_path / "metadata.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "title TEXT)"
            )
            conn.execute("INSERT INTO books (id, title) VALUES (42, 'Test Book')")
            conn.commit()

            # Run the schema setup (this is what cps/db.py calls on startup).
            from cps.progress_syncing.models import ensure_calibre_db_tables
            ensure_calibre_db_tables(conn)

            # Now exercise store_checksum directly against the same DB. This
            # mimics the ingest-processor / cover-enforcer / kindle-epub-fixer
            # path that fails in #219.
            from cps.progress_syncing.checksums.manager import store_checksum
            ok = store_checksum(
                book_id=42,
                book_format="EPUB",
                checksum="deadbeef" * 4,
                version="koreader",
                db_connection=conn,
            )
            assert ok is True, (
                "store_checksum must succeed after ensure_calibre_db_tables — "
                "this is the user-visible symptom from #219."
            )

            row = conn.execute(
                "SELECT book, format, checksum FROM book_format_checksums "
                "WHERE book = 42"
            ).fetchone()
            assert row is not None
            assert row[0] == 42
        finally:
            conn.close()
        assert row[1].upper() == "EPUB"
        assert row[2] == "deadbeef" * 4
