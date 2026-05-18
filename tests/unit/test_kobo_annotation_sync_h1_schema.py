# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the H1 Phase 1 schema migration on
``kobo_annotation_sync`` (extends the Hardcover-sync table with Kobo-native
position columns + source tracking — see
``notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md`` §1.1).

Coverage:

1. The ``KoboAnnotationSync`` model declares the 12 new H1 columns.
2. ``migrate_kobo_annotation_sync_h1_columns`` adds missing columns to a
   pre-H1 (Hardcover-only) schema and backfills ``source='hardcover'`` for
   rows that came from the Hardcover sync path.
3. The migration is idempotent — running it twice on the same DB is a
   no-op and doesn't damage existing data.
4. Pre-existing Hardcover-sync rows are readable through the new model
   (the position fields default to ``None``, no constraint violations).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


# --- Helpers ---------------------------------------------------------------

# The exact schema kobo_annotation_sync had BEFORE the H1 migration ran.
# Matches the production app.db on teenyverse pre-v4.0.78 (verified via
# `sqlite3 .schema kobo_annotation_sync` on 2026-05-18).
PRE_H1_SCHEMA = """
CREATE TABLE kobo_annotation_sync (
    id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    annotation_id VARCHAR NOT NULL,
    book_id INTEGER NOT NULL,
    synced_to_hardcover BOOLEAN,
    hardcover_journal_id INTEGER,
    created_at DATETIME,
    last_synced DATETIME,
    highlighted_text VARCHAR,
    highlight_color VARCHAR,
    note_text VARCHAR,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES user (id)
)
"""

PRE_H1_INDEX_USER_ANN = (
    "CREATE INDEX ix_kobo_annotation_sync_user_annotation "
    "ON kobo_annotation_sync (user_id, annotation_id)"
)
PRE_H1_INDEX_USER_BOOK = (
    "CREATE INDEX ix_kobo_annotation_sync_user_book "
    "ON kobo_annotation_sync (user_id, book_id)"
)

H1_NEW_COLUMNS = {
    "content_id",
    "start_container_path",
    "start_container_child_index",
    "start_offset",
    "end_container_path",
    "end_container_child_index",
    "end_offset",
    "context_string",
    "chapter_progress",
    "cfi_range",
    "source",
    "hidden",
}


def _build_pre_h1_db():
    """Spin up an in-memory SQLite that matches the pre-H1 production
    schema, with a couple of rows so we can verify they survive the
    migration."""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
        conn.exec_driver_sql(PRE_H1_SCHEMA)
        conn.exec_driver_sql(PRE_H1_INDEX_USER_ANN)
        conn.exec_driver_sql(PRE_H1_INDEX_USER_BOOK)
        # Two rows the Hardcover sync path would have inserted.
        conn.exec_driver_sql(
            "INSERT INTO kobo_annotation_sync (user_id, annotation_id, book_id, "
            "synced_to_hardcover, hardcover_journal_id, highlighted_text, "
            "highlight_color, note_text) "
            "VALUES (1, 'aaa-111', 42, 1, 9001, 'animal farm passage', "
            "'yellow', 'my note')"
        )
        conn.exec_driver_sql(
            "INSERT INTO kobo_annotation_sync (user_id, annotation_id, book_id, "
            "synced_to_hardcover, hardcover_journal_id, highlighted_text) "
            "VALUES (1, 'bbb-222', 42, 0, NULL, 'another passage')"
        )
        conn.commit()
    return engine


# --- 1. Model declaration --------------------------------------------------


@pytest.mark.unit
class TestKoboAnnotationSyncModelDeclaration:
    """Pin the SQLAlchemy model — H1 columns must be declared on the
    ``KoboAnnotationSync`` class so ORM-level reads/writes see them."""

    def test_model_declares_all_h1_columns(self):
        from cps.ub import KoboAnnotationSync

        declared = {c.name for c in KoboAnnotationSync.__table__.columns}
        missing = H1_NEW_COLUMNS - declared
        assert not missing, f"H1 columns missing from model: {sorted(missing)}"

    def test_h1_columns_are_nullable(self):
        from cps.ub import KoboAnnotationSync

        cols_by_name = {c.name: c for c in KoboAnnotationSync.__table__.columns}
        # Every H1 addition must be nullable so pre-H1 rows continue to
        # satisfy NOT NULL constraints.
        for name in H1_NEW_COLUMNS:
            assert cols_by_name[name].nullable, (
                f"Column {name!r} must be nullable to preserve pre-H1 rows"
            )

    def test_position_columns_are_correct_types(self):
        """Pin column SQL types so a future refactor can't quietly change
        them (a Kobo position swapping Integer↔String would silently break
        the CFI converter)."""
        from cps.ub import KoboAnnotationSync

        cols = {c.name: c for c in KoboAnnotationSync.__table__.columns}
        # Integer-typed positions
        for name in (
            "start_container_child_index",
            "start_offset",
            "end_container_child_index",
            "end_offset",
        ):
            assert cols[name].type.__class__.__name__ in {"Integer", "INTEGER"}, (
                f"{name} must be Integer-typed, got {type(cols[name].type).__name__}"
            )
        # Float-typed progress
        assert cols["chapter_progress"].type.__class__.__name__ in {"Float", "FLOAT"}, (
            "chapter_progress must be Float-typed"
        )


# --- 2. Migration adds missing columns + backfills source ------------------


@pytest.mark.unit
class TestH1MigrationOnPreH1Database:
    """End-to-end: run the migration against a pre-H1 schema and verify
    columns appear with the correct types AND existing rows survive AND
    Hardcover rows get their ``source`` backfilled."""

    def test_migration_adds_all_h1_columns(self):
        from cps import ub

        engine = _build_pre_h1_db()
        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        # Sanity: pre-migration the new columns must NOT exist (otherwise
        # this test would be coverage theatre — passing with no fix).
        insp = inspect(engine)
        pre_cols = {c["name"] for c in insp.get_columns("kobo_annotation_sync")}
        assert H1_NEW_COLUMNS.isdisjoint(pre_cols), (
            "Test bug: pre-H1 schema already has H1 columns"
        )

        ub.migrate_kobo_annotation_sync_h1_columns(engine, session)

        post_cols = {c["name"] for c in inspect(engine).get_columns("kobo_annotation_sync")}
        missing = H1_NEW_COLUMNS - post_cols
        assert not missing, f"Migration failed to add: {sorted(missing)}"

    def test_pre_h1_rows_survive_migration(self):
        from cps import ub

        engine = _build_pre_h1_db()
        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        ub.migrate_kobo_annotation_sync_h1_columns(engine, session)

        with engine.connect() as conn:
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM kobo_annotation_sync"
            ).scalar()
            assert count == 2

            # The Hardcover-specific fields are untouched.
            row = conn.exec_driver_sql(
                "SELECT highlighted_text, highlight_color, note_text, "
                "synced_to_hardcover, hardcover_journal_id "
                "FROM kobo_annotation_sync WHERE annotation_id = 'aaa-111'"
            ).fetchone()
            assert row == ("animal farm passage", "yellow", "my note", 1, 9001)

            # The new columns are NULL on pre-H1 rows.
            row2 = conn.exec_driver_sql(
                "SELECT content_id, start_offset, cfi_range, hidden "
                "FROM kobo_annotation_sync WHERE annotation_id = 'aaa-111'"
            ).fetchone()
            # hidden has a SQL-level DEFAULT 0 so it's not strictly NULL —
            # but for ALTER TABLE ADD COLUMN ... DEFAULT, SQLite back-fills
            # the literal default into all existing rows.
            assert row2[0] is None
            assert row2[1] is None
            assert row2[2] is None
            assert row2[3] in (0, False)

    def test_source_backfilled_for_hardcover_rows(self):
        """The Hardcover sync path is the only writer to this table
        pre-H1, so its rows are the unambiguous backfill candidates. After
        the migration, rows with ``synced_to_hardcover = 1`` get
        ``source = 'hardcover'``; the un-synced row is left NULL so a
        subsequent ingestion path can claim it."""
        from cps import ub

        engine = _build_pre_h1_db()
        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        ub.migrate_kobo_annotation_sync_h1_columns(engine, session)

        with engine.connect() as conn:
            synced_source = conn.exec_driver_sql(
                "SELECT source FROM kobo_annotation_sync WHERE annotation_id = 'aaa-111'"
            ).scalar()
            unsynced_source = conn.exec_driver_sql(
                "SELECT source FROM kobo_annotation_sync WHERE annotation_id = 'bbb-222'"
            ).scalar()

        assert synced_source == "hardcover"
        assert unsynced_source is None

    def test_migration_idempotent(self):
        from cps import ub

        engine = _build_pre_h1_db()
        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        ub.migrate_kobo_annotation_sync_h1_columns(engine, session)
        # Inject a row that simulates a non-Hardcover origin AFTER the
        # first migration ran, so we can prove the second run doesn't
        # clobber it.
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "INSERT INTO kobo_annotation_sync (user_id, annotation_id, book_id, "
                "synced_to_hardcover, highlighted_text, source) "
                "VALUES (1, 'ccc-333', 42, 0, 'web-reader hl', 'webreader')"
            )
            conn.commit()

        # Re-run: must not raise, must not damage rows.
        ub.migrate_kobo_annotation_sync_h1_columns(engine, session)

        with engine.connect() as conn:
            webreader_source = conn.exec_driver_sql(
                "SELECT source FROM kobo_annotation_sync WHERE annotation_id = 'ccc-333'"
            ).scalar()
        assert webreader_source == "webreader", (
            "Second migration run must not overwrite an already-set source"
        )


# --- 3. ORM-level read+write through the new columns -----------------------


@pytest.mark.unit
class TestModelORMRoundTrip:
    """The migration is only useful if the model can actually read/write
    the new columns via SQLAlchemy. This catches schema/model drift —
    e.g. a column-name typo where DDL says ``cfi_range`` but the model
    says ``cfi_rang`` would silently fail at SELECT time."""

    def test_full_h1_record_round_trips_through_orm(self):
        from cps import ub

        engine = create_engine("sqlite:///:memory:", future=True)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
        ub.Base.metadata.create_all(engine)

        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        record = ub.KoboAnnotationSync(
            user_id=7,
            annotation_id="dead-beef-1234",
            book_id=348,  # Animal Farm in Maggie's library
            highlighted_text="All animals are equal",
            highlight_color="yellow",
            note_text="key thesis",
            content_id="b3d1b38b-74fd-43b7-a796-996e5a6a8b04!!chapter6.html",
            start_container_path="span#kobo\\.4\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.4\\.2",
            end_container_child_index=-99,
            end_offset=116,
            context_string="...All animals are equal but some animals are more equal...",
            chapter_progress=0.024,
            cfi_range="epubcfi(/6/18!/4[kobo.4.1]:0,/4[kobo.4.2]:116)",
            source="kobo",
            hidden=False,
        )
        session.add(record)
        session.commit()

        # Read back through a fresh session to defeat identity-map caching.
        session2 = Session()
        row = session2.query(ub.KoboAnnotationSync).filter_by(annotation_id="dead-beef-1234").one()
        assert row.cfi_range == "epubcfi(/6/18!/4[kobo.4.1]:0,/4[kobo.4.2]:116)"
        assert row.start_offset == 0
        assert row.end_offset == 116
        assert row.chapter_progress == 0.024
        assert row.source == "kobo"
        assert row.hidden in (0, False)


# --- 4. Hardcover sync path tags new rows with source='hardcover' ---------


@pytest.mark.unit
class TestHardcoverSyncTagsSource:
    """Source-pin: the Hardcover annotation sync path in
    ``cps/readingservices.py::process_annotation_for_sync`` must pass
    ``source='hardcover'`` when constructing a new ``KoboAnnotationSync``.

    Without this, every Hardcover-sync row gets ``source=NULL`` at insert
    time — the migration backfill only labels CURRENT rows at restart,
    not rows created between restarts. Source-pinning the constructor
    keeps the source column meaningful for the H1 import path's
    deduplication and source-of-truth logic.
    """

    def test_readingservices_constructor_passes_source(self):
        import inspect as py_inspect
        from cps import readingservices

        src = py_inspect.getsource(readingservices)
        # The constructor block must include source='hardcover'.
        assert "source='hardcover'" in src or 'source="hardcover"' in src, (
            "readingservices.py must tag new Hardcover-sync rows with "
            "source='hardcover'; otherwise they appear as un-sourced "
            "until the next migrate_Database run backfills them"
        )
