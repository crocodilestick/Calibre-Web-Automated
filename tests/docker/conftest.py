# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Docker-specific pytest fixtures using testcontainers.

These fixtures spin up actual CWA Docker containers for integration
and E2E testing using the production docker-compose.yml configuration.
"""

import pytest
import os
import time
import tempfile
import shutil
from pathlib import Path
from typing import Generator
import requests
from testcontainers.compose import DockerCompose


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    """Return path to the docker-compose.yml file."""
    repo_root = Path(__file__).parent.parent.parent
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
    # Note: tmp_path_factory automatically cleans up, but we can add explicit cleanup if needed
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
        compose = DockerCompose(
            filepath=str(repo_root),
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
    - volumes: Paths to mounted volumes
    """
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
    from tests.fixtures.generate_synthetic import create_minimal_epub
    
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


def pytest_configure(config):
    """Register custom markers for Docker tests."""
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
    Skip Docker tests if Docker is not available or explicitly disabled.
    
    Use `pytest -m "not docker_integration"` to skip Docker tests.
    """
    import shutil
    
    skip_docker = pytest.mark.skip(reason="Docker not available")
    has_docker = shutil.which('docker') is not None
    
    for item in items:
        if ("docker_integration" in item.keywords or "docker_e2e" in item.keywords) and not has_docker:
            item.add_marker(skip_docker)
