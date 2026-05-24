# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migration perf test on a realistic household-sized populated DB.

5000 rows of mixed-state annotations (~50/50 synced_to_hardcover) with
realistic-length text fields. Verifies:
  - migration completes under a sane time budget
  - SHA-256 preservation of every preserved column
  - row counts match expected post-migration distribution

Marked @pytest.mark.slow so it doesn't run on every CI invocation; runs
on the integration job.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.slow


PRE_MIGRATION_DDL = """
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
"""

PRESERVED = [
    "id", "user_id", "annotation_id", "book_id",
    "highlighted_text", "highlight_color", "note_text",
    "content_id", "start_container_path", "start_container_child_index",
    "start_offset", "end_container_path", "end_container_child_index",
    "end_offset", "context_string", "chapter_progress", "cfi_range",
    "hidden",
]


def _fingerprint(conn, table):
    cols_csv = ", ".join(PRESERVED)
    rows = conn.execute(text(f"SELECT {cols_csv} FROM {table} ORDER BY id")).fetchall()
    payload = [{c: row[i] for i, c in enumerate(PRESERVED)} for row in rows]
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _build_populated_db(tmp_path, n_rows=5000):
    """Build a SQLite file with n_rows of varied data."""
    db_path = str(tmp_path / "app.db")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(PRE_MIGRATION_DDL))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_annotation "
            "ON kobo_annotation_sync (user_id, annotation_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_book "
            "ON kobo_annotation_sync (user_id, book_id)"
        ))
        base_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Use a more realistic text length distribution.
        lorem = ("There is no such thing as a moral or an immoral book. Books "
                 "are well written, or badly written. That is all. "
                 "Beauty, real beauty, ends where an intellectual expression "
                 "begins. I can resist everything except temptation.")
        for i in range(n_rows):
            conn.execute(text("""
                INSERT INTO kobo_annotation_sync (
                    user_id, annotation_id, book_id, synced_to_hardcover,
                    hardcover_journal_id, created_at, last_synced,
                    highlighted_text, highlight_color, note_text,
                    content_id, start_container_path, start_container_child_index,
                    start_offset, end_container_path, end_container_child_index,
                    end_offset, context_string, chapter_progress, cfi_range,
                    source, hidden
                ) VALUES (
                    :user_id, :annotation_id, :book_id, :synced_to_hardcover,
                    :hardcover_journal_id, :created_at, :last_synced,
                    :highlighted_text, :highlight_color, :note_text,
                    :content_id, :start_container_path, :start_container_child_index,
                    :start_offset, :end_container_path, :end_container_child_index,
                    :end_offset, :context_string, :chapter_progress, :cfi_range,
                    :source, :hidden
                )
            """), {
                "user_id": (i % 10) + 1,
                "annotation_id": f"kobo-uuid-{i:06d}",
                "book_id": (i % 100) + 1,
                "synced_to_hardcover": 1 if i % 2 == 0 else 0,
                "hardcover_journal_id": 100000 + i if i % 2 == 0 else None,
                "created_at": (base_dt + timedelta(minutes=i)).isoformat(),
                "last_synced": (base_dt + timedelta(minutes=i + 5)).isoformat(),
                "highlighted_text": lorem[i % len(lorem):i % len(lorem) + 80],
                "highlight_color": ["yellow", "red", "green", "blue"][i % 4],
                "note_text": f"note number {i}" if i % 3 == 0 else None,
                "content_id": f"!!chapter-{i % 32}.html",
                "start_container_path": f"/span[@id='kobo.{i}.start']/text()",
                "start_container_child_index": i % 5,
                "start_offset": i * 13 % 1000,
                "end_container_path": f"/span[@id='kobo.{i}.end']/text()",
                "end_container_child_index": (i % 5) + 1,
                "end_offset": i * 13 % 1000 + 80,
                "context_string": f"...context around highlight {i} with some more text...",
                "chapter_progress": (i % 100) / 100.0,
                "cfi_range": f"epubcfi(/6/{i % 20}!/4/2/1:{i})" if i % 3 == 0 else None,
                "source": (
                    "hardcover" if (i % 2 == 0 and i % 4 == 0)
                    else "kobo" if i % 2 == 0
                    else None
                ),
                "hidden": 1 if i % 50 == 0 else 0,
            })
    return engine


def test_large_db_migration_timing_and_preservation(tmp_path):
    """5000-row migration completes in <5s and preserves every preserved column."""
    from cps.ub import migrate_annotation_decouple_source_target, migrate_annotation_polymorphic_position
    engine = _build_populated_db(tmp_path, n_rows=5000)
    with engine.connect() as conn:
        pre_fp = _fingerprint(conn, "kobo_annotation_sync")
        pre_count = conn.execute(text("SELECT COUNT(*) FROM kobo_annotation_sync")).scalar()
        pre_synced = conn.execute(text(
            "SELECT COUNT(*) FROM kobo_annotation_sync WHERE synced_to_hardcover=1"
        )).scalar()
        pre_hardcover_src = conn.execute(text(
            "SELECT COUNT(*) FROM kobo_annotation_sync WHERE source='hardcover'"
        )).scalar()
    assert pre_count == 5000
    assert pre_synced == 2500  # half synced
    assert pre_hardcover_src == 1250  # quarter

    t0 = time.monotonic()
    migrate_annotation_decouple_source_target(engine, None)
    decouple_elapsed = time.monotonic() - t0

    t1 = time.monotonic()
    migrate_annotation_polymorphic_position(engine, None)
    poly_elapsed = time.monotonic() - t1

    print(
        f"\n  migrate_annotation_decouple_source_target: {decouple_elapsed * 1000:.0f}ms"
        f"\n  migrate_annotation_polymorphic_position:    {poly_elapsed * 1000:.0f}ms"
        f"\n  total migration time on 5000-row DB:        {(decouple_elapsed + poly_elapsed) * 1000:.0f}ms",
    )

    # 5 seconds is generous — typical SQLite RENAME + DROP COLUMN is sub-second.
    assert decouple_elapsed < 5.0, f"decouple migration too slow: {decouple_elapsed:.2f}s"
    assert poly_elapsed < 2.0, f"polymorphic migration too slow: {poly_elapsed:.2f}s"

    # Preservation
    with engine.connect() as conn:
        post_fp = _fingerprint(conn, "annotation")
        post_count = conn.execute(text("SELECT COUNT(*) FROM annotation")).scalar()
        ast_count = conn.execute(text(
            "SELECT COUNT(*) FROM annotation_sync_target WHERE target='hardcover'"
        )).scalar()
        bad_source = conn.execute(text(
            "SELECT COUNT(*) FROM annotation WHERE source='hardcover'"
        )).scalar()

    assert pre_fp == post_fp, "preserved columns changed across large-DB migration"
    assert post_count == 5000
    assert ast_count == 2500  # every previously-synced row migrated to sync_target
    assert bad_source == 0   # source='hardcover' fully normalized to 'kobo'
