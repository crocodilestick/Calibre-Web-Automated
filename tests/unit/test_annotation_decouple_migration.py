# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for migrate_annotation_decouple_source_target — the 8-step
transactional migration that splits per-target sync state out of the
annotation table.

Each step is tested in isolation against synthetic pre-migration DBs.
Full-flow tests verify the orchestrator + idempotency + rollback-on-fail.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def pre_decouple_engine():
    """SQLite engine with the H1 schema (post-H1, pre-decouple)."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE kobo_annotation_sync (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                synced_to_hardcover BOOLEAN DEFAULT 0,
                hardcover_journal_id INTEGER,
                created_at DATETIME,
                last_synced DATETIME,
                highlighted_text VARCHAR,
                highlight_color VARCHAR,
                note_text VARCHAR,
                content_id VARCHAR,
                start_container_path TEXT,
                start_container_child_index INTEGER,
                start_offset INTEGER,
                end_container_path TEXT,
                end_container_child_index INTEGER,
                end_offset INTEGER,
                context_string TEXT,
                chapter_progress REAL,
                cfi_range VARCHAR,
                source VARCHAR,
                hidden BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_annotation "
            "ON kobo_annotation_sync (user_id, annotation_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_book "
            "ON kobo_annotation_sync (user_id, book_id)"
        ))
    return engine


def _seed_row(conn, **overrides):
    """Insert a kobo_annotation_sync row with sensible defaults."""
    defaults = {
        "user_id": 1, "annotation_id": "uuid-001", "book_id": 1,
        "synced_to_hardcover": 0, "hardcover_journal_id": None,
        "created_at": "2026-05-18 10:00:00", "last_synced": "2026-05-18 10:00:00",
        "highlighted_text": "text", "source": None, "hidden": 0,
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(f":{k}" for k in defaults.keys())
    conn.execute(
        text(f"INSERT INTO kobo_annotation_sync ({cols}) VALUES ({placeholders})"),
        defaults,
    )


# ---------------------------------------------------------------------------
# Step 1
# ---------------------------------------------------------------------------

def test_step1_create_target_table(pre_decouple_engine):
    from cps.ub import _migrate_step1_create_target_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
    inspector = sa_inspect(pre_decouple_engine)
    assert "annotation_sync_target" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("annotation_sync_target")}
    assert {"id", "annotation_id", "target", "target_record_id", "status",
            "error_message", "last_attempt", "last_synced",
            "created_at", "updated_at"}.issubset(cols)
    indexes = inspector.get_indexes("annotation_sync_target")
    uniques = inspector.get_unique_constraints("annotation_sync_target")
    has_unique = (
        any(i.get("unique") and set(i["column_names"]) == {"annotation_id", "target"}
            for i in indexes)
        or any(set(uc["column_names"]) == {"annotation_id", "target"}
               for uc in uniques)
    )
    assert has_unique, (
        f"missing uniqueness on (annotation_id, target): "
        f"indexes={indexes} uniques={uniques}"
    )


def test_step1_idempotent(pre_decouple_engine):
    from cps.ub import _migrate_step1_create_target_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
    inspector = sa_inspect(pre_decouple_engine)
    assert "annotation_sync_target" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# Step 2
# ---------------------------------------------------------------------------

def test_step2_backfills_only_synced_rows(pre_decouple_engine):
    from cps.ub import (
        _migrate_step1_create_target_table,
        _migrate_step2_backfill_sync_state,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, annotation_id="synced-1", synced_to_hardcover=1, hardcover_journal_id=100)
        _seed_row(conn, annotation_id="synced-2", synced_to_hardcover=1, hardcover_journal_id=200)
        _seed_row(conn, annotation_id="not-synced", synced_to_hardcover=0)
        inserted = _migrate_step2_backfill_sync_state(conn)
    assert inserted == 2
    with pre_decouple_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT target, target_record_id, status "
            "FROM annotation_sync_target ORDER BY id"
        )).fetchall()
    assert len(rows) == 2
    assert tuple(rows[0]) == ("hardcover", "100", "synced")
    assert tuple(rows[1]) == ("hardcover", "200", "synced")


def test_step2_idempotent(pre_decouple_engine):
    from cps.ub import (
        _migrate_step1_create_target_table,
        _migrate_step2_backfill_sync_state,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42)
        first = _migrate_step2_backfill_sync_state(conn)
        second = _migrate_step2_backfill_sync_state(conn)
    assert first == 1
    assert second == 0
    with pre_decouple_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Step 3
# ---------------------------------------------------------------------------

def test_step3_fixes_source_bug(pre_decouple_engine):
    from cps.ub import _migrate_step3_fix_source_values
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="bug-1", source="hardcover")
        _seed_row(conn, annotation_id="bug-2", source="hardcover")
        _seed_row(conn, annotation_id="clean", source="kobo")
        updated = _migrate_step3_fix_source_values(conn)
    assert updated == 2
    with pre_decouple_engine.connect() as conn:
        sources = {r[0] for r in conn.execute(text(
            "SELECT source FROM kobo_annotation_sync"
        )).fetchall()}
    assert sources == {"kobo"}


def test_step3_idempotent(pre_decouple_engine):
    from cps.ub import _migrate_step3_fix_source_values
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, source="hardcover")
        first = _migrate_step3_fix_source_values(conn)
        second = _migrate_step3_fix_source_values(conn)
    assert first == 1
    assert second == 0


# ---------------------------------------------------------------------------
# Step 4
# ---------------------------------------------------------------------------

def test_step4_sanity_passes_when_counts_match(pre_decouple_engine):
    from cps.ub import (
        _migrate_step1_create_target_table,
        _migrate_step2_backfill_sync_state,
        _migrate_step4_sanity_check,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=10)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=20)
        _migrate_step2_backfill_sync_state(conn)
        _migrate_step4_sanity_check(conn)  # no raise


def test_step4_raises_on_mismatch(pre_decouple_engine):
    from cps.ub import (
        _migrate_step1_create_target_table,
        _migrate_step4_sanity_check,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=10)
        # Skip step 2 → count mismatch
        with pytest.raises(RuntimeError, match="count mismatch"):
            _migrate_step4_sanity_check(conn)


# ---------------------------------------------------------------------------
# Steps 5 + 6
# ---------------------------------------------------------------------------

def test_step5_renames_table(pre_decouple_engine):
    from cps.ub import _migrate_step5_rename_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    assert "annotation" in tables
    assert "kobo_annotation_sync" not in tables


def test_step6_renames_indexes(pre_decouple_engine):
    from cps.ub import _migrate_step5_rename_table, _migrate_step6_rename_indexes
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step6_rename_indexes(conn)
    inspector = sa_inspect(pre_decouple_engine)
    idx_names = {i["name"] for i in inspector.get_indexes("annotation")}
    assert "ix_annotation_user_annotation" in idx_names
    assert "ix_annotation_user_book" in idx_names
    assert "ix_kobo_annotation_sync_user_annotation" not in idx_names
    assert "ix_kobo_annotation_sync_user_book" not in idx_names


# ---------------------------------------------------------------------------
# Step 7
# ---------------------------------------------------------------------------

def test_step7_drops_hardcover_columns(pre_decouple_engine):
    from cps.ub import (
        _migrate_step5_rename_table,
        _migrate_step7_drop_old_columns,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step7_drop_old_columns(conn)
    inspector = sa_inspect(pre_decouple_engine)
    cols = {c["name"] for c in inspector.get_columns("annotation")}
    assert "synced_to_hardcover" not in cols
    assert "hardcover_journal_id" not in cols
    # Content columns survive
    assert "highlighted_text" in cols
    assert "source" in cols
    assert "cfi_range" in cols


def test_step7_idempotent_when_columns_absent(pre_decouple_engine):
    from cps.ub import (
        _migrate_step5_rename_table,
        _migrate_step7_drop_old_columns,
    )
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step7_drop_old_columns(conn)
        _migrate_step7_drop_old_columns(conn)  # second run: no-op


# ---------------------------------------------------------------------------
# Full-flow orchestrator
# ---------------------------------------------------------------------------

def test_full_migration_on_h1_fixture(pre_decouple_engine):
    """End-to-end migration on populated H1 fixture lands in final state."""
    from cps.ub import migrate_annotation_decouple_source_target
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="a1", synced_to_hardcover=1, hardcover_journal_id=11, source="hardcover")
        _seed_row(conn, annotation_id="a2", synced_to_hardcover=1, hardcover_journal_id=22, source="hardcover")
        _seed_row(conn, annotation_id="a3", synced_to_hardcover=0, source="kobo")
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    assert "annotation" in tables
    assert "annotation_sync_target" in tables
    assert "kobo_annotation_sync" not in tables
    cols = {c["name"] for c in inspector.get_columns("annotation")}
    assert "synced_to_hardcover" not in cols
    assert "hardcover_journal_id" not in cols
    with pre_decouple_engine.connect() as conn:
        ast_rows = conn.execute(text(
            "SELECT target_record_id, status FROM annotation_sync_target ORDER BY id"
        )).fetchall()
        ann_rows = conn.execute(text(
            "SELECT annotation_id, source FROM annotation ORDER BY id"
        )).fetchall()
    assert len(ast_rows) == 2
    assert all(r.status == "synced" for r in ast_rows)
    assert tuple(ann_rows[0]) == ("a1", "kobo")  # source corrected
    assert tuple(ann_rows[1]) == ("a2", "kobo")  # source corrected
    assert tuple(ann_rows[2]) == ("a3", "kobo")


def test_full_migration_idempotent(pre_decouple_engine):
    """Running the orchestrator twice is a no-op the second time."""
    from cps.ub import migrate_annotation_decouple_source_target
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42, source="hardcover")
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    with pre_decouple_engine.connect() as conn:
        ann_count = conn.execute(text("SELECT COUNT(*) FROM annotation")).scalar()
        ast_count = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert ann_count == 1
    assert ast_count == 1


def test_full_migration_fresh_install_noop():
    """Migration on a DB with no kobo_annotation_sync table is a clean no-op."""
    from cps.ub import migrate_annotation_decouple_source_target
    engine = create_engine("sqlite:///:memory:")
    migrate_annotation_decouple_source_target(engine, None)
    inspector = sa_inspect(engine)
    assert "annotation" not in inspector.get_table_names()


def test_full_migration_handles_orm_created_placeholder(pre_decouple_engine):
    """add_missing_tables() runs before the migration during migrate_Database
    and creates an empty 'annotation' table from ORM. Migration must drop
    the empty placeholder before RENAME-ing kobo_annotation_sync onto it.
    """
    from cps.ub import migrate_annotation_decouple_source_target

    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="a1", synced_to_hardcover=1, hardcover_journal_id=11)
        # Simulate add_missing_tables having just created an empty annotation.
        conn.execute(text("""
            CREATE TABLE annotation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                source VARCHAR
            )
        """))
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    assert "annotation" in tables
    assert "kobo_annotation_sync" not in tables
    with pre_decouple_engine.connect() as conn:
        # The user's row from kobo_annotation_sync survived under the new name.
        row = conn.execute(text("SELECT annotation_id FROM annotation")).fetchone()
    assert row.annotation_id == "a1"


def test_full_migration_refuses_when_placeholder_has_rows(pre_decouple_engine):
    """If both tables exist AND placeholder annotation has rows, refuse +
    raise rather than silently destroying data. Operator must investigate."""
    from cps.ub import migrate_annotation_decouple_source_target

    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="legacy", synced_to_hardcover=1, hardcover_journal_id=11)
        conn.execute(text("""
            CREATE TABLE annotation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, annotation_id VARCHAR, book_id INTEGER,
                source VARCHAR
            )
        """))
        conn.execute(text(
            "INSERT INTO annotation (user_id, annotation_id, book_id, source) "
            "VALUES (1, 'rogue', 1, 'kobo')"
        ))
    with pytest.raises(RuntimeError, match="manual investigation required"):
        migrate_annotation_decouple_source_target(pre_decouple_engine, None)


def test_full_migration_rollback_on_failure(pre_decouple_engine, monkeypatch):
    """Inject a failure between step 6 and 7 — DB rolls back to pre-migration."""
    from cps import ub
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42, source="hardcover")
    real_step6 = ub._migrate_step6_rename_indexes
    def boom(conn):
        real_step6(conn)
        raise RuntimeError("simulated failure between step 6 and 7")
    monkeypatch.setattr(ub, "_migrate_step6_rename_indexes", boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        ub.migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    # Transaction rolled back: original table name still present, no annotation
    assert "kobo_annotation_sync" in tables
    assert "annotation" not in tables
