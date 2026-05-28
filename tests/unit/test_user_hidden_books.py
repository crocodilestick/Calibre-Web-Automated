# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #64 — per-user hide-books feature.

Pre-fix: no way to declutter a personal view of the library; archive was
the only opt-out and it has different semantics (sync-pause). Users with
large Project-Gutenberg-style hoards wanted a "hide" toggle that drops a
book out of their index, search, OPDS feeds, and shelves without deleting
or affecting other users.

Post-fix: `UserHiddenBook` table (per-user × book_id, unique pair) +
`common_filters()` extension that excludes hidden book ids for
`current_user`. `/hidden` listing bypasses the exclusion via
`allow_show_hidden=True`.
"""

import inspect
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps.ub import Base, User, UserHiddenBook


@pytest.fixture
def in_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def user_alice(in_memory_session):
    u = User()
    u.name = "alice"
    u.email = "alice@example.com"
    u.password = ""
    in_memory_session.add(u)
    in_memory_session.commit()
    in_memory_session.refresh(u)
    return u


@pytest.mark.unit
class TestUserHiddenBookModel:
    """Pin the schema invariants — same shape as ArchivedBook plus a
    unique constraint on (user_id, book_id) so we can't double-hide."""

    def test_can_insert_a_hidden_book(self, in_memory_session, user_alice):
        row = UserHiddenBook(user_id=user_alice.id, book_id=42)
        in_memory_session.add(row)
        in_memory_session.commit()
        in_memory_session.refresh(row)
        assert row.id is not None
        assert row.hidden_at is not None, "hidden_at default must populate"

    def test_unique_constraint_prevents_double_hide(self, in_memory_session, user_alice):
        in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=42))
        in_memory_session.commit()
        in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=42))
        with pytest.raises(Exception):
            in_memory_session.commit()
        in_memory_session.rollback()

    def test_same_book_can_be_hidden_by_multiple_users(self, in_memory_session, user_alice):
        u2 = User()
        u2.name = "bob"
        u2.email = "bob@example.com"
        u2.password = ""
        in_memory_session.add(u2)
        in_memory_session.commit()
        in_memory_session.refresh(u2)

        in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=42))
        in_memory_session.add(UserHiddenBook(user_id=u2.id, book_id=42))
        in_memory_session.commit()  # must NOT raise; constraint is per-user

        rows = in_memory_session.query(UserHiddenBook).filter(
            UserHiddenBook.book_id == 42).all()
        assert len(rows) == 2

    def test_different_books_for_same_user(self, in_memory_session, user_alice):
        for bid in [1, 2, 3, 100, 9999]:
            in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=bid))
        in_memory_session.commit()

        rows = in_memory_session.query(UserHiddenBook).filter(
            UserHiddenBook.user_id == user_alice.id).all()
        assert len(rows) == 5


@pytest.mark.unit
class TestCommonFiltersHiddenBranch:
    """common_filters() must accept and apply allow_show_hidden. The
    filter expression is what excludes hidden books from index, search,
    OPDS, and shelf listings. Source-pin the contract; full SQLAlchemy
    semantics are exercised in integration tests."""

    def test_signature_accepts_allow_show_hidden(self):
        from cps.db import CalibreDB
        sig = inspect.signature(CalibreDB.common_filters)
        assert "allow_show_hidden" in sig.parameters, (
            "common_filters must expose allow_show_hidden so the /hidden "
            "listing can bypass the exclusion (otherwise users couldn't "
            "see what they hid in order to unhide it)"
        )
        assert sig.parameters["allow_show_hidden"].default is False, (
            "default must be False so existing callers keep excluding hidden books"
        )

    def test_source_queries_user_hidden_book_table(self):
        """Pin that the implementation actually reads UserHiddenBook —
        not just adds a no-op `true()` placeholder."""
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent.parent
        src = (repo_root / "cps" / "db.py").read_text()
        assert "ub.UserHiddenBook" in src, (
            "common_filters must query ub.UserHiddenBook to compute the "
            "exclusion list — see fork issue #64"
        )
        assert "allow_show_hidden" in src, (
            "common_filters must reference allow_show_hidden — pinned by signature test"
        )

    def test_filter_returned_includes_hidden_filter_when_user_has_hidden_books(
            self, in_memory_session, user_alice):
        """End-to-end: with a hidden book and current_user=alice, the
        filter expression returned by common_filters must produce a SQL
        clause that excludes that book id."""
        from cps import db as cps_db
        in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=42))
        in_memory_session.add(UserHiddenBook(user_id=user_alice.id, book_id=99))
        in_memory_session.commit()

        # Build a CalibreDB stub just enough to exercise common_filters'
        # branches that don't depend on the calibre-side metadata.db.
        cdb = MagicMock(spec=cps_db.CalibreDB)
        cdb.config = MagicMock(config_restricted_column=0)

        mock_user = MagicMock()
        mock_user.id = user_alice.id
        mock_user.is_anonymous = False
        mock_user.filter_language.return_value = "all"
        mock_user.list_denied_tags.return_value = ['']
        mock_user.list_allowed_tags.return_value = ['']
        mock_user.allowed_column_value = ''
        mock_user.denied_column_value = ''

        with patch("cps.db.current_user", mock_user), \
                patch("cps.db.ub", MagicMock(
                    session=in_memory_session,
                    UserHiddenBook=UserHiddenBook,
                    ArchivedBook=MagicMock(),
                )):
            # ub.session.query returns SQLAlchemy results for
            # UserHiddenBook (real session) and a stub for ArchivedBook
            # (no rows, returns []).
            real_session = in_memory_session
            mock_session = MagicMock()
            archived_query = MagicMock()
            archived_query.filter.return_value.filter.return_value.all.return_value = []

            def _query(model):
                if model is UserHiddenBook:
                    return real_session.query(model)
                return archived_query
            mock_session.query.side_effect = _query

            with patch("cps.db.ub.session", mock_session):
                # Bypass full CalibreDB init; call as bound method.
                filter_expr = cps_db.CalibreDB.common_filters(cdb)

        # The filter expression is a SQLAlchemy AND clause. The presence
        # of the hidden book ids in the .compile()d SQL is what we pin.
        compiled = str(filter_expr.compile(compile_kwargs={"literal_binds": True}))
        # Both hidden book ids appear in the NOT IN clause:
        assert "42" in compiled
        assert "99" in compiled
        assert "NOT IN" in compiled.upper()


@pytest.mark.unit
class TestHideRouteShape:
    """Source-level pins on the Flask routes — they must exist and use
    the right HTTP verbs / paths so OPDS clients and the detail-page JS
    handler can rely on them."""

    def test_toggle_hidden_route_is_post_only(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent.parent / "cps" / "web.py").read_text()
        assert '/ajax/togglehidden/<int:book_id>' in src, (
            "POST /ajax/togglehidden/<book_id> must exist for the detail-page Hide button"
        )
        # Pin that it's POST-only (not GET — would be CSRF-relevant if mistakenly added)
        import re
        m = re.search(
            r'@web\.route\("/ajax/togglehidden/<int:book_id>",\s*methods=\[([^\]]+)\]\)',
            src,
        )
        assert m is not None, "togglehidden route declaration not found in expected shape"
        assert "'POST'" in m.group(1) or '"POST"' in m.group(1)

    def test_hidden_listing_route_dispatch_is_present(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent.parent / "cps" / "web.py").read_text()
        assert 'data == "hidden"' in src, (
            "The data-dispatch must include the 'hidden' branch so /hidden URL renders"
        )
        assert "render_hidden_books(" in src, (
            "render_hidden_books helper must be invoked by the dispatch"
        )

    def test_render_hidden_books_uses_allow_show_hidden(self):
        """The /hidden listing must bypass the hidden-book exclusion or
        users can never see what they hid (defeats the whole feature)."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent.parent / "cps" / "web.py").read_text()
        import re
        match = re.search(
            r"def render_hidden_books\(.*?\n(?=\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert match is not None, "render_hidden_books function not found"
        body = match.group(0)
        assert "allow_show_hidden=True" in body, (
            "render_hidden_books must pass allow_show_hidden=True to the helper"
        )


@pytest.mark.unit
class TestHiddenBooksRecoveryFlow:
    """Issue #319 — the per-user hide feature shipped unrecoverable.

    Three independent breakages combined so a user who hid a book by
    accident could never get it back:

      1. The /hidden listing rendered a blank page. render_hidden_books
         passed page="hidden"; layout.html emits <body class="{{ page }}">
         so the body got class "hidden"; Bootstrap ships
         .hidden{display:none!important} — the whole body was hidden.
      2. Even past the blank page, covers link to the detail page, but
         show_book() filtered hidden books out (get_book_read_archived
         never forwarded allow_show_hidden), so the detail route bounced
         with "Selected book is unavailable" — and the Unhide toggle
         lives only on the detail page. Net: no reachable Unhide.
      3. The bare /hidden URL (referenced in #64's own comments) 404'd;
         only /hidden/<sort_param> was routed.
    """

    @staticmethod
    def _web_src():
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent.parent / "cps" / "web.py").read_text()

    def test_render_hidden_books_page_name_avoids_bootstrap_hidden_collision(self):
        """The body class must not be the bare token "hidden" — that is a
        Bootstrap display:none!important utility and blanks the page."""
        import re
        match = re.search(
            r"def render_hidden_books\(.*?\n(?=\n\ndef |\nclass |\Z)",
            self._web_src(), re.DOTALL,
        )
        assert match is not None, "render_hidden_books function not found"
        body = match.group(0)
        m = re.search(r'page_name\s*=\s*["\']([^"\']+)["\']', body)
        assert m is not None, "render_hidden_books must set page_name for the body class"
        assert m.group(1) != "hidden", (
            'page_name "hidden" renders <body class="hidden">, which Bootstrap\'s '
            ".hidden{display:none!important} utility nukes -> blank page (#319). "
            'Use a non-colliding identifier such as "hidden_books".'
        )

    def test_get_book_read_archived_accepts_allow_show_hidden(self):
        from cps.db import CalibreDB
        sig = inspect.signature(CalibreDB.get_book_read_archived)
        assert "allow_show_hidden" in sig.parameters, (
            "get_book_read_archived must accept allow_show_hidden so the detail "
            "route can reach a hidden book in order to unhide it (#319)"
        )
        assert sig.parameters["allow_show_hidden"].default is False, (
            "default must be False so every existing caller keeps excluding hidden books"
        )

    def test_get_book_read_archived_forwards_allow_show_hidden_to_common_filters(self):
        """Behavioral: with allow_show_hidden=True, the flag must reach
        common_filters — otherwise common_filters defaults to excluding
        hidden books and the detail query returns None."""
        from cps import db as cps_db
        cdb = MagicMock()
        with patch("cps.db.current_user", MagicMock(id=1)):
            cps_db.CalibreDB.get_book_read_archived(
                cdb, 42, None, allow_show_archived=True, allow_show_hidden=True)
        assert cdb.common_filters.called, "get_book_read_archived must call common_filters"
        call = cdb.common_filters.call_args
        forwarded = call.kwargs.get("allow_show_hidden")
        if forwarded is None and len(call.args) >= 4:
            forwarded = call.args[3]
        assert forwarded is True, (
            "get_book_read_archived must forward allow_show_hidden into "
            "common_filters so a hidden book's detail page (and its Unhide "
            "toggle) is reachable — issue #319"
        )

    def test_show_book_reaches_hidden_books_via_allow_show_hidden(self):
        """show_book's single get_book_read_archived call must request
        allow_show_hidden=True, or hidden books 404 on /book/<id>."""
        import re
        m = re.search(
            r"get_book_read_archived\([^)]*allow_show_hidden\s*=\s*True[^)]*\)",
            self._web_src(),
        )
        assert m is not None, (
            "show_book must call get_book_read_archived(..., allow_show_hidden=True) "
            "so a hidden book's detail page is reachable for unhiding (#319)"
        )

    def test_bare_hidden_url_is_routed(self):
        """The documented /hidden URL must resolve (it 404'd in #319 because
        only /<data>/<sort_param> was routed)."""
        import re
        src = self._web_src()
        assert re.search(r"""@web\.route\(\s*["']/hidden["']""", src), (
            "Bare /hidden must be routed (redirect to the canonical "
            "/hidden/<sort_param> listing) so the documented recovery URL "
            "no longer 404s — issue #319"
        )


@pytest.mark.unit
class TestHiddenBooksRouteAccess:
    """Issue #319 pushback (@droM4X, 2026-05-26): the v4.0.136 fix made
    the listing + detail page reachable, but the action buttons on the
    detail page still bounced and the covers never loaded.

    Root cause: ``get_filtered_book`` is the helper every route uses to
    look up "a book the current user is allowed to see," and v4.0.136
    only extended ``get_book_read_archived``. ``get_filtered_book``
    still applies the unscoped common_filters, so for the current user's
    own hidden book it returns None, and the consuming route flashes
    "Selected book is unavailable" or 404s the cover.

    The fix extends ``get_filtered_book`` to accept ``allow_show_hidden``
    and threads it through the routes that legitimately need to reach a
    user's own hidden book: cover serving, read, edit metadata,
    download. A hidden book is hidden from listings, not access-revoked
    — the user can still open it through its detail page (so they can
    unhide it) and through every action that detail page offers."""

    @staticmethod
    def _src(rel):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent.parent / rel).read_text()

    def test_get_filtered_book_accepts_allow_show_hidden(self):
        """Contract: get_filtered_book must expose allow_show_hidden so
        cover/read/edit routes can reach hidden books for the current user."""
        from cps.db import CalibreDB
        sig = inspect.signature(CalibreDB.get_filtered_book)
        assert "allow_show_hidden" in sig.parameters, (
            "get_filtered_book must accept allow_show_hidden so /cover/<id>, "
            "/read/<id>/<fmt>, /admin/book/<id> can reach a user's own "
            "hidden book (#319 pushback @droM4X)"
        )
        assert sig.parameters["allow_show_hidden"].default is False, (
            "default must be False so every existing caller keeps excluding "
            "hidden books — opt-in per route"
        )

    def test_get_filtered_book_forwards_allow_show_hidden_to_common_filters(self):
        """Behavioral: with allow_show_hidden=True, the flag must reach
        common_filters — otherwise the underlying SQL still excludes the
        hidden book ids and the lookup returns None."""
        from cps import db as cps_db
        cdb = MagicMock()
        with patch("cps.db.current_user", MagicMock(id=1)):
            cps_db.CalibreDB.get_filtered_book(
                cdb, 42, allow_show_archived=True, allow_show_hidden=True)
        assert cdb.common_filters.called, "get_filtered_book must call common_filters"
        call = cdb.common_filters.call_args
        forwarded = call.kwargs.get("allow_show_hidden")
        if forwarded is None and len(call.args) >= 4:
            forwarded = call.args[3]
        assert forwarded is True, (
            "get_filtered_book must forward allow_show_hidden into "
            "common_filters so a hidden book is reachable via cover/read/"
            "edit routes when the caller opts in — #319 pushback"
        )

    def test_get_book_cover_helper_allows_hidden_books(self):
        """get_book_cover services /cover/<book_id>. Without allow_show_hidden
        the cover for a user's own hidden book 404s — leaving covers blank
        on the /hidden/stored listing and on the hidden book's detail
        page (@droM4X #2/#4)."""
        import re
        src = self._src("cps/helper.py")
        # Pin the get_book_cover function body specifically.
        m = re.search(
            r"def get_book_cover\(.*?\n(?=\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "get_book_cover not found in cps/helper.py"
        body = m.group(0)
        assert "allow_show_hidden=True" in body, (
            "get_book_cover must request allow_show_hidden=True from "
            "get_filtered_book so the /cover/<id> route serves covers for a "
            "user's own hidden book (covers blank otherwise — #319 pushback)"
        )

    def test_read_book_route_allows_hidden_books(self):
        """The /read/<book_id>/<book_format> route uses get_filtered_book.
        Without allow_show_hidden=True the reader bounces with "Selected
        book is unavailable" — @droM4X reported this for the reading
        icon on hidden books' detail pages."""
        import re
        src = self._src("cps/web.py")
        # Locate the read_book function body (decorated with @viewer_required).
        m = re.search(
            r"def read_book\(book_id, book_format\).*?\n(?=\n@web\.route|\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "read_book function not found in cps/web.py"
        body = m.group(0)
        assert re.search(
            r"calibre_db\.get_filtered_book\([^)]*allow_show_hidden\s*=\s*True",
            body,
        ), (
            "read_book must call get_filtered_book(..., allow_show_hidden=True) "
            "so a user can read their own hidden book from its detail page "
            "(@droM4X #319 pushback: reading icon errored 'unavailable')"
        )

    def test_edit_book_render_allows_hidden_books(self):
        """render_edit_book backs the /admin/book/<id> GET route. Without
        allow_show_hidden=True the metadata-edit page errors 'unavailable'
        for a user's own hidden book — @droM4X reported this for the
        metadata icon on hidden books' detail pages."""
        import re
        src = self._src("cps/editbooks.py")
        m = re.search(
            r"def render_edit_book\(.*?\n(?=\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "render_edit_book function not found in cps/editbooks.py"
        body = m.group(0)
        assert re.search(
            r"calibre_db\.get_filtered_book\([^)]*allow_show_hidden\s*=\s*True",
            body,
        ), (
            "render_edit_book must call get_filtered_book(..., "
            "allow_show_hidden=True) so a user can edit metadata on their "
            "own hidden book (@droM4X #319 pushback: metadata icon errored "
            "'unavailable')"
        )

    def test_edit_book_post_allows_hidden_books(self):
        """do_edit_book backs the /admin/book/<id> POST route. Same fix:
        the POST handler must allow_show_hidden so a user's metadata
        save against their own hidden book succeeds instead of bouncing
        with 'unavailable'."""
        import re
        src = self._src("cps/editbooks.py")
        m = re.search(
            r"def do_edit_book\(.*?\n(?=\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "do_edit_book function not found in cps/editbooks.py"
        body = m.group(0)
        # First lookup call only — defensive about future calls in the
        # function body that legitimately may not need allow_show_hidden.
        first_call = re.search(
            r"calibre_db\.get_filtered_book\([^)]*\)",
            body,
        )
        assert first_call is not None, (
            "do_edit_book must call calibre_db.get_filtered_book to load the book"
        )
        assert "allow_show_hidden=True" in first_call.group(0), (
            "do_edit_book's primary book lookup must pass allow_show_hidden=True "
            "so the metadata save succeeds against a user's own hidden book "
            "(@droM4X #319 pushback)"
        )

    def test_serve_book_route_allows_hidden_books(self):
        """The /show/<book_id>/<book_format> download route uses
        get_filtered_book. Without allow_show_hidden=True, attempting to
        download a hidden book returns 'File not in Database'. Users can
        access their own hidden books through the detail page; the
        download flow must mirror that."""
        import re
        src = self._src("cps/web.py")
        m = re.search(
            r"def serve_book\(book_id, book_format, anyname\).*?\n(?=\n@web\.route|\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "serve_book function not found in cps/web.py"
        body = m.group(0)
        assert re.search(
            r"calibre_db\.get_filtered_book\([^)]*allow_show_hidden\s*=\s*True",
            body,
        ), (
            "serve_book must pass allow_show_hidden=True so a user can "
            "download their own hidden book from the detail page (#319)"
        )

    def test_get_download_link_allows_hidden_books(self):
        """get_download_link backs OPDS/Send-to-eReader/eReader download
        flows. The user's own hidden book must remain downloadable
        through the same paths the detail page exposes."""
        import re
        src = self._src("cps/helper.py")
        m = re.search(
            r"def get_download_link\(.*?\n(?=\n\ndef |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m is not None, "get_download_link function not found in cps/helper.py"
        body = m.group(0)
        # First (primary) lookup must allow hidden.
        first_call = re.search(
            r"calibre_db\.get_filtered_book\([^)]*\)",
            body,
        )
        assert first_call is not None, "get_download_link must call get_filtered_book"
        assert "allow_show_hidden=True" in first_call.group(0), (
            "get_download_link's primary book lookup must pass allow_show_hidden=True "
            "so Send-to-eReader and OPDS download paths reach a user's own hidden book"
        )

    def test_profile_page_links_hidden_books_listing(self):
        """Discoverability (@droM4X #319 pushback #1): the /me profile
        page must surface a link to /hidden/stored when the user has
        hidden books. Without this users can never find the recovery
        page; v4.0.136 added the redirect but the URL is undocumented
        outside the issue thread."""
        from pathlib import Path
        tpl = (Path(__file__).resolve().parent.parent.parent
               / "cps" / "templates" / "user_edit.html").read_text()
        # Either a url_for to web.books_list with data='hidden', or a
        # direct /hidden anchor. Both are acceptable shapes; what matters
        # is a discoverable link from the profile page.
        import re
        has_url_for = re.search(
            r"url_for\(\s*['\"]web\.books_list['\"]\s*,[^)]*data\s*=\s*['\"]hidden['\"]",
            tpl,
        )
        has_direct = '"/hidden' in tpl or "'/hidden" in tpl
        assert has_url_for or has_direct, (
            "user_edit.html (/me profile page) must contain a link to the "
            "Hidden Books listing so users can discover the recovery flow "
            "(@droM4X #319 pushback: '/hidden page/link is still not "
            "discoverable anywhere')"
        )

    def test_profile_page_hidden_link_is_gated_on_having_hidden_books(self):
        """The discoverability link should only appear when the user has
        hidden books. Showing it to every user clutters the profile and
        teases a feature they haven't opted into."""
        from pathlib import Path
        tpl = (Path(__file__).resolve().parent.parent.parent
               / "cps" / "templates" / "user_edit.html").read_text()
        # Locate the section that renders the Hidden Books link.
        import re
        # Find any occurrence of /hidden in a url_for or anchor, then
        # check that an {% if ... hidden ... %} guard is nearby (within
        # 6 lines before the anchor).
        link_idx = -1
        for pattern in [
            r"url_for\(\s*['\"]web\.books_list['\"]\s*,[^)]*data\s*=\s*['\"]hidden['\"]",
            r"['\"]/hidden",
        ]:
            m = re.search(pattern, tpl)
            if m:
                link_idx = m.start()
                break
        assert link_idx > -1, "Hidden Books link not found in template (gated assertion)"
        # Get the 600 chars preceding the link — generous window so the
        # {% if hidden_book_count %} can live in a parent block.
        window = tpl[max(0, link_idx - 600):link_idx]
        # Allow either an `if` on a count variable or a `for` over a
        # collection of hidden books, both gate the link to non-empty.
        gated = re.search(
            r"\{%\s*if\s+[^%]*hidden",
            window,
            flags=re.IGNORECASE,
        )
        assert gated is not None, (
            "The Hidden Books profile link must be wrapped in a Jinja "
            "{% if hidden_book_count %} (or equivalent) so it appears only "
            "for users who have hidden at least one book"
        )
