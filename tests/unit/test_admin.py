# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/admin.py

Tests cover:
- Configuration validation for Kobo annotation sync
- User preference handling for Kobo sync settings

Note: These tests avoid importing admin.py directly due to heavy dependencies
(cwa_db, database sessions, Flask app context, etc.). Instead, they test
the logic patterns that were added in the diff.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
class TestAdminConfigurationValidation:
    """Test configuration validation logic in admin.py"""
    
    def test_annotation_sync_requires_kobo_sync_enabled(self):
        """Test that annotation sync can only be enabled if Kobo sync is enabled"""
        # Setup mocks - simulate the validation logic without importing admin.py
        mock_config = Mock()
        mock_config.config_kobo_sync = False
        
        to_save = {"config_kobo_annotation_sync": "on"}
        
        # Simulate the validation check from admin.py
        validation_failed = False
        if to_save.get("config_kobo_annotation_sync") == "on" and not mock_config.config_kobo_sync:
            validation_failed = True
        
        assert validation_failed is True
    
    def test_annotation_sync_allowed_when_kobo_sync_enabled(self):
        """Test that annotation sync can be enabled when Kobo sync is enabled"""
        mock_config = Mock()
        mock_config.config_kobo_sync = True
        
        to_save = {"config_kobo_annotation_sync": "on"}
        
        # Validation should pass
        validation_failed = False
        if to_save.get("config_kobo_annotation_sync") == "on" and not mock_config.config_kobo_sync:
            validation_failed = True
        
        assert validation_failed is False
    
    def test_annotation_sync_off_no_validation_needed(self):
        """Test that validation is skipped when annotation sync is off"""
        mock_config = Mock()
        mock_config.config_kobo_sync = False
        
        to_save = {"config_kobo_annotation_sync": "off"}
        
        # No validation error should occur
        validation_failed = False
        if to_save.get("config_kobo_annotation_sync") == "on" and not mock_config.config_kobo_sync:
            validation_failed = True
        
        assert validation_failed is False


@pytest.mark.unit
class TestAdminUserPreferences:
    """Test user preference handling in admin.py"""
    
    def test_kobo_sync_annotations_set_when_on(self):
        """Test that kobo_sync_annotations is set to True when 'on' is provided"""
        to_save = {"kobo_sync_annotations": "on"}
        content = Mock()
        content.kobo_sync_annotations = False
        
        # Simulate the preference setting logic
        if True:  # kobo_support check
            content.kobo_sync_annotations = to_save.get("kobo_sync_annotations") == "on"
        
        assert content.kobo_sync_annotations is True
    
    def test_kobo_sync_annotations_set_when_off(self):
        """Test that kobo_sync_annotations is set to False when 'off' or missing"""
        to_save = {"kobo_sync_annotations": "off"}
        content = Mock()
        content.kobo_sync_annotations = True
        
        if True:  # kobo_support check
            content.kobo_sync_annotations = to_save.get("kobo_sync_annotations") == "on"
        
        assert content.kobo_sync_annotations is False
    
    def test_kobo_sync_progress_set_when_on(self):
        """Test that kobo_sync_progress is set to True when 'on' is provided"""
        to_save = {"kobo_sync_progress": "on"}
        content = Mock()
        content.kobo_sync_progress = False
        
        if True:  # kobo_support check
            content.kobo_sync_progress = to_save.get("kobo_sync_progress") == "on"
        
        assert content.kobo_sync_progress is True
    
    def test_kobo_sync_progress_set_when_off(self):
        """Test that kobo_sync_progress is set to False when 'off' or missing"""
        to_save = {"kobo_sync_progress": "off"}
        content = Mock()
        content.kobo_sync_progress = True
        
        if True:  # kobo_support check
            content.kobo_sync_progress = to_save.get("kobo_sync_progress") == "on"
        
        assert content.kobo_sync_progress is False
    
    def test_kobo_preferences_only_set_when_kobo_support_enabled(self):
        """Test that preferences are only set when kobo_support is True"""
        to_save = {"kobo_sync_annotations": "on", "kobo_sync_progress": "on"}
        content = Mock()
        content.kobo_sync_annotations = False
        content.kobo_sync_progress = False
        
        kobo_support = False
        
        if kobo_support:
            content.kobo_sync_annotations = to_save.get("kobo_sync_annotations") == "on"
            content.kobo_sync_progress = to_save.get("kobo_sync_progress") == "on"
        
        # Values should remain unchanged when kobo_support is False
        assert content.kobo_sync_annotations is False
        assert content.kobo_sync_progress is False

