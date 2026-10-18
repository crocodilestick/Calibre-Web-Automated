# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise #1172 through the real shelf queries, renderer and cover templates.

All records live in an in-memory SQLite database. Only unrelated layout,
activity logging and URL generation are replaced; status queries are real.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template
from flask_babel import Babel
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.unit
CC_ID = 934


@pytest.fixture(scope="module")
def read_column():
    from cps import db

    columns = db.CalibreDB.setup_db_cc_classes([SimpleNamespace(id=CC_ID, datatype="bool")])
    return columns[CC_ID]


@pytest.fixture
def library(monkeypatch, read_column):
    import cwa_db

    from cps import config, db, magic_shelf, ub, web

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def attach_calibre(connection, connection_record):
        connection.execute("ATTACH DATABASE ':memory:' AS calibre")

    db.Base.metadata.create_all(engine)
    ub.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    monkeypatch.setattr(ub, "session", session)
    monkeypatch.setattr(db.CalibreDB, "_init", True)
    monkeypatch.setattr(db.CalibreDB, "session_factory", staticmethod(factory))
    monkeypatch.setattr(db.CalibreDB, "config", config)
    monkeypatch.setattr(db, "cc_classes", {CC_ID: read_column})
    for key, value in {
        "config_read_column": 0,
        "config_restricted_column": 0,
        "config_books_per_page": 20,
        "config_title_regex": r"^(A|The)\s+",
        "config_kobo_sync_magic_shelves": True,
    }.items():
        monkeypatch.setattr(config, key, value, raising=False)

    user = SimpleNamespace(
        id=1,
        name="Synthetic reader",
        is_authenticated=True,
        show_detail_random=lambda: False,
        filter_language=lambda: "all",
        list_denied_tags=lambda: [""],
        list_allowed_tags=lambda: [""],
        role_admin=lambda: False,
        role_download=lambda: False,
        role_edit_shelfs=lambda: False,
    )
    for module in (db, magic_shelf, web):
        monkeypatch.setattr(module, "current_user", user)
    cdb = db.CalibreDB(init=True)
    monkeypatch.setattr(web, "calibre_db", cdb)
    monkeypatch.setattr(cwa_db, "CWA_DB", Mock())
    monkeypatch.setattr(web, "get_sort_function", lambda *args: ([db.Books.id.desc()], "zyx"))

    session.execute(
        insert(db.Books),
        [
            {"id": i, "title": f"Synthetic Book {i}", "sort": f"Book {i}", "author_sort": "", "uuid": f"synthetic-{i}"}
            for i in range(1, 5)
        ],
    )
    regular_shelf = ub.Shelf(id=1, name="Regular shelf", user_id=1)
    session.add_all(
        [
            ub.User(id=1, name="reader-one", email="one@example.invalid"),
            ub.User(id=2, name="reader-two", email="two@example.invalid"),
            ub.ReadBook(user_id=1, book_id=1, read_status=ub.ReadBook.STATUS_FINISHED),
            ub.ReadBook(user_id=1, book_id=2, read_status=ub.ReadBook.STATUS_UNREAD),
            ub.ReadBook(user_id=1, book_id=3, read_status=ub.ReadBook.STATUS_IN_PROGRESS),
            ub.ReadBook(user_id=2, book_id=2, read_status=ub.ReadBook.STATUS_FINISHED),
            read_column(book=1, value=True),
            read_column(book=2, value=False),
            read_column(book=3, value=None),
            ub.MagicShelf(
                id=1,
                name="Synthetic shelf",
                user_id=1,
                is_public=1,
                kobo_sync=True,
                rules={
                    "condition": "AND",
                    "rules": [{"id": "title", "field": "title", "operator": "contains", "value": "Synthetic"}],
                },
            ),
            regular_shelf,
            ub.BookShelf(ub_shelf=regular_shelf, book_id=1, order=0),
            ub.BookShelf(ub_shelf=regular_shelf, book_id=2, order=1),
        ]
    )
    session.commit()

    app = Flask(__name__, template_folder=str(Path(__file__).parents[2] / "cps/templates"))
    app.config["TESTING"] = True
    Babel(app)
    app.jinja_loader = ChoiceLoader(
        [
            DictLoader({"layout.html": "{% block body %}{% endblock %}"}),
            app.jinja_loader,
        ]
    )
    app.jinja_env.globals.update(
        _=lambda message, **kwargs: message % kwargs if kwargs else message,
        url_for=lambda endpoint, **kwargs: f"/{endpoint}",
        csrf_token=lambda: "synthetic-csrf-token",
    )
    app.jinja_env.filters.update(
        shortentitle=lambda value, *args: value,
        formatfloat=lambda value, *args: value,
        music=lambda value: False,
        get_cover_srcset=lambda value: "",
        get_series_srcset=lambda value: "",
        last_modified=lambda value: "0",
        cache_timestamp=lambda value: "0",
    )
    context = {}

    def render(template, **kwargs):
        context.clear()
        context.update(kwargs)
        return render_template(template, current_user=user, **kwargs)

    monkeypatch.setattr(web, "render_title_template", render)
    app.add_url_rule(
        "/magic/<int:shelf_id>/<int:page>",
        "magic",
        lambda shelf_id, page: web.render_magic_shelf.__wrapped__(shelf_id, "zyx", page),
    )
    state = SimpleNamespace(
        app=app,
        client=app.test_client(),
        engine=engine,
        session=session,
        cdb=cdb,
        user=user,
        config=config,
        context=context,
        render=render,
        read_column=read_column,
        db=db,
        ub=ub,
        magic_shelf=magic_shelf,
    )
    yield state
    cdb.session.close()
    session.close()
    engine.dispose()


def cards(html):
    return {
        int(link["data-book-id"]): bool(link.select_one(".badge.read"))
        for link in BeautifulSoup(html, "html.parser").select("a.book-cover-link")
    }


def show(library, refresh=False, page=1):
    response = library.client.get(f"/magic/1/{page}", query_string={"refresh": int(refresh)})
    assert response.status_code == 200
    return cards(response.get_data(as_text=True))


@pytest.mark.parametrize("custom_column", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_magic_shelf_read_badges(library, custom_column, refresh):
    library.config.config_read_column = CC_ID if custom_column else 0
    # Populate the ID cache first, so refresh=False exercises a cache hit.
    library.magic_shelf.get_books_for_magic_shelf(1)
    assert show(library, refresh) == {4: False, 3: False, 2: False, 1: True}


@pytest.mark.parametrize("custom_column", [False, True])
def test_status_changes_are_visible_without_refresh(library, custom_column, monkeypatch):
    from cps import helper

    monkeypatch.setattr(helper, "current_user", library.user)
    monkeypatch.setattr(helper, "calibre_db", library.cdb)
    library.config.config_read_column = CC_ID if custom_column else 0
    assert show(library)[1]
    assert helper.edit_book_read_status(1, False) == ""
    assert not show(library)[1]
    assert helper.edit_book_read_status(2, True) == ""
    assert show(library)[2]


def test_public_shelf_badges_belong_to_viewer(library):
    assert show(library)[1]
    library.user.id = 2
    assert show(library) == {4: False, 3: False, 2: True, 1: False}
    # Same public shelf, but each viewer also has their own ID cache.
    assert show(library) == {4: False, 3: False, 2: True, 1: False}


def test_custom_column_takes_precedence_over_personal_status(library):
    library.config.config_read_column = CC_ID
    library.user.id = 2
    assert show(library) == {4: False, 3: False, 2: False, 1: True}


@pytest.mark.parametrize("shelf_id, status", [(999, 404), (1, 403)])
def test_missing_and_private_shelves_are_rejected(library, shelf_id, status):
    library.session.get(library.ub.MagicShelf, 1).is_public = 0
    library.session.commit()
    library.user.id = 2
    assert library.client.get(f"/magic/{shelf_id}/1").status_code == status


@pytest.mark.parametrize("template", ["index.html", "shelf.html"])
@pytest.mark.parametrize("custom_column", [False, True])
def test_existing_library_and_regular_shelf_badges(library, template, custom_column):
    library.config.config_read_column = CC_ID if custom_column else 0
    db, ub = library.db, library.ub
    joins = (ub.BookShelf, ub.BookShelf.book_id == db.Books.id) if template == "shelf.html" else ()
    entries, _, pagination = library.cdb.fill_indexpage(
        1,
        20,
        db.Books,
        db.Books.id.in_([1, 2]),
        [db.Books.id.asc()],
        True,
        library.config.config_read_column,
        *joins,
    )
    with library.app.test_request_context():
        html = library.render(
            template,
            entries=entries,
            pagination=pagination,
            shelf=library.session.get(ub.Shelf, 1),
            page="new",
            title="Synthetic library",
            order="abc",
            id=1,
        )
    assert cards(html) == {1: True, 2: False}


def test_nested_rules_pagination_and_order_are_preserved(library):
    shelf = library.session.get(library.ub.MagicShelf, 1)
    shelf.rules = {
        "condition": "AND",
        "rules": [
            {"id": "title", "field": "title", "operator": "contains", "value": "Synthetic"},
            {
                "condition": "OR",
                "rules": [
                    {"id": "title", "field": "title", "operator": "equal", "value": "Synthetic Book 1"},
                    {"id": "title", "field": "title", "operator": "equal", "value": "Synthetic Book 3"},
                ],
            },
        ],
    }
    library.session.commit()
    library.config.config_books_per_page = 1
    assert show(library, refresh=True) == {3: False}
    assert library.context["pagination"].total_count == 2
    assert show(library, page=2) == {1: True}
    assert show(library, page=3) == {}


def test_user_permission_filters_still_apply(library):
    tag = library.db.Tags("Restricted")
    book = library.session.get(library.db.Books, 1)
    book.tags.append(tag)
    library.session.commit()
    library.user.list_denied_tags = lambda: ["Restricted"]
    assert show(library, refresh=True) == {4: False, 3: False, 2: False}


@pytest.mark.parametrize("custom_column", [False, True])
def test_read_status_rules_still_select_finished_books(library, custom_column):
    library.config.config_read_column = CC_ID if custom_column else 0
    library.session.get(library.ub.MagicShelf, 1).rules = {
        "condition": "AND",
        "rules": [
            {"id": "title", "operator": "contains", "value": "Synthetic"},
            {"id": "read_status", "operator": "equal", "value": 1},
        ],
    }
    library.session.commit()
    assert show(library, refresh=True) == {1: True}
    assert show(library) == {1: True}


def test_large_shelf_status_is_joined_only_for_current_page(library):
    db, ub = library.db, library.ub
    library.session.execute(
        insert(db.Books),
        [
            {"id": i, "title": f"Synthetic Book {i}", "sort": f"Book {i}", "author_sort": "", "uuid": f"synthetic-{i}"}
            for i in range(5, 1505)
        ],
    )
    library.session.add(ub.ReadBook(user_id=1, book_id=1504, read_status=1))
    library.session.commit()
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(library.engine, "before_cursor_execute", record)
    try:
        result = show(library, refresh=True)
        assert len(result) == 20
        assert list(result) == list(range(1504, 1484, -1))
        assert result[1504]
        assert library.context["pagination"].total_count == 1504
        joined = [(sql, params) for sql, params in statements if "JOIN book_read_link" in sql]
        assert len(joined) == 1
        assert "books.id IN" in joined[0][0]
        assert len(joined[0][1]) == 22  # Two user IDs plus this page's twenty IDs.
    finally:
        event.remove(library.engine, "before_cursor_execute", record)


def test_kobo_and_opds_keep_plain_book_contract(library, monkeypatch):
    from cps import kobo, opds

    monkeypatch.setattr(kobo, "current_user", library.user)
    assert show(library)[1]
    books, total = library.magic_shelf.get_books_for_magic_shelf(1)
    assert total == 4
    assert all(isinstance(book, library.db.Books) for book in books)
    assert {book.id for book in books} == {1, 2, 3, 4}
    assert kobo.get_magic_shelf_book_ids_for_kobo(1) == {1, 2, 3, 4}
    monkeypatch.setattr(opds.auth, "current_user", lambda: library.user)
    monkeypatch.setattr(library.user, "is_anonymous", False, raising=False)
    monkeypatch.setattr(opds, "render_xml_template", lambda template, **kwargs: kwargs)
    with library.app.test_request_context():
        feed = opds.feed_magic_shelf.__wrapped__(1)
    assert {entry.Books.id for entry in feed["entries"]} == {1, 2, 3, 4}


@pytest.mark.parametrize("custom_column", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_status_join_adds_no_queries(library, custom_column, refresh):
    library.config.config_read_column = CC_ID if custom_column else 0
    # Warm the ID cache for both modes before comparing their SQL query counts.
    library.magic_shelf.get_books_for_magic_shelf(1)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(library.engine, "before_cursor_execute", record)
    try:
        library.magic_shelf.get_books_for_magic_shelf(1, bypass_cache=refresh)
        plain_count = len(statements)
        statements.clear()
        entries, _ = library.magic_shelf.get_books_for_magic_shelf(1, bypass_cache=refresh, include_read_status=True)
        assert len(statements) == plain_count
        assert {entry.Books.id: entry[2] == 1 for entry in entries} == {
            1: True,
            2: False,
            3: False,
            4: False,
        }
    finally:
        event.remove(library.engine, "before_cursor_execute", record)


def test_view_does_not_change_read_or_kobo_state(library):
    session, ub = library.session, library.ub
    state = ub.KoboReadingState(user_id=1, book_id=1)
    state.current_bookmark = ub.KoboBookmark(location_value="synthetic-location", progress_percent=100)
    state.statistics = ub.KoboStatistics()
    session.query(ub.ReadBook).filter_by(user_id=1, book_id=1).one().kobo_reading_state = state
    session.commit()

    def snapshot(model):
        return session.query(*model.__table__.columns).order_by(model.id).all()

    before = session.query(
        ub.ReadBook.user_id, ub.ReadBook.book_id, ub.ReadBook.read_status, ub.ReadBook.last_modified
    ).all()
    kobo_models = (ub.KoboReadingState, ub.KoboBookmark, ub.KoboStatistics)
    kobo_before = [snapshot(model) for model in kobo_models]
    show(library, refresh=True)
    show(library)
    assert (
        session.query(
            ub.ReadBook.user_id, ub.ReadBook.book_id, ub.ReadBook.read_status, ub.ReadBook.last_modified
        ).all()
        == before
    )
    assert [snapshot(model) for model in kobo_models] == kobo_before
