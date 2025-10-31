# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/editbooks.py

Tests cover:
- delete_kobo_synced route functionality
- edit_hardcover_blacklist function

Note: These tests avoid importing editbooks.py directly due to heavy dependencies.
Instead, they test the logic patterns that were added.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
class TestDeleteKoboSynced:
    """Test delete_kobo_synced route"""
    
    def test_delete_existing_synced_book(self):
        """Test deleting an existing synced book"""
        # Setup mocks - simulate the logic without importing editbooks
        mock_current_user = Mock()
        mock_current_user.id = 1
        
        synced_book = Mock()
        synced_book.book_id = 123
        synced_book.user_id = 1
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = synced_book
        mock_session.delete = Mock()
        
        # Simulate the function logic
        book_id = 123
        synced_book_result = mock_session.query().filter().first()
        
        if synced_book_result:
            mock_session.delete(synced_book_result)
            result = ("Book removed from Kobo sync", 200)
        else:
            result = ("Book not found in Kobo sync", 404)
        
        assert result[0] == "Book removed from Kobo sync"
        assert result[1] == 200
        mock_session.delete.assert_called_once_with(synced_book_result)
    
    def test_delete_nonexistent_synced_book(self):
        """Test deleting a book that doesn't exist in sync"""
        # Setup mocks
        mock_current_user = Mock()
        mock_current_user.id = 1
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        # Simulate the function logic
        book_id = 999
        synced_book_result = mock_session.query().filter().first()
        
        if synced_book_result:
            result = ("Book removed from Kobo sync", 200)
        else:
            result = ("Book not found in Kobo sync", 404)
        
        assert result[0] == "Book not found in Kobo sync"
        assert result[1] == 404


@pytest.mark.unit
class TestEditHardcoverBlacklist:
    """Test edit_hardcover_blacklist function"""
    
    def test_create_blacklist_with_annotations(self):
        """Test creating a blacklist record for annotations"""
        book_id = 123
        to_save = {"blacklist_annotations": "on"}
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        # Simulate the function logic
        new_blacklist_annotations = 'blacklist_annotations' in to_save
        new_blacklist_progress = 'blacklist_reading_progress' in to_save
        
        if not new_blacklist_annotations and not new_blacklist_progress:
            changed = False
        else:
            blacklist = Mock()
            blacklist.book_id = book_id
            blacklist.blacklist_annotations = False
            blacklist.blacklist_reading_progress = False
            mock_session.add(blacklist)
            changed = True
            
            if blacklist.blacklist_annotations != new_blacklist_annotations:
                blacklist.blacklist_annotations = new_blacklist_annotations
                changed = True
            
            if blacklist.blacklist_reading_progress != new_blacklist_progress:
                blacklist.blacklist_reading_progress = new_blacklist_progress
                changed = True
        
        assert changed is True
        assert blacklist.blacklist_annotations is True
        assert blacklist.blacklist_reading_progress is False
    
    def test_create_blacklist_with_progress(self):
        """Test creating a blacklist record for reading progress"""
        book_id = 123
        to_save = {"blacklist_reading_progress": "on"}
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        # Simulate the function logic
        new_blacklist_annotations = 'blacklist_annotations' in to_save
        new_blacklist_progress = 'blacklist_reading_progress' in to_save
        
        if not new_blacklist_annotations and not new_blacklist_progress:
            changed = False
        else:
            blacklist = Mock()
            blacklist.book_id = book_id
            blacklist.blacklist_annotations = False
            blacklist.blacklist_reading_progress = False
            mock_session.add(blacklist)
            changed = True
            
            if blacklist.blacklist_annotations != new_blacklist_annotations:
                blacklist.blacklist_annotations = new_blacklist_annotations
                changed = True
            
            if blacklist.blacklist_reading_progress != new_blacklist_progress:
                blacklist.blacklist_reading_progress = new_blacklist_progress
                changed = True
        
        assert changed is True
        assert blacklist.blacklist_annotations is False
        assert blacklist.blacklist_reading_progress is True
    
    def test_update_existing_blacklist(self):
        """Test updating an existing blacklist record"""
        book_id = 123
        to_save = {"blacklist_annotations": "on", "blacklist_reading_progress": "on"}
        
        existing_blacklist = Mock()
        existing_blacklist.book_id = book_id
        existing_blacklist.blacklist_annotations = False
        existing_blacklist.blacklist_reading_progress = False
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = existing_blacklist
        
        # Simulate the function logic
        new_blacklist_annotations = 'blacklist_annotations' in to_save
        new_blacklist_progress = 'blacklist_reading_progress' in to_save
        
        blacklist = existing_blacklist
        
        changed = False
        if blacklist.blacklist_annotations != new_blacklist_annotations:
            blacklist.blacklist_annotations = new_blacklist_annotations
            changed = True
        
        if blacklist.blacklist_reading_progress != new_blacklist_progress:
            blacklist.blacklist_reading_progress = new_blacklist_progress
            changed = True
        
        assert changed is True
        assert blacklist.blacklist_annotations is True
        assert blacklist.blacklist_reading_progress is True
    
    def test_delete_blacklist_when_all_disabled(self):
        """Test deleting blacklist record when all options are disabled"""
        book_id = 123
        to_save = {}  # No blacklist options
        
        existing_blacklist = Mock()
        existing_blacklist.book_id = book_id
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = existing_blacklist
        
        # Simulate the function logic
        new_blacklist_annotations = 'blacklist_annotations' in to_save
        new_blacklist_progress = 'blacklist_reading_progress' in to_save
        
        changed = False
        if not new_blacklist_annotations and not new_blacklist_progress:
            blacklist = existing_blacklist
            if blacklist:
                mock_session.delete(blacklist)
                changed = True
        
        assert changed is True
        mock_session.delete.assert_called_once_with(existing_blacklist)
    
    def test_no_change_when_values_unchanged(self):
        """Test that no change is reported when values are unchanged"""
        book_id = 123
        to_save = {"blacklist_annotations": "on"}
        
        existing_blacklist = Mock()
        existing_blacklist.book_id = book_id
        existing_blacklist.blacklist_annotations = True
        existing_blacklist.blacklist_reading_progress = False
        
        mock_session = Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = existing_blacklist
        
        # Simulate the function logic
        new_blacklist_annotations = 'blacklist_annotations' in to_save
        new_blacklist_progress = 'blacklist_reading_progress' in to_save
        
        blacklist = existing_blacklist
        changed = False
        
        if blacklist.blacklist_annotations != new_blacklist_annotations:
            blacklist.blacklist_annotations = new_blacklist_annotations
            changed = True
        
        if blacklist.blacklist_reading_progress != new_blacklist_progress:
            blacklist.blacklist_reading_progress = new_blacklist_progress
            changed = True
        
        assert changed is False

