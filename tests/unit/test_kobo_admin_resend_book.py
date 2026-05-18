# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for A2 — per-book "Resend to Kobo" admin action.

Goal:
    Admin clicks "Resend" on user_edit.html, the (user_id, book_id)
    row in kobo_synced_books is cleared, and Books.last_modified is
    bumped to NOW. On the user's next Kobo sync, the device receives
    the book again (as NewEntitlement since the synced-row is gone)
    and re-downloads the file.

Why both:
    The row deletion alone isn't enough — if the cursor has advanced
    past Books.last_modified, the sync filter
    ``Books.last_modified > sync_token.books_last_modified`` excludes
    the book and the device never sees it again. The fix must do
    both: clear the per-user sync record AND bump last_modified.

These tests pin the implementation at the source-text level (route
shape, function shape) so a future refactor that drops one of the
two writes silently re-introduces a partial-fix bug.
"""

import inspect

import pytest


@pytest.mark.unit
class TestRouteRegistered:
    def test_kobo_resend_endpoint_is_admin_only(self):
        from cps import admin as admin_mod
        src = inspect.getsource(admin_mod)
        # The route must require admin (admin_required decorator).
        # Pinning the exact route + decorator stack catches refactors
        # that accidentally drop the admin gate, which would let any
        # logged-in user resend books to any other user's Kobo.
        assert "/ajax/kobo_resend/" in src, (
            "admin module must register /ajax/kobo_resend/<userid>/<bookid> "
            "route for the per-book resend action."
        )
        # Find the route registration and verify decorator stack
        idx = src.index("/ajax/kobo_resend/")
        # Look at the ~400 chars around the route for the decorator stack.
        window = src[idx:idx + 400]
        assert "@admin_required" in window, (
            "/ajax/kobo_resend/<userid>/<bookid> must be @admin_required. "
            "Without this gate any logged-in user could clear another "
            "user's Kobo sync state."
        )
        assert "methods=[\"POST\"]" in window, (
            "/ajax/kobo_resend/<userid>/<bookid> must be POST-only."
        )

    def test_endpoint_passes_userid_and_bookid(self):
        from cps.admin import ajax_kobo_resend
        # The handler signature must take both user and book parameters
        # so the SQL filter narrows to the (user, book) pair.
        sig = inspect.signature(ajax_kobo_resend)
        params = list(sig.parameters)
        assert params == ["userid", "bookid"], (
            "ajax_kobo_resend must accept (userid, bookid) so it can "
            "delete the exact (user_id, book_id) row from "
            "kobo_synced_books."
        )


@pytest.mark.unit
class TestDoKoboResendShape:
    """Source-pinned: the helper must perform two writes — clear the
    sync row AND bump last_modified. Either one alone is a partial fix
    that doesn't restore device-side delivery."""

    def test_clears_kobo_synced_books_row_for_pair(self):
        from cps.admin import do_kobo_resend
        src = inspect.getsource(do_kobo_resend)
        assert "ub.KoboSyncedBooks" in src, (
            "do_kobo_resend must touch the KoboSyncedBooks table — "
            "without the deletion the next sync emits "
            "ChangedEntitlement rather than re-delivering the file."
        )
        assert ".delete()" in src, (
            "do_kobo_resend must call .delete() on the filtered query "
            "so the (user_id, book_id) row goes away."
        )
        # Both filters must be present so we delete only the targeted
        # pair (not all rows for the user or all rows for the book).
        assert "user_id" in src and "book_id" in src, (
            "do_kobo_resend must filter the delete by both user_id "
            "AND book_id; deleting all rows for a user is "
            "do_full_kobo_sync's job, and deleting all rows for a "
            "book is remove_synced_book(all=True)."
        )

    def test_bumps_last_modified_with_aware_datetime(self):
        from cps.admin import do_kobo_resend
        src = inspect.getsource(do_kobo_resend)
        assert "last_modified" in src, (
            "do_kobo_resend must bump Books.last_modified so the sync "
            "filter `Books.last_modified > books_last_modified` picks "
            "up the book even when the cursor has advanced past the "
            "book's original mtime."
        )
        # Use timezone-aware UTC datetime to match the cps/editbooks
        # canonical writer pattern (datetime.now(timezone.utc)).
        assert "datetime.now(timezone.utc)" in src, (
            "do_kobo_resend must bump last_modified using "
            "datetime.now(timezone.utc) for parity with editbooks.py "
            "writers — naive timestamps drift across DST boundaries "
            "and can land in the past relative to the sync cursor."
        )

    def test_validates_book_exists_before_writing(self):
        from cps.admin import do_kobo_resend
        src = inspect.getsource(do_kobo_resend)
        # The book existence check must happen so an admin entering an
        # invalid book ID gets feedback rather than a silent no-op.
        assert "calibre_db.session.query(db.Books)" in src, (
            "do_kobo_resend must verify the book exists in the calibre "
            "library before bumping last_modified — otherwise an "
            "invalid book ID silently no-ops."
        )

    def test_commits_both_sessions(self):
        from cps.admin import do_kobo_resend
        src = inspect.getsource(do_kobo_resend)
        # Both writes go to different SQLAlchemy sessions — calibre_db
        # for Books.last_modified, ub for KoboSyncedBooks — so both
        # need explicit commits.
        assert "calibre_db.session.commit()" in src, (
            "do_kobo_resend must commit calibre_db.session — without "
            "the commit the Books.last_modified bump is lost on the "
            "next session expire/rollback."
        )
        assert "ub.session_commit" in src, (
            "do_kobo_resend must commit ub.session — without the "
            "commit the KoboSyncedBooks deletion is rolled back."
        )


@pytest.mark.unit
class TestSecurityShape:
    """Defensive: the route accepts integer IDs, requires admin auth,
    and doesn't expose either user or book IDs to non-admins."""

    def test_route_uses_int_converters(self):
        from cps import admin as admin_mod
        src = inspect.getsource(admin_mod)
        # The route signature must use <int:...> not <...> so Flask
        # rejects non-integer paths before reaching our handler. This
        # makes SQL injection on the path effectively impossible.
        idx = src.index("/ajax/kobo_resend/")
        window = src[idx:idx + 100]
        assert "/<int:userid>/<int:bookid>" in window, (
            "/ajax/kobo_resend route must use <int:userid>/<int:bookid> "
            "Flask converters to reject non-numeric paths at the "
            "routing layer."
        )

    def test_route_is_user_login_required_and_admin_required(self):
        from cps import admin as admin_mod
        src = inspect.getsource(admin_mod)
        idx = src.index("/ajax/kobo_resend/")
        window = src[idx:idx + 400]
        assert "@user_login_required" in window, (
            "/ajax/kobo_resend route must require login."
        )
        assert "@admin_required" in window, (
            "/ajax/kobo_resend route must require admin."
        )
