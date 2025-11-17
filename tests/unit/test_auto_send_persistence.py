#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Test suite for auto-send persistence and user settings.
Verifies that auto_send_enabled field is correctly saved and queried.
"""

import pytest
import sys
import os

# Mark all tests in this file as unit tests
pytestmark = pytest.mark.unit

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAutoSendPersistence:
    """Test auto-send user setting persistence"""
    
    def test_user_model_has_auto_send_field(self):
        """Verify User model has auto_send_enabled column"""
        from cps import ub
        
        # Check that the User class has the auto_send_enabled attribute
        assert hasattr(ub.User, 'auto_send_enabled')
        
        # Check it's a Column
        assert hasattr(ub.User.auto_send_enabled, 'type')
    
    def test_anonymous_user_has_auto_send_disabled(self):
        """Verify anonymous user has auto-send disabled by default"""
        from cps.ub import Anonymous
        
        anon = Anonymous()
        assert hasattr(anon, 'auto_send_enabled')
        assert anon.auto_send_enabled is False
    
    def test_ingest_query_structure(self):
        """Verify ingest processor queries users correctly"""
        # Read ingest_processor.py and verify query structure
        ingest_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts',
            'ingest_processor.py'
        )
        
        with open(ingest_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify query checks auto_send_enabled = 1
        assert 'auto_send_enabled = 1' in content
        # Verify query checks kindle_mail is not null/empty
        assert 'kindle_mail IS NOT NULL' in content
        assert "kindle_mail != ''" in content
    
    def test_web_handler_saves_auto_send(self):
        """Verify web.py profile handler saves auto_send_enabled"""
        web_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cps',
            'web.py'
        )
        
        with open(web_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify handler saves the field from form data
        assert 'current_user.auto_send_enabled = to_save.get("auto_send_enabled") == "on"' in content
    
    def test_admin_handler_saves_auto_send(self):
        """Verify admin.py user edit handler saves auto_send_enabled"""
        admin_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cps',
            'admin.py'
        )
        
        with open(admin_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify admin handler saves the field
        assert 'content.auto_send_enabled = to_save.get("auto_send_enabled") == "on"' in content
    
    def test_auto_send_task_checks_user_setting(self):
        """Verify TaskAutoSend checks user's auto_send_enabled setting"""
        task_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cps',
            'tasks',
            'auto_send.py'
        )
        
        with open(task_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify task checks if user has auto_send_enabled
        assert 'user.auto_send_enabled' in content
    
    def test_template_has_checkbox(self):
        """Verify user_edit.html template has auto_send_enabled checkbox"""
        template_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cps',
            'templates',
            'user_edit.html'
        )
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify checkbox exists with correct attributes
        assert 'id="auto_send_enabled"' in content
        assert 'name="auto_send_enabled"' in content
        assert 'content.auto_send_enabled' in content
    
    def test_migration_adds_column(self):
        """Verify ub.py has migration logic for auto_send_enabled column"""
        ub_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cps',
            'ub.py'
        )
        
        with open(ub_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify migration checks for column and adds if missing
        assert 'User.auto_send_enabled' in content
        assert "ALTER TABLE user ADD column 'auto_send_enabled' Boolean DEFAULT 0" in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
