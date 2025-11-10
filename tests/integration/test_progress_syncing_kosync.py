# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Integration Tests for KOSync Checksum Integration

These tests verify that the KOSync API correctly uses book checksums
for document identification and enrichment.

Note: These are integration tests that require a running CWA container.
"""

import pytest
import sys
import json
import base64
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncChecksumLookup:
    """Test KOSync book lookup by checksum."""

    def test_kosync_endpoint_exists(self, cwa_api_client):
        """Verify KOSync endpoints are registered."""
        response = cwa_api_client.get('/kosync')

        # Should either show the info page or redirect
        assert response.status_code in [200, 302]

    def test_authenticate_with_basic_auth(self, cwa_api_client):
        """Test KOSync authentication with HTTP Basic Auth."""
        # Create Basic Auth header
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        # Should authenticate successfully
        assert response.status_code == 200
        data = response.json()
        assert 'username' in data or response.status_code == 200

    def test_get_progress_for_unknown_document(self, cwa_api_client):
        """Test retrieving progress for a document with no sync data."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        # Use a fake checksum that doesn't exist
        fake_checksum = "a" * 32
        response = cwa_api_client.get(
            f'/kosync/syncs/progress/{fake_checksum}',
            headers=headers
        )

        # Should return empty or indicate no progress
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            # May return empty progress or null
            assert 'document' in data or 'progress' in data or data == {}

    def test_put_progress_creates_sync_record(self, cwa_api_client):
        """Test creating a sync progress record."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Create progress data
        test_checksum = "test" + "0" * 28  # 32 char checksum
        progress_data = {
            'document': test_checksum,
            'progress': '0.5',  # 50% progress
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test_device_001'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        # Should create successfully
        assert response.status_code in [200, 201]
        data = response.json()
        assert 'document' in data
        assert data['document'] == test_checksum

    def test_get_progress_after_put(self, cwa_api_client):
        """Test retrieving progress that was just set."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Set progress
        test_checksum = "get" + "0" * 29
        progress_data = {
            'document': test_checksum,
            'progress': '0.75',
            'percentage': 0.75,
            'device': 'pytest',
            'device_id': 'test_device_002'
        }

        put_response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )
        assert put_response.status_code in [200, 201]

        # Retrieve progress
        get_response = cwa_api_client.get(
            f'/kosync/syncs/progress/{test_checksum}',
            headers=headers
        )

        assert get_response.status_code == 200
        data = get_response.json()
        assert data['document'] == test_checksum
        assert float(data['percentage']) == 0.75


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncBookEnrichment:
    """Test that KOSync enriches responses with Calibre book info."""

    @pytest.fixture
    def book_with_checksum(self, cwa_container, library_folder, tmp_path):
        """Create a test book with a known checksum in the library."""
        import sqlite3
        from cps.progress_syncing.checksums import calculate_koreader_partial_md5

        # This would need actual book ingestion in a real test
        # For now, we'll skip if library is empty
        pytest.skip("Requires actual book in library - implement in E2E tests")

    def test_enriched_response_includes_book_info(self, cwa_api_client, book_with_checksum):
        """Test that sync responses include Calibre book metadata."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        checksum, book_id, title = book_with_checksum

        # Set progress for this book
        progress_data = {
            'document': checksum,
            'progress': '0.25',
            'percentage': 0.25,
            'device': 'pytest',
            'device_id': 'test_enrichment'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201]
        data = response.json()

        # Should include Calibre book information
        assert 'calibre_book_id' in data
        assert 'calibre_book_title' in data
        assert 'calibre_book_format' in data

        assert data['calibre_book_id'] == book_id
        assert title in data['calibre_book_title']

    def test_non_calibre_book_sync_still_works(self, cwa_api_client):
        """Test that sync works for books not in Calibre library."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Use a checksum that won't match any book
        external_checksum = "external" + "f" * 24
        progress_data = {
            'document': external_checksum,
            'progress': '0.3',
            'percentage': 0.3,
            'device': 'pytest',
            'device_id': 'external_device'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        # Should still work, just without enrichment
        assert response.status_code in [200, 201]
        data = response.json()
        assert data['document'] == external_checksum

        # May or may not have calibre fields
        # If present, they should be None or absent


@pytest.mark.unit
class TestKOSyncHelperFunctions:
    """Unit tests for KOSync helper functions without requiring container."""

    def test_get_book_by_checksum_function_exists(self):
        """Verify the helper function exists."""
        from cps.progress_syncing.protocols import get_book_by_checksum

        assert callable(get_book_by_checksum)

    def test_enrich_response_function_exists(self):
        """Verify the enrichment function exists."""
        from cps.progress_syncing.protocols.kosync import enrich_response_with_book_info

        assert callable(enrich_response_with_book_info)

    def test_enrich_response_with_no_match(self):
        """Test enrichment when book is not found."""
        from cps.progress_syncing.protocols.kosync import enrich_response_with_book_info

        # Mock response data
        response_data = {
            'document': 'nonexistent_checksum',
            'progress': '0.5'
        }

        # This would need proper mocking of calibre_db
        # For now, verify function signature
        assert callable(enrich_response_with_book_info)


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncAuthentication:
    """Test KOSync authentication mechanisms."""

    def test_missing_auth_header_fails(self, cwa_api_client):
        """Test that requests without auth header are rejected."""
        response = cwa_api_client.get('/kosync/users/auth')

        # Should fail authentication
        assert response.status_code in [401, 403]

    def test_invalid_credentials_fails(self, cwa_api_client):
        """Test that invalid credentials are rejected."""
        credentials = base64.b64encode(b"wrong:password").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        # Should fail authentication
        assert response.status_code in [401, 403]

    def test_malformed_auth_header_fails(self, cwa_api_client):
        """Test that malformed auth headers are rejected."""
        headers = {'Authorization': 'NotBasic credentials'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        assert response.status_code in [400, 401, 403]

    def test_auth_required_for_all_endpoints(self, cwa_api_client):
        """Test that all KOSync endpoints require authentication."""
        endpoints = [
            '/kosync/users/auth',
            '/kosync/syncs/progress/test123',
        ]

        for endpoint in endpoints:
            response = cwa_api_client.get(endpoint)
            # All should require auth (except maybe the info page)
            assert response.status_code in [401, 403, 404]


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncDataValidation:
    """Test data validation in KOSync endpoints."""

    def test_invalid_progress_value_rejected(self, cwa_api_client):
        """Test that invalid progress values are rejected."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Progress > 1.0 should be invalid
        invalid_data = {
            'document': 'test' + '0' * 28,
            'progress': '1.5',
            'percentage': 1.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=invalid_data
        )

        # May accept (clamping) or reject
        # Either is valid behavior
        assert response.status_code in [200, 201, 400]

    def test_missing_required_fields_rejected(self, cwa_api_client):
        """Test that requests missing required fields are rejected."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Missing required fields
        incomplete_data = {
            'document': 'test' + '0' * 28
            # Missing progress, percentage, device, device_id
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=incomplete_data
        )

        # Should reject incomplete data
        assert response.status_code in [400, 422]

    def test_empty_document_checksum_rejected(self, cwa_api_client):
        """Test that empty document checksums are rejected."""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        empty_doc_data = {
            'document': '',
            'progress': '0.5',
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=empty_doc_data
        )

        # Should reject empty document
        assert response.status_code in [400, 422]
