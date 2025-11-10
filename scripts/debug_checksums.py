#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug Checksum Utility

This script helps diagnose checksum mismatches between CWA and KOReader by:
1. Listing all stored checksums in the database
2. Recalculating checksums for specific books
3. Comparing KOReader's checksum with CWA's stored checksum

Usage:
    # List all checksums
    python3 scripts/debug_checksums.py --list

    # Recalculate checksum for a specific book
    python3 scripts/debug_checksums.py --book-id 123 --format EPUB

    # Compare checksum with what KOReader would send
    python3 scripts/debug_checksums.py --check-file /path/to/book.epub --expected a2a46e1ffd055f4ef7e36b9a41a3fef0
"""

import argparse
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cps import db, calibre_db, logger
from cps.progress_syncing.checksums import calculate_koreader_partial_md5
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

log = logger.create()


def list_checksums():
    """List all checksums stored in the database."""
    print("\n=== Stored Checksums ===\n")

    try:
        results = calibre_db.session.query(
            db.BookFormatChecksum.book,
            db.BookFormatChecksum.format,
            db.BookFormatChecksum.checksum,
            db.BookFormatChecksum.version,
            db.Books.title
        ).join(
            db.Books, db.BookFormatChecksum.book == db.Books.id
        ).order_by(db.Books.title, db.BookFormatChecksum.format).all()

        if not results:
            print("No checksums found in database.")
            return

        current_book = None
        for book_id, book_format, checksum, version, title in results:
            if book_id != current_book:
                if current_book is not None:
                    print()  # Blank line between books
                print(f"Book ID: {book_id}")
                print(f"Title:   {title}")
                current_book = book_id
            print(f"  Format:  {book_format}")
            print(f"  Checksum: {checksum} (v{version})")
        print()

    except Exception as e:
        log.error(f"Error listing checksums: {e}")
        print(f"ERROR: {e}")
def recalculate_checksum(book_id: int, book_format: str):
    """Recalculate checksum for a specific book."""
    print(f"\n=== Recalculating Checksum for Book {book_id} ({book_format}) ===\n")

    try:
        # Get book details
        book = calibre_db.session.query(db.Books).filter(db.Books.id == book_id).first()
        if not book:
            print(f"ERROR: Book ID {book_id} not found")
            return

        print(f"Title: {book.title}")
        print(f"Path:  {book.path}")

        # Get the specific format data
        book_data = calibre_db.session.query(db.Data).filter(
            db.Data.book == book_id,
            db.Data.format == book_format.upper()
        ).first()

        if not book_data:
            print(f"ERROR: Format {book_format} not found for book {book_id}")
            return

        # Construct file path
        config = calibre_db.get_book_path_config()
        calibre_path = config.config_calibre_dir
        book_path = os.path.join(calibre_path, book.path, f"{book_data.name}.{book_format.lower()}")

        print(f"File:  {book_path}")

        if not os.path.exists(book_path):
            print(f"ERROR: File does not exist: {book_path}")
            return

        file_size = os.path.getsize(book_path)
        print(f"Size:  {file_size} bytes")

        # Check existing checksum
        existing = calibre_db.session.query(db.BookFormatChecksum).filter(
            db.BookFormatChecksum.book == book_id,
            db.BookFormatChecksum.format == book_format.upper()
        ).all()

        if existing:
            print("\nExisting Checksums:")
            for cs in existing:
                print(f"  Checksum: {cs.checksum} (v{cs.version})")
        else:
            print("\nNo existing checksums found")

        # Calculate new checksum
        print("\nCalculating partial MD5...")
        new_checksum = calculate_koreader_partial_md5(book_path)

        if new_checksum:
            print(f"New Checksum: {new_checksum}")

            if existing:
                matches = [cs for cs in existing if cs.checksum == new_checksum]
                if matches:
                    print(f"\n✓ Checksum matches existing checksum - no changes needed")
                else:
                    print(f"\n✗ MISMATCH: New checksum differs from all existing checksums")
                    print("  This means the file has been modified or the algorithm changed")
        else:
            print("ERROR: Failed to calculate checksum")

    except Exception as e:
        log.error(f"Error recalculating checksum: {e}")
        print(f"ERROR: {e}")


def check_file(filepath: str, expected_checksum: str = None):
    """Calculate checksum for a file and compare with expected value."""
    print(f"\n=== Checking File: {filepath} ===\n")

    if not os.path.exists(filepath):
        print(f"ERROR: File does not exist: {filepath}")
        return

    file_size = os.path.getsize(filepath)
    print(f"Size: {file_size} bytes")

    print("\nCalculating partial MD5...")
    checksum = calculate_koreader_partial_md5(filepath)

    if checksum:
        print(f"Checksum: {checksum}")

        if expected_checksum:
            print(f"Expected: {expected_checksum}")
            if checksum.lower() == expected_checksum.lower():
                print("\n✓ Checksums match!")
            else:
                print("\n✗ MISMATCH: Checksums do not match")
                print("  Possible reasons:")
                print("  - File was modified after KOReader calculated its checksum")
                print("  - Different file versions (e.g., before/after conversion)")
                print("  - Algorithm implementation difference (unlikely)")
    else:
        print("ERROR: Failed to calculate checksum")


def main():
    parser = argparse.ArgumentParser(description="Debug checksum mismatches between CWA and KOReader")
    parser.add_argument("--list", action="store_true", help="List all stored checksums")
    parser.add_argument("--book-id", type=int, help="Book ID to recalculate checksum for")
    parser.add_argument("--format", help="Book format (e.g., EPUB, PDF)")
    parser.add_argument("--check-file", help="Path to file to check")
    parser.add_argument("--expected", help="Expected checksum to compare against")

    args = parser.parse_args()

    # Initialize database
    try:
        calibre_db.setup_db()
    except Exception as e:
        print(f"ERROR: Failed to initialize database: {e}")
        return 1

    if args.list:
        list_checksums()
    elif args.book_id and args.format:
        recalculate_checksum(args.book_id, args.format)
    elif args.check_file:
        check_file(args.check_file, args.expected)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
