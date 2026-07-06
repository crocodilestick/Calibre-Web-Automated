#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Smoke Tests for CWA Endpoint Authentication

Fast static verification tests that check Convert Library and EPUB Fixer
endpoints have proper authentication decorators applied.

These tests verify the fix for the authentication vulnerability where endpoints
were accessible without login/admin privileges.
"""

import pytest
import re
from pathlib import Path

# Mark all tests in this file as smoke tests
pytestmark = pytest.mark.smoke

# Get project root (3 levels up from this file)
project_root = Path(__file__).parent.parent.parent


class TestConvertLibraryAuthenticationDecorators:
    """Test Convert Library endpoints have proper authentication decorators."""

    def test_overview_page_requires_authentication(self):
        """Verify show_convert_library_page has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@convert_library\.route\('/cwa-convert-library-overview'.*?\n@login_required_if_no_ano\n@admin_required\ndef show_convert_library_page\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "show_convert_library_page must have @login_required_if_no_ano and @admin_required decorators"

    def test_start_endpoint_requires_authentication(self):
        """Verify start_conversion has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@convert_library\.route\('/cwa-convert-library-start'.*?\n@login_required_if_no_ano\n@admin_required\ndef start_conversion\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "start_conversion must have @login_required_if_no_ano and @admin_required decorators"

    def test_cancel_endpoint_requires_authentication(self):
        """Verify cancel_convert_library has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@convert_library\.route\('/convert-library-cancel'.*?\n@login_required_if_no_ano\n@admin_required\ndef cancel_convert_library\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "cancel_convert_library must have @login_required_if_no_ano and @admin_required decorators"

    def test_status_endpoint_requires_authentication(self):
        """Verify get_status (convert library) has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the convert-library-status route and its get_status function
        # Note: There are two get_status functions, we need the convert-library one
        pattern = r"@convert_library\.route\('/convert-library-status'.*?\n@login_required_if_no_ano\n@admin_required\ndef get_status\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "get_status (convert-library) must have @login_required_if_no_ano and @admin_required decorators"

    def test_log_archive_requires_authentication(self):
        """Verify show_convert_library_logs has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@convert_library\.route\('/cwa-convert-library/log-archive'.*?\n@login_required_if_no_ano\n@admin_required\ndef show_convert_library_logs\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "show_convert_library_logs must have @login_required_if_no_ano and @admin_required decorators"

    def test_download_log_requires_authentication(self):
        """Verify download_current_log (convert library) has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        # Note: There are two download_current_log functions, we need the convert-library one
        pattern = r"@convert_library\.route\('/cwa-convert-library/download-current-log/<log_filename>'\)\n@login_required_if_no_ano\n@admin_required\ndef download_current_log\(log_filename\):"
        assert re.search(pattern, content, re.DOTALL), \
            "download_current_log (convert-library) must have @login_required_if_no_ano and @admin_required decorators"

    def test_schedule_endpoint_requires_authentication(self):
        """Verify schedule_convert_library has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # The schedule endpoint should already have decorators from before
        pattern = r"@convert_library\.route\('/cwa-convert-library/schedule/<int:delay>'.*?\n@login_required_if_no_ano\n@admin_required\ndef schedule_convert_library"
        assert re.search(pattern, content, re.DOTALL), \
            "schedule_convert_library must have @login_required_if_no_ano and @admin_required decorators"


class TestEpubFixerAuthenticationDecorators:
    """Test EPUB Fixer endpoints have proper authentication decorators."""

    def test_overview_page_requires_authentication(self):
        """Verify show_epub_fixer_page has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@epub_fixer\.route\('/cwa-epub-fixer-overview'.*?\n@login_required_if_no_ano\n@admin_required\ndef show_epub_fixer_page\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "show_epub_fixer_page must have @login_required_if_no_ano and @admin_required decorators"

    def test_start_endpoint_requires_authentication(self):
        """Verify start_epub_fixer has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@epub_fixer\.route\('/cwa-epub-fixer-start'.*?\n@login_required_if_no_ano\n@admin_required\ndef start_epub_fixer\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "start_epub_fixer must have @login_required_if_no_ano and @admin_required decorators"

    def test_cancel_endpoint_requires_authentication(self):
        """Verify cancel_epub_fixer has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@epub_fixer\.route\('/epub-fixer-cancel'.*?\n@login_required_if_no_ano\n@admin_required\ndef cancel_epub_fixer\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "cancel_epub_fixer must have @login_required_if_no_ano and @admin_required decorators"

    def test_status_endpoint_requires_authentication(self):
        """Verify get_status (epub fixer) has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the epub-fixer-status route and its get_status function
        # Note: There are two get_status functions, we need the epub-fixer one
        pattern = r"@epub_fixer\.route\('/epub-fixer-status'.*?\n@login_required_if_no_ano\n@admin_required\ndef get_status\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "get_status (epub-fixer) must have @login_required_if_no_ano and @admin_required decorators"

    def test_log_archive_requires_authentication(self):
        """Verify show_epub_fixer_logs has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        pattern = r"@epub_fixer\.route\('/cwa-epub-fixer/log-archive'.*?\n@login_required_if_no_ano\n@admin_required\ndef show_epub_fixer_logs\(\):"
        assert re.search(pattern, content, re.DOTALL), \
            "show_epub_fixer_logs must have @login_required_if_no_ano and @admin_required decorators"

    def test_download_log_requires_authentication(self):
        """Verify download_current_log (epub fixer) has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the route and function definition
        # Note: There are two download_current_log functions, we need the epub-fixer one
        pattern = r"@epub_fixer\.route\('/cwa-epub-fixer/download-current-log/<log_filename>'\)\n@login_required_if_no_ano\n@admin_required\ndef download_current_log\(log_filename\):"
        assert re.search(pattern, content, re.DOTALL), \
            "download_current_log (epub-fixer) must have @login_required_if_no_ano and @admin_required decorators"

    def test_schedule_endpoint_requires_authentication(self):
        """Verify schedule_epub_fixer has authentication decorators."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # The schedule endpoint should already have decorators from before
        pattern = r"@epub_fixer\.route\('/cwa-epub-fixer/schedule/<int:delay>'.*?\n@login_required_if_no_ano\n@admin_required\ndef schedule_epub_fixer"
        assert re.search(pattern, content, re.DOTALL), \
            "schedule_epub_fixer must have @login_required_if_no_ano and @admin_required decorators"


class TestAuthenticationImports:
    """Test that required authentication components are imported."""

    def test_required_decorators_imported(self):
        """Verify authentication decorators are imported."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check imports
        assert 'from .usermanagement import login_required_if_no_ano' in content, \
            "login_required_if_no_ano must be imported"
        assert 'from .admin import admin_required' in content, \
            "admin_required must be imported"

    def test_security_functions_imported(self):
        """Verify security functions are imported."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check security-related imports
        assert 'from werkzeug.utils import secure_filename' in content, \
            "secure_filename must be imported for path sanitization"
        assert 'from flask import' in content and 'abort' in content, \
            "abort must be imported from Flask"
        assert 'from flask import' in content and 'redirect' in content, \
            "redirect must be imported from Flask"


class TestPathSanitization:
    """Test that log download endpoints use proper path sanitization."""

    def test_download_log_uses_secure_filename(self):
        """Verify download_log function uses secure_filename."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find download_log function and check for secure_filename usage
        download_log_pattern = r"def download_log\(log_filename\):.*?secure_filename\(log_filename\)"
        assert re.search(download_log_pattern, content, re.DOTALL), \
            "download_log must use secure_filename to prevent directory traversal"

    def test_read_log_uses_secure_filename(self):
        """Verify read_log function uses secure_filename."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find read_log function and check for secure_filename usage
        read_log_pattern = r"def read_log\(log_filename\):.*?secure_filename\(log_filename\)"
        assert re.search(read_log_pattern, content, re.DOTALL), \
            "read_log must use secure_filename to prevent directory traversal"

    def test_download_current_log_uses_secure_filename(self):
        """Verify download_current_log functions use secure_filename."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Count occurrences of download_current_log with secure_filename
        # There should be 2 (one for convert library, one for epub fixer)
        pattern = r"def download_current_log\(log_filename\):.*?secure_filename"
        matches = re.findall(pattern, content, re.DOTALL)
        assert len(matches) >= 2, \
            "Both download_current_log functions must use secure_filename"

    def test_log_endpoints_check_directory_traversal(self):
        """Verify log endpoints validate paths are within allowed directory."""
        cwa_functions_file = project_root / 'cps' / 'cwa_functions.py'

        with open(cwa_functions_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for path validation in download_log
        assert 'if not file_path.startswith(os.path.abspath(LOG_ARCHIVE))' in content, \
            "download_log must validate path is within LOG_ARCHIVE"
        assert 'abort(403)' in content, \
            "download_log must abort with 403 for invalid paths"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
