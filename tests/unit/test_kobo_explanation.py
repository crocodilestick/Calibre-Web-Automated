# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo Sync Explanation Backend."""

import pytest
from unittest.mock import patch, MagicMock

from cps import ub, db
from cps.kobo import get_kobo_book_sync_explanation


@pytest.mark.unit
class TestKoboSyncExplanation:

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_book_not_found(self, mock_calibre_db_class, mock_session, mock_config):
        """When book is not found in Calibre DB, returns appropriate dict."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_session.query().filter().first.return_value = fake_user
        mock_config.config_kobo_sync_magic_shelves = False

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = None
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 999)
        assert res is not None
        assert res["exists"] is False
        assert res["sync_mode"] == "selective"
        assert res["is_allowed_on_device"] is False
        assert res["blocker_reasons"] == ["not_found"]

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_selective_sync_no_source(self, mock_calibre_db_class, mock_session, mock_config):
        """Selective sync mode: when a book has no release source, is_allowed_by_selection is False."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        # Setup mock session query results
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_exclusion_shelf_query = MagicMock()
        mock_exclusion_shelf_query.filter.return_value.all.return_value = []

        mock_synced_query = MagicMock()
        mock_synced_query.filter_by.return_value.first.return_value = None

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_exclusion_shelf_query
            elif model is ub.KoboSyncedBooks:
                return mock_synced_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        # Calibre DB setup
        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["exists"] is True
        assert res["sync_mode"] == "selective"
        assert res["is_allowed_by_selection"] is False
        assert res["is_allowed_on_device"] is False
        assert res["is_visible_on_device"] is False
        assert res["blocker_reasons"] == ["no_source"]

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_selective_sync_allowed_by_normal_shelf(self, mock_calibre_db_class, mock_session, mock_config):
        """Selective sync mode: book is in a normal shelf with kobo_sync = True."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        fake_shelf = MagicMock()
        fake_shelf.id = 10
        fake_shelf.name = "My Sync Shelf"
        fake_shelf.kobo_sync = True

        # Setup mock queries
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []

        mock_sync_shelf_query = MagicMock()
        mock_sync_shelf_query.join().filter().all.return_value = [fake_shelf]

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_sync_shelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_by_selection"] is True
        assert len(res["release_sources"]) == 1
        assert res["release_sources"][0]["type"] == "normal_shelf"
        assert res["release_sources"][0]["id"] == 10
        assert res["release_sources"][0]["name"] == "My Sync Shelf"
        assert res["is_allowed_on_device"] is True
        assert res["is_visible_on_device"] is True
        assert res["blocker_reasons"] == []

    @patch('cps.kobo.config')
    @patch('cps.kobo.magic_shelf')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_selective_sync_allowed_by_magic_shelf(self, mock_calibre_db_class, mock_session, mock_magic_shelf_module, mock_config):
        """Selective sync mode: book matched by Magic Shelf with kobo_sync = True."""
        mock_config.config_kobo_sync_magic_shelves = True

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True

        fake_book = MagicMock()
        fake_book.id = 42

        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 20
        fake_magic_shelf.name = "My Magic Shelf"
        fake_magic_shelf.rules = {"rules": [{"field": "tags", "operator": "equal", "value": "Sci-Fi"}]}
        fake_magic_shelf.is_public = False
        fake_magic_shelf.kobo_sync = True
        fake_magic_shelf.kobo_display = False

        # Setup mock queries
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.join().filter().all.return_value = []
        mock_shelf_query.filter().all.return_value = []

        mock_magic_shelf_query = MagicMock()
        mock_magic_shelf_query.filter_by.return_value.all.return_value = [fake_magic_shelf]

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.MagicShelf:
                return mock_magic_shelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        # Mock Magic Shelf matching
        mock_magic_shelf_module.build_query_from_rules.return_value = "fake-filter"
        mock_magic_shelf_module.get_books_for_magic_shelf.return_value = ([], 0)

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_cdb.session.query().filter().filter().filter().filter().first.return_value = (42,)
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_by_selection"] is True
        assert len(res["release_sources"]) == 1
        assert res["release_sources"][0]["type"] == "magic_shelf"
        assert res["release_sources"][0]["id"] == 20
        assert res["release_sources"][0]["name"] == "My Magic Shelf"
        assert res["is_allowed_on_device"] is True
        assert res["blocker_reasons"] == []

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_selective_sync_blocked_by_exclusion_shelf(self, mock_calibre_db_class, mock_session, mock_config):
        """Selective sync mode: book is in normal sync shelf but also in exclusion shelf."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        fake_sync_shelf = MagicMock()
        fake_sync_shelf.id = 10
        fake_sync_shelf.name = "My Sync Shelf"
        fake_sync_shelf.kobo_sync = True

        fake_ex_shelf = MagicMock()
        fake_ex_shelf.id = 99
        fake_ex_shelf.name = "Kobo: Ausgeschlossen"

        # Setup mock queries
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = [fake_ex_shelf]
        mock_shelf_query.join().filter().all.return_value = [fake_sync_shelf]

        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter().filter().first.return_value = MagicMock()

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.BookShelf:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_by_selection"] is True
        assert res["is_blocked_by_exclusion"] is True
        assert res["is_allowed_on_device"] is False
        assert res["is_visible_on_device"] is False
        assert res["blocker_reasons"] == ["exclusion_shelf"]

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_collections_separation_for_blocked_book(self, mock_calibre_db_class, mock_session, mock_config):
        """Check that display collections are populated, but actual collections are empty for a blocked book."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        fake_sync_shelf = MagicMock()
        fake_sync_shelf.id = 10
        fake_sync_shelf.name = "My Sync Shelf"
        fake_sync_shelf.kobo_sync = True

        fake_ex_shelf = MagicMock()
        fake_ex_shelf.id = 99
        fake_ex_shelf.name = "Kobo: Ausgeschlossen"

        fake_display_shelf = MagicMock()
        fake_display_shelf.id = 11
        fake_display_shelf.name = "My Display Shelf"
        fake_display_shelf.kobo_display = True

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = [fake_ex_shelf]

        mock_join_query = MagicMock()
        mock_shelf_query.join.return_value = mock_join_query

        mock_join_query.filter().all.side_effect = [
            [fake_sync_shelf],     # first call: normal_sync_shelves
            [fake_display_shelf]   # second call: display_shelves
        ]

        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter().filter().first.return_value = MagicMock()

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.BookShelf:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_on_device"] is False
        assert len(res["kobo_display_collections"]) == 1
        assert res["kobo_display_collections"][0]["id"] == 11
        assert len(res["kobo_actual_collections"]) == 0
        assert res["blocker_reasons"] == ["exclusion_shelf"]

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_full_sync_ignores_exclusion_shelf(self, mock_calibre_db_class, mock_session, mock_config):
        """Full sync mode: exclusion shelf is ignored, book is allowed on device."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = False
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        fake_ex_shelf = MagicMock()
        fake_ex_shelf.id = 99
        fake_ex_shelf.name = "Kobo: Ausgeschlossen"

        # Setup mock queries
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = [fake_ex_shelf]
        mock_shelf_query.join().filter().all.return_value = []

        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter().filter().first.return_value = MagicMock()

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.BookShelf:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["sync_mode"] == "full"
        assert res["is_allowed_by_selection"] is True
        assert res["is_blocked_by_exclusion"] is False
        assert res["is_allowed_on_device"] is True
        assert res["is_visible_on_device"] is True
        assert res["blocker_reasons"] == []

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_archived_semantics(self, mock_calibre_db_class, mock_session, mock_config):
        """Archived books do not block selection, but make the book not visible on device."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = False
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        fake_archived = MagicMock()
        fake_archived.is_archived = True

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = fake_archived

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []
        mock_shelf_query.join().filter().all.return_value = []

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_by_selection"] is True
        assert res["is_archived"] is True
        assert res["is_allowed_on_device"] is True
        assert res["is_visible_on_device"] is False
        assert res["blocker_reasons"] == ["archived"]

    @patch('cps.kobo.config')
    @patch('cps.kobo.magic_shelf')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_magic_shelves_disabled(self, mock_calibre_db_class, mock_session, mock_magic_shelf_module, mock_config):
        """When magic shelves config is False, magic shelves are completely ignored."""
        mock_config.config_kobo_sync_magic_shelves = False

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True

        fake_book = MagicMock()
        fake_book.id = 42

        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 20
        fake_magic_shelf.name = "My Magic Shelf"
        fake_magic_shelf.rules = {"rules": []}

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []
        mock_shelf_query.join().filter().all.return_value = []

        mock_magic_query = MagicMock()
        mock_magic_query.filter_by.return_value.all.return_value = [fake_magic_shelf]

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.MagicShelf:
                return mock_magic_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert len(res["release_sources"]) == 0
        assert len(res["kobo_display_collections"]) == 0
        assert res["blocker_reasons"] == ["no_source"]

    @patch('cps.kobo.config')
    @patch('cps.kobo.magic_shelf')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_magic_shelf_1000_cap(self, mock_calibre_db_class, mock_session, mock_magic_shelf_module, mock_config):
        """Magic shelf index > 1000 sets capped = True on display collection and excludes it from actual collections."""
        mock_config.config_kobo_sync_magic_shelves = True

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True

        fake_book = MagicMock()
        fake_book.id = 42

        fake_magic_shelf = MagicMock()
        fake_magic_shelf.id = 20
        fake_magic_shelf.name = "My Capped Shelf"
        fake_magic_shelf.rules = {"rules": []}
        fake_magic_shelf.kobo_sync = True
        fake_magic_shelf.kobo_display = True
        fake_magic_shelf.is_public = False

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []
        mock_shelf_query.join().filter().all.return_value = []

        mock_magic_query = MagicMock()
        mock_magic_query.filter_by.return_value.all.return_value = [fake_magic_shelf]

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.MagicShelf:
                return mock_magic_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        # Mock Magic Shelf matching
        mock_magic_shelf_module.build_query_from_rules.return_value = "fake-filter"

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_cdb.session.query().filter().filter().filter().filter().first.return_value = (42,)
        mock_calibre_db_class.return_value = mock_cdb

        # Mock get_books_for_magic_shelf
        another_book = MagicMock()
        another_book.id = 999
        mock_magic_shelf_module.get_books_for_magic_shelf.return_value = ([another_book], 1500)

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["is_allowed_by_selection"] is True
        assert len(res["release_sources"]) == 1
        assert res["release_sources"][0]["id"] == 20
        assert res["is_allowed_on_device"] is True
        assert len(res["kobo_display_collections"]) == 1
        assert res["kobo_display_collections"][0]["id"] == 20
        assert res["kobo_display_collections"][0]["capped"] is True
        assert len(res["kobo_actual_collections"]) == 0
        assert res["blocker_reasons"] == []
