#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Generate Partial MD5 Checksums for Existing Books

This utility script generates KOReader-compatible partial MD5 checksums for all
books in a Calibre library that don't already have checksums stored. This runs
on every boot (via cwa-checksum-backfill service) to backfill any missing checksums
for newly added books.

Usage:
    python generate_book_checksums.py [--library-path /path/to/calibre/library] [--books-path /path/to/books] [--force]

Options:
    --library-path  Path to Calibre library directory (defaults to /calibre-library)
    --books-path    Path to books directory (defaults to config_calibre_split_dir setting with --library-path fallback)
    --force         Regenerate checksums even if they already exist
    --batch-size    Number of books to process before committing (default: 100)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

# Import the centralized partial MD5 calculation function
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cps.progress_syncing.checksums import calculate_koreader_partial_md5, CHECKSUM_VERSION
from cps.progress_syncing.settings import is_koreader_sync_enabled


def _flush_batch(metadata_db: str, batch_rows):
    if not batch_rows:
        return
    try:
        conn = sqlite3.connect(metadata_db, timeout=30)
        cur = conn.cursor()
        cur.executemany(
            '''
            INSERT INTO book_format_checksums (book, format, checksum, version, created)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM book_format_checksums
                WHERE book = ? AND format = ? AND checksum = ?
            )
            ''',
            batch_rows
        )
        conn.commit()
    finally:
        conn.close()


def generate_checksums(library_path: str, books_path: str = None, force: bool = False, batch_size: int = 100):
    """Generate checksums for all books in the library

    Args:
        library_path: Path to Calibre library directory (contains metadata.db)
        books_path: Path to books directory (if different from library_path in split mode)
        force: If True, regenerate checksums even if they exist
        batch_size: Number of books to process before committing
    """
    if not is_koreader_sync_enabled():
        print("KOReader sync is disabled; skipping checksum generation.")
        return
    metadata_db = os.path.join(library_path, 'metadata.db')

    if not os.path.exists(metadata_db):
        print(f"ERROR: Calibre database not found at {metadata_db}")
        sys.exit(1)

    # Use books_path if provided and valid, otherwise fall back to library_path
    base_path = books_path if (books_path and os.path.exists(books_path)) else library_path

    print(f"Connecting to Calibre library at: {library_path}")
    if base_path != library_path:
        print(f"Books path (split library mode): {base_path}")
    else:
        print(f"Books path: {base_path}")
    print(f"Force regenerate: {force}")
    print(f"Batch size: {batch_size}")
    print(f"Checksum version: {CHECKSUM_VERSION}")
    print()

    try:
        # Read missing formats without holding the DB open during checksum computation
        conn = sqlite3.connect(metadata_db, timeout=30)
        cur = conn.cursor()

        if force:
            query = '''
                SELECT b.id, b.path, b.title, d.format, d.name
                FROM books b
                JOIN data d ON b.id = d.book
                ORDER BY b.id
            '''
            formats = cur.execute(query).fetchall()
        else:
            query = '''
                SELECT b.id, b.path, b.title, d.format, d.name
                FROM books b
                JOIN data d ON b.id = d.book
                LEFT JOIN book_format_checksums bfc ON (
                    bfc.book = b.id
                    AND bfc.format = d.format
                )
                WHERE bfc.id IS NULL
                ORDER BY b.id
            '''
            formats = cur.execute(query).fetchall()
    except sqlite3.Error as e:
        print(f"ERROR: Database error: {e}")
        sys.exit(1)
    finally:
        conn.close()

    total = len(formats)

    if total == 0:
        print("✓ All books already have checksums!")
        return

    print(f"Found {total} book format(s) to process\n")

    processed = 0
    queued = 0
    failed = 0
    skipped = 0
    batch_rows = []

    for book_id, book_path, title, format_ext, format_name in formats:
        processed += 1

        file_path = os.path.join(base_path, book_path, f"{format_name}.{format_ext.lower()}")

        if not os.path.exists(file_path):
            print(f"[{processed}/{total}] SKIP: File not found - {title} ({format_ext})")
            skipped += 1
            continue

        checksum = calculate_koreader_partial_md5(file_path)

        if checksum:
            created = datetime.now(timezone.utc).isoformat()
            fmt = format_ext.upper()
            batch_rows.append((book_id, fmt, checksum, CHECKSUM_VERSION, created, book_id, fmt, checksum))
            queued += 1

            if queued % batch_size == 0:
                _flush_batch(metadata_db, batch_rows)
                batch_rows = []
                print(f"  → Committed {queued} checksums to database")
        else:
            print(f"[{processed}/{total}] FAIL: Could not generate checksum - {title} ({format_ext})")
            failed += 1

    if batch_rows:
        _flush_batch(metadata_db, batch_rows)

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Total processed: {processed}")
    print(f"  Queued:          {queued}")
    print(f"  Failed:          {failed}")
    print(f"  Skipped:         {skipped}")
    print("=" * 60)


def get_books_path():
    """
    Get the split library books path from app.db if split mode is enabled.
    
    Returns:
        The books path from config_calibre_split_dir if it exists and is valid,
        otherwise None to indicate the library path should be used.
    """
    try:
        conn = sqlite3.connect("/config/app.db", timeout=30)
        cur = conn.cursor()

        # Check if split mode is enabled and get split path
        result = cur.execute('SELECT config_calibre_split, config_calibre_split_dir FROM settings LIMIT 1;').fetchone()
        
        if not result:
            return None
            
        split_enabled, split_path = result
        
        # Only return split path if split mode is enabled, path is not NULL, and path exists
        if split_enabled and split_path and os.path.exists(split_path):
            return split_path
            
        return None

    except sqlite3.Error as e:
        # Log warning but don't crash - fall back to library path
        print(f"WARNING: Could not read split library setting from app.db: {e}")
        print(f"WARNING: Falling back to --library-path for books location")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Generate KOReader sync checksums for books in Calibre library',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--library-path',
        default='/calibre-library',
        help='Path to Calibre library directory (default: /calibre-library)'
    )

    parser.add_argument(
        '--books-path',
        default=get_books_path(),
        help='Path to books directory (default: config_calibre_split_dir setting or --library-path)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Regenerate checksums even if they already exist'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of books to process before committing (default: 100)'
    )

    args = parser.parse_args()

    # Validate library path
    if not os.path.isdir(args.library_path):
        print(f"ERROR: Library path does not exist: {args.library_path}")
        sys.exit(1)

    try:
        generate_checksums(args.library_path, args.books_path, args.force, args.batch_size)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(130)


if __name__ == '__main__':
    main()
