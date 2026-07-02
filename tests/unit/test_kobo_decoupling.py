# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo Sync Decoupling (2-Säulen-Prinzip)."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from cps import ub, db
from cps.kobo import (
    get_kobo_allowed_book_ids,
    create_kobo_tag,
    create_kobo_tag_magic,
    sync_shelves
)


@pytest.mark.unit
class TestKoboSyncDecoupling:

    @patch('cps.ub.session')
    def test_get_kobo_allowed_book_ids_all_books(self, mock_session):
        """When kobo_only_shelves_sync is False, allowed book IDs must be None (all allowed)."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = False

        mock_session.query().filter().first.return_value = fake_user

        allowed = get_kobo_allowed_book_ids(1)
        assert allowed is None

    @patch('cps.kobo.get_magic_shelf_book_ids_for_kobo')
    @patch('cps.ub.session')
    def test_get_kobo_allowed_book_ids_restricted_union(self, mock_session, mock_get_magic):
        """When kobo_only_shelves_sync is True, allowed books must be the union of normal shelves and magic shelves."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True

        # Mock user query
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user

        # Mock normal shelf books query: returns book IDs [10, 20]
        fake_bookshelf_records = [MagicMock(book_id=10), MagicMock(book_id=20)]
        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.join().filter().all.return_value = fake_bookshelf_records

        def query_side_effect(model_or_column):
            if model_or_column is ub.User:
                return mock_user_query
            elif model_or_column is ub.BookShelf.book_id:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        # Mock magic shelf allowed books: returns book IDs [20, 30]
        mock_get_magic.return_value = {20, 30}

        allowed = get_kobo_allowed_book_ids(1)

        # Expected union: {10, 20, 30}
        assert allowed == {10, 20, 30}

    @patch('cps.calibre_db.get_book')
    def test_create_kobo_tag_security_barrier(self, mock_get_book):
        """Tag items must be filtered against allowed_book_ids (security barrier)."""
        fake_shelf = MagicMock()
        fake_shelf.created = datetime.now(timezone.utc)
        fake_shelf.last_modified = datetime.now(timezone.utc)
        fake_shelf.uuid = "shelf-uuid"
        fake_shelf.name = "My Collection"

        # Shelf has books 100, 200, 300
        fake_book_shelves = [
            MagicMock(book_id=100),
            MagicMock(book_id=200),
            MagicMock(book_id=300)
        ]
        fake_shelf.books = fake_book_shelves

        # Calibre DB returns valid books
        fake_book_100 = MagicMock(uuid="uuid-100")
        fake_book_300 = MagicMock(uuid="uuid-300")

        def get_book_side_effect(book_id):
            if book_id == 100:
                return fake_book_100
            elif book_id == 300:
                return fake_book_300
            return None

        mock_get_book.side_effect = get_book_side_effect

        # Only [100, 300] are in allowed_book_ids (book 200 is restricted)
        allowed_ids = {100, 300}

        result = create_kobo_tag(fake_shelf, allowed_ids)
        items = result["Tag"]["Items"]

        # Only allowed books (100 and 300) should be included
        assert len(items) == 2
        assert items[0]["RevisionId"] == "uuid-100"
        assert items[1]["RevisionId"] == "uuid-300"

    def test_create_kobo_tag_magic_security_barrier(self):
        """Magic Tag items must be filtered against allowed_book_ids."""
        fake_shelf = MagicMock()
        fake_shelf.created = datetime.now(timezone.utc)
        fake_shelf.last_modified = datetime.now(timezone.utc)
        fake_shelf.uuid = "magic-uuid"
        fake_shelf.name = "Magic Collection"

        fake_books = [
            MagicMock(id=10, uuid="uuid-10"),
            MagicMock(id=20, uuid="uuid-20")
        ]

        # Only book 10 is allowed
        allowed_ids = {10}

        result = create_kobo_tag_magic(fake_shelf, fake_books, allowed_ids)
        items = result["Tag"]["Items"]

        assert len(items) == 1
        assert items[0]["RevisionId"] == "uuid-10"

    @patch('cps.ub.session')
    @patch('cps.kobo.create_kobo_tag')
    @patch('cps.kobo.shelf_lib.check_shelf_view_permissions')
    @patch('cps.kobo.current_user')
    def test_sync_shelves_display_and_archive_propagation(self, mock_user, mock_permissions, mock_create_tag, mock_session):
        """Test that sync_shelves uses kobo_display, filters by modification time, and processes ShelfArchive."""
        mock_user.id = 1
        mock_permissions.return_value = True

        # 1. Setup ShelfArchive record (deleted tag)
        fake_archive = MagicMock()
        fake_archive.uuid = "deleted-uuid"
        fake_archive.last_modified = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)

        # 2. Setup Active Shelf (kobo_display == True)
        fake_active_shelf = MagicMock()
        fake_active_shelf.uuid = "active-uuid"
        fake_active_shelf.created = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
        fake_active_shelf.last_modified = datetime(2026, 7, 2, 13, 0, 0, tzinfo=timezone.utc)

        # 3. Setup Deactivated Shelf (kobo_display == False) which was recently modified
        fake_deactivated_shelf = MagicMock()
        fake_deactivated_shelf.uuid = "deactivated-uuid"
        fake_deactivated_shelf.last_modified = datetime(2026, 7, 2, 14, 0, 0, tzinfo=timezone.utc)

        # Mock Queries
        mock_archive_query = MagicMock()
        mock_archive_query.filter.return_value = [fake_archive]

        # Mock Active and Deactivated shelves queries
        mock_shelf_query = MagicMock()

        # When querying shelves, we need side effects because query structure differs
        def shelf_query_side_effect(*args, **kwargs):
            return mock_shelf_query

        # Let the query return the deactivated shelf for deactivated query
        # and active shelf for active query.
        mock_shelf_query.filter.return_value = [fake_deactivated_shelf]
        mock_shelf_query.outerjoin.return_value.filter.return_value.distinct.return_value.order_by.return_value = [fake_active_shelf]

        def query_side_effect(model):
            if model is ub.ShelfArchive:
                return mock_archive_query
            elif model is ub.Shelf:
                return mock_shelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        # Mock Tag generation
        mock_create_tag.return_value = {"Tag": {"Id": "active-uuid", "Name": "Active"}}

        sync_token = MagicMock()
        # Last sync was at 11:00
        sync_token.tags_last_modified = datetime(2026, 7, 2, 11, 0, 0, tzinfo=timezone.utc)

        sync_results = []
        sync_shelves(sync_token, sync_results, allowed_book_ids=None, only_kobo_shelves=False)

        deleted_uuids = [
            res["DeletedTag"]["Tag"]["Id"]
            for res in sync_results
            if "DeletedTag" in res
        ]
        assert "deleted-uuid" in deleted_uuids
        assert "deactivated-uuid" in deleted_uuids

        new_tags = [
            res["NewTag"]["Tag"]["Id"]
            for res in sync_results
            if "NewTag" in res
        ]
        changed_tags = [
            res["ChangedTag"]["Tag"]["Id"]
            for res in sync_results
            if "ChangedTag" in res
        ]
        assert ("active-uuid" in new_tags) or ("active-uuid" in changed_tags)

        # Assert ShelfArchive entry was deleted after sync
        mock_session.delete.assert_called_with(fake_archive)

    @patch('cps.kobo.make_response')
    @patch('scripts.cwa_db.CWA_DB')
    @patch('cps.kobo.get_download_url_for_book')
    @patch('cps.kobo.magic_shelf')
    @patch('cps.kobo.config')
    @patch('cps.kobo.calibre_db')
    @patch('cps.kobo.ub.session')
    @patch('cps.kobo.SyncToken.SyncToken')
    def test_handle_sync_request_reading_states_no_name_error(
        self, mock_sync_token_cls, mock_session, mock_calibre_db, mock_config, mock_magic_shelf, mock_get_download_url, mock_cwa_db, mock_make_response
    ):
        """Verify that HandleSyncRequest runs without NameError when only_kobo_shelves is active."""
        import cps.kobo
        import cps.kobo_auth

        # Setup current_user
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.kobo_only_shelves_sync = True
        mock_user.role_download.return_value = True

        # Back up Flask globals
        original_request = cps.kobo.request
        original_current_user = cps.kobo.current_user
        original_current_app = cps.kobo.current_app
        original_g = cps.kobo_auth.g

        cps.kobo.request = MagicMock()
        cps.kobo.current_user = mock_user
        cps.kobo.current_app = MagicMock()

        # Setup a mock for g that supports "auth_token" in g
        mock_g = MagicMock()
        mock_g.__contains__.return_value = True
        cps.kobo_auth.g = mock_g

        # Patch download link generator
        mock_get_download_url.return_value = "http://dummy/download"

        # Mock CWA_DB to bypass DB connection logic
        mock_cwa_db.return_value = MagicMock()

        # Mock make_response to return a Response-like mock object
        mock_response_obj = MagicMock()
        mock_response_obj.headers = {}
        mock_make_response.return_value = mock_response_obj

        try:
            # Setup SyncToken
            fake_sync_token = MagicMock()
            fake_sync_token.books_last_modified = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
            fake_sync_token.books_last_created = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
            fake_sync_token.reading_state_last_modified = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
            fake_sync_token.tags_last_modified = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
            mock_sync_token_cls.from_headers.return_value = fake_sync_token

            # Setup config
            mock_config.config_kobo_sync_magic_shelves = False
            mock_config.config_kobo_proxy = False

            # Mock KoboSyncedBooks query count
            mock_synced_books_query = MagicMock()
            mock_synced_books_query.filter.return_value.count.return_value = 1

            # Mock KoboReadingState query chain with Fluent Mocking
            mock_reading_states_query = MagicMock()
            mock_reading_states_query.filter.return_value = mock_reading_states_query
            mock_reading_states_query.order_by.return_value = mock_reading_states_query
            mock_reading_states_query.limit.return_value = mock_reading_states_query
            mock_reading_states_query.count.return_value = 0
            mock_reading_states_query.all.return_value = []

            # Mock calibre_db queries for changed_entries
            mock_changed_entries = MagicMock()
            # Return self from query methods chain to allow calling filter, join etc.
            mock_changed_entries.join.return_value = mock_changed_entries
            mock_changed_entries.outerjoin.return_value = mock_changed_entries
            mock_changed_entries.filter.return_value = mock_changed_entries
            mock_changed_entries.order_by.return_value = mock_changed_entries
            mock_changed_entries.distinct.return_value = mock_changed_entries

            # Setup mock expectations
            mock_changed_entries.count.return_value = 0
            mock_changed_entries.first.return_value = None
            mock_changed_entries.limit.return_value.all.return_value = []

            def query_side_effect(model):
                if model is ub.KoboSyncedBooks:
                    return mock_synced_books_query
                elif model is ub.KoboReadingState:
                    return mock_reading_states_query
                elif model is ub.ShelfArchive:
                    return MagicMock()
                elif model is ub.Shelf:
                    return MagicMock()
                return MagicMock()

            mock_session.query.side_effect = query_side_effect
            mock_calibre_db.session.query.return_value = mock_changed_entries

            # We mock our new Helper to return some book IDs
            with patch('cps.kobo.get_kobo_allowed_book_ids') as mock_get_allowed:
                mock_get_allowed.return_value = {100, 200}

                # Executing HandleSyncRequest bypassing decorator with __wrapped__
                response = cps.kobo.HandleSyncRequest.__wrapped__()

                # Ensure get_kobo_allowed_book_ids was called
                mock_get_allowed.assert_called_with(1)
                # Ensure query on KoboReadingState was filtered with the allowed book ids
                filter_calls = mock_reading_states_query.filter.return_value.filter.call_args_list
                assert len(filter_calls) > 0
        finally:
            # Restore Flask globals
            cps.kobo.request = original_request
            cps.kobo.current_user = original_current_user
            cps.kobo.current_app = original_current_app
            cps.kobo_auth.g = original_g
