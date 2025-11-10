#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Database Models and Setup for Progress Syncing

Handles database tables for progress syncing functionality:
- book_format_checksums: Stores checksums for book formats (KOReader sync)
- kosync_progress: Stores reading progress from KOSync protocol
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Float, text

from .. import logger
from ..db import Base as CalibreBase  # For metadata.db tables (books)
from ..ub import Base as AppBase  # For app.db tables (users)

log = logger.create()


def ensure_calibre_db_tables(conn):
    """
    Ensure progress syncing tables for metadata.db (Calibre library) exist.

    Creates or validates tables that reference books in the Calibre library:
    - book_format_checksums: Stores checksums for book formats

    Args:
        conn: SQLAlchemy connection object or sqlite3 connection for metadata.db

    Note:
        This function is designed to be safe for production - it will log warnings
        for schema mismatches rather than automatically modifying tables to prevent
        data loss. Manual migration is required for schema changes.
    """
    ensure_checksum_table(conn)


def ensure_app_db_tables(conn):
    """
    Ensure progress syncing tables for app.db (Flask/user database) exist.

    Creates or validates tables that reference users:
    - kosync_progress: Stores reading progress from KOSync protocol

    Args:
        conn: SQLAlchemy connection object or sqlite3 connection for app.db

    Note:
        This function is designed to be safe for production - it will log warnings
        for schema mismatches rather than automatically modifying tables to prevent
        data loss. Manual migration is required for schema changes.
    """
    ensure_kosync_progress_table(conn)


def ensure_checksum_table(conn):
    """
    Ensure the book_format_checksums table exists with the correct schema.

    This function is called during database initialization to create the checksum
    table if it doesn't exist. If the table exists with a different schema, a
    warning is logged and the table is left as-is to allow for proper migration.

    Args:
        conn: SQLAlchemy connection object or sqlite3 connection
    """
    try:
        # Detect connection type - SQLAlchemy uses text() wrapper, sqlite3 uses raw strings
        is_sqlalchemy = hasattr(conn, 'execute') and hasattr(conn.execute.__self__, 'dialect')

        def execute_sql(sql):
            """Execute SQL with appropriate wrapper based on connection type."""
            if is_sqlalchemy:
                return conn.execute(text(sql))
            else:
                return conn.execute(sql)

        # Check if table exists
        result = execute_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums'")
        table_exists = result.fetchone() is not None

        if table_exists:
            # Check if table has the expected schema
            pragma_result = execute_sql("PRAGMA table_info(book_format_checksums)")
            columns = [row[1] for row in pragma_result.fetchall()]

            expected_columns = {'id', 'book', 'format', 'checksum', 'version', 'created'}
            actual_columns = set(columns)

            # If schema doesn't match, log warning and skip (requires migration)
            if actual_columns != expected_columns:
                missing = expected_columns - actual_columns
                extra = actual_columns - expected_columns
                log.warning(
                    f"book_format_checksums table schema mismatch. "
                    f"Expected columns: {expected_columns}. "
                    f"Missing: {missing}. Extra: {extra}. "
                    f"Migration required."
                )
                return  # Skip creation, table exists but needs migration

        if not table_exists:
            # Create table for book format checksums
            execute_sql("""
                CREATE TABLE book_format_checksums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book INTEGER NOT NULL,
                    format TEXT NOT NULL COLLATE NOCASE,
                    checksum TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT 'koreader',
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (book) REFERENCES books(id)
                )
            """)
            execute_sql("CREATE INDEX idx_checksum ON book_format_checksums(checksum)")
            execute_sql("CREATE INDEX idx_checksum_version ON book_format_checksums(checksum, version)")
            execute_sql("CREATE INDEX idx_book_format ON book_format_checksums(book, format)")
            execute_sql("CREATE INDEX idx_created ON book_format_checksums(created)")
            conn.commit()
            log.info("Created book_format_checksums table with indexes")

    except Exception as e:
        log.error(f"Could not create book_format_checksums table: {e}")
        import traceback
        log.error(traceback.format_exc())


def ensure_kosync_progress_table(conn):
    """
    Ensure the kosync_progress table exists with the correct schema.

    This function is called during database initialization to create the KOSync
    progress table if it doesn't exist. If the table exists with a different schema,
    a warning is logged and the table is left as-is to allow for proper migration.

    Args:
        conn: SQLAlchemy connection object or sqlite3 connection
    """
    try:
        # Detect connection type - SQLAlchemy uses text() wrapper, sqlite3 uses raw strings
        is_sqlalchemy = hasattr(conn, 'execute') and hasattr(conn.execute.__self__, 'dialect')

        def execute_sql(sql):
            """Execute SQL with appropriate wrapper based on connection type."""
            if is_sqlalchemy:
                return conn.execute(text(sql))
            else:
                return conn.execute(sql)

        # Check if table exists
        result = execute_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='kosync_progress'")
        table_exists = result.fetchone() is not None

        if table_exists:
            # Check if table has the expected schema
            pragma_result = execute_sql("PRAGMA table_info(kosync_progress)")
            columns = [row[1] for row in pragma_result.fetchall()]

            expected_columns = {'id', 'user_id', 'document', 'progress', 'percentage', 'device', 'device_id', 'timestamp'}
            actual_columns = set(columns)

            # If schema doesn't match, log warning and skip (requires migration)
            if actual_columns != expected_columns:
                missing = expected_columns - actual_columns
                extra = actual_columns - expected_columns
                log.warning(
                    f"kosync_progress table schema mismatch. "
                    f"Expected columns: {expected_columns}. "
                    f"Missing: {missing}. Extra: {extra}. "
                    f"Migration required."
                )
                return  # Skip creation, table exists but needs migration

        if not table_exists:
            # Create table for KOSync reading progress
            execute_sql("""
                CREATE TABLE kosync_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    progress TEXT NOT NULL,
                    percentage REAL NOT NULL,
                    device TEXT NOT NULL,
                    device_id TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user(id)
                )
            """)
            execute_sql("CREATE INDEX idx_kosync_user_document ON kosync_progress(user_id, document)")
            execute_sql("CREATE INDEX idx_kosync_document ON kosync_progress(document)")
            conn.commit()
            log.info("Created kosync_progress table with indexes")

    except Exception as e:
        log.error(f"Could not create kosync_progress table: {e}")
        import traceback
        log.error(traceback.format_exc())


class BookFormatChecksum(CalibreBase):
    """
    Stores partial MD5 checksums for book formats to support KOReader sync.

    This table maps book formats to their partial MD5 checksums, which are used
    by KOReader devices to identify documents for reading progress synchronization.
    Each book format (EPUB, PDF, etc.) gets its own checksum since different formats
    are distinct files.

    Checksum History:
    - Maintains a complete history of checksums as files are modified through
      metadata enforcement, EPUB fixing, format conversion, OPDS embedding, etc.
    - All checksums are kept in the database to support sync with any file version
      that may exist on user devices
    - The 'created' timestamp indicates when each checksum was generated
    - Use ORDER BY created DESC to get the most recent checksum
    - No distinction between 'library' and 'opds' checksums - all are stored together

    Version field allows for algorithm updates and checksum regeneration if bugs
    are found or improvements are made. Current version: 'koreader' (KOReader partialMD5).
    """
    __tablename__ = 'book_format_checksums'

    id = Column(Integer, primary_key=True, autoincrement=True)
    book = Column(Integer, ForeignKey('books.id'), nullable=False)
    format = Column(String(collation='NOCASE'), nullable=False)
    checksum = Column(String(32), nullable=False)  # MD5 hex digest is always 32 chars
    version = Column(String, nullable=False, default='koreader')  # Algorithm version identifier
    created = Column(TIMESTAMP, default=lambda: datetime.now(timezone.utc))

    def __init__(self, book, format, checksum, version='koreader'):
        super().__init__()
        self.book = book
        self.format = format
        self.checksum = checksum
        self.version = version
        # Set created timestamp if not already set (for standalone instantiation in tests)
        if not hasattr(self, 'created') or self.created is None:
            self.created = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<BookFormatChecksum(book={self.book}, format={self.format}, checksum={self.checksum}, version={self.version})>"


class KOSyncProgress(AppBase):
    """
    Stores KOReader sync progress data for reading position synchronization.

    This table maintains reading progress for documents synced via the KOSync protocol,
    which is used by KOReader e-reader devices. Each record represents a user's
    reading position for a specific document.

    Fields:
        user_id: Foreign key to the user who owns this progress record
        document: Document identifier (typically a checksum or file path)
        progress: Raw progress value (string representation, format varies)
        percentage: Normalized percentage (0-100) of reading progress
        device: Device name that last synced this progress
        device_id: Unique identifier for the device
        timestamp: Last update time for this progress record
    """
    __tablename__ = 'kosync_progress'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    document = Column(String, nullable=False)
    progress = Column(String, nullable=False)
    percentage = Column(Float, nullable=False)
    device = Column(String, nullable=False)
    device_id = Column(String)
    timestamp = Column(TIMESTAMP, default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<KOSyncProgress user={self.user_id} doc={self.document}>'
