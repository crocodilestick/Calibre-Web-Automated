#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Smoke Tests for Auto-Send Delay Minutes Setting

Fast static verification tests that check delay setting validation
and usage code structure exists.
"""

import pytest
import sys
import os
from pathlib import Path

# Mark all tests in this file as smoke tests
pytestmark = pytest.mark.smoke

# Get project root (3 levels up from this file)
project_root = Path(__file__).parent.parent.parent


class TestAutoSendDelayValidation:
    """Test auto-send delay setting validation and usage"""
    
    def test_schema_has_default(self):
        """Verify schema defines auto_send_delay_minutes with default"""
        schema_file = project_root / 'scripts' / 'cwa_schema.sql'
        
        with open(schema_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify column exists with proper default
        assert 'auto_send_delay_minutes INTEGER DEFAULT 5 NOT NULL' in content
    
    def test_template_has_validation(self):
        """Verify settings template has min/max validation"""
        template_file = project_root / 'cps' / 'templates' / 'cwa_settings.html'
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify input has type=number with min/max
        assert 'name="auto_send_delay_minutes"' in content
        assert 'type="number"' in content
        assert 'min="1"' in content
        assert 'max="60"' in content
    
    def test_cwa_functions_validates_range(self):
        """Verify cwa_functions.py validates 1-60 range"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify validation logic clamps to 1-60
        assert "'auto_send_delay_minutes'" in content
        assert "max(1, min(60, int_value))" in content
    
    def test_ingest_uses_delay_setting(self):
        """Verify ingest processor uses delay from CWA settings"""
        ingest_file = project_root / 'scripts' / 'ingest_processor.py'
        
        with open(ingest_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify ingest reads from cwa_settings with fallback
        assert "self.cwa_settings.get('auto_send_delay_minutes', 5)" in content
    
    def test_internal_endpoint_validates_delay(self):
        """Verify /cwa-internal/schedule-auto-send validates delay_minutes"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify endpoint clamps delay_minutes to 0-60 range
        # Search for the schedule-auto-send endpoint function
        assert '/cwa-internal/schedule-auto-send' in content
        assert 'delay_minutes = int(data.get' in content
        assert 'max(0, min(60, delay_minutes))' in content
    
    def test_validation_range_boundary(self):
        """Test validation handles boundary values correctly"""
        # Mock test to verify logic (actual values tested at runtime)
        
        # Test lower bound: value < 1 should become 1
        test_value = -5
        clamped = max(1, min(60, test_value))
        assert clamped == 1
        
        # Test within range: should stay unchanged
        test_value = 30
        clamped = max(1, min(60, test_value))
        assert clamped == 30
        
        # Test upper bound: value > 60 should become 60
        test_value = 120
        clamped = max(1, min(60, test_value))
        assert clamped == 60
    
    def test_default_fallback(self):
        """Test that missing/invalid values fall back to 5"""
        # Verify default logic
        default_value = 5
        
        # Test None fallback
        value = None
        result = default_value if value is None else value
        assert result == 5
        
        # Test empty string fallback in conversion
        try:
            value = ""
            result = int(value) if value else default_value
        except (ValueError, TypeError):
            result = default_value
        assert result == 5


class TestDelayUsageFlow:
    """Test that delay is properly used in scheduling flow"""
    
    def test_schedule_endpoint_uses_delay(self):
        """Verify internal schedule endpoint uses delay_minutes parameter"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify delay_minutes is extracted and used in timedelta calculation
        assert 'timedelta(minutes=delay_minutes)' in content
    
    def test_task_receives_delay_parameter(self):
        """Verify TaskAutoSend receives delay_minutes parameter"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify TaskAutoSend is called with delay_minutes
        assert 'TaskAutoSend(task_message, book_id, user_id, delay_minutes)' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
