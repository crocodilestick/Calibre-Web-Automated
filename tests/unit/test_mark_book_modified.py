# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pins the single source of truth for "this book changed".

Marking a book modified is a coupled triplet:
  1. bump ``book.last_modified``  → drives the web cover/metadata cache-buster
     (the jinjia ``last_modified`` filter on every cover URL) AND Kobo native
     sync selection (``Books.last_modified > sync_token.books_last_modified``).
  2. ``set_metadata_dirty``        → queues CWA metadata write-back.
  3. ``remove_synced_book(all=True)`` → forces all Kobo devices to re-pull.

That triplet used to be copy-pasted across ~6 call sites with no shared
helper, so a new write path could silently forget a step — exactly the bug
that shipped through v4.0.140 (cover-picker apply never bumped last_modified).
``helper.mark_book_modified`` consolidates it; these tests pin the helper's
behavior AND assert the heterogeneous call sites route through it instead of
re-implementing a raw ``last_modified = datetime.now(...)`` bump.
"""

import datetime
import inspect
from unittest.mock import MagicMock, patch

import pytest


def _book():
    b = MagicMock()
    b.id = 42
    b.last_modified = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    return b


@pytest.mark.unit
class TestMarkBookModified:

    def test_default_bumps_last_modified_and_sets_dirty_without_unsync(self):
        from cps import helper
        b = _book()
        before = b.last_modified
        with patch.object(helper.calibre_db, "set_metadata_dirty") as dirty, \
             patch("cps.kobo_sync_status.remove_synced_book") as unsync:
            helper.mark_book_modified(b)
        assert b.last_modified > before
        dirty.assert_called_once_with(42)
        unsync.assert_not_called()

    def test_set_dirty_false_skips_metadata_dirty(self):
        from cps import helper
        b = _book()
        before = b.last_modified
        with patch.object(helper.calibre_db, "set_metadata_dirty") as dirty, \
             patch("cps.kobo_sync_status.remove_synced_book") as unsync:
            helper.mark_book_modified(b, set_dirty=False)
        assert b.last_modified > before
        dirty.assert_not_called()
        unsync.assert_not_called()

    def test_unsync_true_removes_synced_books_for_all_users(self):
        from cps import helper
        b = _book()
        before = b.last_modified
        with patch.object(helper.calibre_db, "set_metadata_dirty") as dirty, \
             patch("cps.kobo_sync_status.remove_synced_book") as unsync:
            helper.mark_book_modified(b, unsync=True)
        assert b.last_modified > before
        dirty.assert_called_once_with(42)
        unsync.assert_called_once_with(42, all=True)

    def test_source_pins_the_triplet(self):
        from cps import helper
        src = inspect.getsource(helper.mark_book_modified)
        assert "last_modified" in src
        assert "set_metadata_dirty" in src
        assert "remove_synced_book" in src


@pytest.mark.unit
class TestCallSitesRouteThroughHelper:
    """The class-of-bug guard: no write path may re-implement a raw
    last_modified bump. Every site goes through mark_book_modified so the
    invariant lives in exactly one place."""

    def test_editbooks_has_no_raw_last_modified_bump(self):
        from cps import editbooks
        src = inspect.getsource(editbooks)
        assert "last_modified = datetime.now" not in src, (
            "editbooks must route last_modified bumps through "
            "helper.mark_book_modified, not a raw assignment"
        )
        assert "mark_book_modified" in src

    def test_cover_picker_has_no_raw_last_modified_bump(self):
        from cps import cover_picker
        src = inspect.getsource(cover_picker)
        assert "last_modified = datetime.now" not in src
        assert "mark_book_modified" in src
