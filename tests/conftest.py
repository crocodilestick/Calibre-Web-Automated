# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
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
import sys
import pytest
import tempfile
import shutil
import time
import requests
import subprocess
from pathlib import Path
from typing import Generator

# Add project root to Python path so 'cps' module can be imported
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Add scripts directory to Python path so 'cwa_db' module can be imported
scripts_dir = project_root / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))


# Check if we should use Docker volumes (for DinD environments)
USE_DOCKER_VOLUMES = os.getenv('USE_DOCKER_VOLUMES', 'false').lower() == 'true'
AUTO_DOCKER_VOLUMES = False  # Auto-fallback when bind mounts are not visible to the container


def _get_test_uid_gid() -> tuple[str, str]:
    """Return UID/GID strings for test containers.

    Uses explicit overrides when provided, otherwise falls back to host uid/gid
    on POSIX systems, or 1000/1000 as a default.
    """
    env_uid = os.getenv("CWA_TEST_PUID", "").strip()
    env_gid = os.getenv("CWA_TEST_PGID", "").strip()
    if env_uid and env_gid:
        return env_uid, env_gid

    if os.name == "posix" and hasattr(os, "getuid") and hasattr(os, "getgid"):
        return str(os.getuid()), str(os.getgid())

    return "1000", "1000"

# Import volume_copy helper if in volume mode (available to all tests)
if USE_DOCKER_VOLUMES:
    print("\n🔄 Docker Volume mode enabled (USE_DOCKER_VOLUMES=true)")
    print("   Using Docker volumes instead of bind mounts for DinD compatibility\n")
    from conftest_volumes import volume_copy, VolumePath
else:
    # Bind mode by default, but support auto-fallback copying via docker cp
    class DockerPath:
        """Represents a path inside a running docker container for auto-fallback mode."""
        def __init__(self, container: str, container_path: str):
            self.container = container
            self.container_path = container_path

        def __truediv__(self, name: str):
            return DockerPath(self.container, f"{self.container_path.rstrip('/')}/{name}")

        def exists(self) -> bool:
            try:
                res = subprocess.run(
                    ["docker", "exec", self.container, "test", "-e", self.container_path],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return res.returncode == 0
            except Exception:
                return False

        def is_dir(self) -> bool:
            try:
                res = subprocess.run(
                    ["docker", "exec", self.container, "test", "-d", self.container_path],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return res.returncode == 0
            except Exception:
                return False

        @property
        def name(self) -> str:
            return os.path.basename(self.container_path.rstrip('/'))

        def __str__(self) -> str:
            return self.container_path

        @property
        def _parent(self) -> str:
            return os.path.dirname(self.container_path.rstrip('/')) or '/'

        def iterdir(self):
            """Iterate immediate children of this directory inside the container."""
            try:
                res = subprocess.run(
                    [
                        "docker", "exec", self.container, "sh", "-lc",
                        f"ls -1A {self.container_path} 2>/dev/null"
                    ],
                    check=False, capture_output=True, text=True
                )
                if res.returncode != 0:
                    return iter(())
                entries = [e for e in res.stdout.splitlines() if e.strip()]
                for name in entries:
                    yield DockerPath(self.container, f"{self.container_path.rstrip('/')}/{name}")
            except Exception:
                return iter(())

        def glob(self, pattern: str):
            """Yield paths matching the glob pattern under this directory."""
            # Use busybox/ash globbing via sh -lc to expand matches
            try:
                res = subprocess.run(
                    [
                        "docker", "exec", self.container, "sh", "-lc",
                        f"set -o noglob; for f in {self.container_path.rstrip('/')}/{pattern}; do echo \"$f\"; done"
                    ],
                    check=False, capture_output=True, text=True
                )
                if res.returncode != 0:
                    return iter(())
                for line in res.stdout.splitlines():
                    p = line.strip()
                    if p:
                        yield DockerPath(self.container, p)
            except Exception:
                return iter(())

    VolumePath = DockerPath  # For isinstance checks in get_db_path auto mode

    def volume_copy(src, dest):
        """Copy file into ingest folder.

        - In normal bind mode: shutil.copy2 to host path
        - In auto-fallback mode and dest is DockerPath: docker cp to container
        """
        if AUTO_DOCKER_VOLUMES and isinstance(dest, DockerPath):
            # Ensure parent exists inside container (best-effort)
            parent = os.path.dirname(dest.container_path)
            subprocess.run(["docker", "exec", dest.container, "mkdir", "-p", parent], check=False)
            # docker cp requires <src> <container>:<path>
            target = f"{dest.container}:{dest.container_path}"
            # docker cp copies into existing directory; ensure parent exists and target filename honored
            return subprocess.run(["docker", "cp", str(src), target], check=True)
        else:
            return shutil.copy2(src, dest)


def check_container_available(port=None):
    """
    Check if a CWA container is available on the specified port.

    Args:
        port: Port to check (defaults to CWA_TEST_PORT env var or 8085)

    Returns:
        bool: True if container is accessible, False otherwise
    """
    if port is None:
        port = os.getenv('CWA_TEST_PORT', '8085')

    try:
        response = requests.get(f"http://localhost:{port}", timeout=2)
        return response.status_code == 200
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False


@pytest.fixture(scope="session")
def container_available():
    """
    Session-scoped fixture that checks once if a container is available.
    Tests can use this to skip if no container is running.
    """
    return check_container_available()


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
    # Auto-fallback mode: copy out from container path
    if AUTO_DOCKER_VOLUMES and isinstance(db_path, VolumePath):
        if tmp_path is None:
            raise ValueError("tmp_path required for database access in auto volume mode")
        local_path = tmp_path / os.path.basename(str(db_path))
        base_container_path = db_path.container_path
        container = db_path.container
        # Copy sqlite db and possible WAL/SHM sidecars to ensure consistent read
        for suffix in ("", "-wal", "-shm"):
            src = f"{container}:{base_container_path}{suffix}"
            dest = str(local_path) + suffix
            try:
                subprocess.run(["docker", "cp", src, dest], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                # Sidecar may not exist; ignore errors for -wal/-shm
                if suffix == "":
                    raise RuntimeError(f"Failed to copy DB from container: {src}")
        return local_path

    # Explicit volume mode (DinD): delegate to conftest_volumes VolumePath
    if USE_DOCKER_VOLUMES and VolumePath and isinstance(db_path, VolumePath):
        if tmp_path is None:
            raise ValueError("tmp_path required for database access in volume mode")
        return db_path.read_to_local(tmp_path)

    # Bind mode: use path directly
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
    from pathlib import Path

    # Add scripts directory to path (works in both dev container and CI)
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

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
    Start the CWA Docker container and wait until it's reachable, measuring real startup time.
    By default, no arbitrary timeout is imposed unless configured via env vars.

    Env controls:
      - CWA_TEST_NO_TIMEOUT=true  -> wait indefinitely
      - CWA_TEST_START_TIMEOUT=N  -> cap wait to N seconds (ignored if NO_TIMEOUT=true)
      - CWA_TEST_PORT=PORT        -> host port to bind (default 8085)
      - CWA_TEST_IMAGE=IMAGE      -> image ref to run (default latest)
    """
    import requests
    import subprocess
    from testcontainers.compose import DockerCompose

    # Get repo root
    repo_root = Path(docker_compose_file).parent

    # Runtime configuration
    test_port = os.getenv('CWA_TEST_PORT', '8085')
    test_image = os.getenv('CWA_TEST_IMAGE', 'crocodilestick/calibre-web-automated:dev')
    test_uid, test_gid = _get_test_uid_gid()

    # Create a temporary docker-compose override for testing
    compose_override = repo_root / "docker-compose.test-override.yml"

    # Write test-specific overrides
    # Note: Container always runs on 8083 internally, we just map host port to it
    override_content = f"""---
services:
  calibre-web-automated:
    image: {test_image}
    container_name: cwa-test-container
    environment:
      - PUID={test_uid}
      - PGID={test_gid}
      - TZ=UTC
      - NETWORK_SHARE_MODE=false
    volumes:
      - {test_volumes['config']}:/config
      - {test_volumes['ingest']}:/cwa-book-ingest
      - {test_volumes['library']}:/calibre-library
    ports:
      - "{test_port}:8083"
    restart: "no"
"""

    compose_override.write_text(override_content)

    try:
        print("\n🐳 Starting CWA Docker container for testing...")
        print(f"   Port: {test_port}")

        # Use testcontainers with docker-compose
        compose = DockerCompose(
            context=str(repo_root),
            compose_file_name=["docker-compose.test-override.yml"],
            pull=False,
        )

        # Start the container
        compose.start()

        # Wait for CWA to be ready (health check)
        print("⏳ Waiting for CWA to be ready...")
        no_timeout = os.getenv('CWA_TEST_NO_TIMEOUT', 'false').lower() == 'true'
        max_wait_env = os.getenv('CWA_TEST_START_TIMEOUT', '').strip()
        max_wait = None if no_timeout or max_wait_env in ('0', '-1') else int(max_wait_env or '600')
        start_time = time.time()
        last_progress = 0

        while True:
            # Enforce optional timeout cap
            if max_wait is not None and (time.time() - start_time) >= max_wait:
                break

            # Try to connect to the web interface (root and login)
            ready = False
            for path in ("/", "/login"):
                try:
                    resp = requests.get(
                        f"http://localhost:{test_port}{path}", timeout=5, allow_redirects=False
                    )
                    if 200 <= resp.status_code < 400:
                        ready = True
                        break
                except requests.exceptions.RequestException:
                    pass

            # Fallback readiness via logs: consider ready when ingest services are watching
            if not ready:
                try:
                    logs = subprocess.run(
                        ['docker', 'compose', '-f', str(compose_override), 'logs', '--no-color', '--tail', '200'],
                        cwd=str(repo_root),
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    log_text = logs.stdout or ""
                    if (
                        "Watching folder: /cwa-book-ingest" in log_text
                        and "metadata-change-detector" in log_text
                    ) or "Connection to localhost" in log_text:
                        ready = True
                except Exception:
                    pass

            if ready:
                duration = int(time.time() - start_time)
                print(f"✅ CWA container is ready! (startup: {duration}s)")
                break

            # Progress output every 5s
            now = time.time()
            if now - last_progress >= 5:
                print(f"… still starting (waited {int(now - start_time)}s)")
                last_progress = now
            time.sleep(2)

        if max_wait is not None and (time.time() - start_time) >= max_wait:
            print("❌ CWA container failed to become ready in time")
            # Attempt to fetch container status/logs for debugging before stopping
            try:
                print("\n--- docker compose ps ---")
                subprocess.run(
                    ['docker', 'compose', '-f', str(compose_override), 'ps'],
                    cwd=str(repo_root),
                    check=False,
                )
                print("\n--- docker compose logs (tail 200) ---")
                subprocess.run(
                    ['docker', 'compose', '-f', str(compose_override), 'logs', '--tail', '200'],
                    cwd=str(repo_root),
                    check=False,
                )
                print("--- end logs ---\n")
            except Exception as e:
                print(f"Warning: Unable to retrieve docker logs: {e}")
            compose.stop()
            raise TimeoutError("CWA container did not start within the allotted time")

        # Container is ready; detect bind-mount visibility and auto-fallback if needed
        try:
            sentinel = test_volumes["ingest"] / f".cwa_bind_check_{int(time.time())}"
            sentinel.write_text("bind-check")
            # Check visibility inside container
            res = subprocess.run(
                ["docker", "exec", "cwa-test-container", "test", "-f", f"/cwa-book-ingest/{sentinel.name}"],
                check=False,
            )
            if res.returncode != 0:
                print("⚠️  Bind mounts not visible in container. Enabling auto volume fallback (docker cp mode).")
                global AUTO_DOCKER_VOLUMES
                AUTO_DOCKER_VOLUMES = True
                # Ensure tests that branch on USE_DOCKER_VOLUMES adapt to auto-fallback
                os.environ['USE_DOCKER_VOLUMES'] = 'true'
            else:
                print("✅ Bind mounts are visible to container.")
        except Exception as e:
            print(f"Warning: bind mount visibility check failed: {e}")
        finally:
            try:
                if 'sentinel' in locals() and sentinel.exists():
                    sentinel.unlink()
            except Exception:
                pass

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
            try:
                compose_override.unlink()
            except Exception as e:
                print(f"Warning: Could not remove override file: {e}")


@pytest.fixture(scope="session")
def container_name(cwa_container) -> str:
    """
    Get the container name string for use in docker commands.

    Handles both CI mode (DockerCompose object) and Docker-in-Docker mode (string).

    Returns:
        str: The container name that can be used with docker exec/logs commands
    """
    # In Docker-in-Docker mode, cwa_container is already a string (container name)
    if isinstance(cwa_container, str):
        return cwa_container

    # In CI mode, cwa_container is a DockerCompose object
    # Container name is hardcoded in the docker-compose override
    return "cwa-test-container"


@pytest.fixture(scope="function")
def cwa_api_client(cwa_container) -> dict:
    """
    Provide a configured API client for interacting with CWA container.

    Skips the test if no container is available on the configured port.

    Returns a dict with:
    - base_url: The CWA web interface URL
    - session: Authenticated requests.Session
    - container: The docker compose instance
    """
    import requests

    # Use configurable port
    # Default to 8085 to avoid conflicts with production CWA on 8083
    test_port = os.getenv('CWA_TEST_PORT', '8085')
    base_url = f"http://localhost:{test_port}"

    # Check if container is accessible
    if not check_container_available(test_port):
        pytest.skip(f"No CWA container available on port {test_port}")

    # Create session with default credentials
    session = requests.Session()

    # Login to CWA (default credentials: admin/admin123)
    try:
        login_response = session.post(
            f"{base_url}/login",
            data={"username": "admin", "password": "admin123"},
            allow_redirects=False,
            timeout=5
        )

        if login_response.status_code not in (200, 302):
            pytest.skip("Could not authenticate with CWA container")
    except requests.exceptions.RequestException as e:
        pytest.skip(f"Could not connect to CWA container: {e}")

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
def ingest_folder(test_volumes: dict, container_name: str) -> Path:
    """
    Provide the path to the ingest folder mounted in the container.

    Tests can drop files here to trigger ingest processing.
    """
    if AUTO_DOCKER_VOLUMES:
        return VolumePath(container_name, "/cwa-book-ingest")
    return test_volumes["ingest"]


@pytest.fixture(scope="function")
def library_folder(test_volumes: dict, container_name: str) -> Path:
    """
    Provide the path to the Calibre library folder mounted in the container.

    Tests can check this folder for imported books.
    """
    if AUTO_DOCKER_VOLUMES:
        return VolumePath(container_name, "/calibre-library")
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


