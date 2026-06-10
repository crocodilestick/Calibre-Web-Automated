# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #334 (@Glennza1962): add a whole series to a shelf in one action,
plus the series/shelf audit fixes that rode along:

- A1: add_to_shelf's Hardcover sync ran only for XHR requests — plain form
  adds silently skipped it. The block now precedes the response split.
- A3: add_selected_to_shelf reported 'partial_success' with a positive
  added_count after a commit failure whose rollback persisted NOTHING.
- A4: add_selected_to_shelf re-queried max(order) per book (correct only
  through autoflush); single query + in-memory increment now.
- A5: the series page defaulted to newest-first; it now defaults to series
  order (matching the OPDS series feed) when the user has no stored sort.

Route-level end-to-end (real HTTP, real UI) happens in the container per the
verification standard; these tests pin the logic and the wiring.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELF_PY = (REPO_ROOT / "cps" / "shelf.py").read_text()
WEB_PY = (REPO_ROOT / "cps" / "web.py").read_text()
INDEX_HTML = (REPO_ROOT / "cps" / "templates" / "index.html").read_text()


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def ub_session():
    from cps import ub
    engine = create_engine("sqlite:///:memory:", future=True)
    ub.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    original = ub.session
    ub.session = s
    try:
        yield s
    finally:
        ub.session = original
        s.close()


@pytest.fixture
def calibre_session():
    """Mirror production's engine shape: StaticPool single connection with
    the calibre schema ATTACHed (db.py models are schema-qualified)."""
    from sqlalchemy.pool import StaticPool
    from cps import db
    engine = create_engine(
        "sqlite://", future=True, poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("attach database ':memory:' as calibre")
        conn.commit()
    db.Base.metadata.create_all(engine)
    with engine.connect() as conn:
        # Rebuild books with series_index REAL, exactly like calibre's real
        # metadata.db. The ORM declares the column String (inherited from
        # upstream), so create_all gives it TEXT affinity, which would
        # string-order series ('10.0' < '2.0'). Real installs order
        # numerically only because the genuine calibre schema's REAL
        # affinity wins — the fixture must mirror production, not the
        # model's footgun. (Models map the UNQUALIFIED 'books' name; in
        # production main is empty and SQLite falls through to the attached
        # calibre schema — here main.books is the live table.)
        conn.exec_driver_sql("DROP TABLE books")
        conn.exec_driver_sql(
            "CREATE TABLE books ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " title TEXT NOT NULL DEFAULT 'Unknown' COLLATE NOCASE,"
            " sort TEXT COLLATE NOCASE,"
            " author_sort TEXT COLLATE NOCASE,"
            " timestamp TIMESTAMP,"
            " pubdate TIMESTAMP,"
            " series_index REAL NOT NULL DEFAULT 1.0,"
            " last_modified TIMESTAMP,"
            " path TEXT NOT NULL DEFAULT '',"
            " has_cover BOOL DEFAULT 0,"
            " uuid TEXT)"
        )
        conn.commit()
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _mk_series_books(s, series_id=1, name="Chronicles", indexes=(3.0, 1.0, 2.0)):
    """Books inserted OUT of series order on purpose — ordering must come
    from the query, not insertion order."""
    from cps import db
    series = db.Series(name=name, sort=name)
    series.id = series_id
    s.add(series)
    s.flush()
    books = []
    for i, idx in enumerate(indexes, start=1):
        b = db.Books(
            title=f"{name} {idx}", sort=f"{name} {idx}",
            author_sort="A", timestamp=None, pubdate=None,
            series_index=idx, last_modified=None, path=f"p/{i}",
            has_cover=0, authors=[], tags=[],
        )
        b.id = i * 10
        s.add(b)
        s.flush()
        s.execute(db.books_series_link.insert().values(book=b.id, series=series_id))
        books.append(b)
    s.commit()
    return books


# ------------------------------------------------- series-order insertion

class TestSeriesOrderQuery:
    def test_books_come_back_in_series_index_order(self, calibre_session):
        """The route's exact query shape returns series order regardless of
        insertion order — including index 10 after index 2, which separates
        numeric ordering (calibre's REAL column) from the string ordering
        the ORM's String declaration would produce ('10.0' < '2.0')."""
        from cps import db
        _mk_series_books(calibre_session, indexes=(10.0, 1.0, 2.0))
        rows = (calibre_session.query(db.Books)
                .filter(db.Books.series.any(db.Series.id == 1))
                .order_by(db.Books.series_index.asc(), db.Books.id.asc())
                .all())
        assert [float(r.series_index) for r in rows] == [1.0, 2.0, 10.0]

    def test_shelf_append_preserves_series_order_and_continues_max(self, ub_session, calibre_session):
        """Dedup + order continuation: an existing entry keeps its slot, new
        books append after current max(order), in series order."""
        from cps import db, ub
        books = _mk_series_books(calibre_session, indexes=(2.0, 1.0, 3.0))
        shelf = ub.Shelf(name="S", is_public=0, user_id=1)
        shelf.id = 5
        ub_session.add(shelf)
        # Book with series_index 1.0 (id 20) is already on the shelf at order
        # 7 — appended through the relationship, exactly like the route does
        # (ub.py's flush hook walks BookShelf.ub_shelf and crashes on bare-FK
        # inserts; the relationship path is the supported one).
        shelf.books.append(ub.BookShelf(shelf=5, book_id=20, order=7))
        ub_session.commit()

        ordered = (calibre_session.query(db.Books)
                   .filter(db.Books.series.any(db.Series.id == 1))
                   .order_by(db.Books.series_index.asc(), db.Books.id.asc()).all())
        existing = {row.book_id for row in
                    ub_session.query(ub.BookShelf.book_id).filter(ub.BookShelf.shelf == 5).all()}
        to_add = [b for b in ordered if b.id not in existing]
        assert [b.series_index for b in to_add] == [2.0, 3.0], "dedup must skip the shelved book"

        max_order = ub_session.query(func.max(ub.BookShelf.order)).filter(
            ub.BookShelf.shelf == 5).scalar() or 0
        assert max_order == 7
        for b in to_add:
            max_order += 1
            shelf.books.append(ub.BookShelf(shelf=5, book_id=b.id, order=max_order))
        ub_session.commit()

        rows = (ub_session.query(ub.BookShelf).filter(ub.BookShelf.shelf == 5)
                .order_by(ub.BookShelf.order).all())
        assert [(r.book_id, r.order) for r in rows] == [(20, 7), (10, 8), (30, 9)], (
            "series additions must extend the shelf after existing entries, in series order"
        )


# ------------------------------------------------------------ source pins

class TestRouteWiring:
    def test_route_exists_post_only_and_login_gated(self):
        m = re.search(
            r'@shelf\.route\("/shelf/add_series/<int:shelf_id>/<int:series_id>",\s*methods=\["POST"\]\)\s*'
            r'@user_login_required\s*\ndef add_series_to_shelf\(',
            SHELF_PY,
        )
        assert m, "POST-only, login-gated /shelf/add_series/<shelf>/<series> route must exist"

    def test_route_applies_common_filters_and_series_order(self):
        body = SHELF_PY.split("def add_series_to_shelf", 1)[1].split("\n@shelf.route", 1)[0]
        assert "common_filters()" in body, (
            "bulk series add must apply common_filters so restricted users "
            "can't shelf books they can't see"
        )
        assert "series_index.asc()" in body, "books must be appended in series order"
        assert "check_shelf_edit_permissions" in body

    def test_template_dropdown_only_on_real_series_pages(self):
        assert "add_series_to_shelf" in INDEX_HTML
        guard = re.search(r"{%\s*if page == 'series' and id\|string != '-1' and g\.shelves_access", INDEX_HTML)
        assert guard, (
            "dropdown must be gated to real series pages (not the 'None' "
            "series view) and to users with shelf access"
        )

    def test_dropdown_respects_public_shelf_role(self):
        block = INDEX_HTML.split("add_series_to_shelf", 1)[1][:800]
        assert "role_edit_shelfs()" in block, (
            "public shelves must only be offered to users with the edit-public-shelves role"
        )


# ---------------------------------------------------- A5: series page sort

class TestSeriesDefaultSort:
    def _call(self, monkeypatch, stored, data="series", sort_param="stored"):
        from cps import web
        stub = SimpleNamespace(
            get_view_property=lambda d, k: stored,
            set_view_property=lambda d, k, v: None,
        )
        monkeypatch.setattr(web, "current_user", stub)
        return web.get_sort_function(sort_param, data)

    def test_series_page_defaults_to_series_order(self, monkeypatch):
        from cps import db
        order, name = self._call(monkeypatch, stored=None)
        assert name == "seriesasc"
        assert str(order[0]) == str(db.Books.series_index.asc())

    def test_explicit_stored_sort_still_honored(self, monkeypatch):
        order, name = self._call(monkeypatch, stored="new")
        assert name == "new"

    def test_other_pages_keep_newest_first(self, monkeypatch):
        order, name = self._call(monkeypatch, stored=None, data="author")
        assert name == "new"


# ------------------------------------------- A3: honest bulk-add failures

class TestBulkAddFailureHonesty:
    def test_commit_failure_reports_error_not_partial_success(self):
        """Source pin on the corrected block: after rollback the response is
        a plain 500 with added_count 0 — never 'partial_success'."""
        body = SHELF_PY.split("def add_selected_to_shelf", 1)[1].split("\n@shelf.route", 1)[0]
        failure_zone = body.split("except (OperationalError, InvalidRequestError)", 1)[1]
        commit_failure = failure_zone.split("if errors:", 1)[0]
        assert "'added_count': 0" in commit_failure, (
            "a failed commit rolled back EVERYTHING — added_count must be 0"
        )
        assert "partial_success" not in commit_failure, (
            "commit failure must not be reported as partial success"
        )

    def test_max_order_hoisted_out_of_loop(self):
        body = SHELF_PY.split("def add_selected_to_shelf", 1)[1].split("\n@shelf.route", 1)[0]
        loop = body.split("for book_id in book_ids:", 1)[1]
        assert "func.max" not in loop, (
            "max(order) must be computed once before the loop, not per book"
        )


# ------------------------------------- Greptile P1: .orig on the wrong class

class TestDbErrorMessageNeverCrashes:
    def test_no_bare_orig_access_in_shelf_error_paths(self):
        """InvalidRequestError is a plain SQLAlchemyError — it has no .orig.
        Every error message in shelf.py must use getattr(e, 'orig', e), or a
        session-state error turns the friendly flash into its own 500."""
        assert not re.search(r"\be(?:x)?\.orig\b", SHELF_PY), (
            "bare .orig access found — InvalidRequestError has no .orig; "
            "use getattr(e, 'orig', e)"
        )


# -------------------------------------------- A1: hardcover transport parity

class TestHardcoverTransportParity:
    def test_hardcover_block_precedes_response_split(self):
        """In add_to_shelf, the Hardcover sync must run before the xhr/non-xhr
        response branches — both transports get the same outcome."""
        body = SHELF_PY.split("def add_to_shelf", 1)[1].split("\n@shelf.route", 1)[0]
        # Since fork #381 the sync is a queued task; the enqueue call is the
        # transport-parity point and must still precede the response split.
        hardcover_pos = body.find("queue_hardcover_sync(shelf, [book_id])")
        response_split_pos = body.find('flash(_("Book has been added to shelf')
        assert hardcover_pos != -1 and response_split_pos != -1
        assert hardcover_pos < response_split_pos, (
            "Hardcover sync sat behind the non-XHR early return, so plain "
            "form adds silently skipped it — it must precede the response split"
        )
