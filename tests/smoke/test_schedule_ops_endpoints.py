#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Smoke Tests for Operations Scheduling Endpoints

Fast static verification tests that check Convert Library and EPUB Fixer
scheduling code structure exists and is properly integrated.
"""

import pytest
import sys
import os
from pathlib import Path

# Mark all tests in this file as smoke tests
pytestmark = pytest.mark.smoke

# Get project root (3 levels up from this file)
project_root = Path(__file__).parent.parent.parent


class TestConvertLibraryScheduling:
    """Test Convert Library scheduling integration"""
    
    def test_convert_library_has_schedule_route(self):
        """Verify convert_library blueprint has schedule/<delay> route"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify route exists
        assert "@convert_library.route('/cwa-convert-library/schedule/<int:delay>'" in content
    
    def test_convert_library_schedule_calls_internal_api(self):
        """Verify schedule handler calls internal /cwa-internal/schedule-convert-library"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify internal endpoint is called
        assert 'http://127.0.0.1:{port}/cwa-internal/schedule-convert-library' in content
    
    def test_internal_convert_library_endpoint_exists(self):
        """Verify /cwa-internal/schedule-convert-library endpoint exists"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify internal endpoint function exists
        assert "@cwa_internal.route('/cwa-internal/schedule-convert-library'" in content
        assert "def cwa_internal_schedule_convert_library():" in content
    
    def test_convert_library_persists_to_db(self):
        """Verify convert_library scheduling persists job to cwa.db"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify DB persistence call with correct job type
        assert "db.scheduled_add_job('convert_library'" in content
    
    def test_convert_library_template_has_schedule_buttons(self):
        """Verify convert library template has scheduling buttons"""
        template_file = project_root / 'cps' / 'templates' / 'cwa_convert_library.html'
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify buttons call JS function
        assert 'scheduleConvertLibrary(5)' in content
        assert 'scheduleConvertLibrary(15)' in content
    
    def test_convert_library_task_wrapper_exists(self):
        """Verify TaskConvertLibraryRun task wrapper exists"""
        # Check if ops.py imports or defines the task
        ops_file = project_root / 'cps' / 'tasks' / 'ops.py'
        
        if os.path.exists(ops_file):
            with open(ops_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            assert 'TaskConvertLibraryRun' in content


class TestEpubFixerScheduling:
    """Test EPUB Fixer scheduling integration"""
    
    def test_epub_fixer_has_schedule_route(self):
        """Verify epub_fixer blueprint has schedule/<delay> route"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify route exists
        assert "@epub_fixer.route('/cwa-epub-fixer/schedule/<int:delay>'" in content
    
    def test_epub_fixer_schedule_calls_internal_api(self):
        """Verify schedule handler calls internal /cwa-internal/schedule-epub-fixer"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify internal endpoint is called
        assert 'http://127.0.0.1:{port}/cwa-internal/schedule-epub-fixer' in content
    
    def test_internal_epub_fixer_endpoint_exists(self):
        """Verify /cwa-internal/schedule-epub-fixer endpoint exists"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify internal endpoint function exists
        assert "@cwa_internal.route('/cwa-internal/schedule-epub-fixer'" in content
        assert "def cwa_internal_schedule_epub_fixer():" in content
    
    def test_epub_fixer_persists_to_db(self):
        """Verify epub_fixer scheduling persists job to cwa.db"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify DB persistence call with correct job type
        assert "db.scheduled_add_job('epub_fixer'" in content
    
    def test_epub_fixer_template_has_schedule_buttons(self):
        """Verify epub fixer template has scheduling buttons"""
        template_file = project_root / 'cps' / 'templates' / 'cwa_epub_fixer.html'
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify buttons call JS function
        assert 'scheduleEpubFixer(5)' in content
        assert 'scheduleEpubFixer(15)' in content
    
    def test_epub_fixer_task_wrapper_exists(self):
        """Verify TaskEpubFixerRun task wrapper exists"""
        ops_file = project_root / 'cps' / 'tasks' / 'ops.py'
        
        if os.path.exists(ops_file):
            with open(ops_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            assert 'TaskEpubFixerRun' in content


class TestUpcomingOpsEndpoint:
    """Test /cwa-scheduled/upcoming-ops endpoint"""
    
    def test_upcoming_ops_endpoint_exists(self):
        """Verify /cwa-scheduled/upcoming-ops endpoint exists"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify endpoint exists
        assert "@cwa_stats.route('/cwa-scheduled/upcoming-ops'" in content
        assert "def cwa_scheduled_upcoming_ops():" in content
    
    def test_upcoming_ops_queries_both_types(self):
        """Verify upcoming-ops endpoint queries both convert_library and epub_fixer"""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'
        
        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify both job types are queried
        assert "'convert_library', 'epub_fixer'" in content or "('convert_library', 'epub_fixer')" in content
    
    def test_tasks_template_shows_upcoming_ops(self):
        """Verify tasks.html template displays upcoming operations"""
        template_file = project_root / 'cps' / 'templates' / 'tasks.html'
        
        with open(template_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify upcoming ops table exists
        assert 'Upcoming scheduled operations' in content or 'cwa_scheduled_upcoming_ops' in content
        assert 'upcomingopstable' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
