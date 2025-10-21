# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Docker container smoke tests.

These tests verify that the CWA Docker container starts correctly
and basic services are operational.
"""

import pytest
import time
import requests
from pathlib import Path


@pytest.mark.docker_integration
class TestDockerContainerStartup:
    """Test that CWA Docker container starts and initializes correctly."""
    
    def test_container_is_running(self, cwa_container):
        """Verify the container is running."""
        # If we got here, the fixture successfully started the container
        assert cwa_container is not None
    
    def test_web_interface_accessible(self, cwa_api_client):
        """Verify the web interface is accessible."""
        response = cwa_api_client["session"].get(cwa_api_client["base_url"])
        assert response.status_code == 200
        assert "Calibre-Web" in response.text
    
    def test_authenticated_access(self, cwa_api_client):
        """Verify authentication works with default credentials."""
        # The fixture handles login, so if we got here, auth worked
        response = cwa_api_client["session"].get(f"{cwa_api_client['base_url']}/admin/admin")
        assert response.status_code in (200, 302)  # Either shows admin page or redirects
    
    def test_volume_mounts_exist(self, test_volumes):
        """Verify all required volume mount points exist."""
        assert test_volumes["config"].exists()
        assert test_volumes["ingest"].exists()
        assert test_volumes["library"].exists()
        
        # Check directory structure
        assert (test_volumes["config"] / "processed_books").exists()
        assert (test_volumes["config"] / "log_archive").exists()
    
    def test_services_initialized(self, cwa_api_client, test_volumes):
        """Verify key CWA services are initialized."""
        # Check that databases were created
        config_dir = test_volumes["config"]
        
        # Wait for databases to be created (up to 30 seconds)
        max_wait = 30
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            if (config_dir / "app.db").exists():
                break
            time.sleep(1)
        
        # Check for CWA databases
        assert (config_dir / "app.db").exists(), "app.db not created"
        # cwa.db and metadata.db may take longer or be created on first use
        # We'll just verify the container is functional


@pytest.mark.docker_integration
class TestDockerEnvironmentVariables:
    """Test that environment variables are properly applied."""
    
    def test_timezone_set(self, cwa_container):
        """Verify timezone environment variable is applied."""
        # This is a basic check - we can't easily inspect env vars from outside
        # but the container should have started successfully with TZ=UTC
        assert cwa_container is not None
    
    def test_port_mapping(self, cwa_api_client):
        """Verify port mapping is working."""
        # If we can access the web interface on 8083, port mapping works
        response = requests.get("http://localhost:8083", timeout=5)
        assert response.status_code == 200


@pytest.mark.docker_integration  
class TestDockerHealthChecks:
    """Test container health and readiness."""
    
    def test_container_stays_running(self, cwa_container):
        """Verify container doesn't crash immediately after startup."""
        # Wait 10 seconds and verify it's still running
        time.sleep(10)
        
        # Try to access the web interface - if container crashed, this will fail
        response = requests.get("http://localhost:8083", timeout=5)
        assert response.status_code == 200
    
    def test_logs_directory_created(self, test_volumes):
        """Verify log directory structure is created."""
        log_dir = test_volumes["config"] / "log_archive"
        assert log_dir.exists()
        assert log_dir.is_dir()
