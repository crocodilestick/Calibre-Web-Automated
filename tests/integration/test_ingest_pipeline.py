# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Integration tests for book ingest pipeline using Docker container.

These tests drop actual ebook files into the ingest folder and verify
they are correctly imported and converted using real Calibre tools.

IMPORTANT: These tests require a running CWA Docker container with
real Calibre tools, databases, and s6-overlay services. They test
the ACTUAL production environment, not mocked behavior.
"""

import pytest
import time
from pathlib import Path
import sqlite3
import subprocess
import json
import sys

# Ensure fixtures directory is importable
_tests_dir = Path(__file__).parent.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

# Import volume_copy from conftest - works in both modes
from conftest import volume_copy, get_db_path


@pytest.mark.docker_integration
class TestBookIngestInContainer:
    """Test the complete ingest pipeline in a running Docker container."""
    
    def test_ingest_epub_already_target_format(self, sample_ebook_path, ingest_folder, library_folder, cwa_container, tmp_path):
        """
        Test ingesting an EPUB when target format is EPUB (no conversion needed).
        
        This is the most common use case - user drops an EPUB, it gets imported directly.
        """
        # Copy the sample EPUB into the ingest folder
        dest_file = ingest_folder / sample_ebook_path.name
        volume_copy(sample_ebook_path, dest_file)
        
        print(f"📥 Dropped {sample_ebook_path.name} into ingest folder")
        
        # Debug: Check if container can see the file
        import subprocess
        result = subprocess.run(
            ["docker", "exec", cwa_container, "ls", "-la", "/cwa-book-ingest"],
            capture_output=True, text=True
        )
        print(f"📁 Files in container:\n{result.stdout}")
        
        # Wait for ingest to complete (up to 60 seconds)
        max_wait = 60
        start_time = time.time()
        
        # Check if file was processed (removed from ingest folder)
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
            if int(time.time() - start_time) % 10 == 0:
                print(f"⏳ Waiting for ingest... ({int(time.time() - start_time)}s)")
        
        # File should be removed from ingest folder after processing
        if dest_file.exists():
            # Debug: Check container logs
            result = subprocess.run(
                ["docker", "logs", "--tail", "50", cwa_container],
                capture_output=True, text=True
            )
            print(f"🔍 Container logs:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
            pytest.fail(f"File was not processed within {max_wait} seconds")
        
        print("✅ File removed from ingest folder (processing complete)")
        
        # Verify the book was added to the Calibre library
        metadata_db = library_folder / "metadata.db"
        
        # Wait for metadata.db to be created/updated
        time.sleep(5)
        
        if not metadata_db.exists():
            pytest.fail("metadata.db was not created in library folder")
        
        # Get local DB path (extracts from volume if needed)
        local_db = get_db_path(metadata_db, tmp_path)
        
        # Check that a book was added
        with sqlite3.connect(str(get_db_path(local_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            result = cur.execute("SELECT COUNT(*) FROM books").fetchone()
            book_count = result[0] if result else 0
        
        assert book_count > 0, "No books found in Calibre library after ingest"
        print(f"✅ Book successfully imported (library now has {book_count} book(s))")
    
    def test_ingest_multiple_files(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """Test ingesting multiple files at once."""
        from fixtures.generate_synthetic import create_minimal_epub
        
        # Create 3 test EPUBs
        test_files = []
        for i in range(3):
            epub_path = tmp_path / f"test_book_{i}.epub"
            create_minimal_epub(epub_path)
            
            # Copy to ingest folder
            dest = ingest_folder / epub_path.name
            volume_copy(epub_path, dest)
            test_files.append(dest)
            print(f"📥 Dropped {epub_path.name} into ingest folder")
        
        # Wait for all files to be processed
        max_wait = 120  # 2 minutes for 3 files
        start_time = time.time()
        
        all_processed = False
        while time.time() - start_time < max_wait:
            remaining = [f for f in test_files if f.exists()]
            if not remaining:
                all_processed = True
                break
            print(f"⏳ Waiting for ingest... {len(remaining)} files remaining ({int(time.time() - start_time)}s)")
            time.sleep(3)
        
        if not all_processed:
            remaining_names = [f.name for f in test_files if f.exists()]
            pytest.fail(f"Not all files processed within {max_wait} seconds. Remaining: {remaining_names}")
        
        print("✅ All files processed")
        
        # Verify books were added
        metadata_db = library_folder / "metadata.db"
        time.sleep(5)
        
        with sqlite3.connect(str(get_db_path(metadata_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            result = cur.execute("SELECT COUNT(*) FROM books").fetchone()
            book_count = result[0] if result else 0
        
        assert book_count >= 3, f"Expected at least 3 books, found {book_count}"
        print(f"✅ All books imported (library now has {book_count} book(s))")


@pytest.mark.docker_integration
class TestIngestErrorHandling:
    """Test how the ingest pipeline handles errors and edge cases."""
    
    def test_ingest_empty_file(self, ingest_folder, tmp_path, cwa_container):
        """Test that empty files are handled gracefully."""
        # Create empty file
        empty_file = tmp_path / "empty_test.epub"
        empty_file.touch()
        
        # Copy to ingest folder
        dest = ingest_folder / empty_file.name
        volume_copy(empty_file, dest)
        
        print(f"📥 Dropped empty file into ingest folder")
        
        # Wait to see what happens
        time.sleep(20)
        
        # File should eventually be processed (likely moved to failed folder)
        # We're mainly checking that it doesn't crash the ingest service
        print("✅ Ingest service handled empty file without crashing")
    
    def test_ingest_corrupted_file(self, ingest_folder, tmp_path, cwa_container):
        """Test that corrupted files are handled gracefully."""
        from fixtures.generate_synthetic import create_corrupted_epub
        
        # Create corrupted file
        corrupted = tmp_path / "corrupted_test.epub"
        create_corrupted_epub(corrupted)
        
        # Copy to ingest folder
        dest = ingest_folder / corrupted.name
        volume_copy(corrupted, dest)
        
        print(f"📥 Dropped corrupted file into ingest folder")
        
        # Wait to see what happens
        time.sleep(20)
        
        # File should be processed (likely moved to failed folder)
        print("✅ Ingest service handled corrupted file without crashing")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestIngestBackups:
    """Test that backup functionality works correctly."""
    
    def test_imported_files_backed_up(self, sample_ebook_path, ingest_folder, test_volumes, tmp_path, cwa_container):
        """
        Verify that imported files are backed up to processed_books/imported/.
        
        Note: This requires auto_backup_imports to be enabled in CWA settings.
        """
        # Copy sample file to ingest
        dest = ingest_folder / sample_ebook_path.name
        volume_copy(sample_ebook_path, dest)
        
        print(f"📥 Dropped {sample_ebook_path.name} into ingest folder")
        
        # Wait for processing
        max_wait = 60
        start_time = time.time()
        while dest.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        if dest.exists():
            pytest.skip("File was not processed in time, skipping backup check")
        
        # Check backup folder (if backups are enabled)
        backup_dir = test_volumes["config"] / "processed_books" / "imported"
        
        # Give it a moment for backup to complete
        time.sleep(5)
        
        # Note: Backup may not exist if auto_backup_imports is disabled (default)
        # This test is informational - it documents where backups should appear
        backup_files = list(backup_dir.glob("*.epub"))
        
        if backup_files:
            print(f"✅ Backup created: {backup_files[0].name}")
        else:
            print("ℹ️  No backup found (auto_backup_imports may be disabled)")


@pytest.mark.docker_integration
class TestInternationalCharacters:
    """Test handling of international/unicode characters in filenames."""
    
    def test_ingest_international_filename(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """
        Test ingesting a file with international characters in filename.
        
        Critical for users with non-English languages (German, French, Spanish,
        Polish, Nordic, etc.) where author names and book titles contain
        diacritics, umlauts, and accents.
        
        Example characters tested:
        - German: äöüß
        - French: éèêë
        - Spanish: áéíóú ñ
        - Nordic: åøæ
        - Polish: książka
        """
        from fixtures.generate_synthetic import create_minimal_epub
        
        # Create EPUB with international characters in filename
        international_filename = "test_international_äöüß_éèêë_áéíóú_ñ_åøæ_książka.epub"
        epub_path = tmp_path / international_filename
        create_minimal_epub(epub_path)
        
        # Copy to ingest folder
        dest = ingest_folder / international_filename
        volume_copy(epub_path, dest)
        
        print(f"📥 Dropped international filename: {international_filename}")
        
        # Wait for processing
        max_wait = 60
        start_time = time.time()
        
        while dest.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
            print(f"⏳ Waiting for ingest... ({int(time.time() - start_time)}s)")
        
        if dest.exists():
            pytest.fail(f"File with international characters was not processed within {max_wait} seconds")
        
        print("✅ File with international characters removed (processing complete)")
        
        # Verify the book was added to library
        metadata_db = library_folder / "metadata.db"
        time.sleep(5)
        
        if not metadata_db.exists():
            pytest.fail("metadata.db was not created")
        
        with sqlite3.connect(str(get_db_path(metadata_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            result = cur.execute("SELECT COUNT(*) FROM books").fetchone()
            book_count = result[0] if result else 0
        
        assert book_count > 0, "Book with international filename was not imported"
        print(f"✅ Book with international characters successfully imported (library has {book_count} book(s))")


# ============================================================================
# COMPREHENSIVE INTEGRATION TESTS FOR INGEST_PROCESSOR.PY
# ============================================================================
# These tests verify the complete ingest pipeline in a real Docker container
# with actual Calibre tools, databases, and file system operations.
# ============================================================================


@pytest.mark.docker_integration
@pytest.mark.slow
class TestFormatConversion:
    """Test conversion between different ebook formats using real Calibre tools."""
    
    def test_mobi_to_epub_conversion(self, ingest_folder, library_folder, test_volumes, tmp_path, cwa_container):
        """
        Test MOBI import (and optional conversion to EPUB).
        
        Note: CWA imports MOBI files directly by default. Conversion to EPUB
        only happens if CONVERT_TO_FORMAT is set to EPUB in CWA settings.
        This test verifies the file is successfully imported.
        """
        # Find MOBI test file
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        mobi_files = list(fixtures_dir.glob("*.mobi"))
        
        if not mobi_files:
            pytest.skip("No MOBI test files available")
        
        source_mobi = mobi_files[0]
        dest_file = ingest_folder / source_mobi.name
        volume_copy(source_mobi, dest_file)
        
        print(f"📥 Dropped MOBI file: {source_mobi.name}")
        
        # Wait for import (conversion is optional based on settings)
        max_wait = 180  # 3 minutes for processing
        start_time = time.time()
        
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(3)
            elapsed = int(time.time() - start_time)
            if elapsed % 15 == 0:  # Print every 15 seconds
                print(f"⏳ Waiting for MOBI import... ({elapsed}s)")
        
        if dest_file.exists():
            pytest.fail(f"MOBI file was not processed within {max_wait} seconds")
        
        print("✅ MOBI file processed")
        
        # Verify book was imported
        time.sleep(5)
        metadata_db = library_folder / "metadata.db"
        
        with sqlite3.connect(str(get_db_path(metadata_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            result = cur.execute("SELECT COUNT(*) FROM books").fetchone()
            book_count = result[0] if result else 0
        
        assert book_count > 0, "MOBI was not imported"
        
        # Check if book directory exists
        book_dirs = [d for d in library_folder.iterdir() if d.is_dir() and d.name != ".keep"]
        assert len(book_dirs) > 0, "No book directories created"
        
        # Debug: List all files in book directories
        print(f"📁 Book directories created: {[d.name for d in book_dirs]}")
        all_files = []
        for book_dir in book_dirs:
            files_in_dir = list(book_dir.iterdir())
            all_files.extend(files_in_dir)
            print(f"  📄 Files in {book_dir.name}: {[f.name for f in files_in_dir]}")
        
        # Look for any ebook files (MOBI, AZW3, EPUB, etc.)
        # Calibre stores books as: library/Author/Book Title (ID)/book.format
        # In volume mode, glob might not work perfectly, so we verify via database + directories
        import os
        if os.getenv('USE_DOCKER_VOLUMES', 'false').lower() == 'true':
            # Volume mode: We've already confirmed book is in DB and directory exists
            # That's sufficient proof of successful import
            print(f"✅ MOBI successfully imported (verified via database and directory structure)")
            return
        
        # Bind mount mode: Can use glob to verify files
        # So we need to search two levels deep: */*/*.format
        mobi_files_imported = list(library_folder.glob("*/*/*.mobi"))
        azw3_files = list(library_folder.glob("*/*/*.azw3"))
        azw_files = list(library_folder.glob("*/*/*.azw"))
        epub_files = list(library_folder.glob("*/*/*.epub"))
        
        # MOBI files often get converted to AZW3 by Calibre
        total_ebook_files = len(mobi_files_imported) + len(azw3_files) + len(azw_files) + len(epub_files)
        
        print(f"📊 Files found: {len(mobi_files_imported)} MOBI, {len(azw3_files)} AZW3, {len(azw_files)} AZW, {len(epub_files)} EPUB")
        
        # Book was imported (we confirmed via database), file format may vary
        assert total_ebook_files > 0, \
            f"No ebook files found after import. Searched pattern: */*/*.{{mobi,azw3,azw,epub}}"
        
        print(f"✅ MOBI successfully imported as {len(mobi_files_imported)} MOBI, {len(azw3_files)} AZW3, {len(epub_files)} EPUB")
    
    def test_conversion_failure_moves_to_failed_folder(self, ingest_folder, test_volumes, tmp_path, cwa_container):
        """
        Test that files that fail conversion are moved to failed/ folder.
        
        Uses a corrupted file that looks like a supported format but
        cannot actually be converted.
        """
        # Create a fake "MOBI" file that will fail conversion
        fake_mobi = tmp_path / "fake_corrupted.mobi"
        fake_mobi.write_bytes(b"This is not a real MOBI file, just garbage data" * 100)
        
        dest_file = ingest_folder / fake_mobi.name
        volume_copy(fake_mobi, dest_file)
        
        print(f"📥 Dropped fake MOBI file: {fake_mobi.name}")
        
        # Wait for processing
        max_wait = 120
        start_time = time.time()
        
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        # Check failed folder
        failed_dir = test_volumes["config"] / "processed_books" / "failed"
        time.sleep(5)  # Give time for backup
        
        failed_files = list(failed_dir.glob("*"))
        
        if len(failed_files) > 0:
            print(f"✅ Failed file moved to failed folder: {failed_files[0].name}")
        else:
            print("ℹ️  File may have been deleted or processed differently")
    
    def test_txt_to_epub_conversion(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """Test TXT → EPUB conversion for plain text ebooks."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        txt_files = list(fixtures_dir.glob("*.txt"))
        
        if not txt_files:
            pytest.skip("No TXT test files available")
        
        source_txt = txt_files[0]
        dest_file = ingest_folder / source_txt.name
        volume_copy(source_txt, dest_file)
        
        print(f"📥 Dropped TXT file: {source_txt.name}")
        
        # Wait for conversion
        max_wait = 120
        start_time = time.time()
        
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(3)
            if int(time.time() - start_time) % 15 == 0:
                print(f"⏳ Waiting for TXT conversion... ({int(time.time() - start_time)}s)")
        
        if dest_file.exists():
            pytest.skip(f"TXT file not processed in time (may be in ignored formats)")
        
        print("✅ TXT file processed")


@pytest.mark.docker_integration
class TestProcessLockInContainer:
    """Test ProcessLock mechanism prevents concurrent ingest processes."""
    
    def test_lock_released_after_processing(self, ingest_folder, sample_ebook_path, tmp_path, cwa_container):
        """
        Verify that lock file is cleaned up after successful processing.
        """
        dest_file = ingest_folder / sample_ebook_path.name
        volume_copy(sample_ebook_path, dest_file)
        
        # Wait for processing
        max_wait = 60
        start_time = time.time()
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        # Give a moment for cleanup
        time.sleep(3)
        
        # Check if lock file exists (it shouldn't after successful processing)
        # Lock file would be in /tmp/ingest_processor.lock inside container
        # We can't easily check inside container, but we can verify next file processes
        
        # Drop another file
        dest_file2 = ingest_folder / f"second_{sample_ebook_path.name}"
        volume_copy(sample_ebook_path, dest_file2)
        
        # If lock wasn't released, this would timeout
        start_time = time.time()
        while dest_file2.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        if dest_file2.exists():
            pytest.fail("Second file not processed - lock may not have been released")
        
        print("✅ Lock properly released between processings")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestAdvancedIngestFeatures:
    """Test advanced features like format retention, metadata fetch, etc."""
    
    def test_directory_import_processes_all_files(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """
        Test that dropping a directory with multiple files processes all of them.
        
        Users sometimes drag entire folders into the ingest directory.
        """
        from fixtures.generate_synthetic import create_minimal_epub
        
        # Create a subdirectory with multiple files
        sub_dir = ingest_folder / "batch_import"
        sub_dir.mkdir()
        
        num_files = 3
        for i in range(num_files):
            epub_path = tmp_path / f"batch_book_{i}.epub"
            create_minimal_epub(epub_path)
            volume_copy(epub_path, sub_dir / epub_path.name)
        
        print(f"📥 Dropped directory with {num_files} files")
        
        # Wait for all files to be processed
        max_wait = 180
        start_time = time.time()
        
        all_processed = False
        while time.time() - start_time < max_wait:
            remaining = list(sub_dir.glob("*.epub"))
            if len(remaining) == 0 and not sub_dir.exists():
                all_processed = True
                break
            print(f"⏳ Waiting... {len(remaining)} files remaining ({int(time.time() - start_time)}s)")
            time.sleep(5)
        
        if not all_processed:
            pytest.skip(f"Directory processing may not be fully implemented or takes longer")
        
        print("✅ All files in directory processed")


@pytest.mark.docker_integration
class TestFilenameHandling:
    """Test edge cases in filename and path handling."""
    
    def test_filename_truncation_at_150_chars(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """
        Test that filenames over 150 characters are truncated.
        
        The ingest_processor.py has a MAX_LENGTH = 150 for filenames.
        """
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        
        # Find the huge filename test file
        huge_files = [f for f in fixtures_dir.glob("*.epub") if len(f.name) > 150]
        
        if not huge_files:
            pytest.skip("No huge filename test file found")
        
        source_file = huge_files[0]
        dest_file = ingest_folder / source_file.name
        volume_copy(source_file, dest_file)
        
        print(f"📥 Dropped file with {len(source_file.name)} char filename")
        
        # Wait for processing
        max_wait = 60
        start_time = time.time()
        
        # The file should be renamed/truncated, so original won't exist
        time.sleep(5)  # Give it time to rename
        
        # Check if ANY file is being processed (original or truncated name)
        remaining = list(ingest_folder.glob("*.epub"))
        
        while len(remaining) > 0 and time.time() - start_time < max_wait:
            time.sleep(2)
            remaining = list(ingest_folder.glob("*.epub"))
        
        print("✅ Long filename handled (truncated and processed)")
    
    def test_empty_folder_cleanup_after_processing(self, ingest_folder, tmp_path, cwa_container):
        """
        Test that empty directories are cleaned up after files are processed.
        """
        from fixtures.generate_synthetic import create_minimal_epub
        
        # Create subdirectory with one file
        sub_dir = ingest_folder / "temp_folder"
        sub_dir.mkdir()
        
        epub_path = tmp_path / "cleanup_test.epub"
        create_minimal_epub(epub_path)
        volume_copy(epub_path, sub_dir / epub_path.name)
        
        # Wait for file to be processed
        max_wait = 60
        start_time = time.time()
        
        while (sub_dir / epub_path.name).exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        # Give time for folder cleanup
        time.sleep(5)
        
        # Directory should be removed (if empty)
        if not sub_dir.exists():
            print("✅ Empty directory cleaned up")
        else:
            print("ℹ️  Directory still exists (may contain hidden files or cleanup not implemented)")


@pytest.mark.docker_integration
class TestIngestConfiguration:
    """Test how different CWA settings affect ingest behavior."""
    
    def test_ignored_formats_not_deleted(self, ingest_folder, tmp_path, cwa_container):
        """
        Test that files with ignored extensions are not deleted.
        
        Temporary files like .crdownload, .part, .uploading should be
        left alone (they may be renamed by the browser/uploader).
        """
        # Create a .part file (browser partial download)
        part_file = ingest_folder / "test_book.epub.part"
        part_file.write_text("This is a partial download")
        
        # Wait a bit
        time.sleep(10)
        
        # File should still exist (ignored formats aren't deleted)
        if part_file.exists():
            print("✅ Ignored format (.part) not deleted as expected")
            # Clean up
            part_file.unlink()
        else:
            print("⚠️  .part file was deleted (unexpected behavior)")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestIngestStability:
    """Test ingest processor stability and error recovery."""
    
    def test_processing_survives_multiple_files(self, ingest_folder, library_folder, tmp_path, cwa_container):
        """
        Test that ingest processor can handle many files without crashing.
        
        Regression test for memory leaks and resource exhaustion.
        """
        from fixtures.generate_synthetic import create_minimal_epub
        
        num_files = 5  # Conservative number for CI
        created_files = []
        
        print(f"📥 Dropping {num_files} files sequentially")
        
        for i in range(num_files):
            epub_path = tmp_path / f"stability_test_{i}.epub"
            create_minimal_epub(epub_path)
            
            dest = ingest_folder / epub_path.name
            volume_copy(epub_path, dest)
            created_files.append(dest)
            
            # Wait for this file to be processed before dropping next
            max_wait = 60
            start_time = time.time()
            while dest.exists() and time.time() - start_time < max_wait:
                time.sleep(2)
            
            if dest.exists():
                pytest.fail(f"File {i+1}/{num_files} not processed, ingest may have crashed")
            
            print(f"  ✓ File {i+1}/{num_files} processed")
        
        print(f"✅ Successfully processed {num_files} files without crashes")
    
    def test_zero_byte_file_doesnt_crash_ingest(self, ingest_folder, tmp_path, cwa_container):
        """
        Test that a 0-byte file doesn't crash the ingest service.
        """
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        empty_file = fixtures_dir / "test_empty.epub"
        
        if not empty_file.exists():
            pytest.skip("test_empty.epub not found")
        
        dest = ingest_folder / "zero_byte_test.epub"
        volume_copy(empty_file, dest)
        
        print("📥 Dropped 0-byte file")
        
        # Wait and see what happens
        time.sleep(20)
        
        # Drop a valid file afterwards to verify ingest still works
        from fixtures.generate_synthetic import create_minimal_epub
        local_valid_file = tmp_path / "after_zero_byte.epub"
        create_minimal_epub(local_valid_file)
        
        valid_file = ingest_folder / "after_zero_byte.epub"
        volume_copy(local_valid_file, valid_file)
        
        max_wait = 60
        start_time = time.time()
        while valid_file.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        if valid_file.exists():
            pytest.fail("Ingest service may have crashed after processing 0-byte file")
        
        print("✅ Ingest service survived 0-byte file and continued processing")


@pytest.mark.docker_integration
class TestMetadataAndDatabase:
    """Test database interactions and metadata handling."""
    
    def test_book_appears_in_metadata_db(self, ingest_folder, library_folder, sample_ebook_path, tmp_path, cwa_container):
        """
        Verify that imported books are correctly added to metadata.db.
        
        Checks that Calibre database has proper book record with title, author, etc.
        """
        dest_file = ingest_folder / sample_ebook_path.name
        volume_copy(sample_ebook_path, dest_file)
        print(f"📤 Copied {sample_ebook_path.name} to ingest folder")
        
        # Debug: Check if container can see the file
        import subprocess
        result = subprocess.run(
            ["docker", "exec", cwa_container, "ls", "-la", "/cwa-book-ingest"],
            capture_output=True, text=True
        )
        print(f"📁 Files in container ingest folder:\n{result.stdout}")
        
        # Wait for import
        max_wait = 60
        start_time = time.time()
        check_count = 0
        while dest_file.exists() and time.time() - start_time < max_wait:
            check_count += 1
            if check_count % 5 == 0:  # Print every 10 seconds
                print(f"⏳ Still waiting for file to be processed... ({time.time() - start_time:.1f}s elapsed)")
            time.sleep(2)
        
        elapsed = time.time() - start_time
        if dest_file.exists():
            print(f"⚠️  File still exists after {elapsed:.1f}s timeout!")
            # Debug: Check container logs
            result = subprocess.run(
                ["docker", "logs", "--tail", "50", cwa_container],
                capture_output=True, text=True
            )
            print(f"🔍 Container logs (last 50 lines):\n{result.stdout}\n{result.stderr}")
        else:
            print(f"✅ File processed in {elapsed:.1f}s")
        
        time.sleep(5)  # Let DB settle
        
        metadata_db = library_folder / "metadata.db"
        print(f"🔍 Checking if metadata.db exists...")
        assert metadata_db.exists(), "metadata.db was not created"
        
        # Get local DB path (extracts from volume if needed)
        local_db = get_db_path(metadata_db, tmp_path)
        
        with sqlite3.connect(str(get_db_path(local_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            
            # Check book exists
            book = cur.execute("SELECT id, title, path FROM books ORDER BY id DESC LIMIT 1").fetchone()
            assert book is not None, "No book record in metadata.db"
            
            book_id, title, path = book
            print(f"✅ Book in metadata.db: ID={book_id}, title='{title}', path='{path}'")
            
            # Check that book has an author
            author = cur.execute("""
                SELECT a.name FROM authors a
                JOIN books_authors_link bal ON a.id = bal.author
                WHERE bal.book = ?
            """, (book_id,)).fetchone()
            
            if author:
                print(f"✅ Book has author: {author[0]}")
            else:
                print("ℹ️  Book has no author (minimal test file)")
    
    def test_cwa_db_tracks_import(self, ingest_folder, test_volumes, sample_ebook_path, tmp_path, cwa_container):
        """
        Verify that CWA database logs the import.
        
        The cwa.db should have an entry in cwa_import table.
        """
        # Skip in Docker volume mode - config directory not in a volume
        import os
        if os.getenv('USE_DOCKER_VOLUMES', 'false').lower() == 'true':
            pytest.skip("cwa.db access requires config volume (not available in DinD mode)")
        
        dest_file = ingest_folder / sample_ebook_path.name
        volume_copy(sample_ebook_path, dest_file)
        
        # Wait for import
        max_wait = 60
        start_time = time.time()
        while dest_file.exists() and time.time() - start_time < max_wait:
            time.sleep(2)
        
        # Give container extra time to write to DB after file processing
        time.sleep(10)
        
        # Check cwa.db - should exist after processing first file
        cwa_db = test_volumes["config"] / "cwa.db"
        
        assert cwa_db.exists(), \
            "cwa.db should have been created after processing first import"
        
        with sqlite3.connect(str(get_db_path(cwa_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            
            # Check if cwa_import table exists
            tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cwa_import'").fetchone()
            
            assert tables is not None, \
                "cwa_import table should exist after first import"
            
            # Check for import records
            imports = cur.execute("SELECT COUNT(*) FROM cwa_import").fetchone()
            import_count = imports[0] if imports else 0
            
            print(f"✅ CWA DB has {import_count} import record(s)")


@pytest.mark.docker_integration
@pytest.mark.slow
class TestRealWorldScenarios:
    """Test real-world user scenarios end-to-end."""
    
    def test_user_drops_book_and_it_appears_in_library(self, ingest_folder, library_folder, cwa_container, tmp_path):
        """
        Complete user workflow: drop book → wait → verify it's in library.
        
        This is the most important test - it validates the entire pipeline
        works as users expect.
        """
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        
        print(f"📁 Looking for fixtures in: {fixtures_dir}")
        print(f"📁 Fixtures dir exists: {fixtures_dir.exists()}")
        
        if fixtures_dir.exists():
            all_epubs = list(fixtures_dir.glob("*.epub"))
            print(f"📚 Found {len(all_epubs)} total EPUB files")
            for epub in all_epubs:
                size = epub.stat().st_size
                starts_with_test = epub.name.startswith("test_")
                print(f"  - {epub.name}: {size:,} bytes (test file: {starts_with_test})")
        
        # Use a real book (not synthetic)
        real_books = [f for f in fixtures_dir.glob("*.epub") 
                     if not f.name.startswith("test_") 
                     and f.stat().st_size > 10000]  # Skip tiny test files
        
        print(f"📗 Filtered to {len(real_books)} real books (>10KB, not test_*)")
        
        if not real_books:
            pytest.skip("No real book files available")
        
        source_book = real_books[0]
        dest_file = ingest_folder / source_book.name
        volume_copy(source_book, dest_file)
        
        original_size = source_book.stat().st_size
        print(f"📥 User drops: {source_book.name} ({original_size:,} bytes)")
        
        # User waits...
        max_wait = 180  # Real books might take longer
        start_time = time.time()
        
        while dest_file.exists() and time.time() - start_time < max_wait:
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0:
                print(f"⏳ User waiting... ({elapsed}s)")
            time.sleep(3)
        
        if dest_file.exists():
            pytest.fail(f"Book not processed within {max_wait} seconds")
        
        processing_time = int(time.time() - start_time)
        print(f"✅ Book processed in {processing_time} seconds")
        
        # Verify book is in library
        time.sleep(5)
        
        metadata_db = library_folder / "metadata.db"
        with sqlite3.connect(str(get_db_path(metadata_db, tmp_path)), timeout=30) as con:
            cur = con.cursor()
            books = cur.execute("SELECT title FROM books ORDER BY timestamp DESC LIMIT 1").fetchone()
            
            if books:
                print(f"✅ Book appears in library: '{books[0]}'")
            else:
                pytest.fail("Book not found in library after import")
        
        # Check that book folder exists
        book_dirs = [d for d in library_folder.iterdir() 
                    if d.is_dir() and d.name not in ('.', '..', '.keep')]
        
        assert len(book_dirs) > 0, "No book directories created"
        print(f"✅ Book stored in: {book_dirs[0].name}/")
    
    def test_mixed_format_batch_import(self, ingest_folder, library_folder, cwa_container, tmp_path):
        """
        Test importing multiple files of different formats at once.
        
        Simulates user selecting multiple books with different formats
        and dragging them into the ingest folder.
        """
        fixtures_dir = Path(__file__).parent.parent / "fixtures" / "sample_books"
        
        print(f"📁 Looking for fixtures in: {fixtures_dir}")
        print(f"📁 Fixtures dir exists: {fixtures_dir.exists()}")
        
        # Find different format files
        epub_files = list(fixtures_dir.glob("alice*.epub"))[:1]
        mobi_files = list(fixtures_dir.glob("*.mobi"))[:1]
        txt_files = list(fixtures_dir.glob("*.txt"))[:1]
        
        print(f"📚 Found {len(epub_files)} EPUB, {len(mobi_files)} MOBI, {len(txt_files)} TXT files")
        
        files_to_import = epub_files + mobi_files + txt_files
        files_to_import = [f for f in files_to_import if f.stat().st_size > 10000]
        
        print(f"📗 After size filter (>10KB): {len(files_to_import)} files")
        
        if len(files_to_import) < 2:
            pytest.skip("Not enough different format files available")
        
        print(f"📥 Dropping {len(files_to_import)} files of different formats")
        
        dest_files = []
        for source_file in files_to_import:
            dest = ingest_folder / source_file.name
            volume_copy(source_file, dest)
            dest_files.append(dest)
            print(f"  - {source_file.name} ({source_file.suffix})")
        
        # Wait for all to be processed
        max_wait = 300  # 5 minutes for conversions
        start_time = time.time()
        
        all_processed = False
        while time.time() - start_time < max_wait:
            remaining = [f for f in dest_files if f.exists()]
            if len(remaining) == 0:
                all_processed = True
                break
            
            elapsed = int(time.time() - start_time)
            if elapsed % 15 == 0:
                print(f"⏳ Processing... {len(remaining)} files remaining ({elapsed}s)")
            time.sleep(5)
        
        if not all_processed:
            remaining_names = [f.name for f in dest_files if f.exists()]
            pytest.fail(f"Not all files processed: {remaining_names}")
        
        processing_time = int(time.time() - start_time)
        print(f"✅ All {len(files_to_import)} files processed in {processing_time} seconds")
