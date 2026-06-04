# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase 2 — `device_origin_id` column migration.

Adds the nullable `device_origin_id` column to `annotation` (the KOReader
bridge records the per-device row id here to dedup + suppress feedback loops).

Same PRAGMA-guarded, per-statement-try/except shape as the v4.0.131
polymorphic migration — so a stale SQLAlchemy inspector can't make the
existence check disagree with the live DDL (the bug that shipped inert in
v4.0.130). These tests pin: bare table → column added; already-present → clean
no-op (the stale-inspector trap); no table → clean return.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.unit


def _bare_annotation(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE annotation (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                highlighted_text VARCHAR
            )
        """))


def test_adds_device_origin_id_on_bare_table(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        _bare_annotation(engine)
        from cps.ub import migrate_annotation_device_origin
        migrate_annotation_device_origin(engine, None)
        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(annotation)")).fetchall()}
        assert "device_origin_id" in cols
    finally:
        engine.dispose()


def test_idempotent_when_column_already_present(tmp_path):
    """The stale-inspector trap: column already exists. Must NOT raise
    duplicate-column — the PRAGMA check sees the real live schema."""
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE annotation (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    annotation_id VARCHAR NOT NULL,
                    book_id INTEGER NOT NULL,
                    device_origin_id VARCHAR
                )
            """))
        from cps.ub import migrate_annotation_device_origin
        migrate_annotation_device_origin(engine, None)  # must not raise
        # second run is also a clean no-op
        migrate_annotation_device_origin(engine, None)
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(annotation)")).fetchall()]
        assert cols.count("device_origin_id") == 1
    finally:
        engine.dispose()


def test_noop_when_no_annotation_table(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        from cps.ub import migrate_annotation_device_origin
        migrate_annotation_device_origin(engine, None)  # must not raise
    finally:
        engine.dispose()


def test_full_metadata_create_all_has_column(tmp_path):
    """The model itself declares the column, so a fresh create_all install
    has it without the migration."""
    from cps import ub
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        ub.Base.metadata.create_all(engine)
        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(annotation)")).fetchall()}
        assert "device_origin_id" in cols
    finally:
        engine.dispose()
