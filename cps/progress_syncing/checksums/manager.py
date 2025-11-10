#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Checksum Management Module

Centralized management of book file checksums with full history tracking.
Maintains a complete history of checksums as files are modified through
various operations (metadata enforcement, EPUB fixing, format conversion, OPDS embedding, etc.).

This allows KOReader sync to work with any version of a book file that exists
in the wild. All checksums are kept indefinitely, and the most recent one can be
determined by the 'created' timestamp.

No distinction is made between 'library' and 'opds' checksums - all are stored
together and any can be matched for sync purposes.
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from ... import logger
from .koreader import calculate_koreader_partial_md5, CHECKSUM_VERSION

log = logger.create()


def store_checksum(
    book_id: int,
    book_format: str,
    checksum: str,
    version: str = CHECKSUM_VERSION,
    db_connection=None
) -> bool:
    """
    Store a checksum in the database with history tracking.

    Simply inserts the checksum without checking for duplicates or superseding old entries.
    All checksums are kept for historical lookup.

    Args:
        book_id: Calibre book ID
        book_format: File format (EPUB, AZW3, etc.)
        checksum: MD5 checksum string
        version: Algorithm version identifier
        db_connection: Optional SQLAlchemy connection (uses calibre_db if None)

    Returns:
        True if successful, False otherwise

    Example:
        >>> store_checksum(123, 'EPUB', 'abc123...')
        True
    """
    try:
        from ... import calibre_db
        from sqlalchemy import text

        if db_connection is None:
            db_connection = calibre_db.engine.connect()
            should_close = True
        else:
            should_close = False

        # Detect connection type - SQLAlchemy uses text() wrapper, sqlite3 uses raw strings
        is_sqlalchemy = hasattr(db_connection, 'execute') and hasattr(db_connection.execute.__self__, 'dialect')

        try:
            # Check if this exact checksum already exists to avoid duplicates
            if is_sqlalchemy:
                existing = db_connection.execute(text('''
                    SELECT id FROM book_format_checksums
                    WHERE book = :book_id
                    AND format = :format
                    AND checksum = :checksum
                '''), {
                    'book_id': book_id,
                    'format': book_format.upper(),
                    'checksum': checksum
                }).fetchone()
            else:
                cursor = db_connection.execute('''
                    SELECT id FROM book_format_checksums
                    WHERE book = ?
                    AND format = ?
                    AND checksum = ?
                ''', (book_id, book_format.upper(), checksum))
                existing = cursor.fetchone()

            if existing:
                return True

            # Insert new checksum
            timestamp = datetime.now(timezone.utc).isoformat()
            if is_sqlalchemy:
                db_connection.execute(text('''
                    INSERT INTO book_format_checksums
                    (book, format, checksum, version, created)
                    VALUES (:book_id, :format, :checksum, :version, :created)
                '''), {
                    'book_id': book_id,
                    'format': book_format.upper(),
                    'checksum': checksum,
                    'version': version,
                    'created': timestamp
                })
            else:
                db_connection.execute('''
                    INSERT INTO book_format_checksums
                    (book, format, checksum, version, created)
                    VALUES (?, ?, ?, ?, ?)
                ''', (book_id, book_format.upper(), checksum, version, timestamp))

            db_connection.commit()
            return True

        finally:
            if should_close:
                db_connection.close()

    except Exception as e:
        log.error(f"Failed to store checksum for book {book_id}: {e}")
        return False


def calculate_and_store_checksum(
    book_id: int,
    book_format: str,
    file_path: str,
    db_connection=None
) -> Optional[str]:
    """
    Calculate and store a checksum for a book file.

    Args:
        book_id: Calibre book ID
        book_format: File format (EPUB, AZW3, etc.)
        file_path: Absolute path to the book file
        db_connection: Optional database connection (SQLAlchemy or sqlite3)

    Returns:
        The calculated checksum string, or None if failed

    Example:
        >>> calculate_and_store_checksum(123, 'EPUB', '/path/to/book.epub')
        'abc123def456...'
    """
    if not os.path.exists(file_path):
        return None

    checksum = calculate_koreader_partial_md5(file_path)
    if not checksum:
        return None

    success = store_checksum(
        book_id=book_id,
        book_format=book_format,
        checksum=checksum,
        version=CHECKSUM_VERSION,
        db_connection=db_connection
    )

    if success:
        return checksum
    else:
        return None


def get_latest_checksum(
    book_id: int,
    book_format: str
) -> Optional[str]:
    """
    Get the most recent checksum for a book/format (by created timestamp).

    Args:
        book_id: Calibre book ID
        book_format: File format (EPUB, AZW3, etc.)

    Returns:
        The most recent checksum string, or None if not found
    """
    try:
        from ... import calibre_db
        from sqlalchemy import text

        with calibre_db.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT checksum FROM book_format_checksums
                WHERE book = :book_id
                AND format = :format
                ORDER BY created DESC
                LIMIT 1
            '''), {
                'book_id': book_id,
                'format': book_format.upper()
            }).fetchone()

            return result[0] if result else None

    except Exception as e:
        log.error(f"Failed to get latest checksum for book {book_id}: {e}")
        return None


def get_checksum_history(
    book_id: int,
    book_format: str
) -> List[Tuple[str, datetime, str]]:
    """
    Get the complete checksum history for a book/format.

    Args:
        book_id: Calibre book ID
        book_format: File format (EPUB, AZW3, etc.)

    Returns:
        List of tuples: (checksum, created, version)
        Ordered by created timestamp (newest first)
    """
    try:
        from ... import calibre_db
        from sqlalchemy import text

        with calibre_db.engine.connect() as conn:
            results = conn.execute(text('''
                SELECT checksum, created, version
                FROM book_format_checksums
                WHERE book = :book_id
                AND format = :format
                ORDER BY created DESC
            '''), {
                'book_id': book_id,
                'format': book_format.upper()
            }).fetchall()

            return [(r[0], r[1], r[2]) for r in results]

    except Exception as e:
        log.error(f"Failed to get checksum history for book {book_id}: {e}")
        return []
