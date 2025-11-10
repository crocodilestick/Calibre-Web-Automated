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
    python generate_book_checksums.py [--library-path /path/to/calibre/library] [--force]

Options:
    --library-path  Path to Calibre library directory (defaults to /calibre-library)
    --force         Regenerate checksums even if they already exist
    --batch-size    Number of books to process before committing (default: 100)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Import the centralized partial MD5 calculation function
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cps.progress_syncing.checksums import calculate_koreader_partial_md5, store_checksum, CHECKSUM_VERSION
def generate_checksums(library_path: str, force: bool = False, batch_size: int = 100):
    """Generate checksums for all books in the library

    Args:
        library_path: Path to Calibre library directory
        force: If True, regenerate checksums even if they exist
        batch_size: Number of books to process before committing
    """
    metadata_db = os.path.join(library_path, 'metadata.db')

    if not os.path.exists(metadata_db):
        print(f"ERROR: Calibre database not found at {metadata_db}")
        sys.exit(1)

    print(f"Connecting to Calibre library at: {library_path}")
    print(f"Force regenerate: {force}")
    print(f"Batch size: {batch_size}")
    print(f"Checksum version: {CHECKSUM_VERSION}")
    print()

    try:
        conn = sqlite3.connect(metadata_db, timeout=30)
        cur = conn.cursor()

        # Get all book formats
        if force:
            # Get all formats
            query = '''
                SELECT b.id, b.path, b.title, d.format, d.name
                FROM books b
                JOIN data d ON b.id = d.book
                ORDER BY b.id
            '''
            formats = cur.execute(query).fetchall()
        else:
            # Only get formats without checksums
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

        total = len(formats)

        if total == 0:
            print("✓ All books already have checksums!")
            return

        print(f"Found {total} book format(s) to process\n")

        processed = 0
        success = 0
        failed = 0
        skipped = 0

        for book_id, book_path, title, format_ext, format_name in formats:
            processed += 1

            # Construct full file path
            file_path = os.path.join(library_path, book_path, f"{format_name}.{format_ext.lower()}")

            if not os.path.exists(file_path):
                print(f"[{processed}/{total}] SKIP: File not found - {title} ({format_ext})")
                skipped += 1
                continue

            # Generate checksum
            checksum = calculate_koreader_partial_md5(file_path)

            if checksum:
                # Store in database using centralized manager function
                success_stored = store_checksum(
                    book_id=book_id,
                    book_format=format_ext.upper(),
                    checksum=checksum,
                    version=CHECKSUM_VERSION,
                    db_connection=conn
                )

                if success_stored:
                    print(f"[{processed}/{total}] ✓ {title} ({format_ext}): {checksum} (v{CHECKSUM_VERSION})")
                    success += 1

                    # Commit periodically
                    if success % batch_size == 0:
                        conn.commit()
                        print(f"  → Committed {success} checksums to database")
                else:
                    print(f"[{processed}/{total}] ERROR: Failed to store checksum for {title} ({format_ext})")
                    failed += 1
            else:
                print(f"[{processed}/{total}] FAIL: Could not generate checksum - {title} ({format_ext})")
                failed += 1

        # Final commit
        conn.commit()

        print()
        print("=" * 60)
        print("Summary:")
        print(f"  Total processed: {processed}")
        print(f"  Success:         {success}")
        print(f"  Failed:          {failed}")
        print(f"  Skipped:         {skipped}")
        print("=" * 60)

    except sqlite3.Error as e:
        print(f"ERROR: Database error: {e}")
        sys.exit(1)
    finally:
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
        generate_checksums(args.library_path, args.force, args.batch_size)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(130)


if __name__ == '__main__':
    main()
