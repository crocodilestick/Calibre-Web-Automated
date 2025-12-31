# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Edge case and validation tests for KOSync"""

import pytest
import base64
import json


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncValidationEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_document_id_at_max_length(self, cwa_api_client):
        """Test document ID at maximum allowed length (255 chars)"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Create document ID at exactly max length
        max_doc_id = "a" * 255
        progress_data = {
            'document': max_doc_id,
            'progress': '0.5',
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201], "Should accept max length document ID"

    def test_document_id_exceeds_max_length(self, cwa_api_client):
        """Test document ID exceeding maximum length is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        # Create document ID exceeding max length
        too_long_doc_id = "a" * 256
        progress_data = {
            'document': too_long_doc_id,
            'progress': '0.5',
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject document ID exceeding max length"

    def test_progress_string_at_max_length(self, cwa_api_client):
        """Test progress string at maximum length (255 chars)"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        max_progress = "x" * 255
        progress_data = {
            'document': 'test' + '0' * 28,
            'progress': max_progress,
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201], "Should accept max length progress string"

    def test_progress_string_exceeds_max_length(self, cwa_api_client):
        """Test progress string exceeding maximum length is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        too_long_progress = "x" * 256
        progress_data = {
            'document': 'test' + '0' * 28,
            'progress': too_long_progress,
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject progress exceeding max length"

    def test_device_name_at_max_length(self, cwa_api_client):
        """Test device name at maximum length (100 chars)"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        max_device = "d" * 100
        progress_data = {
            'document': 'test' + '0' * 28,
            'progress': '0.5',
            'percentage': 0.5,
            'device': max_device,
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201], "Should accept max length device name"

    def test_device_name_exceeds_max_length(self, cwa_api_client):
        """Test device name exceeding maximum length is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        too_long_device = "d" * 101
        progress_data = {
            'document': 'test' + '0' * 28,
            'progress': '0.5',
            'percentage': 0.5,
            'device': too_long_device,
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject device name exceeding max length"

    def test_percentage_at_zero(self, cwa_api_client):
        """Test percentage at exactly 0.0"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        progress_data = {
            'document': 'zero' + '0' * 28,
            'progress': '0.0',
            'percentage': 0.0,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201], "Should accept 0.0 percentage"

    def test_percentage_at_one_hundred(self, cwa_api_client):
        """Test percentage at exactly 100.0 (as 1.0 decimal)"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        progress_data = {
            'document': 'complete' + '0' * 24,
            'progress': '1.0',
            'percentage': 1.0,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code in [200, 201], "Should accept 1.0 percentage"

    def test_percentage_negative(self, cwa_api_client):
        """Test negative percentage is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        progress_data = {
            'document': 'negative' + '0' * 24,
            'progress': '-0.5',
            'percentage': -0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject negative percentage"

    def test_percentage_above_one_hundred(self, cwa_api_client):
        """Test percentage above 100 is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        progress_data = {
            'document': 'over' + '0' * 28,
            'progress': '1.5',
            'percentage': 150.0,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject percentage over 100"

    def test_document_id_with_colon_rejected(self, cwa_api_client):
        """Test document ID containing colon is rejected"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

        progress_data = {
            'document': 'invalid:colon',
            'progress': '0.5',
            'percentage': 0.5,
            'device': 'pytest',
            'device_id': 'test'
        }

        response = cwa_api_client.put(
            '/kosync/syncs/progress',
            headers=headers,
            json=progress_data
        )

        assert response.status_code == 400, "Should reject document ID with colon"


@pytest.mark.docker_integration
@pytest.mark.slow
class TestKOSyncAuthenticationEdgeCases:
    """Test authentication edge cases"""

    def test_auth_with_unicode_password(self, cwa_api_client):
        """Test authentication with Unicode characters in password"""
        # Note: This assumes a user with Unicode password exists
        # In practice, admin password is ASCII
        credentials = base64.b64encode("admin:café☕".encode('utf-8')).decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        # Should handle Unicode gracefully (may fail auth but not crash)
        assert response.status_code in [200, 401]

    def test_auth_with_unicode_username(self, cwa_api_client):
        """Test authentication with Unicode characters in username"""
        credentials = base64.b64encode("用户:password".encode('utf-8')).decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        # Should handle Unicode gracefully
        assert response.status_code in [200, 401]

    def test_auth_with_colon_in_password(self, cwa_api_client):
        """Test authentication with colon in password (edge case for parsing)"""
        # Password contains colon - should be handled correctly
        credentials = base64.b64encode(b"admin:pass:word:123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        # Should parse correctly (split on first colon only)
        assert response.status_code in [200, 401]

    def test_auth_with_empty_password(self, cwa_api_client):
        """Test authentication with empty password"""
        credentials = base64.b64encode(b"admin:").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        assert response.status_code == 401, "Should reject empty password"

    def test_auth_with_empty_username(self, cwa_api_client):
        """Test authentication with empty username"""
        credentials = base64.b64encode(b":password").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        assert response.status_code == 401, "Should reject empty username"

    def test_auth_with_invalid_base64(self, cwa_api_client):
        """Test authentication with invalid base64 encoding"""
        headers = {'Authorization': 'Basic not_valid_base64!!!'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        assert response.status_code in [400, 401], "Should reject invalid base64"

    def test_auth_without_colon_separator(self, cwa_api_client):
        """Test authentication without colon separator in credentials"""
        credentials = base64.b64encode(b"adminpassword").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        response = cwa_api_client.get('/kosync/users/auth', headers=headers)

        assert response.status_code in [400, 401], "Should reject credentials without colon"
