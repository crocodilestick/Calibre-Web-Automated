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
        """Exclusion entries should be returned with Calibre titles for the dashboard."""
        fake_row = MagicMock(book_id=20)
        mock_session.query.return_value.filter_by.return_value.all.return_value = [fake_row]

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

    @patch('cps.kobo.get_kobo_blocked_book_ids')
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
        mock_allowed_dashboard_books,
        mock_blocked_books
    ):
        """Test basic dashboard aggregation and counts in two-column mode."""
        mock_blocked_books.return_value = {40}
        # Setup config
        mock_config.config_kobo_sync_magic_shelves = True
        mock_excluded.return_value = [{"id": 40, "title": "Blocked Book"}]
        mock_allowed_dashboard_books.return_value = [{"id": 10, "title": "Allowed Book"}]

        # Mock user
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = True
        fake_user.kobo_only_shelves_sync = 1  # Two-column mode

        # Mock allowed book IDs (union of kobo_sync shelves)
        mock_allowed_books.return_value = {10, 20, 30}

        # Mock KoboSyncedBooks
        fake_synced = [MagicMock(book_id=10), MagicMock(book_id=20)]

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

        # Mock remote token check
        mock_token = MagicMock()

        def session_query_side_effect(*args):
            q = MagicMock()
            if not args:
                return q
            model_str = str(args[0])
            if "RemoteAuthToken" in model_str:
                q.filter_by.return_value.first.return_value = mock_token
            elif "KoboSyncedBooks" in model_str:
                q.filter_by.return_value.all.return_value = fake_synced
            elif "KoboBookOverride" in model_str:
                q.filter_by.return_value.all.return_value = [MagicMock(book_id=40, reader_override="never")]
            elif "Shelf" in model_str and "MagicShelf" not in model_str:
                q.filter_by.return_value.all.return_value = [fake_normal_shelf]
            elif "MagicShelf" in model_str:
                q.filter_by.return_value.all.return_value = [fake_magic_shelf]
            return q

        mock_session.query.side_effect = session_query_side_effect

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

    @patch('cps.kobo.get_kobo_blocked_book_ids')
    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    def test_get_kobo_dashboard_data_warnings(self, mock_session, mock_allowed_books, mock_magic_ids, mock_config, mock_excluded, mock_blocked):
        """Test specific warnings generated by get_kobo_dashboard_data."""
        mock_blocked.return_value = set()
        # Setup config
        mock_config.config_kobo_sync_magic_shelves = False
        mock_excluded.return_value = []

        # User lacks download role and runs full sync
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = False
        fake_user.kobo_only_shelves_sync = 0  # Full Sync mode

        # Token exists
        mock_token = MagicMock()

        # In Full Sync mode allowed_book_ids is None
        mock_allowed_books.return_value = None

        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 99
        fake_magic_shelf.uuid = "magic-uuid"
        fake_magic_shelf.name = "My Magic Shelf"
        fake_magic_shelf.kobo_sync = True
        mock_magic_ids.return_value = set()

        def session_query_side_effect(*args):
            q = MagicMock()
            if not args:
                return q
            model_str = str(args[0])
            if "RemoteAuthToken" in model_str:
                q.filter_by.return_value.first.return_value = mock_token
            elif "KoboSyncedBooks" in model_str:
                q.filter_by.return_value.all.return_value = []
            elif "KoboBookOverride" in model_str:
                q.filter_by.return_value.all.return_value = []
            elif "Shelf" in model_str and "MagicShelf" not in model_str:
                q.filter_by.return_value.all.return_value = []
            elif "MagicShelf" in model_str:
                q.filter_by.return_value.all.return_value = [fake_magic_shelf]
            return q

        mock_session.query.side_effect = session_query_side_effect

        dashboard_data = get_kobo_dashboard_data(fake_user)
        warns = dashboard_data["warnings"]

        warn_codes = [w["code"] for w in warns]
        assert "MISSING_DOWNLOAD_ROLE" in warn_codes
        assert "FULL_SYNC_MODE" in warn_codes
        assert "MAGIC_SHELVES_DISABLED" in warn_codes
        assert "EMPTY_COLLECTION" in warn_codes
        assert next(w for w in warns if w["code"] == "FULL_SYNC_MODE")["type"] == "info"
        assert next(w for w in warns if w["code"] == "MAGIC_SHELVES_DISABLED")["type"] == "info"

    @patch('cps.kobo.get_kobo_blocked_book_ids')
    @patch('cps.kobo_dashboard.db.CalibreDB')
    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo_dashboard.get_magic_shelf_book_ids_direct')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    def test_get_kobo_dashboard_data_full_sync_allowed_count_query(
        self,
        mock_session,
        mock_allowed_books,
        mock_magic_ids,
        mock_config,
        mock_excluded,
        mock_calibre_db_cls,
        mock_blocked_books
    ):
        """Test allowed_book_count calculation in Full Sync mode.
        It should filter by Kobo formats and exclude blocked books in SQL query.
        """
        # ID 40 is blocked (never override)
        mock_blocked_books.return_value = {40}
        mock_config.config_kobo_sync_magic_shelves = False
        mock_excluded.return_value = []
        mock_allowed_books.return_value = None  # Full Sync

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = True
        fake_user.kobo_only_shelves_sync = 0  # Full Sync

        # Mock token & synced & shelves
        mock_session.query().filter_by().first.return_value = MagicMock()
        mock_session.query().filter_by().all.return_value = []

        # Mock CalibreDB Session query for total_visible_count
        mock_cdb = MagicMock()
        mock_calibre_db_cls.return_value = mock_cdb
        mock_cdb_session = MagicMock()
        mock_cdb.session = mock_cdb_session

        # Mock query chain
        mock_query = mock_cdb_session.query.return_value
        mock_join = mock_query.join.return_value
        mock_filter1 = mock_join.filter.return_value
        mock_filter2 = mock_filter1.filter.return_value
        mock_filter3 = mock_filter2.filter.return_value
        mock_distinct = mock_filter3.distinct.return_value
        mock_distinct.count.return_value = 5

        # Call dashboard data
        dashboard_data = get_kobo_dashboard_data(fake_user)

        # The allowed count must be exactly 5
        assert dashboard_data["allowed_book_count"] == 5

        # Verify SQL filter arg for notin_ was called
        mock_filter2.filter.assert_called_once()
        filter_arg = mock_filter2.filter.call_args[0][0]
        assert filter_arg is not True

    @patch('cps.magic_shelf.invalidate_magic_shelf_cache')
    @patch('cps.kobo_auth.url_for')
    @patch('cps.kobo_auth.redirect')
    @patch('cps.kobo_auth.flash')
    @patch('cps.kobo_auth.current_user')
    @patch('cps.kobo_auth.ub.session')
    def test_allow_excluded_book_removes_entry(self, mock_session, mock_current_user, mock_flash, mock_redirect, mock_url_for, mock_invalidate):
        """The re-allow action removes the KoboBookOverride entry."""
        from cps.kobo_auth import allow_excluded_book

        mock_current_user.id = 1
        mock_url_for.return_value = "/kobo_auth/dashboard"
        mock_redirect.side_effect = lambda target: target

        fake_override = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = fake_override

        response = allow_excluded_book.__wrapped__(20)

        assert response == "/kobo_auth/dashboard"
        mock_session.delete.assert_called_once_with(fake_override)
        mock_invalidate.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_flash.assert_called_once()

    @patch('cps.magic_shelf.invalidate_magic_shelf_cache')
    @patch('cps.kobo_auth.url_for')
    @patch('cps.kobo_auth.redirect')
    @patch('cps.kobo_auth.flash')
    @patch('cps.kobo_auth.current_user')
    @patch('cps.kobo_auth.ub.session')
    def test_allow_excluded_book_ignores_always_override(self, mock_session, mock_current_user, mock_flash, mock_redirect, mock_url_for, mock_invalidate):
        """The re-allow action does not touch 'always' overrides."""
        from cps.kobo_auth import allow_excluded_book

        mock_current_user.id = 1
        mock_url_for.return_value = "/kobo_auth/dashboard"
        mock_redirect.side_effect = lambda target: target

        # No 'never' override found (since we query for reader_override='never')
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = allow_excluded_book.__wrapped__(20)

        assert response == "/kobo_auth/dashboard"
        assert not mock_session.delete.called
        mock_invalidate.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_flash.assert_called_once()

    @patch('cps.magic_shelf.invalidate_magic_shelf_cache')
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
        mock_invalidate
    ):
        """The block action adds an override entry with reader_override='never'."""
        from cps.kobo_auth import block_kobo_book

        mock_current_user.id = 1
        mock_url_for.return_value = "/kobo_auth/dashboard"
        mock_redirect.side_effect = lambda target: target

        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = block_kobo_book.__wrapped__(20)

        assert response == "/kobo_auth/dashboard"
        mock_session.add.assert_called_once()
        added_override = mock_session.add.call_args[0][0]
        assert isinstance(added_override, ub.KoboBookOverride)
        assert added_override.book_id == 20
        assert added_override.reader_override == "never"
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
        assert "{{ _('Manuell für den Kobo blockiert („Nicht auf Kobo“).') }}" in template
        assert "Kobo: Ausgeschlossen" not in template
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

    def test_kobo_dashboard_script_runs_after_global_jquery(self):
        """Dashboard click handlers must be in the js block after layout loads jQuery."""
        template = Path("cps/templates/kobo_dashboard.html").read_text(encoding="utf-8")

        assert "{% block js %}" in template
        assert template.index("{% block js %}") < template.index(".kobo-book-details")
        assert template.index("{% block js %}") < template.index("$('.kobo-collection-details')")

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

    @patch('cps.kobo.magic_shelf.build_query_from_rules')
    @patch('cps.kobo.magic_shelf.get_books_for_magic_shelf')
    @patch('cps.kobo.db.CalibreDB')
    @patch('cps.kobo.ub.session')
    @patch('cps.kobo.config')
    def test_get_kobo_books_sync_explanations_golden_cases(
        self,
        mock_config,
        mock_session,
        mock_calibredb_cls,
        mock_get_magic_books,
        mock_build_query
    ):
        """Test Batch Sync Explanations with golden cases (always, never, auto, passive collection)."""
        from cps.kobo import get_kobo_books_sync_explanations
        mock_config.config_kobo_sync_magic_shelves = True

        # Mock user
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = 1 # selective sync
        mock_session.query.return_value.filter.return_value.first.return_value = fake_user

        # Books list
        book_ids = [10, 20, 30, 40, 50]

        # Mock Calibre Books
        fake_books = []
        for bid in book_ids:
            b = MagicMock()
            b.id = bid
            b.title = f"Book {bid}"
            fake_books.append(b)

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.all.return_value = fake_books

        # Mocks for database tables
        # ArchivedBooks: Book 30 is archived
        fake_archived = MagicMock(book_id=30, is_archived=True)
        # Overrides: Book 10 is 'always', Book 20 is 'never', Book 30, 40, 50 are 'auto'
        fake_override_10 = MagicMock(book_id=10, reader_override="always")
        fake_override_20 = MagicMock(book_id=20, reader_override="never")

        # SyncedBooks: Book 10 and 20 are synced
        fake_synced_10 = MagicMock(book_id=10)
        fake_synced_20 = MagicMock(book_id=20)

        # Setup mock row objects
        fake_row_40 = MagicMock()
        fake_row_40.book_id = 40
        fake_row_40.id = 100
        fake_row_40.name = "Active Sync Shelf"
        fake_row_40.kobo_sync = True
        fake_row_40.kobo_display = True

        fake_row_50 = MagicMock()
        fake_row_50.book_id = 50
        fake_row_50.id = 200
        fake_row_50.name = "Passive Display Shelf"
        fake_row_50.kobo_sync = False
        fake_row_50.kobo_display = True

        # Mock session query side effect
        def query_side_effect(model, *args):
            q = MagicMock()
            if model is ub.User:
                q.filter.return_value.first.return_value = fake_user
            elif model is ub.ArchivedBook:
                q.filter.return_value.all.return_value = [fake_archived]
            elif model is ub.KoboBookOverride:
                q.filter.return_value.all.return_value = [fake_override_10, fake_override_20]
            elif model is ub.MagicShelf:
                q.filter_by.return_value.all.return_value = []
            elif model is ub.KoboSyncedBooks:
                q.filter.return_value.all.return_value = [fake_synced_10, fake_synced_20]
            else:
                # normal shelves column join returning rows
                q.join.return_value.filter.return_value.filter.return_value.all.return_value = [
                    fake_row_40, fake_row_50
                ]
            return q

        mock_session.query.side_effect = query_side_effect

        explanations = get_kobo_books_sync_explanations(1, book_ids)

        assert len(explanations) == 5

        # Book 10: always override
        assert explanations[10]["reader_override"] == "always"
        assert explanations[10]["is_allowed_on_device"] is True
        assert explanations[10]["is_synced"] is True

        # Book 20: never override
        assert explanations[20]["reader_override"] == "never"
        assert explanations[20]["is_allowed_on_device"] is False
        assert explanations[20]["is_synced"] is True

        # Book 30: archived, auto, not allowed
        assert explanations[30]["reader_override"] == "auto"
        assert explanations[30]["is_archived"] is True
        assert explanations[30]["is_allowed_on_device"] is False

        # Book 40: in active sync shelf -> allowed
        assert explanations[40]["reader_override"] == "auto"
        assert explanations[40]["is_allowed_on_device"] is True
        assert len(explanations[40]["kobo_actual_collections"]) == 1
        assert explanations[40]["kobo_actual_collections"][0]["name"] == "Active Sync Shelf"

        # Book 50: in passive display shelf, but not allowed (no sync source)
        assert explanations[50]["reader_override"] == "auto"
        assert explanations[50]["is_allowed_on_device"] is False
        assert len(explanations[50]["kobo_display_collections"]) == 1
        assert len(explanations[50]["kobo_actual_collections"]) == 0

    @patch('cps.kobo.magic_shelf.build_query_from_rules')
    @patch('cps.kobo.magic_shelf.get_books_for_magic_shelf')
    @patch('cps.kobo.db.CalibreDB')
    @patch('cps.kobo.ub.session')
    @patch('cps.kobo.config')
    def test_passive_collection_rendered_when_book_allowed_by_other_source(
        self,
        mock_config,
        mock_session,
        mock_calibredb_cls,
        mock_get_magic_books,
        mock_build_query
    ):
        """A book in a passive collection (kobo_display=True, kobo_sync=False) should render if allowed by another source."""
        from cps.kobo import get_kobo_books_sync_explanations
        mock_config.config_kobo_sync_magic_shelves = True

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = 1

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        fake_book = MagicMock(id=10, title="Multi-shelf Book")
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.all.return_value = [fake_book]

        # Setup mock row objects
        fake_row_100 = MagicMock()
        fake_row_100.book_id = 10
        fake_row_100.id = 100
        fake_row_100.name = "Active Sync Only"
        fake_row_100.kobo_sync = True
        fake_row_100.kobo_display = False

        fake_row_200 = MagicMock()
        fake_row_200.book_id = 10
        fake_row_200.id = 200
        fake_row_200.name = "Passive Display Only"
        fake_row_200.kobo_sync = False
        fake_row_200.kobo_display = True

        def query_side_effect(model, *args):
            q = MagicMock()
            if model is ub.User:
                q.filter.return_value.first.return_value = fake_user
            elif model is ub.ArchivedBook:
                q.filter.return_value.all.return_value = []
            elif model is ub.KoboBookOverride:
                q.filter.return_value.all.return_value = []
            elif model is ub.MagicShelf:
                q.filter_by.return_value.all.return_value = []
            elif model is ub.KoboSyncedBooks:
                q.filter.return_value.all.return_value = []
            else:
                q.join.return_value.filter.return_value.filter.return_value.all.return_value = [
                    fake_row_100, fake_row_200
                ]
            return q

        mock_session.query.side_effect = query_side_effect

        explanations = get_kobo_books_sync_explanations(1, [10, 11])

        assert explanations[10]["is_allowed_on_device"] is True
        assert len(explanations[10]["kobo_display_collections"]) == 1
        assert explanations[10]["kobo_display_collections"][0]["id"] == 200
        assert len(explanations[10]["kobo_actual_collections"]) == 1
        assert explanations[10]["kobo_actual_collections"][0]["id"] == 200

    @patch('cps.kobo.get_kobo_books_sync_explanations')
    @patch('cps.kobo.get_kobo_blocked_book_ids')
    @patch('cps.kobo_dashboard.get_kobo_excluded_books')
    @patch('cps.kobo_dashboard.config')
    @patch('cps.kobo.get_kobo_allowed_book_ids')
    @patch('cps.ub.session')
    @patch('cps.kobo_dashboard.db.CalibreDB')
    def test_get_kobo_dashboard_data_full_sync_limits_workspace(
        self,
        mock_calibredb_cls,
        mock_session,
        mock_allowed_books,
        mock_config,
        mock_excluded,
        mock_blocked,
        mock_batch_explain
    ):
        """In Full Sync mode, the workspace books list is limited to SyncedBooks + Overrides."""
        mock_blocked.return_value = set()
        mock_config.config_kobo_sync_magic_shelves = False
        mock_excluded.return_value = []

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.role_download.return_value = True
        fake_user.kobo_only_shelves_sync = 0

        mock_allowed_books.return_value = None

        fake_synced = [MagicMock(book_id=10)]
        fake_override = MagicMock(book_id=20, reader_override="always")

        q = MagicMock()
        q.filter_by.return_value.first.return_value = MagicMock()
        q.filter_by.return_value.all.side_effect = [
            fake_synced,
            [fake_override],
            [],
            []
        ]
        mock_session.query.return_value = q

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        fake_book_10 = MagicMock(id=10, title="Synced Book")
        fake_book_20 = MagicMock(id=20, title="Override Book")
        mock_cdb.session.query.return_value.filter.return_value.filter.return_value.all.return_value = [fake_book_10, fake_book_20]

        mock_batch_explain.return_value = {
            10: {"is_synced": True, "is_allowed_on_device": True, "reader_override": "auto", "kobo_actual_collections": []},
            20: {"is_synced": False, "is_allowed_on_device": True, "reader_override": "always", "kobo_actual_collections": []}
        }

        dashboard_data = get_kobo_dashboard_data(fake_user)

        called_book_ids = set(mock_batch_explain.call_args[0][1])
        assert called_book_ids == {10, 20}

        wb = dashboard_data["workspace_books"]
        assert len(wb) == 2
        assert wb[0]["id"] == 10
        assert wb[1]["id"] == 20
