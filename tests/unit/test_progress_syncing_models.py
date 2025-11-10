# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit Tests for Progress Syncing Models Module"""

import pytest
import sqlite3
from sqlalchemy import create_engine, text
from datetime import datetime

from cps.progress_syncing.models import ensure_checksum_table, BookFormatChecksum


@pytest.mark.unit
class TestEnsureChecksumTable:
    """Test ensure_checksum_table function."""

    def test_creates_table(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        ensure_checksum_table(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums'")
        assert cursor.fetchone() is not None

    def test_creates_columns(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        ensure_checksum_table(conn)

        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {'id', 'book', 'format', 'checksum', 'version', 'created'}

    def test_creates_unique_index(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        ensure_checksum_table(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='book_format_checksums'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert any('book_format' in idx for idx in indexes)

    def test_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        ensure_checksum_table(conn)
        ensure_checksum_table(conn)

        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {'id', 'book', 'format', 'checksum', 'version', 'created'}

    def test_handles_missing_columns(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE book_format_checksums (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, checksum TEXT)")
        conn.commit()

        ensure_checksum_table(conn)

        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'version' in columns
        assert 'created' in columns

    def test_handles_extra_columns(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE book_format_checksums (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, checksum TEXT, old_column TEXT)")
        conn.commit()

        ensure_checksum_table(conn)

        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {'id', 'book', 'format', 'checksum', 'version', 'created'}


@pytest.mark.unit
class TestBookFormatChecksumModel:
    """Test BookFormatChecksum ORM model."""

    def test_creates_instance(self):
        checksum = BookFormatChecksum(book=1, format='EPUB', checksum='abc123')
        assert checksum.book == 1
        assert checksum.format == 'EPUB'
        assert checksum.checksum == 'abc123'

    def test_defaults_version(self):
        checksum = BookFormatChecksum(book=1, format='EPUB', checksum='abc123')
        assert checksum.version == 'koreader'

    def test_sets_created_timestamp(self):
        checksum = BookFormatChecksum(book=1, format='EPUB', checksum='abc123')
        assert checksum.created is not None
        assert isinstance(checksum.created, datetime)
