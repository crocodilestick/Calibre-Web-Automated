# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Shared pytest fixtures and configuration for CWA tests.

This module contains common fixtures that are automatically available
to all tests without needing to import them explicitly.
"""

import pytest
import tempfile
import shutil
from pathlib import Path


# ============================================================================
# Temporary Directory Fixtures
# ============================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory that's cleaned up after the test."""
    yield tmp_path
    # Cleanup happens automatically with tmp_path


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary /config directory structure for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # Create subdirectories
    (config_dir / "processed_books" / "converted").mkdir(parents=True)
    (config_dir / "processed_books" / "imported").mkdir(parents=True)
    (config_dir / "processed_books" / "failed").mkdir(parents=True)
    (config_dir / "processed_books" / "fixed_originals").mkdir(parents=True)
    (config_dir / "log_archive").mkdir()
    (config_dir / ".cwa_conversion_tmp").mkdir()
    
    yield config_dir


@pytest.fixture
def temp_library_dir(tmp_path):
    """Create a temporary Calibre library directory for testing."""
    library = tmp_path / "calibre-library"
    library.mkdir()
    
    # Create minimal metadata.db
    import sqlite3
    db_path = library / "metadata.db"
    con = sqlite3.connect(str(db_path))
    
    # Minimal schema (just enough to not crash)
    con.execute("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Unknown',
            sort TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pubdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            series_index REAL NOT NULL DEFAULT 1.0,
            author_sort TEXT,
            isbn TEXT DEFAULT '',
            lccn TEXT DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            flags INTEGER NOT NULL DEFAULT 1,
            uuid TEXT,
            has_cover BOOL DEFAULT 0,
            last_modified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    con.execute("""
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE,
            sort TEXT COLLATE NOCASE,
            link TEXT NOT NULL DEFAULT ''
        )
    """)
    
    con.execute("""
        CREATE TABLE books_authors_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book INTEGER NOT NULL,
            author INTEGER NOT NULL,
            UNIQUE(book, author)
        )
    """)
    
    con.commit()
    con.close()
    
    yield library


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def temp_cwa_db(tmp_path, monkeypatch):
    """
    Create a temporary CWA database for testing.
    
    Uses monkeypatch to temporarily override the database path
    so tests don't interfere with real data.
    """
    import sys
    sys.path.insert(0, '/app/calibre-web-automated/scripts/')
    
    from cwa_db import CWA_DB
    
    # Override the database path
    db_path = tmp_path / "cwa.db"
    monkeypatch.setenv('CWA_DB_PATH', str(tmp_path))
    
    # Create the database
    db = CWA_DB(verbose=False)
    
    yield db
    
    # Cleanup
    if db.con:
        db.con.close()


# ============================================================================
# Sample Data Fixtures
# ============================================================================

@pytest.fixture
def sample_book_data():
    """Provide sample book metadata for testing."""
    return {
        'title': 'Test Book',
        'author': 'Test Author',
        'isbn': '9781234567890',
        'publisher': 'Test Publisher',
        'year': 2024,
        'language': 'eng',
        'description': 'A test book for unit testing',
        'tags': ['test', 'fiction']
    }


@pytest.fixture
def sample_user_data():
    """Provide sample user data for testing."""
    return {
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'TestPass123!',
        'role': 'user'
    }


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_calibre_tools(mocker):
    """
    Mock Calibre CLI tools (calibredb, ebook-convert, ebook-meta).
    
    Returns a dictionary of mocked subprocess calls.
    """
    mocks = {
        'calibredb': mocker.patch('subprocess.run'),
        'ebook_convert': mocker.patch('subprocess.run'),
        'ebook_meta': mocker.patch('subprocess.run')
    }
    
    # Configure default successful returns
    for mock in mocks.values():
        mock.return_value.returncode = 0
        mock.return_value.stdout = b'Success'
        mock.return_value.stderr = b''
    
    return mocks


# ============================================================================
# Skip Markers for Conditional Tests
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "requires_docker: mark test as requiring Docker environment"
    )
    config.addinivalue_line(
        "markers", "requires_calibre: mark test as requiring Calibre CLI tools"
    )


def pytest_collection_modifyitems(config, items):
    """
    Automatically skip tests based on environment.
    
    Skip Docker tests if not in Docker environment.
    Skip Calibre tests if Calibre tools not installed.
    """
    import shutil
    import os
    
    skip_docker = pytest.mark.skip(reason="Not running in Docker environment")
    skip_calibre = pytest.mark.skip(reason="Calibre tools not installed")
    
    in_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'
    has_calibre = shutil.which('calibredb') is not None
    
    for item in items:
        if "requires_docker" in item.keywords and not in_docker:
            item.add_marker(skip_docker)
        if "requires_calibre" in item.keywords and not has_calibre:
            item.add_marker(skip_calibre)
