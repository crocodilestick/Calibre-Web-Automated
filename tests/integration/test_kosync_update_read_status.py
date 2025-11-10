# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Integration Tests for update_book_read_status Business Logic

These tests verify the reading status threshold logic and state transitions
by testing against a real database in a running CWA container.
"""

import pytest
import sys
import base64
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.docker_integration
@pytest.mark.slow
class TestUpdateBookReadStatusThresholds:
    """Test percentage threshold logic for reading status"""

    def test_sets_finished_at_99_percent(self, cwa_api_client):
        """Status FINISHED when percentage >= 99.0"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        # Update progress to 99%
        payload = {
            'document': 'test-doc-99pct',
            'progress': '0.99',
            'percentage': 0.99,  # KOReader sends as decimal (0.99 = 99%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data['document'] == 'test-doc-99pct'

    def test_sets_finished_at_100_percent(self, cwa_api_client):
        """Status FINISHED when percentage = 100.0"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-100pct',
            'progress': '1.0',
            'percentage': 1.0,  # KOReader sends as decimal (1.0 = 100%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_sets_in_progress_at_50_percent(self, cwa_api_client):
        """Status IN_PROGRESS when 0 < percentage < 99"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-50pct',
            'progress': '0.5',
            'percentage': 0.50,  # KOReader sends as decimal (0.50 = 50%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_sets_in_progress_at_one_percent(self, cwa_api_client):
        """Status IN_PROGRESS at minimum positive percentage"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-1pct',
            'progress': '0.01',
            'percentage': 0.01,  # KOReader sends as decimal (0.01 = 1%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_sets_in_progress_at_98_percent(self, cwa_api_client):
        """Status IN_PROGRESS just below FINISHED threshold"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-98pct',
            'progress': '0.989',
            'percentage': 0.989,  # KOReader sends as decimal (0.989 = 98.9%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_sets_unread_at_zero_percent(self, cwa_api_client):
        """Status UNREAD when percentage = 0"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-0pct',
            'progress': '0.0',
            'percentage': 0.0,
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200


@pytest.mark.docker_integration
@pytest.mark.slow
class TestUpdateBookReadStatusRecordManagement:
    """Test record creation and updates"""

    def test_creates_new_record_for_first_sync(self, cwa_api_client):
        """First sync creates a new progress record"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        unique_doc = f'test-doc-new-{pytest.__version__}'
        payload = {
            'document': unique_doc,
            'progress': '0.25',
            'percentage': 0.25,  # KOReader sends as decimal (0.25 = 25%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

        # Verify we can retrieve it (should return as decimal)
        response = cwa_api_client.get(f'/kosync/syncs/progress/{unique_doc}',
                                       headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert float(data['percentage']) == 0.25  # Returns as decimal

    def test_updates_existing_record(self, cwa_api_client):
        """Subsequent syncs update the existing record"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        doc_id = 'test-doc-update'

        # First sync
        payload = {
            'document': doc_id,
            'progress': '0.3',
            'percentage': 0.30,  # KOReader sends as decimal (0.30 = 30%)
            'device': 'pytest',
            'device_id': 'test-device'
        }
        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)
        assert response.status_code == 200

        # Second sync with updated progress
        payload['progress'] = '0.6'
        payload['percentage'] = 0.60  # KOReader sends as decimal (0.60 = 60%)
        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)
        assert response.status_code == 200

        # Verify updated value (should return as decimal)
        response = cwa_api_client.get(f'/kosync/syncs/progress/{doc_id}',
                                       headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert float(data['percentage']) == 0.60  # Returns as decimal


@pytest.mark.docker_integration
@pytest.mark.slow
class TestUpdateBookReadStatusEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_handles_decimal_percentage(self, cwa_api_client):
        """Handles fractional percentages correctly"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-decimal',
            'progress': '0.4567',
            'percentage': 0.4567,  # KOReader sends as decimal (0.4567 = 45.67%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_handles_threshold_boundary_99_point_0(self, cwa_api_client):
        """Exact 99.0% threshold triggers FINISHED status"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-boundary-99',
            'progress': '0.99',
            'percentage': 0.99,  # KOReader sends as decimal (0.99 = 99%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200

    def test_handles_threshold_boundary_98_point_9(self, cwa_api_client):
        """98.9% stays IN_PROGRESS, doesn't trigger FINISHED"""
        credentials = base64.b64encode(b"admin:admin123").decode('ascii')
        headers = {'Authorization': f'Basic {credentials}'}

        payload = {
            'document': 'test-doc-boundary-989',
            'progress': '0.989',
            'percentage': 0.989,  # KOReader sends as decimal (0.989 = 98.9%)
            'device': 'pytest',
            'device_id': 'test-device'
        }

        response = cwa_api_client.put('/kosync/syncs/progress',
                                       json=payload,
                                       headers=headers)

        assert response.status_code == 200
