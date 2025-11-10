# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Unit Tests for Book Checksum Generation Script

These tests verify the generate_book_checksums.py script works correctly
for backfilling checksums in existing libraries.
"""

import pytest
import sys
import sqlite3
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
scripts_dir = project_root / "scripts"
sys.path.insert(0, str(scripts_dir))

from cps.progress_syncing.checksums import calculate_koreader_partial_md5


def create_minimal_calibre_library(library_path: Path):
    """Create a minimal Calibre library with test books."""
    library_path.mkdir(exist_ok=True)

    # Create metadata.db
    db_path = library_path / "metadata.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create minimal schema
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

    cur.execute('''
        CREATE TABLE IF NOT EXISTS data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            format TEXT NOT NULL,
            uncompressed_size INTEGER DEFAULT 0,
            name TEXT NOT NULL,
            FOREIGN KEY (book) REFERENCES books(id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS book_format_checksums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            format TEXT NOT NULL COLLATE NOCASE,
            checksum TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'koreader',
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book) REFERENCES books(id)
        )
    ''')

    cur.execute("CREATE INDEX IF NOT EXISTS idx_checksum ON book_format_checksums(checksum)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_checksum_version ON book_format_checksums(checksum, version)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_book_format ON book_format_checksums(book, format)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_created ON book_format_checksums(created)")

    conn.commit()
    conn.close()

    return db_path


def add_book_to_library(library_path: Path, title: str, formats: list):
    """Add a book with given formats to the test library."""
    db_path = library_path / "metadata.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Add book
    book_path = title.replace(" ", "_")
    cur.execute("""
        INSERT INTO books (title, sort, path, has_cover)
        VALUES (?, ?, ?, 0)
    """, (title, title, book_path))

    book_id = cur.lastrowid

    # Create book directory
    book_dir = library_path / book_path
    book_dir.mkdir(exist_ok=True)

    # Add formats
    for fmt in formats:
        # Create actual file
        file_name = f"{book_path}.{fmt.lower()}"
        file_path = book_dir / file_name
        file_path.write_bytes(b"Test content for " + title.encode() + b" in " + fmt.encode())

        # Add to data table
        cur.execute("""
            INSERT INTO data (book, format, name)
            VALUES (?, ?, ?)
        """, (book_id, fmt, book_path))

    conn.commit()
    conn.close()

    return book_id


@pytest.mark.unit
class TestChecksumGenerationScript:
    """Test the generate_book_checksums.py script functionality."""

    def test_script_exists(self):
        """Verify the script file exists."""
        script_path = scripts_dir / "generate_book_checksums.py"
        assert script_path.exists()
        assert script_path.is_file()

    def test_script_is_executable(self):
        """Verify script has execute permissions or can be run with python."""
        script_path = scripts_dir / "generate_book_checksums.py"

        # Try running with --help
        result = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "Generate" in result.stdout

    def test_generates_checksums_for_new_library(self, tmp_path):
        """Test generating checksums for a library without any checksums."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add test books
        add_book_to_library(library_path, "Test Book 1", ["EPUB", "PDF"])
        add_book_to_library(library_path, "Test Book 2", ["MOBI"])

        # Run script
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0

        # Verify checksums were created
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        checksums = cur.execute("SELECT * FROM book_format_checksums").fetchall()
        conn.close()

        # Should have 3 checksums (2 formats for book 1, 1 for book 2)
        assert len(checksums) >= 3

    def test_skips_existing_checksums_by_default(self, tmp_path):
        """Test that script doesn't regenerate existing checksums."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add a book
        book_id = add_book_to_library(library_path, "Existing Book", ["EPUB"])

        # Manually add a checksum
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        original_checksum = "original_checksum_value"
        cur.execute("""
            INSERT INTO book_format_checksums (book, format, checksum)
            VALUES (?, ?, ?)
        """, (book_id, "EPUB", original_checksum))
        conn.commit()
        conn.close()

        # Run script without --force
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Verify original checksum is unchanged
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums
            WHERE book = ? AND format = ?
        """, (book_id, "EPUB")).fetchone()

        conn.close()

        # Should still have original checksum (not regenerated)
        assert checksum[0] == original_checksum

    def test_force_flag_regenerates_checksums(self, tmp_path):
        """Test that --force flag regenerates existing checksums."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add a book
        book_id = add_book_to_library(library_path, "Force Book", ["EPUB"])

        # Manually add an incorrect checksum
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        original_checksum = "incorrect_checksum"
        cur.execute("""
            INSERT INTO book_format_checksums (book, format, checksum)
            VALUES (?, ?, ?)
        """, (book_id, "EPUB", original_checksum))
        conn.commit()
        conn.close()

        # Run script with --force
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path),
             "--library-path", str(library_path),
             "--force"],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0

        # Verify checksum was regenerated
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Get the most recent checksum (should be the newly generated one)
        new_checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums
            WHERE book = ? AND format = ?
            ORDER BY created DESC
            LIMIT 1
        """, (book_id, "EPUB")).fetchone()

        conn.close()

        # Should have new checksum (not the incorrect one)
        assert new_checksum[0] != original_checksum
        assert len(new_checksum[0]) == 32  # Valid MD5 length

    def test_handles_missing_files_gracefully(self, tmp_path):
        """Test that script handles missing book files without crashing."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add book to DB but don't create the file
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO books (title, sort, path, has_cover)
            VALUES (?, ?, ?, 0)
        """, ("Missing File", "Missing File", "missing_file"))

        book_id = cur.lastrowid

        cur.execute("""
            INSERT INTO data (book, format, name)
            VALUES (?, ?, ?)
        """, (book_id, "EPUB", "missing_file"))

        conn.commit()
        conn.close()

        # Run script - should not crash
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Script should complete (may skip the missing file)
        assert result.returncode == 0
        assert "SKIP" in result.stdout or "not found" in result.stdout.lower()

    def test_batch_size_parameter(self, tmp_path):
        """Test that batch-size parameter is respected."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add multiple books
        for i in range(5):
            add_book_to_library(library_path, f"Book {i}", ["EPUB"])

        # Run with small batch size
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path),
             "--library-path", str(library_path),
             "--batch-size", "2"],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0

        # Verify all checksums were created
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        count = cur.execute("SELECT COUNT(*) FROM book_format_checksums").fetchone()[0]
        conn.close()

        assert count == 5

    def test_invalid_library_path(self, tmp_path):
        """Test script handles invalid library path gracefully."""
        nonexistent = tmp_path / "nonexistent"

        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path),
             "--library-path", str(nonexistent)],
            capture_output=True,
            text=True,
            timeout=10
        )

        # Should exit with error
        assert result.returncode != 0
        assert "ERROR" in result.stdout or "error" in result.stderr.lower()


@pytest.mark.unit
class TestChecksumGenerationAccuracy:
    """Test that generated checksums match expected values."""

    def test_generated_checksums_are_valid_md5(self, tmp_path):
        """Verify generated checksums are valid MD5 hashes."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add a book
        add_book_to_library(library_path, "Valid Hash Book", ["EPUB"])

        # Run script
        script_path = scripts_dir / "generate_book_checksums.py"
        result = subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0

        # Check checksum format
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums LIMIT 1
        """).fetchone()

        conn.close()

        assert checksum is not None
        assert len(checksum[0]) == 32  # MD5 is 32 hex chars
        assert all(c in '0123456789abcdef' for c in checksum[0].lower())

    def test_same_file_generates_same_checksum(self, tmp_path):
        """Test that running twice on same file generates same checksum."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add a book
        add_book_to_library(library_path, "Consistent Book", ["EPUB"])

        script_path = scripts_dir / "generate_book_checksums.py"

        # Run once
        subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            timeout=30
        )

        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        first_checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums LIMIT 1
        """).fetchone()[0]

        conn.close()

        # Run again with --force
        subprocess.run(
            [sys.executable, str(script_path),
             "--library-path", str(library_path),
             "--force"],
            capture_output=True,
            timeout=30
        )

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        second_checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums LIMIT 1
        """).fetchone()[0]

        conn.close()

        # Should be identical
        assert first_checksum == second_checksum

    def test_checksum_matches_direct_calculation(self, tmp_path):
        """Test that script-generated checksum matches direct calculation."""
        library_path = tmp_path / "test_library"
        create_minimal_calibre_library(library_path)

        # Add a book with known content
        book_id = add_book_to_library(library_path, "Direct Calc Book", ["EPUB"])

        # Calculate checksum directly
        book_dir = library_path / "Direct_Calc_Book"
        epub_file = book_dir / "Direct_Calc_Book.epub"
        direct_checksum = calculate_koreader_partial_md5(str(epub_file))

        # Run script
        script_path = scripts_dir / "generate_book_checksums.py"
        subprocess.run(
            [sys.executable, str(script_path), "--library-path", str(library_path)],
            capture_output=True,
            timeout=30
        )

        # Get script-generated checksum
        db_path = library_path / "metadata.db"
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        script_checksum = cur.execute("""
            SELECT checksum FROM book_format_checksums
            WHERE book = ? AND format = ?
        """, (book_id, "EPUB")).fetchone()[0]

        conn.close()

        # Should match
        assert script_checksum == direct_checksum
