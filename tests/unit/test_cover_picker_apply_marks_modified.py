# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for the cover-picker apply path's sync/cache invariants.

Bug (shipped through v4.0.140): applying a new cover via the focused
cover-picker (`POST /book/<id>/cover/apply`) committed `has_cover=1` and
busted the picker's OWN preview with a one-off `?ts=` URL, but it never
bumped `book.last_modified`. Two user-visible consequences, same root cause:

  * Web — every cover URL in the app cache-busts on `book.last_modified`
    (jinjia.py `last_modified` filter feeds the `c=` param on detail, grid
    srcset, edit page, and og:image). A stale `last_modified` means the
    browser keeps serving the cached cover until a manual refresh.
  * Kobo — native sync selects changed books with
    `Books.last_modified > sync_token.books_last_modified` (kobo.py). A stale
    `last_modified` means the device never re-pulls the (correctly
    content-hashed) cover.

The edit-book path (editbooks.py:976-979) already does the right thing on a
cover change: bump last_modified, remove_synced_book(all=True), and
set_metadata_dirty. These tests pin the cover-picker path to the same
contract. We exercise `_apply_response` directly — the single funnel that
all three apply kinds (file/url/embedded) return through.
"""

import datetime
import inspect
import json
from unittest.mock import MagicMock, patch

import flask
import pytest


def _fake_book():
    book = MagicMock()
    book.id = 527
    book.has_cover = 0
    book.path = "Joseph Sheridan Le Fanu/Carmilla (527)"
    # Deliberately old so a successful apply must move it forward.
    book.last_modified = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    return book


def _patched_apply(book, ok, message):
    """Call cover_picker._apply_response with all external side-effect
    collaborators patched, inside a request context (jsonify needs one).
    Returns (response, set_dirty_mock, remove_synced_mock)."""
    from cps import cover_picker

    app = flask.Flask(__name__)
    with app.test_request_context():
        with patch.object(cover_picker.calibre_db, "session", MagicMock()), \
             patch.object(cover_picker.calibre_db, "set_metadata_dirty") as set_dirty, \
             patch("cps.kobo_sync_status.remove_synced_book") as remove_synced, \
             patch.object(cover_picker.helper, "replace_cover_thumbnail_cache"), \
             patch(
                 "cps.cover_picker.url_for",
                 side_effect=lambda ep, **kw: f"/cover/{kw.get('book_id')}/{kw.get('resolution')}",
             ):
            resp = cover_picker._apply_response(ok, message, book)
    return resp, set_dirty, remove_synced


@pytest.mark.unit
class TestCoverApplyMarksModified:

    def test_successful_apply_bumps_last_modified_and_forces_kobo_resync(self):
        book = _fake_book()
        before = book.last_modified
        resp, set_dirty, remove_synced = _patched_apply(book, True, None)

        # last_modified moved forward → all c=last_modified cover URLs
        # (detail / grid srcset / edit / og:image) bust their browser cache,
        # AND Kobo's `Books.last_modified > token` selector re-sends the book.
        assert book.last_modified > before

        # Force the device to re-pull on next sync (matches edit-book path).
        remove_synced.assert_called_once_with(book.id, all=True)

        # Queue metadata write-back (matches edit-book path).
        set_dirty.assert_called_once_with(book.id)

        data = json.loads(resp.get_data(as_text=True))
        assert data["ok"] is True
        # Picker's own live preview swap still needs a unique URL each apply.
        assert "ts=" in data["cover_url"]

    def test_failed_save_leaves_sync_state_untouched(self):
        book = _fake_book()
        before = book.last_modified
        resp, set_dirty, remove_synced = _patched_apply(book, False, "save blew up")

        assert book.last_modified == before
        remove_synced.assert_not_called()
        set_dirty.assert_not_called()
        assert resp.status_code == 400

    def test_commit_failure_reports_error_and_skips_post_commit(self):
        """If recording the cover change fails, the apply must NOT report
        success (the cover bytes are on disk but last_modified never
        persisted) and must not run the post-commit Kobo/thumbnail steps."""
        from cps import cover_picker

        book = _fake_book()
        app = flask.Flask(__name__)
        failing_session = MagicMock()
        failing_session.commit.side_effect = RuntimeError("db is locked")
        with app.test_request_context():
            with patch.object(cover_picker.calibre_db, "session", failing_session), \
                 patch.object(cover_picker.calibre_db, "set_metadata_dirty"), \
                 patch("cps.kobo_sync_status.remove_synced_book") as remove_synced, \
                 patch.object(cover_picker.helper, "replace_cover_thumbnail_cache") as thumb, \
                 patch("cps.cover_picker._", side_effect=lambda s: s), \
                 patch(
                     "cps.cover_picker.url_for",
                     side_effect=lambda ep, **kw: f"/cover/{kw.get('book_id')}/{kw.get('resolution')}",
                 ):
                resp = cover_picker._apply_response(True, None, book)

        assert resp.status_code == 500
        body = json.loads(resp.get_data(as_text=True))
        assert body.get("ok") is False
        failing_session.rollback.assert_called_once()
        remove_synced.assert_not_called()
        thumb.assert_not_called()

    def test_source_pins_sync_invariant(self):
        """Refactor guard: a future cleanup of the apply path must not
        silently drop the cache/sync invalidation that fixes the
        v4.0.14x cover-staleness bug."""
        from cps import cover_picker

        src = inspect.getsource(cover_picker._apply_response)
        assert "last_modified" in src, "apply path must bump last_modified"
        assert "remove_synced_book" in src, "apply path must force Kobo re-sync"
        assert "set_metadata_dirty" in src, "apply path must queue metadata write-back"
