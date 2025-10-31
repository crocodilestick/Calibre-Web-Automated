# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for kobo.py external ID retrieval and reading progress sync logic.

NOTE: These tests currently validate the logic patterns used in kobo.py rather than
directly testing the production code. This is because kobo.py functions require:
- Flask application context
- Database sessions (ub.session, calibre_db)
- Complex dependency injection (config, current_user, kobo_reading_state, etc.)

TODO: Refactor these into integration tests with proper Flask test client and database
fixtures, or extract the logic into testable helper functions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
class TestGetExternalIds:
    """Test get_external_ids function"""
    
    def test_get_external_ids_with_identifiers(self):
        """Test building external IDs with book identifiers"""
        # Create mock book with identifiers
        book = Mock()
        book.id = 123
        
        identifier1 = Mock()
        identifier1.type = "ISBN"
        identifier1.val = "9781234567890"
        
        identifier2 = Mock()
        identifier2.type = "ASIN"
        identifier2.val = "B01234567"
        
        book.identifiers = [identifier1, identifier2]
        
        # Simulate the function logic
        external_ids = []
        
        if book.identifiers:
            for identifier in book.identifiers:
                external_ids.append(f"{identifier.type.lower()}:{identifier.val}")
        
        external_ids.append(f"calibre:{book.id}")
        
        assert len(external_ids) == 3
        assert "isbn:9781234567890" in external_ids
        assert "asin:B01234567" in external_ids
        assert "calibre:123" in external_ids
    
    def test_get_external_ids_without_identifiers(self):
        """Test building external IDs without identifiers"""
        book = Mock()
        book.id = 456
        book.identifiers = []
        
        # Simulate the function logic
        external_ids = []
        
        if book.identifiers:
            for identifier in book.identifiers:
                external_ids.append(f"{identifier.type.lower()}:{identifier.val}")
        
        external_ids.append(f"calibre:{book.id}")
        
        assert len(external_ids) == 1
        assert external_ids[0] == "calibre:456"
    
    def test_get_external_ids_with_none_identifiers(self):
        """Test building external IDs when identifiers is None"""
        book = Mock()
        book.id = 789
        book.identifiers = None
        
        # Simulate the function logic
        external_ids = []
        
        if book.identifiers:
            for identifier in book.identifiers:
                external_ids.append(f"{identifier.type.lower()}:{identifier.val}")
        
        external_ids.append(f"calibre:{book.id}")
        
        assert len(external_ids) == 1
        assert external_ids[0] == "calibre:789"
    
    def test_get_external_ids_lowercases_identifier_types(self):
        """Test that identifier types are lowercased"""
        book = Mock()
        book.id = 999
        
        identifier = Mock()
        identifier.type = "MOBI_ASIN"
        identifier.val = "B987654321"
        
        book.identifiers = [identifier]
        
        # Simulate the function logic
        external_ids = []
        
        if book.identifiers:
            for identifier in book.identifiers:
                external_ids.append(f"{identifier.type.lower()}:{identifier.val}")
        
        external_ids.append(f"calibre:{book.id}")
        
        assert "mobi_asin:B987654321" in external_ids


@pytest.mark.unit
class TestReadingProgressSync:
    """Test reading progress sync logic with user preferences and blacklist"""
    
    def test_progress_sync_when_user_preference_enabled(self):
        """Test that progress sync occurs when user preference is enabled"""
        mock_config = Mock()
        mock_config.config_hardcover_sync = True
        
        mock_current_user = Mock()
        mock_current_user.kobo_sync_progress = True
        
        hardcover = Mock()
        book = Mock()
        book.id = 123
        
        # Simulate the condition check
        should_sync = (mock_config.config_hardcover_sync and 
                      mock_current_user.kobo_sync_progress and 
                      bool(hardcover))
        
        assert should_sync is True
    
    def test_progress_sync_skipped_when_user_preference_disabled(self):
        """Test that progress sync is skipped when user preference is disabled"""
        mock_config = Mock()
        mock_config.config_hardcover_sync = True
        
        mock_current_user = Mock()
        mock_current_user.kobo_sync_progress = False
        
        hardcover = Mock()
        
        # Simulate the condition check
        should_sync = (mock_config.config_hardcover_sync and 
                      mock_current_user.kobo_sync_progress and 
                      bool(hardcover))
        
        assert should_sync is False
    
    def test_progress_sync_skipped_when_blacklisted(self):
        """Test that progress sync is skipped when book is blacklisted"""
        mock_config = Mock()
        mock_config.config_hardcover_sync = True
        
        mock_current_user = Mock()
        mock_current_user.kobo_sync_progress = True
        
        hardcover = Mock()
        book = Mock()
        book.id = 123
        
        # Create blacklist mock
        blacklist = Mock()
        blacklist.blacklist_reading_progress = True
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = blacklist
        
        # Simulate the condition check
        if (mock_config.config_hardcover_sync and 
            mock_current_user.kobo_sync_progress and 
            bool(hardcover)):
            
            book_blacklist = mock_session.query().filter().first()
            
            if book_blacklist and book_blacklist.blacklist_reading_progress:
                should_sync = False
            else:
                should_sync = True
        else:
            should_sync = False
        
        assert should_sync is False
    
    def test_progress_sync_when_not_blacklisted(self):
        """Test that progress sync occurs when book is not blacklisted"""
        mock_config = Mock()
        mock_config.config_hardcover_sync = True
        
        mock_current_user = Mock()
        mock_current_user.kobo_sync_progress = True
        
        hardcover = Mock()
        book = Mock()
        book.id = 123
        
        # No blacklist exists
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        # Simulate the condition check
        if (mock_config.config_hardcover_sync and 
            mock_current_user.kobo_sync_progress and 
            bool(hardcover)):
            
            book_blacklist = mock_session.query().filter().first()
            
            if book_blacklist and book_blacklist.blacklist_reading_progress:
                should_sync = False
            else:
                should_sync = True
        else:
            should_sync = False
        
        assert should_sync is True

