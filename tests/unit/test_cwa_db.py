# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Unit Tests for CWA Database Module

These tests verify the CWA_DB class functions correctly in isolation.
"""

import pytest
import sys

# Add scripts directory to path
sys.path.insert(0, '/app/calibre-web-automated/scripts/')

from cwa_db import CWA_DB


@pytest.mark.unit
class TestCWADBInitialization:
    """Test CWA database initialization and schema creation."""
    
    def test_database_creates_successfully(self, temp_cwa_db):
        """Verify database is created and accessible."""
        assert temp_cwa_db is not None
        assert temp_cwa_db.con is not None
        assert temp_cwa_db.cur is not None
    
    def test_all_required_tables_exist(self, temp_cwa_db):
        """Verify all required tables are created."""
        expected_tables = {
            'cwa_enforcement',
            'cwa_import', 
            'cwa_conversions',
            'epub_fixes',
            'cwa_settings'
        }
        
        # Extract table names from CREATE TABLE statements
        import re
        actual_table_names = set()
        for table_stmt in temp_cwa_db.tables:
            match = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)\(', table_stmt)
            if match:
                actual_table_names.add(match.group(1))
        
        assert expected_tables.issubset(actual_table_names), \
            f"Missing tables: {expected_tables - actual_table_names}"
    
    def test_schema_matches_expected(self, temp_cwa_db):
        """Verify database schema structure is correct."""
        # Check that schema was loaded
        assert temp_cwa_db.schema is not None
        assert len(temp_cwa_db.schema) > 0


@pytest.mark.unit
class TestCWADBSettings:
    """Test CWA settings management."""
    
    def test_default_settings_initialized(self, temp_cwa_db):
        """Verify default settings are created on initialization."""
        settings = temp_cwa_db.get_cwa_settings()
        assert settings is not None
        assert isinstance(settings, dict)
    
    def test_settings_have_expected_keys(self, temp_cwa_db):
        """Verify all expected settings keys are present"""
        settings = temp_cwa_db.get_cwa_settings()
        
        expected_keys = ['auto_backup_imports', 'auto_convert', 'auto_convert_target_format']
        for key in expected_keys:
            assert key in settings, f"Missing expected setting: {key}"
    
    def test_can_update_setting(self, temp_cwa_db):
        """Test updating a setting"""
        temp_cwa_db.update_cwa_settings({'auto_backup_imports': False})
        settings = temp_cwa_db.get_cwa_settings()
        assert settings['auto_backup_imports'] == False
    
    def test_setting_persists_across_queries(self, temp_cwa_db):
        """Test that settings persist between queries"""
        temp_cwa_db.update_cwa_settings({'auto_convert_target_format': 'mobi'})
        settings1 = temp_cwa_db.get_cwa_settings()
        settings2 = temp_cwa_db.get_cwa_settings()
        assert settings1['auto_convert_target_format'] == settings2['auto_convert_target_format'] == 'mobi'


@pytest.mark.unit  
class TestCWADBEnforcementLogging:
    """Test enforcement operation logging."""
    
    def test_can_insert_enforcement_log(self, temp_cwa_db):
        """Verify enforcement logs can be inserted."""
        log_info = {
            'timestamp': '2024-01-01 12:00:00',
            'book_id': 1,
            'title': 'Test Book',
            'authors': 'Test Author',
            'file_path': '/test/path.epub'
        }
        temp_cwa_db.enforce_add_entry_from_log(log_info)
        
        # Verify entry exists in database (schema: id, timestamp, book_id, book_title, author, file_path, trigger_type)
        temp_cwa_db.cur.execute("SELECT * FROM cwa_enforcement WHERE book_title='Test Book'")
        result = temp_cwa_db.cur.fetchone()
        assert result is not None
        assert result[3] == 'Test Book'  # Column 3 is book_title
        assert result[2] == 1  # Column 2 is book_id
    
    def test_enforcement_log_has_timestamp(self, temp_cwa_db):
        """Verify enforcement logs include timestamp."""
        log_info = {
            'timestamp': '2024-01-01 12:00:00',
            'book_id': 1,
            'title': 'Test Book',
            'authors': 'Test Author',
            'file_path': '/test/path.epub'
        }
        temp_cwa_db.enforce_add_entry_from_log(log_info)
        
        # Query database directly
        temp_cwa_db.cur.execute("SELECT timestamp FROM cwa_enforcement WHERE book_id=1")
        result = temp_cwa_db.cur.fetchone()
        assert result is not None
        assert result[0] == '2024-01-01 12:00:00'
    
    def test_multiple_enforcement_logs(self, temp_cwa_db):
        """Verify multiple enforcement operations are logged correctly."""
        # Get current count first (may have entries from previous tests in this class)
        temp_cwa_db.cur.execute("SELECT COUNT(*) FROM cwa_enforcement")
        initial_count = temp_cwa_db.cur.fetchone()[0]
        
        # Insert multiple logs using production API
        for i in range(5):
            log_info = {
                'timestamp': f'2024-01-01 12:00:0{i}',
                'book_id': 100 + i,  # Use unique IDs to avoid conflicts
                'title': f'Multi-Book {i}',
                'authors': f'Author {i}',
                'file_path': f'/test/multi-book{i}.epub'
            }
            temp_cwa_db.enforce_add_entry_from_log(log_info)
        
        # Verify 5 new entries were added
        temp_cwa_db.cur.execute("SELECT COUNT(*) FROM cwa_enforcement")
        final_count = temp_cwa_db.cur.fetchone()[0]
        assert final_count == initial_count + 5
        
        # Verify specific entry
        temp_cwa_db.cur.execute("SELECT book_title FROM cwa_enforcement WHERE book_id=103")
        result = temp_cwa_db.cur.fetchone()
        assert result[0] == 'Multi-Book 3'


@pytest.mark.unit
class TestCWADBImportLogging:
    """Test book import operation logging."""
    
    def test_can_insert_import_log(self, temp_cwa_db):
        """Verify import operations can be logged."""
        temp_cwa_db.import_add_entry(
            filename="book.epub",
            original_backed_up="true"
        )
        
        # Verify entry exists
        temp_cwa_db.cur.execute("SELECT * FROM cwa_import WHERE filename='book.epub'")
        result = temp_cwa_db.cur.fetchone()
        assert result is not None
        assert result[2] == 'book.epub'  # filename column
        assert result[3] == 'true'  # original_backed_up column
    
    def test_import_log_includes_metadata(self, temp_cwa_db):
        """Verify import logs capture key metadata."""
        temp_cwa_db.import_add_entry(
            filename="test_book.mobi",
            original_backed_up="false"
        )
        
        # Verify entry with timestamp
        temp_cwa_db.cur.execute("SELECT * FROM cwa_import WHERE filename='test_book.mobi'")
        result = temp_cwa_db.cur.fetchone()
        
        assert result is not None
        assert result[1] is not None  # timestamp column
        assert result[2] == "test_book.mobi"  # filename
        assert result[3] == "false"  # original_backed_up


@pytest.mark.unit
class TestCWADBConversionLogging:
    """Test format conversion logging."""
    
    def test_can_insert_conversion_log(self, temp_cwa_db):
        """Verify conversion operations can be logged."""
        temp_cwa_db.insert_conversion_log(
            book_id=1,
            title="Test Book",
            from_format="AZW3",
            to_format="EPUB",
            success=True
        )
        
        logs = temp_cwa_db.query_conversion_logs(limit=1)
        assert len(logs) == 1
        assert logs[0]['from_format'] == "AZW3"
        assert logs[0]['to_format'] == "EPUB"
        assert logs[0]['success'] == True
    
    def test_conversion_failure_logged(self, temp_cwa_db):
        """Verify failed conversions are logged."""
        temp_cwa_db.insert_conversion_log(
            book_id=1,
            title="Test Book",
            from_format="PDF",
            to_format="EPUB",
            success=False,
            error_message="Conversion failed: unsupported PDF type"
        )
        
        logs = temp_cwa_db.query_conversion_logs(limit=1)
        assert logs[0]['success'] == False
        assert 'error_message' in logs[0]
        assert "unsupported PDF" in logs[0]['error_message']


@pytest.mark.unit
class TestCWADBStatistics:
    """Test statistics aggregation functions."""
    
    def test_can_get_total_imports(self, temp_cwa_db):
        """Verify total imports count is calculated correctly."""
        # Insert some import logs
        for i in range(10):
            temp_cwa_db.insert_import_log(
                book_id=i,
                title=f"Book {i}",
                format="EPUB",
                file_path=f"/path/{i}.epub"
            )
        
        total = temp_cwa_db.get_total_imports()
        assert total == 10
    
    def test_can_get_total_conversions(self, temp_cwa_db):
        """Verify total conversions count is calculated correctly."""
        # Insert conversion logs
        for i in range(5):
            temp_cwa_db.insert_conversion_log(
                book_id=i,
                title=f"Book {i}",
                from_format="MOBI",
                to_format="EPUB",
                success=True
            )
        
        total = temp_cwa_db.get_total_conversions()
        assert total == 5
    
    def test_statistics_reflect_all_operations(self, temp_cwa_db):
        """Verify statistics aggregate across all operation types."""
        # Mix of operations
        temp_cwa_db.insert_import_log(1, "Book 1", "EPUB", "/path/1.epub")
        temp_cwa_db.insert_conversion_log(1, "Book 1", "EPUB", "MOBI", True)
        temp_cwa_db.insert_enforcement_log(1, "Book 1", "cover")
        
        # All counts should be 1
        assert temp_cwa_db.get_total_imports() == 1
        assert temp_cwa_db.get_total_conversions() == 1
        assert temp_cwa_db.get_total_enforcements() == 1


@pytest.mark.unit
class TestCWADBErrorHandling:
    """Test database error handling and edge cases."""
    
    def test_handles_missing_database_gracefully(self, tmp_path, monkeypatch):
        """Verify graceful handling when database doesn't exist."""
        # Point to non-existent path
        monkeypatch.setenv('CWA_DB_PATH', str(tmp_path / "nonexistent"))
        
        # This should create the database, not crash
        db = CWA_DB(verbose=False)
        assert db.con is not None
    
    def test_handles_invalid_query_gracefully(self, temp_cwa_db):
        """Verify invalid queries don't crash the application."""
        # Attempt invalid query
        try:
            temp_cwa_db.cur.execute("SELECT * FROM nonexistent_table")
            pytest.fail("Should have raised an exception")
        except Exception as e:
            # This is expected
            assert "no such table" in str(e).lower()
    
    def test_connection_can_be_closed_safely(self, temp_cwa_db):
        """Verify database connection can be closed without errors."""
        temp_cwa_db.con.close()
        # Should not raise exception


if __name__ == '__main__':
    # Allow running directly
    pytest.main([__file__, '-v'])
