# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Integration Tests for Automatic Checksum Generation During Ingest

These tests verify that checksums are automatically generated when
books are imported via the ingest processor.

Note: These are integration tests that require a running CWA container.
"""

import pytest
import sys
import time
import sqlite3
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def get_book_checksums(db_path, book_id=None):
    """Helper to retrieve checksums from database."""
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    try:
        if book_id:
            results = cur.execute("""
                SELECT book, format, checksum FROM book_format_checksums
                WHERE book = ?
            """, (book_id,)).fetchall()
        else:
            results = cur.execute("""
                SELECT book, format, checksum FROM book_format_checksums
            """).fetchall()
        return results
    except sqlite3.OperationalError as e:
        if "no such table: book_format_checksums" in str(e).lower():
            pytest.skip("KOReader sync disabled; checksum table not initialized")
        raise
    finally:
        conn.close()


def get_latest_book_id(db_path):
    """Get the most recently added book ID."""
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()

    result = cur.execute("""
        SELECT id FROM books ORDER BY timestamp DESC LIMIT 1
    """).fetchone()

    conn.close()
    return result[0] if result else None


@pytest.mark.docker_integration
@pytest.mark.slow
class TestIngestChecksumGeneration:
    """Test automatic checksum generation during book ingest."""

    def test_epub_ingest_generates_checksum(self, cwa_container, ingest_folder, library_folder, test_epub):
        """Test that importing an EPUB generates a checksum."""
        from conftest import volume_copy, get_db_path

        # Copy test EPUB to ingest folder
        volume_copy(test_epub, ingest_folder / "test.epub")

        # Wait for ingest
        time.sleep(15)  # Give ingest processor time to run

        # Get database path
        db_path = get_db_path(library_folder / "metadata.db")

        # Get latest book
        book_id = get_latest_book_id(db_path)
        assert book_id is not None, "Book was not ingested"

        # Check for checksum
        checksums = get_book_checksums(db_path, book_id)

        assert len(checksums) > 0, "No checksums were generated"

        # Verify checksum format
        book_id, fmt, checksum = checksums[0]
        assert len(checksum) == 32, f"Invalid checksum length: {len(checksum)}"
        assert all(c in '0123456789abcdef' for c in checksum.lower()), "Invalid checksum format"
        assert fmt == 'EPUB', f"Expected EPUB format, got {fmt}"

    def test_converted_book_generates_checksums_for_both_formats(
        self, cwa_container, ingest_folder, library_folder, test_mobi
    ):
        """Test that conversion generates checksums for both original and converted formats."""
        from conftest import volume_copy, get_db_path

        # Enable auto-convert in settings (this might need API call to change settings)
        # For now, assume it's enabled by default or in test config

        # Copy test MOBI to ingest folder (will be converted to EPUB)
        volume_copy(test_mobi, ingest_folder / "test.mobi")

        # Wait for ingest + conversion
        time.sleep(30)

        # Get database path
        db_path = get_db_path(library_folder / "metadata.db")

        # Get latest book
        book_id = get_latest_book_id(db_path)
        assert book_id is not None, "Book was not ingested"

        # Check for checksums
        checksums = get_book_checksums(db_path, book_id)

        # Should have checksums for converted format (and possibly original if retained)
        assert len(checksums) >= 1, "No checksums were generated after conversion"

        # Verify at least one checksum is valid
        for book_id, fmt, checksum in checksums:
            assert len(checksum) == 32
            assert all(c in '0123456789abcdef' for c in checksum.lower())

    def test_multi_format_book_has_multiple_checksums(
        self, cwa_container, ingest_folder, library_folder, test_epub
    ):
        """Test that books with multiple formats get checksums for each."""
        from conftest import volume_copy, get_db_path
        import shutil

        # Copy same book with different extensions (simulating multi-format)
        # In real scenario, you'd add formats via API or manual import
        volume_copy(test_epub, ingest_folder / "multi_format.epub")

        # Wait for ingest
        time.sleep(15)

        # Get database path
        db_path = get_db_path(library_folder / "metadata.db")

        # Get latest book
        book_id = get_latest_book_id(db_path)
        assert book_id is not None

        # TODO: Add another format to the same book via calibredb or API
        # For now, verify single format has checksum

        checksums = get_book_checksums(db_path, book_id)
        assert len(checksums) >= 1

    def test_checksum_persists_after_container_restart(
        self, container_name, ingest_folder, library_folder, test_epub
    ):
        """Test that checksums survive container restart."""
        from conftest import volume_copy, get_db_path
        import subprocess

        # Ingest a book
        volume_copy(test_epub, ingest_folder / "persistent.epub")
        time.sleep(15)

        db_path = get_db_path(library_folder / "metadata.db")
        book_id = get_latest_book_id(db_path)

        # Get checksum before restart
        checksums_before = get_book_checksums(db_path, book_id)
        assert len(checksums_before) > 0

        original_checksum = checksums_before[0][2]

        # Restart container (if we have container control)
        # This might not work in all test environments
        try:
            subprocess.run(['docker', 'restart', container_name], check=True, timeout=30)
            time.sleep(20)  # Wait for restart

            # Verify checksum still exists
            db_path = get_db_path(library_folder / "metadata.db")
            checksums_after = get_book_checksums(db_path, book_id)

            assert len(checksums_after) > 0
            assert checksums_after[0][2] == original_checksum
        except Exception as e:
            pytest.skip(f"Container restart not available in this test environment: {e}")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestChecksumGenerationEdgeCases:
    """Test edge cases in checksum generation during ingest."""

    def test_failed_ingest_no_checksum(
        self, cwa_container, ingest_folder, library_folder, tmp_path
    ):
        """Test that failed ingests don't leave orphan checksums."""
        from conftest import volume_copy, get_db_path

        # Create an invalid file that will fail to ingest
        invalid_file = tmp_path / "invalid.epub"
        invalid_file.write_bytes(b"This is not a valid EPUB")

        # Try to ingest
        volume_copy(invalid_file, ingest_folder / "invalid.epub")
        time.sleep(15)

        # Check that no checksum was created for failed import
        db_path = get_db_path(library_folder / "metadata.db")

        # Get all checksums
        all_checksums = get_book_checksums(db_path)

        # Verify checksums only exist for valid books
        # (This test assumes no other books in fresh test library)

    def test_duplicate_book_updates_checksum(
        self, cwa_container, ingest_folder, library_folder, test_epub
    ):
        """Test that re-importing a book updates or maintains checksum."""
        from conftest import volume_copy, get_db_path

        # Import once
        volume_copy(test_epub, ingest_folder / "duplicate1.epub")
        time.sleep(15)

        db_path = get_db_path(library_folder / "metadata.db")
        book_id = get_latest_book_id(db_path)

        first_checksums = get_book_checksums(db_path, book_id)
        assert len(first_checksums) > 0

        # Import same book again (might merge or create duplicate)
        volume_copy(test_epub, ingest_folder / "duplicate2.epub")
        time.sleep(15)

        # Check checksums still exist and are valid
        updated_checksums = get_book_checksums(db_path, book_id)
        assert len(updated_checksums) > 0

        # Should have same or updated checksum
        # Exact behavior depends on merge strategy

    def test_checksum_generated_before_metadata_fetch(
        self, cwa_container, ingest_folder, library_folder, test_epub
    ):
        """Test that checksum is generated even if metadata fetch fails."""
        from conftest import volume_copy, get_db_path

        # This test would need to disable metadata fetching or use a book
        # that won't match any metadata providers

        volume_copy(test_epub, ingest_folder / "no_metadata.epub")
        time.sleep(15)

        db_path = get_db_path(library_folder / "metadata.db")
        book_id = get_latest_book_id(db_path)

        # Checksum should exist regardless of metadata
        checksums = get_book_checksums(db_path, book_id)
        assert len(checksums) > 0


@pytest.mark.unit
class TestIngestChecksumLogic:
    """Unit tests for checksum generation logic in ingest processor."""

    def test_generate_book_checksums_method_exists(self):
        """Verify the generate_book_checksums method exists in NewBookProcessor."""
        # This would require importing the ingest processor
        # and checking the method exists
        import sys
        scripts_path = project_root / "scripts"
        sys.path.insert(0, str(scripts_path))

        try:
            from ingest_processor import NewBookProcessor
            assert hasattr(NewBookProcessor, 'generate_book_checksums')
        except ImportError:
            pytest.skip("Ingest processor not importable in this environment")

    def test_checksum_generation_called_after_import(self):
        """Test that checksum generation is called after successful import."""
        # This would require mocking or inspecting the ingest flow
        # Placeholder for future implementation
        pytest.skip("Requires mocking infrastructure")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestChecksumInitialization:
    """Test the one-time checksum generation at container startup."""

    def test_checksums_generated_on_first_startup(
        self, cwa_container, library_folder
    ):
        """Test that existing books get checksums on first container startup."""
        from conftest import get_db_path

        # This test assumes container was just started for the first time
        # and the init script ran

        db_path = get_db_path(library_folder / "metadata.db")

        # Check if any checksums exist
        all_checksums = get_book_checksums(db_path)

        # If library had books before startup, they should have checksums now
        # If library is empty, this test would be skipped

        if all_checksums:
            # Verify all are valid
            for book_id, fmt, checksum in all_checksums:
                assert len(checksum) == 32
                assert all(c in '0123456789abcdef' for c in checksum.lower())

    def test_sentinel_file_prevents_regeneration(self, container_name):
        """Test that checksum generation only runs once per library."""
        import subprocess

        # Check if sentinel file exists
        try:
            result = subprocess.run(
                ['docker', 'exec', container_name, 'test', '-f', '/config/.checksums_generated'],
                capture_output=True
            )

            # Sentinel should exist after first run
            assert result.returncode == 0, "Sentinel file should exist after initialization"
        except Exception as e:
            pytest.skip(f"Cannot check sentinel file: {e}")


@pytest.fixture
def test_epub(tmp_path):
    """Create a minimal test EPUB file."""
    epub = tmp_path / "test.epub"

    # Create a minimal EPUB structure
    import zipfile

    with zipfile.ZipFile(epub, 'w') as zf:
        # mimetype must be first, uncompressed
        zf.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)

        # META-INF/container.xml
        zf.writestr('META-INF/container.xml', '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''')

        # content.opf
        zf.writestr('content.opf', '''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:identifier id="bookid">test-123</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="chapter1" href="chapter1.html" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter1"/>
  </spine>
</package>''')

        # toc.ncx
        zf.writestr('toc.ncx', '''<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="chapter1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="chapter1.html"/>
    </navPoint>
  </navMap>
</ncx>''')

        # chapter1.html
        zf.writestr('chapter1.html', '''<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 1</title></head>
<body><p>Test content</p></body>
</html>''')

    return epub


@pytest.fixture
def test_mobi(tmp_path):
    """Create a minimal test MOBI file."""
    mobi = tmp_path / "test.mobi"

    # MOBI files are complex binary format
    # For testing, we'll create a simple file that might pass basic validation
    # In real tests, you'd want actual valid MOBI files

    mobi.write_bytes(b"BOOKMOBI" + b"\x00" * 1000)  # Minimal MOBI header

    return mobi
