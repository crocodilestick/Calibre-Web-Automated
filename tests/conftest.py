# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Shared pytest fixtures and configuration for CWA tests.

This module contains common fixtures that are automatically available
to all tests without needing to import them explicitly.

Environment Variables:
    USE_DOCKER_VOLUMES: Set to 'true' to use Docker volumes instead of bind mounts.
                       Required for Docker-in-Docker test environments.
                       Example: USE_DOCKER_VOLUMES=true pytest tests/integration/
"""

import os
import pytest
import tempfile
import shutil
import time
from pathlib import Path
from typing import Generator


# Check if we should use Docker volumes (for DinD environments)
USE_DOCKER_VOLUMES = os.getenv('USE_DOCKER_VOLUMES', 'false').lower() == 'true'

# Import volume_copy helper if in volume mode (available to all tests)
if USE_DOCKER_VOLUMES:
    print("\n🔄 Docker Volume mode enabled (USE_DOCKER_VOLUMES=true)")
    print("   Using Docker volumes instead of bind mounts for DinD compatibility\n")
    from conftest_volumes import volume_copy, VolumePath
else:
    # In bind mount mode, volume_copy is just shutil.copy2
    volume_copy = shutil.copy2
    VolumePath = None


def get_db_path(db_path, tmp_path=None):
    """
    Get a local filesystem path for database access.
    
    In bind mount mode: Returns the path directly
    In volume mode: Extracts DB to temp location and returns local path
    
    Args:
        db_path: Path or VolumePath to database file
        tmp_path: Temporary directory (required in volume mode)
    
    Returns:
        Path: Local filesystem path to database file
    """
    if USE_DOCKER_VOLUMES and isinstance(db_path, VolumePath):
        if tmp_path is None:
            raise ValueError("tmp_path required for database access in volume mode")
        return db_path.read_to_local(tmp_path)
    else:
        return db_path


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
    config.addinivalue_line(
        "markers",
        "docker_integration: mark test as requiring Docker container (slow)"
    )
    config.addinivalue_line(
        "markers", 
        "docker_e2e: mark test as end-to-end test requiring full Docker environment (very slow)"
    )


def pytest_collection_modifyitems(config, items):
    """
    Automatically skip tests based on environment.
    
    Skip Docker tests if not in Docker environment.
    Skip Calibre tests if Calibre tools not installed.
    Skip docker_integration tests if Docker not available.
    """
    import shutil
    import os
    
    skip_docker = pytest.mark.skip(reason="Not running in Docker environment")
    skip_calibre = pytest.mark.skip(reason="Calibre tools not installed")
    skip_docker_integration = pytest.mark.skip(reason="Docker not available")
    
    in_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'
    has_calibre = shutil.which('calibredb') is not None
    has_docker = shutil.which('docker') is not None
    
    for item in items:
        if "requires_docker" in item.keywords and not in_docker:
            item.add_marker(skip_docker)
        if "requires_calibre" in item.keywords and not has_calibre:
            item.add_marker(skip_calibre)
        if ("docker_integration" in item.keywords or "docker_e2e" in item.keywords) and not has_docker:
            item.add_marker(skip_docker_integration)


# ============================================================================
# Docker Container Fixtures (for integration/e2e tests)
# ============================================================================

@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    """Return path to the docker-compose.yml file."""
    repo_root = Path(__file__).parent.parent
    return str(repo_root / "docker-compose.yml")


@pytest.fixture(scope="session")
def test_volumes(tmp_path_factory) -> dict:
    """
    Create temporary directories for Docker volume mounts.
    
    Returns a dict with paths for config, ingest, and library volumes.
    """
    base_dir = tmp_path_factory.mktemp("cwa_test_volumes")
    
    volumes = {
        "config": base_dir / "config",
        "ingest": base_dir / "cwa-book-ingest",
        "library": base_dir / "calibre-library",
    }
    
    # Create directory structure
    for vol_dir in volumes.values():
        vol_dir.mkdir(parents=True, exist_ok=True)
    
    # Create minimal config structure
    config_dir = volumes["config"]
    (config_dir / "processed_books" / "converted").mkdir(parents=True, exist_ok=True)
    (config_dir / "processed_books" / "imported").mkdir(parents=True, exist_ok=True)
    (config_dir / "processed_books" / "failed").mkdir(parents=True, exist_ok=True)
    (config_dir / "processed_books" / "fixed_originals").mkdir(parents=True, exist_ok=True)
    (config_dir / "log_archive").mkdir(exist_ok=True)
    (config_dir / ".cwa_conversion_tmp").mkdir(exist_ok=True)
    
    # Create empty Calibre library (CWA will initialize it)
    library_dir = volumes["library"]
    (library_dir / ".keep").touch()
    
    yield volumes
    
    # Cleanup after session
    try:
        shutil.rmtree(base_dir)
    except Exception as e:
        print(f"Warning: Could not clean up test volumes: {e}")


@pytest.fixture(scope="session")
def cwa_container(docker_compose_file: str, test_volumes: dict) -> Generator:
    """
    Spin up CWA Docker container using docker-compose.yml.
    
    This is a session-scoped fixture that starts the container once
    and reuses it for all tests that need it. Container is automatically
    cleaned up after all tests complete.
    
    Yields:
        DockerCompose: The running container instance
    """
    import requests
    from testcontainers.compose import DockerCompose
    
    # Get repo root
    repo_root = Path(docker_compose_file).parent
    
    # Create a temporary docker-compose override for testing
    compose_override = repo_root / "docker-compose.test-override.yml"
    
    # Write test-specific overrides
    override_content = f"""---
services:
  calibre-web-automated:
    image: crocodilestick/calibre-web-automated:latest
    container_name: cwa-test-container
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
      - NETWORK_SHARE_MODE=false
      - CWA_PORT_OVERRIDE=8083
    volumes:
      - {test_volumes['config']}:/config
      - {test_volumes['ingest']}:/cwa-book-ingest
      - {test_volumes['library']}:/calibre-library
    ports:
      - "8083:8083"
    restart: "no"
"""
    
    compose_override.write_text(override_content)
    
    try:
        print("\n🐳 Starting CWA Docker container for testing...")
        
        # Use testcontainers with docker-compose
        # Note: context is the directory path, compose_file_name is the list of compose files
        compose = DockerCompose(
            context=str(repo_root),
            compose_file_name=["docker-compose.yml", "docker-compose.test-override.yml"],
            pull=False,  # Don't pull on every test run (use local image)
        )
        
        # Start the container
        compose.start()
        
        # Wait for CWA to be ready (health check)
        print("⏳ Waiting for CWA to be ready...")
        max_wait = 120  # 2 minutes max
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                # Try to connect to the web interface
                response = requests.get("http://localhost:8083", timeout=5)
                if response.status_code == 200:
                    print("✅ CWA container is ready!")
                    break
            except requests.exceptions.RequestException:
                # Not ready yet, wait
                time.sleep(2)
        else:
            # Timeout reached
            print("❌ CWA container failed to become ready in time")
            compose.stop()
            raise TimeoutError("CWA container did not start within 120 seconds")
        
        # Container is ready, yield it to tests
        yield compose
        
    finally:
        # Cleanup
        print("\n🧹 Stopping CWA Docker container...")
        try:
            compose.stop()
        except Exception as e:
            print(f"Warning: Error stopping container: {e}")
        
        # Remove override file
        if compose_override.exists():
            compose_override.unlink()


@pytest.fixture(scope="function")
def cwa_api_client(cwa_container) -> dict:
    """
    Provide a configured API client for interacting with CWA container.
    
    Returns a dict with:
    - base_url: The CWA web interface URL
    - session: Authenticated requests.Session
    - container: The docker compose instance
    """
    import requests
    
    base_url = "http://localhost:8083"
    
    # Create session with default credentials
    session = requests.Session()
    
    # Login to CWA (default credentials: admin/admin123)
    login_response = session.post(
        f"{base_url}/login",
        data={"username": "admin", "password": "admin123"},
        allow_redirects=False
    )
    
    if login_response.status_code not in (200, 302):
        pytest.skip("Could not authenticate with CWA container")
    
    return {
        "base_url": base_url,
        "session": session,
        "container": cwa_container,
    }


@pytest.fixture(scope="function")
def sample_ebook_path(tmp_path) -> Path:
    """
    Provide path to a minimal test EPUB file.
    
    Creates a fresh minimal EPUB for each test function.
    """
    # Import relative to tests directory
    import sys
    from pathlib import Path as PathLib
    
    # Add tests directory to path if not already there
    tests_dir = PathLib(__file__).parent
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    
    from fixtures.generate_synthetic import create_minimal_epub
    
    epub_path = tmp_path / "test_sample.epub"
    create_minimal_epub(epub_path)
    
    return epub_path


@pytest.fixture(scope="function")
def ingest_folder(test_volumes: dict) -> Path:
    """
    Provide the path to the ingest folder mounted in the container.
    
    Tests can drop files here to trigger ingest processing.
    """
    return test_volumes["ingest"]


@pytest.fixture(scope="function")
def library_folder(test_volumes: dict) -> Path:
    """
    Provide the path to the Calibre library folder mounted in the container.
    
    Tests can check this folder for imported books.
    """
    return test_volumes["library"]


# ============================================================================
# Docker Volume Mode Support (for Docker-in-Docker environments)
# ============================================================================

if USE_DOCKER_VOLUMES:
    # Import volume-based fixtures
    from conftest_volumes import (
        test_volumes_dind,
        cwa_container_dind,
        ingest_folder_dind,
        library_folder_dind,
        VolumeHelper
    )
    
    # Override fixtures to use volume versions
    @pytest.fixture(scope="session")
    def cwa_container(cwa_container_dind):
        """Redirect to Docker volume container implementation."""
        yield cwa_container_dind
    
    @pytest.fixture(scope="session")
    def ingest_folder(ingest_folder_dind):
        """Redirect to VolumeHelper for ingest folder."""
        return ingest_folder_dind
    
    @pytest.fixture(scope="session")
    def library_folder(library_folder_dind):
        """Redirect to VolumeHelper for library folder."""
        return library_folder_dind
    
    print("✅ Docker Volume fixtures loaded successfully\n")


