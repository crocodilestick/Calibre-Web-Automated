# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for Kobo Dashboard data aggregation and warning logic."""

import pytest
from unittest.mock import patch, MagicMock
from cps import ub, db
from cps.kobo_dashboard import get_magic_shelf_book_ids_direct, get_kobo_dashboard_data, get_kobo_excluded_books


@pytest.mark.unit
class TestKoboDashboard:

    @patch('cps.kobo_dashboard.build_query_from_rules')
    @patch('cps.db.CalibreDB')
    def test_get_magic_shelf_book_ids_direct_success(self, mock_calibredb_cls, mock_build_query):
        """Test that get_magic_shelf_book_ids_direct successfully queries CalibreDB and returns IDs."""
        fake_shelf = MagicMock()
        fake_shelf.id = 1
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0
        fake_shelf.rules = {'rules': [{'id': 'tags', 'operator': 'equal', 'value': 'Fantasy'}]}

        # Mock build_query_from_rules to return a dummy filter expression
        mock_build_query.return_value = "dummy_filter"

        # Mock CalibreDB instance
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb

        # Mock query return tuples (book_id,)
        mock_query = mock_cdb.session.query()
        mock_query.filter.return_value = mock_query
        mock_query.with_entities.return_value.all.return_value = [(10,), (20,), (30,)]

        book_ids = get_magic_shelf_book_ids_direct(fake_shelf)

        assert book_ids == {10, 20, 30}
        mock_calibredb_cls.assert_called_once_with(init=True)
        mock_build_query.assert_called_once_with(fake_shelf.rules, user_id=1, is_public=False)

    @patch('cps.kobo_dashboard.build_query_from_rules')
    @patch('cps.db.CalibreDB')
    def test_get_magic_shelf_book_ids_direct_no_rules(self, mock_calibredb_cls, mock_build_query):
        """If shelf has no rules, return an empty set immediately."""
        fake_shelf = MagicMock()
        fake_shelf.rules = None

        book_ids = get_magic_shelf_book_ids_direct(fake_shelf)

        assert book_ids == set()
        mock_calibredb_cls.assert_not_called()
        mock_build_query.assert_not_called()

    @patch('cps.kobo_dashboard.db.CalibreDB')
    @patch('cps.kobo_dashboard.ub.session')
    def test_get_kobo_excluded_books(self, mock_session, mock_calibredb_cls):
        """Exclusion shelf entries should be returned with Calibre titles for the dashboard."""
        fake_row = MagicMock(book_id=20)
        mock_session.query.return_value.join.return_value.filter.return_value.all.return_value = [fake_row]

        fake_book = MagicMock()
        fake_book.id = 20
        fake_book.title = "Blocked Book"

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [fake_book]

        excluded_books = get_kobo_excluded_books(1)

        assert excluded_books == [{"id": 20, "title": "Blocked Book"}]

    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    def test_get_kobo_dashboard_data_basic(self, mock_session, mock_allowed_books, mock_magic_ids, mock_config, mock_excluded):
        """Test basic dashboard aggregation and counts in two-column mode."""
        # Setup config
        mock_config.config_kobo_sync_magic_shelves = True
        mock_excluded.return_value = [{"id": 99, "title": "Blocked Book"}]

        # Mock user
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = True
        fake_user.kobo_only_shelves_sync = 1  # Two-column mode

        # Mock remote token check
        mock_token = MagicMock()
        mock_session.query().filter_by().first.side_effect = [
            mock_token,  # RemoteAuthToken first() call
        ]

        # Mock allowed book IDs (union of kobo_sync shelves)
        mock_allowed_books.return_value = {10, 20, 30}

        # Mock KoboSyncedBooks
        fake_synced = [MagicMock(book_id=10), MagicMock(book_id=20)]
        mock_session.query().filter_by().all.return_value = fake_synced

        # Mock normal shelves query (kobo_display = True)
        fake_normal_shelf = MagicMock()
        fake_normal_shelf.id = 42
        fake_normal_shelf.uuid = "normal-uuid"
        fake_normal_shelf.name = "Normal Display Shelf"
        fake_normal_shelf.kobo_sync = True
        fake_normal_shelf.books = [MagicMock(book_id=10), MagicMock(book_id=40)]

        # Mock magic shelves query (kobo_display = True)
        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 55
        fake_magic_shelf.uuid = "magic-uuid"
        fake_magic_shelf.name = "Magic Display Shelf"
        fake_magic_shelf.kobo_sync = False
        mock_magic_ids.return_value = {20, 30}

        # Setup side effect for normal & magic shelves
        mock_session.query().filter_by().all.side_effect = [
            fake_synced,         # KoboSyncedBooks.all()
            [fake_normal_shelf], # Shelf query
            [fake_magic_shelf]   # MagicShelf query
        ]

        dashboard_data = get_kobo_dashboard_data(fake_user)

        assert dashboard_data["is_two_column_sync"] is True
        assert dashboard_data["has_kobo_token"] is True
        assert dashboard_data["allowed_book_count"] == 3
        assert dashboard_data["excluded_book_count"] == 1
        assert dashboard_data["excluded_books"] == [{"id": 99, "title": "Blocked Book"}]
        assert dashboard_data["synced_book_count"] == 2

        # Check Collections structure
        cols = dashboard_data["collections"]
        assert len(cols) == 2

        col_normal = cols[0]
        assert col_normal["name"] == "Normal Display Shelf"
        assert col_normal["type"] == "normal"
        assert col_normal["total_books"] == 2
        assert col_normal["allowed_books"] == 1
        assert col_normal["synced_books"] == 1

        col_magic = cols[1]
        assert col_magic["name"] == "Magic Display Shelf"
        assert col_magic["type"] == "magic"
        assert col_magic["total_books"] == 2
        assert col_magic["allowed_books"] == 2
        assert col_magic["synced_books"] == 1

        warns = dashboard_data["warnings"]
        assert len(warns) == 1
        assert warns[0]["code"] == "SOME_BOOKS_NOT_ALLOWED"

    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    def test_get_kobo_dashboard_data_warnings(self, mock_session, mock_allowed_books, mock_magic_ids, mock_config, mock_excluded):
        """Test specific warnings generated by get_kobo_dashboard_data."""
        # Setup config
        mock_config.config_kobo_sync_magic_shelves = False
        mock_excluded.return_value = []

        # User lacks download role and runs full sync
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = False
        fake_user.kobo_only_shelves_sync = 0  # Full Sync mode

        # Token exists
        mock_session.query().filter_by().first.return_value = MagicMock()

        # In Full Sync mode allowed_book_ids is None
        mock_allowed_books.return_value = None

        # Synced books
        mock_session.query().filter_by().all.return_value = []

        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 99
        fake_magic_shelf.uuid = "magic-uuid"
        fake_magic_shelf.name = "My Magic Shelf"
        fake_magic_shelf.kobo_sync = True
        mock_magic_ids.return_value = set()

        # Mock session queries
        mock_session.query().filter_by().all.side_effect = [
            [],                  # KoboSyncedBooks
            [],                  # Shelf (no normal shelves)
            [fake_magic_shelf]   # MagicShelf
        ]

        dashboard_data = get_kobo_dashboard_data(fake_user)
        warns = dashboard_data["warnings"]

        warn_codes = [w["code"] for w in warns]
        assert "MISSING_DOWNLOAD_ROLE" in warn_codes
        assert "FULL_SYNC_MODE" in warn_codes
        assert "MAGIC_SHELVES_DISABLED" in warn_codes
        assert "EMPTY_COLLECTION" in warn_codes

    @patch('cps.magic_shelf.invalidate_magic_shelf_cache')
    @patch('cps.kobo_auth.url_for')
    @patch('cps.kobo_auth.redirect')
    @patch('cps.kobo_auth.flash')
    @patch('cps.kobo_auth.current_user')
    @patch('cps.kobo_auth.ub.session')
    def test_allow_excluded_book_removes_entry(self, mock_session, mock_current_user, mock_flash, mock_redirect, mock_url_for, mock_invalidate):
        """The re-allow action removes the book from Kobo: Ausgeschlossen through the loaded shelf relationship."""
        from cps.kobo_auth import allow_excluded_book

        mock_current_user.id = 1
        mock_url_for.return_value = "/kobo_auth/dashboard"
        mock_redirect.side_effect = lambda target: target

        fake_shelf_1 = MagicMock()
        fake_shelf_1.id = 31
        fake_shelf_2 = MagicMock()
        fake_shelf_2.id = 32
        fake_book_shelf_1 = MagicMock()
        fake_book_shelf_1.shelf = 31
        fake_book_shelf_2 = MagicMock()
        fake_book_shelf_2.shelf = 32

        shelf_query = MagicMock()
        shelf_query.filter.return_value.all.return_value = [fake_shelf_1, fake_shelf_2]
        book_shelf_query = MagicMock()
        book_shelf_query.filter.return_value.all.return_value = [fake_book_shelf_1, fake_book_shelf_2]
        mock_session.query.side_effect = [shelf_query, book_shelf_query]

        response = allow_excluded_book.__wrapped__(20)

        assert response == "/kobo_auth/dashboard"
        assert fake_book_shelf_1.ub_shelf is fake_shelf_1
        assert fake_book_shelf_2.ub_shelf is fake_shelf_2
        mock_invalidate.assert_called_once()
        assert mock_session.delete.call_count == 2
        mock_session.commit.assert_called_once()
        mock_flash.assert_called_once()
