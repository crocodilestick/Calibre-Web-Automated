# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for Kobo Dashboard data aggregation and warning logic."""

from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from cps import ub, db
from cps.kobo_dashboard import (
    format_book_count,
    get_kobo_allowed_books_for_dashboard,
    get_kobo_dashboard_data,
    get_kobo_excluded_books,
    get_magic_shelf_book_ids_direct
)


@pytest.mark.unit
class TestKoboDashboard:

    def test_format_book_count_uses_german_singular(self):
        assert format_book_count(1) == "1 Buch"
        assert format_book_count(2) == "2 Bücher"

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

    @patch('cps.kobo_dashboard.db.CalibreDB')
    def test_get_kobo_allowed_books_for_dashboard(self, mock_calibredb_cls):
        """Allowed Kobo book IDs should be returned with Calibre titles for the dashboard block action."""
        fake_book = MagicMock()
        fake_book.id = 10
        fake_book.title = "Allowed Book"

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [fake_book]

        allowed_books = get_kobo_allowed_books_for_dashboard({10})

        assert allowed_books == [{"id": 10, "title": "Allowed Book"}]

    @patch('cps.kobo_dashboard.get_kobo_allowed_books_for_dashboard')
    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    def test_get_kobo_dashboard_data_basic(
        self,
        mock_session,
        mock_allowed_books,
        mock_magic_ids,
        mock_config,
        mock_excluded,
        mock_allowed_dashboard_books
    ):
        """Test basic dashboard aggregation and counts in two-column mode."""
        # Setup config
        mock_config.config_kobo_sync_magic_shelves = True
        mock_excluded.return_value = [{"id": 40, "title": "Blocked Book"}]
        mock_allowed_dashboard_books.return_value = [{"id": 10, "title": "Allowed Book"}]

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
        assert dashboard_data["allowed_books"] == [{"id": 10, "title": "Allowed Book"}]
        assert dashboard_data["excluded_book_count"] == 1
        assert dashboard_data["excluded_books"] == [{"id": 40, "title": "Blocked Book"}]
        assert dashboard_data["synced_book_count"] == 2

        # Check Collections structure
        cols = dashboard_data["collections"]
        assert len(cols) == 2

        col_normal = cols[0]
        assert col_normal["name"] == "Normal Display Shelf"
        assert col_normal["type"] == "normal"
        assert col_normal["total_books"] == 2
        assert col_normal["allowed_books"] == 1
        assert col_normal["blocked_books"] == 1
        assert col_normal["synced_books"] == 1

        col_magic = cols[1]
        assert col_magic["name"] == "Magic Display Shelf"
        assert col_magic["type"] == "magic"
        assert col_magic["total_books"] == 2
        assert col_magic["allowed_books"] == 2
        assert col_magic["blocked_books"] == 0
        assert col_magic["synced_books"] == 1

        warns = dashboard_data["warnings"]
        assert len(warns) == 1
        assert warns[0]["type"] == "info"
        assert warns[0]["code"] == "BLOCKED_BOOKS_IN_COLLECTION"
        assert "ist 1 Buch als Nicht auf Kobo markiert" in warns[0]["message"]

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
        assert next(w for w in warns if w["code"] == "FULL_SYNC_MODE")["type"] == "info"
        assert next(w for w in warns if w["code"] == "MAGIC_SHELVES_DISABLED")["type"] == "info"

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

    @patch('cps.magic_shelf.invalidate_magic_shelf_cache')
    @patch('cps.kobo.get_or_create_kobo_exclusion_shelf')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.kobo_auth.url_for')
    @patch('cps.kobo_auth.redirect')
    @patch('cps.kobo_auth.flash')
    @patch('cps.kobo_auth.current_user')
    @patch('cps.kobo_auth.ub.session')
    def test_block_kobo_book_adds_entry(
        self,
        mock_session,
        mock_current_user,
        mock_flash,
        mock_redirect,
        mock_url_for,
        mock_allowed_ids,
        mock_get_exclusion_shelf,
        mock_invalidate
    ):
        """The block action adds an allowed book to Kobo: Ausgeschlossen through the shelf relationship."""
        from cps.kobo_auth import block_kobo_book

        mock_current_user.id = 1
        mock_current_user.kobo_only_shelves_sync = 1
        mock_allowed_ids.return_value = {20}
        mock_url_for.return_value = "/kobo_auth/dashboard"
        mock_redirect.side_effect = lambda target: target

        fake_shelf = MagicMock()
        fake_shelf.books = MagicMock()
        mock_get_exclusion_shelf.return_value = fake_shelf

        response = block_kobo_book.__wrapped__(20)

        assert response == "/kobo_auth/dashboard"
        fake_shelf.books.append.assert_called_once()
        appended_book_shelf = fake_shelf.books.append.call_args.args[0]
        assert isinstance(appended_book_shelf, ub.BookShelf)
        assert appended_book_shelf.book_id == 20
        mock_invalidate.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_flash.assert_called_once()

    @patch('cps.kobo_dashboard.get_kobo_dashboard_data')
    @patch('cps.kobo_auth.render_title_template')
    def test_dashboard_route_passes_excluded_books_to_template(self, mock_render, mock_dashboard_data):
        """Dashboard smoke test: blocked Kobo books are passed to the UI render context."""
        from cps.kobo_auth import dashboard

        fake_user = MagicMock()
        fake_user.id = 1
        mock_dashboard_data.return_value = {
            "is_two_column_sync": True,
            "has_kobo_token": True,
            "collections": [],
            "warnings": [],
            "excluded_books": [{"id": 20, "title": "Blocked Book"}],
            "allowed_book_count": 3,
            "excluded_book_count": 1,
            "synced_book_count": 2
        }
        mock_render.return_value = "rendered-dashboard"

        with patch('cps.kobo_auth.current_user', fake_user):
            response = dashboard.__wrapped__()

        assert response == "rendered-dashboard"
        mock_dashboard_data.assert_called_once_with(fake_user)
        mock_render.assert_called_once()
        _, render_kwargs = mock_render.call_args
        assert render_kwargs["excluded_books"] == [{"id": 20, "title": "Blocked Book"}]
        assert render_kwargs["excluded_book_count"] == 1
        assert render_kwargs["page"] == "kobo_dashboard"

    def test_kobo_dashboard_template_contains_reallow_smoke_flow(self):
        """Template smoke test: Kobo selection and blocked-books actions stay visible."""
        template = Path("cps/templates/kobo_dashboard.html").read_text(encoding="utf-8")

        assert "{{ _('Für Kobo ausgewählt') }}" in template
        assert "{{ _('Nicht auf Kobo') }}" in template
        assert "{{ _('System-Check & Hinweise') }}" in template
        assert "{{ _('Hinweis:') }}" in template
        assert "{{ _('Warnung:') }}" not in template
        assert "{{ _('Info:') }}" not in template
        assert "panel panel-warning" not in template
        assert "glyphicon-warning-sign" not in template
        assert "{{ _('Synchronisations-Details anzeigen') }}" in template
        assert "#2f3438" in template
        assert "#5f6b73" in template
        assert "{{ _('Diese Bücher sind bewusst als Nicht auf Kobo markiert.') }}" in template
        assert "{{ _('Keine Bücher für Kobo ausgewählt.') }}" in template
        assert "{{ _('Keine Bücher sind als Nicht auf Kobo markiert.') }}" in template
        assert "url_for('kobo_auth.block_kobo_book', book_id=book.id)" in template
        assert "url_for('kobo_auth.allow_excluded_book', book_id=book.id)" in template
        assert "{{ _('Beim nächsten Sync auslassen') }}" in template
        assert "{{ _('Beim nächsten Sync wieder anbieten') }}" in template

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_book_explanation_route_success(self, mock_get_explanation, mock_calibredb_cls):
        """Test book explanation route returns JSON including the book title."""
        from cps.kobo_auth import book_explanation
        from flask import Flask

        # Setup mock explanation
        mock_get_explanation.return_value = {
            "exists": True,
            "is_allowed_on_device": True,
            "is_visible_on_device": True,
            "blocker_reasons": []
        }

        # Mock book and CalibreDB
        fake_book = MagicMock()
        fake_book.title = "Test Book Title"
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        with app.test_request_context():
            with patch('cps.kobo_auth.current_user', fake_user):
                res = book_explanation.__wrapped__(123)
                data = res.get_json()
                assert data["title"] == "Test Book Title"
                assert data["is_allowed_on_device"] is True
                assert data["is_visible_on_device"] is True

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_book_explanation_route_not_found(self, mock_get_explanation):
        """Test book explanation route returns 404 if explanation not found."""
        from cps.kobo_auth import book_explanation
        from werkzeug.exceptions import NotFound
        from flask import Flask

        mock_get_explanation.return_value = None
        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        with app.test_request_context():
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(NotFound):
                    book_explanation.__wrapped__(123)

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    @patch('cps.kobo_auth.ub.session')
    def test_collection_explanation_route_normal_success(self, mock_session, mock_get_explanation, mock_calibredb_cls):
        """Test collection explanation for normal shelf."""
        from cps.kobo_auth import collection_explanation
        from flask import Flask

        # Setup mock shelf
        fake_shelf = MagicMock()
        fake_shelf.name = "My Normal Shelf"
        fake_shelf.books = [MagicMock(book_id=10), MagicMock(book_id=20)]
        
        shelf_query = MagicMock()
        shelf_query.filter.return_value.first.return_value = fake_shelf
        mock_session.query.return_value = shelf_query

        # Mock Calibre DB book titles
        fake_book_10 = MagicMock()
        fake_book_10.id = 10
        fake_book_10.title = "Book Ten"
        fake_book_20 = MagicMock()
        fake_book_20.id = 20
        fake_book_20.title = "Book Twenty"

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.all.return_value = [fake_book_10, fake_book_20]

        # Mock explanation
        mock_get_explanation.side_effect = lambda uid, bid: {
            "book_id": bid,
            "is_allowed_on_device": bid == 10,
            "blocker_reasons": [] if bid == 10 else ["no_source"]
        }

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        with app.test_request_context('/?type=normal'):
            with patch('cps.kobo_auth.current_user', fake_user):
                res = collection_explanation.__wrapped__(42)
                data = res.get_json()
                assert data["collection_name"] == "My Normal Shelf"
                assert data["collection_type"] == "normal"
                assert len(data["books"]) == 2
                
                assert data["books"][0]["book_id"] == 10
                assert data["books"][0]["title"] == "Book Ten"
                assert data["books"][0]["explanation"]["is_allowed_on_device"] is True
                
                assert data["books"][1]["book_id"] == 20
                assert data["books"][1]["title"] == "Book Twenty"
                assert data["books"][1]["explanation"]["is_allowed_on_device"] is False

    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    @patch('cps.kobo_auth.ub.session')
    def test_collection_explanation_route_magic_success(self, mock_session, mock_get_explanation, mock_calibredb_cls, mock_get_magic_ids):
        """Test collection explanation for magic shelf."""
        from cps.kobo_auth import collection_explanation
        from flask import Flask

        # Setup mock magic shelf
        fake_shelf = MagicMock()
        fake_shelf.name = "My Magic Shelf"
        
        shelf_query = MagicMock()
        shelf_query.filter.return_value.first.return_value = fake_shelf
        mock_session.query.return_value = shelf_query

        # Mock direct magic shelf IDs
        mock_get_magic_ids.return_value = {10}

        # Mock Calibre DB book title
        fake_book_10 = MagicMock()
        fake_book_10.id = 10
        fake_book_10.title = "Book Ten"

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.all.return_value = [fake_book_10]

        # Mock explanation
        mock_get_explanation.return_value = {"book_id": 10, "is_allowed_on_device": True}

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        with app.test_request_context('/?type=magic'):
            with patch('cps.kobo_auth.current_user', fake_user):
                res = collection_explanation.__wrapped__(42)
                data = res.get_json()
                assert data["collection_name"] == "My Magic Shelf"
                assert data["collection_type"] == "magic"
                assert len(data["books"]) == 1
                assert data["books"][0]["title"] == "Book Ten"
                mock_get_magic_ids.assert_called_once_with(fake_shelf)

    @patch('cps.kobo_auth.ub.session')
    def test_collection_explanation_route_ownership_security(self, mock_session):
        """Test collection explanation aborts with 404 if shelf is not found/belongs to another user."""
        from cps.kobo_auth import collection_explanation
        from werkzeug.exceptions import NotFound
        from flask import Flask

        # Mock query returning None
        shelf_query = MagicMock()
        shelf_query.filter.return_value.first.return_value = None
        mock_session.query.return_value = shelf_query

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        
        # Test normal shelf
        with app.test_request_context('/?type=normal'):
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(NotFound):
                    collection_explanation.__wrapped__(42)
                    
        # Test magic shelf
        with app.test_request_context('/?type=magic'):
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(NotFound):
                    collection_explanation.__wrapped__(42)

    def test_collection_explanation_route_invalid_type(self):
        """Test collection explanation aborts with 404 if type parameter is invalid."""
        from cps.kobo_auth import collection_explanation
        from werkzeug.exceptions import NotFound
        from flask import Flask

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        
        with app.test_request_context('/?type=invalid'):
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(NotFound):
                    collection_explanation.__wrapped__(42)
