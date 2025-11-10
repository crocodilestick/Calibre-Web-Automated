# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit Tests for Progress Syncing Manager Module"""

import pytest
import sqlite3
from datetime import datetime

from cps.progress_syncing.checksums import (
    store_checksum,
    calculate_and_store_checksum,
    CHECKSUM_VERSION
)
from cps.progress_syncing.models import ensure_checksum_table


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with checksum table."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    ensure_checksum_table(conn)
    yield conn
    conn.close()


@pytest.fixture
def test_file(tmp_path):
    """Create a test file."""
    file_path = tmp_path / "test.epub"
    file_path.write_bytes(b"Test content for checksum calculation")
    return str(file_path)


@pytest.mark.unit
class TestStoreChecksum:
    """Test store_checksum function."""

    def test_stores_new_checksum(self, test_db):
        result = store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)
        assert result is True

    def test_creates_database_record(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)

        cursor = test_db.execute(
            "SELECT book, format, checksum FROM book_format_checksums WHERE book = 1"
        )
        row = cursor.fetchone()
        assert row == (1, 'EPUB', 'abc123')

    def test_uses_default_version(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)

        cursor = test_db.execute("SELECT version FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == CHECKSUM_VERSION

    def test_accepts_custom_version(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', version='custom', db_connection=test_db)

        cursor = test_db.execute("SELECT version FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == 'custom'

    def test_normalizes_format_to_uppercase(self, test_db):
        store_checksum(1, 'epub', 'abc123', db_connection=test_db)

        cursor = test_db.execute("SELECT format FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == 'EPUB'

    def test_prevents_duplicate_checksums(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)
        result = store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)

        cursor = test_db.execute("SELECT COUNT(*) FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == 1
        assert result is True

    def test_allows_different_checksums_for_same_book(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)
        store_checksum(1, 'EPUB', 'def456', db_connection=test_db)

        cursor = test_db.execute("SELECT COUNT(*) FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == 2

    def test_allows_same_checksum_different_format(self, test_db):
        store_checksum(1, 'EPUB', 'abc123', db_connection=test_db)
        store_checksum(1, 'PDF', 'abc123', db_connection=test_db)

        cursor = test_db.execute("SELECT COUNT(*) FROM book_format_checksums WHERE book = 1")
        assert cursor.fetchone()[0] == 2


@pytest.mark.unit
class TestCalculateAndStoreChecksum:
    """Test calculate_and_store_checksum function."""

    def test_returns_checksum_string(self, test_file, test_db):
        checksum = calculate_and_store_checksum(1, 'EPUB', test_file, db_connection=test_db)
        assert isinstance(checksum, str)
        assert len(checksum) == 32

    def test_stores_in_database(self, test_file, test_db):
        checksum = calculate_and_store_checksum(1, 'EPUB', test_file, db_connection=test_db)

        cursor = test_db.execute(
            "SELECT checksum FROM book_format_checksums WHERE book = 1"
        )
        assert cursor.fetchone()[0] == checksum

    def test_returns_none_for_missing_file(self, test_db):
        result = calculate_and_store_checksum(1, 'EPUB', '/nonexistent/file.epub', db_connection=test_db)
        assert result is None

    def test_does_not_store_if_calculation_fails(self, test_db):
        calculate_and_store_checksum(1, 'EPUB', '/nonexistent/file.epub', db_connection=test_db)

        cursor = test_db.execute("SELECT COUNT(*) FROM book_format_checksums")
        assert cursor.fetchone()[0] == 0
