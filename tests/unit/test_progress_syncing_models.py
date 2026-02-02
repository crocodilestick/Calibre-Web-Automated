# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit Tests for Progress Syncing Models Module"""

import pytest
import sqlite3
from sqlalchemy import create_engine, text
from datetime import datetime

from cps.progress_syncing.models import (
    ensure_calibre_db_tables,
    ensure_app_db_tables,
    ensure_checksum_table,
    BookFormatChecksum
)


@pytest.mark.unit
class TestEnsureProgressSyncingTables:
    """Test database table creation for both metadata.db and app.db."""

    def test_creates_all_tables(self, tmp_path):
        """Verify all progress syncing tables are created."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))

        # Create both sets of tables in the same test DB
        ensure_calibre_db_tables(conn)
        ensure_app_db_tables(conn)

        # Check that book_format_checksums table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums'"
        )
        assert cursor.fetchone() is not None

        # Check that kosync_progress table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kosync_progress'"
        )
        assert cursor.fetchone() is not None

    def test_is_idempotent(self, tmp_path):
        """Verify calling multiple times doesn't cause errors."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))

        # Call multiple times
        ensure_calibre_db_tables(conn)
        ensure_app_db_tables(conn)
        ensure_calibre_db_tables(conn)
        ensure_app_db_tables(conn)
        ensure_calibre_db_tables(conn)
        ensure_app_db_tables(conn)

        # Should still work - both tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums'"
        )
        assert cursor.fetchone() is not None

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kosync_progress'"
        )
        assert cursor.fetchone() is not None


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

    def test_handles_missing_columns(self, tmp_path, caplog):
        """Verify missing columns trigger migration warning (production-safe behavior)."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE book_format_checksums (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, checksum TEXT)")
        conn.commit()

        ensure_checksum_table(conn)

        # Should log warning about missing columns instead of auto-migrating
        assert any('schema mismatch' in record.message.lower() for record in caplog.records)
        assert any('missing' in record.message.lower() for record in caplog.records)

        # Columns should NOT be auto-added (migration-safe for production)
        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'version' not in columns  # Not auto-added
        assert 'created' not in columns  # Not auto-added

    def test_handles_extra_columns(self, tmp_path, caplog):
        """Verify extra columns trigger migration warning (production-safe behavior)."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE book_format_checksums (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, checksum TEXT, old_column TEXT)")
        conn.commit()

        ensure_checksum_table(conn)

        # Should log warning about extra columns
        assert any('schema mismatch' in record.message.lower() for record in caplog.records)
        assert any('extra' in record.message.lower() for record in caplog.records)

        # Extra column should remain (no destructive operations)
        cursor = conn.execute("PRAGMA table_info(book_format_checksums)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'old_column' in columns  # Still present (not dropped)


@pytest.mark.unit
class TestEnsureKosyncProgressTable:
    """Test kosync_progress table creation and schema validation."""

    def test_creates_table(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        from cps.progress_syncing.models import ensure_kosync_progress_table
        ensure_kosync_progress_table(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kosync_progress'")
        assert cursor.fetchone() is not None

    def test_creates_columns(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        from cps.progress_syncing.models import ensure_kosync_progress_table
        ensure_kosync_progress_table(conn)

        cursor = conn.execute("PRAGMA table_info(kosync_progress)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {'id', 'user_id', 'document', 'progress', 'percentage', 'device', 'device_id', 'timestamp'}

    def test_creates_indexes(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        from cps.progress_syncing.models import ensure_kosync_progress_table
        ensure_kosync_progress_table(conn)

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='kosync_progress'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert any('user_document' in idx or 'document' in idx for idx in indexes)

    def test_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        from cps.progress_syncing.models import ensure_kosync_progress_table
        ensure_kosync_progress_table(conn)
        ensure_kosync_progress_table(conn)

        cursor = conn.execute("PRAGMA table_info(kosync_progress)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {'id', 'user_id', 'document', 'progress', 'percentage', 'device', 'device_id', 'timestamp'}

    def test_handles_schema_mismatch(self, tmp_path, caplog):
        """Verify schema mismatch triggers warning (production-safe behavior)."""
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        # Create table with wrong schema
        conn.execute("CREATE TABLE kosync_progress (id INTEGER PRIMARY KEY, user_id INTEGER, document TEXT)")
        conn.commit()

        from cps.progress_syncing.models import ensure_kosync_progress_table
        ensure_kosync_progress_table(conn)

        # Should log warning about schema mismatch
        assert any('schema mismatch' in record.message.lower() for record in caplog.records)
        assert any('missing' in record.message.lower() for record in caplog.records)


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
        # Should be recent (within last minute)
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        assert now - checksum.created < timedelta(minutes=1)


@pytest.mark.unit
class TestKOSyncProgressModel:
    """Test KOSyncProgress ORM model."""

    def test_creates_instance(self):
        """Verify KOSyncProgress instance can be created"""
        from cps.progress_syncing.models import KOSyncProgress

        progress = KOSyncProgress(
            user_id=1,
            document='test-doc-123',
            progress='0.5',
            percentage=50.0,
            device='KOReader',
            device_id='device-abc'
        )

        assert progress.user_id == 1
        assert progress.document == 'test-doc-123'
        assert progress.progress == '0.5'
        assert progress.percentage == 50.0
        assert progress.device == 'KOReader'
        assert progress.device_id == 'device-abc'

    def test_repr_format(self):
        """Verify __repr__ returns useful string"""
        from cps.progress_syncing.models import KOSyncProgress

        progress = KOSyncProgress(
            user_id=42,
            document='my-book-checksum',
            progress='0.75',
            percentage=75.0,
            device='KOReader',
            device_id='device-123'
        )

        repr_str = repr(progress)
        assert 'KOSyncProgress' in repr_str
        assert 'user=42' in repr_str
        assert 'my-book-checksum' in repr_str

    def test_model_has_required_fields(self):
        """Verify all required fields are present"""
        from cps.progress_syncing.models import KOSyncProgress
        import inspect

        # Get model columns
        sig = inspect.signature(KOSyncProgress.__init__)

        # Verify critical fields exist as class attributes
        assert hasattr(KOSyncProgress, 'user_id')
        assert hasattr(KOSyncProgress, 'document')
        assert hasattr(KOSyncProgress, 'progress')
        assert hasattr(KOSyncProgress, 'percentage')
        assert hasattr(KOSyncProgress, 'device')
        assert hasattr(KOSyncProgress, 'device_id')
        assert hasattr(KOSyncProgress, 'timestamp')


@pytest.mark.unit
class TestCascadeDelete:
    """Test CASCADE DELETE behavior for book_format_checksums table."""

    def test_cascade_delete_removes_checksums(self, tmp_path):
        """Test that deleting a book also deletes its checksums (CASCADE DELETE)."""
        # Create a minimal Calibre library with test books
        library_path = tmp_path / "test_library"
        library_path.mkdir(exist_ok=True)

        # Create metadata.db
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Create minimal books table schema
        cur.execute('''
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                sort TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pubdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                series_index REAL DEFAULT 1.0,
                author_sort TEXT,
                isbn TEXT,
                lccn TEXT,
                path TEXT NOT NULL,
                flags INTEGER DEFAULT 1,
                uuid TEXT,
                has_cover INTEGER DEFAULT 0,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()

        # Use ensure_checksum_table to create book_format_checksums table
        ensure_checksum_table(conn)

        # Add a book with multiple formats
        book_path = "Delete_Test_Book"
        cur.execute("""
            INSERT INTO books (title, sort, path, has_cover)
            VALUES (?, ?, ?, 0)
        """, ("Delete Test Book", "Delete Test Book", book_path))

        book_id = cur.lastrowid

        # Add checksums for multiple formats
        for fmt in ["EPUB", "PDF", "MOBI"]:
            cur.execute("""
                INSERT INTO book_format_checksums (book, format, checksum)
                VALUES (?, ?, ?)
            """, (book_id, fmt, f"checksum_{fmt.lower()}"))

        conn.commit()

        # Verify checksums were created
        checksums_before = cur.execute("""
            SELECT COUNT(*) FROM book_format_checksums
            WHERE book = ?
        """, (book_id,)).fetchone()[0]

        # Should have checksums for all 3 formats
        assert checksums_before == 3

        # Enable foreign key constraints (required for CASCADE DELETE in SQLite)
        cur.execute("PRAGMA foreign_keys = ON")

        # Delete the book from books table
        cur.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()

        # Verify all checksums for this book are also deleted
        checksums_after = cur.execute("""
            SELECT COUNT(*) FROM book_format_checksums
            WHERE book = ?
        """, (book_id,)).fetchone()[0]

        conn.close()

        # Should have 0 checksums remaining due to CASCADE DELETE
        assert checksums_after == 0

    def test_cascade_delete_removes_kosync_progress(self, tmp_path):
        """Test that deleting a user also deletes their progress records (CASCADE DELETE)."""
        from cps.progress_syncing.models import ensure_kosync_progress_table
        
        # Create app.db
        db_path = tmp_path / "app.db"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Create minimal user table schema
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                email TEXT,
                role INTEGER DEFAULT 0,
                password TEXT
            )
        ''')

        conn.commit()

        # Use ensure_kosync_progress_table to create kosync_progress table
        ensure_kosync_progress_table(conn)

        # Add a test user
        cur.execute("""
            INSERT INTO user (name, email, role, password)
            VALUES (?, ?, ?, ?)
        """, ("test_user", "test@example.com", 0, "hashed_password"))

        user_id = cur.lastrowid

        # Add progress records for multiple documents
        for i, doc in enumerate(["doc_checksum_1", "doc_checksum_2", "doc_checksum_3"]):
            cur.execute("""
                INSERT INTO kosync_progress (user_id, document, progress, percentage, device, device_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, doc, f"0.{i+3}", (i+3)*10.0, "KOReader", f"device-{i+1}"))

        conn.commit()

        # Verify progress records were created
        progress_before = cur.execute("""
            SELECT COUNT(*) FROM kosync_progress
            WHERE user_id = ?
        """, (user_id,)).fetchone()[0]

        # Should have 3 progress records
        assert progress_before == 3

        # Enable foreign key constraints (required for CASCADE DELETE in SQLite)
        cur.execute("PRAGMA foreign_keys = ON")

        # Delete the user from user table
        cur.execute("DELETE FROM user WHERE id = ?", (user_id,))
        conn.commit()

        # Verify all progress records for this user are also deleted
        progress_after = cur.execute("""
            SELECT COUNT(*) FROM kosync_progress
            WHERE user_id = ?
        """, (user_id,)).fetchone()[0]

        conn.close()

        # Should have 0 progress records remaining due to CASCADE DELETE
        assert progress_after == 0
