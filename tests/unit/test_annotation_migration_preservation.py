# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Belt-and-braces test: SHA-256 fingerprint of every preserved column
across a populated 100-row pre-migration DB must match exactly post-
migration. Catches subtle column-reorder + value-drop bugs that the
unit tests would miss.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text


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

# Columns preserved across the migration. excludes synced_to_hardcover +
# hardcover_journal_id (intentionally moved to annotation_sync_target) +
# `source` (intentionally normalized 'hardcover' → 'kobo').
PRESERVED_COLUMNS = [
    "id", "user_id", "annotation_id", "book_id",
    "highlighted_text", "highlight_color", "note_text",
    "content_id", "start_container_path", "start_container_child_index",
    "start_offset", "end_container_path", "end_container_child_index",
    "end_offset", "context_string", "chapter_progress", "cfi_range",
    "hidden",
]


def _fingerprint(conn, table_name):
    """SHA-256 of canonical JSON of every row's preserved columns."""
    cols_csv = ", ".join(PRESERVED_COLUMNS)
    rows = conn.execute(text(
        f"SELECT {cols_csv} FROM {table_name} ORDER BY id"
    )).fetchall()
    payload = [
        {col: row[i] for i, col in enumerate(PRESERVED_COLUMNS)}
        for row in rows
    ]
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@pytest.fixture
def populated_pre_decouple_engine():
    """100 varied rows — half synced_to_hardcover, mixed sources + colors."""
    engine = create_engine("sqlite:///:memory:")
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
        base_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)
        for i in range(100):
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
                "user_id": (i % 5) + 1,
                "annotation_id": f"kobo-uuid-{i:04d}",
                "book_id": (i % 10) + 1,
                "synced_to_hardcover": 1 if i % 2 == 0 else 0,
                "hardcover_journal_id": 1000 + i if i % 2 == 0 else None,
                "created_at": (base_dt + timedelta(minutes=i)).isoformat(),
                "last_synced": (base_dt + timedelta(minutes=i + 5)).isoformat(),
                "highlighted_text": f"highlight text {i}",
                "highlight_color": ["yellow", "red", "green", "blue"][i % 4],
                "note_text": f"note {i}" if i % 3 == 0 else None,
                "content_id": f"!!chapter-{i % 7}.html",
                "start_container_path": f"/span[@id='kobo.{i}.1']/text()",
                "start_container_child_index": i % 3,
                "start_offset": i * 10,
                "end_container_path": f"/span[@id='kobo.{i}.5']/text()",
                "end_container_child_index": (i % 3) + 1,
                "end_offset": i * 10 + 50,
                "context_string": f"...context around highlight {i}...",
                "chapter_progress": (i % 100) / 100.0,
                "cfi_range": f"epubcfi(/6/{i % 20}!/4/2/1:0)" if i % 3 == 0 else None,
                "source": (
                    "hardcover" if (i % 2 == 0 and i % 4 == 0)
                    else "kobo" if i % 2 == 0
                    else None
                ),
                "hidden": 0,
            })
    return engine


def test_preservation_sha256_match(populated_pre_decouple_engine):
    """Pre-migration fingerprint matches post-migration."""
    from cps.ub import migrate_annotation_decouple_source_target
    with populated_pre_decouple_engine.connect() as conn:
        pre_fp = _fingerprint(conn, "kobo_annotation_sync")
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        post_fp = _fingerprint(conn, "annotation")
    assert pre_fp == post_fp, "preserved columns changed across migration"


def test_preservation_row_count(populated_pre_decouple_engine):
    from cps.ub import migrate_annotation_decouple_source_target
    with populated_pre_decouple_engine.connect() as conn:
        pre = conn.execute(text("SELECT COUNT(*) FROM kobo_annotation_sync")).scalar()
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        post = conn.execute(text("SELECT COUNT(*) FROM annotation")).scalar()
        ast = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert pre == 100
    assert post == 100  # all rows preserved
    assert ast == 50    # half were synced_to_hardcover


def test_preservation_source_fully_normalized(populated_pre_decouple_engine):
    """No 'hardcover' values remain in source column after migration."""
    from cps.ub import migrate_annotation_decouple_source_target
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        bad = conn.execute(text(
            "SELECT COUNT(*) FROM annotation WHERE source = 'hardcover'"
        )).scalar()
    assert bad == 0
