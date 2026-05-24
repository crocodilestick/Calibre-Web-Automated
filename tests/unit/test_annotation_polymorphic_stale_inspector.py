# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test for v4.0.130 teenyverse deploy failure.

`migrate_annotation_polymorphic_position` failed in production with
``sqlite3.OperationalError: duplicate column name: position_type`` even
though the live ``PRAGMA table_info(annotation)`` showed the column was
NOT present.

Root cause: SQLAlchemy's reflection cache is stale after the preceding
decouple migration's CREATE TABLE / DROP TABLE / RENAME TABLE sequence.
The polymorphic migration was using ``inspect(engine).get_columns()``
which returned the cached column set from the dropped placeholder
table (which DID have ``position_type`` because Base.metadata.create_all
emitted the current model schema).

Fix v4.0.131: query ``PRAGMA table_info`` directly inside the same
transaction that does the ADD COLUMN — guarantees the existence check
sees the same DB view as the DDL. Plus per-statement try/except
catching duplicate-column-name as belt-and-suspenders idempotency.

This test simulates the failure scenario: create an ``annotation``
table that already has some polymorphic columns (mimicking partial
prior-migration state) + run the polymorphic migration + verify it
completes idempotently without raising.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.unit


def _create_annotation_with_position_type(engine):
    """Create an annotation table that already has the position_type
    column (simulates the post-decouple-rename state on teenyverse where
    the placeholder had been create_all'd with the full model)."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE annotation (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                highlighted_text VARCHAR,
                position_type VARCHAR
            )
        """))


def _create_bare_annotation_table(engine):
    """Create the post-decouple table state WITHOUT any polymorphic columns
    — what the bare RENAME from kobo_annotation_sync produces."""
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


def test_polymorphic_migration_idempotent_when_position_type_already_present(tmp_path):
    """Simulates the exact teenyverse v4.0.130 failure: position_type
    is already on the table when the polymorphic migration runs.
    Migration must complete cleanly, not raise duplicate-column."""
    db = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        _create_annotation_with_position_type(engine)

        from cps.ub import migrate_annotation_polymorphic_position
        migrate_annotation_polymorphic_position(engine, None)

        # Verify all 4 polymorphic columns are now present.
        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text(
                "PRAGMA table_info(annotation)"
            )).fetchall()}
        assert {"position_type", "pdf_page", "pdf_quad_json", "comic_page"}.issubset(cols)
    finally:
        engine.dispose()


def test_polymorphic_migration_adds_all_four_on_bare_table(tmp_path):
    """Happy path: bare annotation table gets all 4 polymorphic columns."""
    db = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        _create_bare_annotation_table(engine)

        from cps.ub import migrate_annotation_polymorphic_position
        migrate_annotation_polymorphic_position(engine, None)

        with engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text(
                "PRAGMA table_info(annotation)"
            )).fetchall()}
        for col in ("position_type", "pdf_page", "pdf_quad_json", "comic_page"):
            assert col in cols, f"missing {col} after migration"
    finally:
        engine.dispose()


def test_polymorphic_migration_noop_on_fully_populated_table(tmp_path):
    """All 4 columns already present — migration must noop cleanly."""
    db = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE annotation (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    annotation_id VARCHAR NOT NULL,
                    book_id INTEGER NOT NULL,
                    position_type VARCHAR,
                    pdf_page INTEGER,
                    pdf_quad_json TEXT,
                    comic_page INTEGER
                )
            """))

        from cps.ub import migrate_annotation_polymorphic_position
        migrate_annotation_polymorphic_position(engine, None)  # Should not raise.
    finally:
        engine.dispose()


def test_polymorphic_migration_noop_when_no_annotation_table(tmp_path):
    """Fresh install with no annotation table at all — must return cleanly."""
    db = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db}")
    try:
        from cps.ub import migrate_annotation_polymorphic_position
        migrate_annotation_polymorphic_position(engine, None)  # Should not raise.
    finally:
        engine.dispose()
