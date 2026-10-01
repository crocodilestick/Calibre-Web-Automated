# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for connection-level SQLite pragmas.

These cover the gap that let `ON DELETE CASCADE` silently do nothing in
production: the cascade tests in `test_progress_syncing_models.py` issue
`PRAGMA foreign_keys = ON` by hand on their own connection, so they pass whether
or not the application ever enables it. The tests here drive the engine the way
`cps.db` / `cps.ub` build it instead, so a regression is caught rather than
masked.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from cps.db_pragmas import enable_sqlite_foreign_keys


# Mirrors the parts of metadata.db this is about: Calibre's `books_pages_link`
# (filled by a trigger on every insert) and CWA's `book_format_checksums`, both
# declaring ON DELETE CASCADE against `books`.
CALIBRE_SUBSET_SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE books_pages_link (
    book INTEGER PRIMARY KEY,
    pages INTEGER DEFAULT 0 NOT NULL,
    FOREIGN KEY (book) REFERENCES books(id) ON DELETE CASCADE
);
CREATE TABLE book_format_checksums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book INTEGER NOT NULL,
    format TEXT NOT NULL COLLATE NOCASE,
    checksum TEXT NOT NULL,
    FOREIGN KEY (book) REFERENCES books(id) ON DELETE CASCADE
);
CREATE TRIGGER books_pages_link_create_trigger AFTER INSERT ON books FOR EACH ROW
BEGIN
    INSERT INTO books_pages_link(book) VALUES(NEW.id);
END;
"""


def _make_library(tmp_path):
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(CALIBRE_SUBSET_SCHEMA)
    conn.commit()
    conn.close()
    return db


def _attached_engine(db_path, with_pragma):
    """Build an engine the way `CalibreDB.setup_db` does: an in-memory database
    over a StaticPool, with the real library ATTACHed onto the same connection."""
    engine = create_engine(
        'sqlite://',
        echo=False,
        isolation_level="SERIALIZABLE",
        connect_args={'check_same_thread': False, 'timeout': 30},
        poolclass=StaticPool,
    )
    if with_pragma:
        enable_sqlite_foreign_keys(engine)
    with engine.begin() as conn:
        conn.execute(text("attach database '{}' as calibre;".format(db_path)))
    return engine


def _add_book(engine, book_id):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO calibre.books (id, title) VALUES (:i, 'Pride and Prejudice')"
        ), {"i": book_id})
        conn.execute(text(
            "INSERT INTO calibre.book_format_checksums (book, format, checksum) "
            "VALUES (:i, 'EPUB', 'deadbeef')"
        ), {"i": book_id})


def _orphan_counts(engine, book_id):
    with engine.begin() as conn:
        pages = conn.execute(text(
            "SELECT COUNT(*) FROM calibre.books_pages_link WHERE book = :i"
        ), {"i": book_id}).scalar()
        sums = conn.execute(text(
            "SELECT COUNT(*) FROM calibre.book_format_checksums WHERE book = :i"
        ), {"i": book_id}).scalar()
        violations = list(conn.execute(text("PRAGMA calibre.foreign_key_check")))
    return pages, sums, violations


@pytest.mark.unit
class TestEnableSqliteForeignKeys:
    """`enable_sqlite_foreign_keys` must make declared cascades actually fire."""

    def test_pragma_is_off_without_the_helper(self, tmp_path):
        """Guards the premise: SQLite leaves foreign_keys OFF by default."""
        engine = _attached_engine(_make_library(tmp_path), with_pragma=False)
        with engine.begin() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 0
        engine.dispose()

    def test_pragma_is_on_with_the_helper(self, tmp_path):
        engine = _attached_engine(_make_library(tmp_path), with_pragma=True)
        with engine.begin() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        engine.dispose()

    def test_deleting_a_book_orphans_children_without_the_helper(self, tmp_path):
        """The bug this module exists to prevent, pinned so it stays fixed."""
        engine = _attached_engine(_make_library(tmp_path), with_pragma=False)
        _add_book(engine, 18)

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM calibre.books WHERE id = 18"))

        pages, sums, violations = _orphan_counts(engine, 18)
        engine.dispose()

        assert pages == 1, "expected books_pages_link to be orphaned without the pragma"
        assert sums == 1, "expected book_format_checksums to be orphaned without the pragma"
        assert len(violations) == 2

    def test_deleting_a_book_cascades_with_the_helper(self, tmp_path):
        engine = _attached_engine(_make_library(tmp_path), with_pragma=True)
        _add_book(engine, 18)

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM calibre.books WHERE id = 18"))

        pages, sums, violations = _orphan_counts(engine, 18)
        engine.dispose()

        assert pages == 0, "books_pages_link row should have been cascaded away"
        assert sums == 0, "book_format_checksums row should have been cascaded away"
        assert violations == []

    def test_pragma_survives_reconnect(self, tmp_path):
        """The listener is per-connection, so it has to fire on new ones too."""
        db = _make_library(tmp_path)
        engine = create_engine('sqlite:///{0}'.format(db), echo=False,
                               connect_args={'timeout': 30})
        enable_sqlite_foreign_keys(engine)
        for _ in range(3):
            with engine.connect() as conn:
                assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            engine.dispose()  # force a fresh DBAPI connection next time round
        engine.dispose()
