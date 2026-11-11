# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for sorting books by rating and by numeric custom columns.

The sort has to be done by the database over the whole library (not per page),
books without a value are listed last in both directions, books with the same
value keep a stable order, and sort parameters are only accepted if they refer
to an existing custom column of datatype int or float.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.expression import text, true

from cps import db, web

pytestmark = pytest.mark.unit

FLOAT_CC, INT_CC, TEXT_CC, SECOND_FLOAT_CC = 9001, 9002, 9003, 9004

# id: (title, rating 0-10 or None, float column, int column)
BOOKS = {
    1: ("Alpha", 10, 4.19, 300),
    2: ("Bravo", 8, 4.95, 0),
    3: ("Charlie", 8, 4.50, 120),
    4: ("Delta", None, 3.10, None),
    5: ("Echo", 0, None, 50),         # a rating of 0 means "not rated" in Calibre
    6: ("Foxtrot", 2, 3.80, 120),
    7: ("Golf", None, None, None),
    8: ("Hotel", 8, 0.0, 900),        # 0 is a regular value of a custom column
}

RATING_DESC = [1, 2, 3, 8, 6, 4, 5, 7]
RATING_ASC = [6, 2, 3, 8, 1, 4, 5, 7]
FLOAT_DESC = [2, 3, 1, 6, 4, 8, 5, 7]
FLOAT_ASC = [8, 4, 6, 1, 3, 2, 5, 7]
INT_DESC = [8, 1, 3, 6, 5, 2, 4, 7]
INT_ASC = [2, 5, 3, 6, 1, 8, 4, 7]


def _remove_cc_classes():
    """Same cleanup as CalibreDB.dispose(), custom column classes are module globals"""
    for attr in list(db.Books.__dict__.keys()):
        if attr.startswith("custom_column_"):
            setattr(db.Books, attr, None)
    for cc_class in db.cc_classes.values():
        db.Base.metadata.remove(cc_class.__table__)
    db.cc_classes.clear()
    for table in reversed(db.Base.metadata.sorted_tables):
        if table.key.startswith(("custom_column_", "books_custom_column_")):
            db.Base.metadata.remove(table)


@pytest.fixture(scope="module")
def library():
    columns = [SimpleNamespace(id=FLOAT_CC, datatype="float"), SimpleNamespace(id=INT_CC, datatype="int"),
               SimpleNamespace(id=TEXT_CC, datatype="text"), SimpleNamespace(id=SECOND_FLOAT_CC, datatype="float")]
    db.CalibreDB.setup_db_cc_classes(columns)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        # like CalibreDB.setup_db(), db.Data refers to the library as attached database
        connection.execute(text("attach database ':memory:' as calibre;"))
    db.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    for label, name, datatype in ((FLOAT_CC, "Community Score", "float"), (INT_CC, "Pages", "int"),
                                  (TEXT_CC, "Notes", "text"), (SECOND_FLOAT_CC, "Second Score", "float")):
        session.add(db.CustomColumns(id=label, label="cc%d" % label, name=name, datatype=datatype, display="{}",
                                     is_multiple=False, normalized=False, editable=True, mark_for_delete=False))
    ratings = {value: db.Ratings(value) for value in (0, 2, 8, 10)}
    session.add_all(ratings.values())
    for book_id, (title, rating, score, pages) in BOOKS.items():
        book = db.Books(title, title, "", None, None, "1.0", None, title, None, [], [])
        book.id = book_id
        if rating is not None:
            book.ratings.append(ratings[rating])
        session.add(book)
        if score is not None:
            session.add(db.cc_classes[FLOAT_CC](book=book_id, value=score))
        if pages is not None:
            session.add(db.cc_classes[INT_CC](book=book_id, value=pages))
    session.commit()

    calibre_db = db.CalibreDB()
    calibre_db.session = session
    yield calibre_db
    session.close()
    engine.dispose()
    _remove_cc_classes()


@pytest.fixture
def config():
    return SimpleNamespace(config_columns_to_ignore=None, config_read_column=0, config_books_per_page=3)


@pytest.fixture
def calibre_db(library, config, monkeypatch):
    monkeypatch.setattr(db, "current_user", SimpleNamespace(show_detail_random=lambda: False))
    monkeypatch.setattr(library, "config", config, raising=False)
    monkeypatch.setattr(library, "common_filters", lambda *args, **kwargs: true(), raising=False)
    return library


@pytest.fixture
def user(calibre_db, config, monkeypatch):
    """web.py with a user who stores the selected sort order, like ub.User.view_settings"""
    settings = {}
    current_user = SimpleNamespace(
        settings=settings,
        get_view_property=lambda page, prop: settings.get(page, {}).get(prop),
        set_view_property=lambda page, prop, value: settings.setdefault(page, {}).__setitem__(prop, value))
    monkeypatch.setattr(web, "current_user", current_user)
    monkeypatch.setattr(web, "calibre_db", calibre_db)
    monkeypatch.setattr(web, "config", config)
    return current_user


def ids(calibre_db, order, db_filter=None):
    query = calibre_db.session.query(db.Books.id)
    if db_filter is not None:
        query = query.filter(db_filter)
    return [row[0] for row in query.order_by(*order).all()]


def page_ids(calibre_db, page, order, db_filter=true(), pagesize=3, join=()):
    entries, __, pagination = calibre_db.fill_indexpage(page, pagesize, db.Books, db_filter, order, False, 0, *join)
    return [book.id for book in entries], pagination


# ---------------------------------------------------------------- sort order

@pytest.mark.parametrize("field, descending, expected", [
    ("rating", True, RATING_DESC),
    ("rating", False, RATING_ASC),
    (FLOAT_CC, True, FLOAT_DESC),
    (FLOAT_CC, False, FLOAT_ASC),
    (INT_CC, True, INT_DESC),
    (INT_CC, False, INT_ASC),
    (str(FLOAT_CC), True, FLOAT_DESC),
])
def test_numeric_sort_order(calibre_db, config, field, descending, expected):
    order = calibre_db.get_numeric_sort_order(field, descending, config)
    assert ids(calibre_db, order) == expected


@pytest.mark.parametrize("field", ["rating", FLOAT_CC, INT_CC])
@pytest.mark.parametrize("descending", [True, False])
def test_books_without_value_are_listed_last(calibre_db, config, field, descending):
    index = {"rating": 1, FLOAT_CC: 2, INT_CC: 3}[field]
    missing = {book_id for book_id, book in BOOKS.items()
               if book[index] is None or (field == "rating" and book[index] == 0)}
    result = ids(calibre_db, calibre_db.get_numeric_sort_order(field, descending, config))
    assert set(result[-len(missing):]) == missing


def test_column_without_any_value_keeps_title_order(calibre_db, config):
    order = calibre_db.get_numeric_sort_order(SECOND_FLOAT_CC, True, config)
    assert ids(calibre_db, order) == sorted(BOOKS)


@pytest.mark.parametrize("field", [TEXT_CC, 424242, -1, "abc", "9001 OR 1=1", None, ""])
def test_unknown_or_not_numeric_columns_are_rejected(calibre_db, config, field):
    assert calibre_db.get_numeric_sort_order(field, True, config) is None


def test_numeric_columns_are_read_from_library(calibre_db, config):
    assert [col.name for col in calibre_db.get_numeric_cc_columns(config)] == \
        ["Community Score", "Pages", "Second Score"]


def test_ignored_and_read_columns_are_not_sortable(calibre_db, config):
    config.config_columns_to_ignore = "^Community"
    config.config_read_column = INT_CC
    assert [col.id for col in calibre_db.get_numeric_cc_columns(config)] == [SECOND_FLOAT_CC]
    assert calibre_db.get_numeric_sort_order(FLOAT_CC, True, config) is None
    assert calibre_db.get_numeric_sort_order(INT_CC, True, config) is None


def test_library_without_custom_columns(calibre_db, config, monkeypatch):
    monkeypatch.setattr(db, "cc_classes", {})
    assert calibre_db.get_numeric_cc_columns(config) == []
    assert calibre_db.get_numeric_sort_order(FLOAT_CC, True, config) is None
    assert ids(calibre_db, calibre_db.get_numeric_sort_order("rating", True, config)) == RATING_DESC


# ---------------------------------------------------------------- pagination, filter, joins

@pytest.mark.parametrize("field, descending, expected", [
    ("rating", True, RATING_DESC),
    (FLOAT_CC, True, FLOAT_DESC),
    (FLOAT_CC, False, FLOAT_ASC),
    (INT_CC, False, INT_ASC),
])
def test_sort_is_applied_to_whole_library_before_paging(calibre_db, config, field, descending, expected):
    order = calibre_db.get_numeric_sort_order(field, descending, config)
    pages = []
    for page in (1, 2, 3):
        result, pagination = page_ids(calibre_db, page, order)
        assert pagination.total_count == len(BOOKS)
        pages.append(result)
    assert pages == [expected[0:3], expected[3:6], expected[6:8]]


@pytest.mark.parametrize("field", ["rating", FLOAT_CC, INT_CC])
def test_paging_is_stable_with_primary_sort_expression_only(calibre_db, config, field):
    """Lists like author, series or category only take the first expression of the sort order"""
    order = [calibre_db.get_numeric_sort_order(field, True, config)[0]]
    first_run = [page_ids(calibre_db, page, order)[0] for page in (1, 2, 3)]
    second_run = [page_ids(calibre_db, page, order)[0] for page in (1, 2, 3)]
    assert first_run == second_run
    assert sorted(book_id for page in first_run for book_id in page) == sorted(BOOKS)


def test_sort_with_filter(calibre_db, config):
    order = calibre_db.get_numeric_sort_order(FLOAT_CC, True, config)
    db_filter = db.Books.ratings.any(db.Ratings.rating == 8)
    assert page_ids(calibre_db, 1, order, db_filter, pagesize=10)[0] == [2, 3, 8]
    order = calibre_db.get_numeric_sort_order("rating", False, config)
    assert page_ids(calibre_db, 1, order, db.Books.title.ilike("%o%"), pagesize=2)[0] == [6, 2]
    assert page_ids(calibre_db, 2, order, db.Books.title.ilike("%o%"), pagesize=2)[0] == [8, 5]
    assert page_ids(calibre_db, 3, order, db.Books.title.ilike("%o%"), pagesize=2)[0] == [7]


def test_sort_with_series_join_of_book_lists(calibre_db, config):
    join = (db.books_series_link, db.Books.id == db.books_series_link.c.book, db.Series)
    order = calibre_db.get_numeric_sort_order(INT_CC, True, config)
    result = [page_ids(calibre_db, page, order, join=join)[0] for page in (1, 2, 3)]
    assert [book_id for page in result for book_id in page] == INT_DESC


# ---------------------------------------------------------------- book lists (web.get_sort_function)

@pytest.mark.parametrize("sort_param, expected", [
    ("ratingdesc", RATING_DESC),
    ("ratingasc", RATING_ASC),
    ("cc%ddesc" % FLOAT_CC, FLOAT_DESC),
    ("cc%dasc" % FLOAT_CC, FLOAT_ASC),
    ("cc%ddesc" % INT_CC, INT_DESC),
    ("cc%dasc" % INT_CC, INT_ASC),
])
def test_get_sort_function(user, calibre_db, sort_param, expected):
    order, param = web.get_sort_function(sort_param, "newest")
    assert param == sort_param
    assert ids(calibre_db, order) == expected
    # selected order is stored for the user and used for the following pages
    assert user.settings["newest"]["stored"] == sort_param
    order, param = web.get_sort_function("stored", "newest")
    assert param == sort_param
    assert ids(calibre_db, order) == expected


def test_get_sort_function_switch_direction(user, calibre_db):
    assert ids(calibre_db, web.get_sort_function("ratingdesc", "newest")[0]) == RATING_DESC
    assert ids(calibre_db, web.get_sort_function("ratingasc", "newest")[0]) == RATING_ASC
    assert web.get_sort_function("stored", "newest")[1] == "ratingasc"


@pytest.mark.parametrize("sort_param", ["cc%ddesc" % TEXT_CC, "cc424242desc", "cc0asc"])
def test_get_sort_function_unknown_column_falls_back_to_default(user, sort_param):
    order, param = web.get_sort_function(sort_param, "newest")
    assert param == "new"
    assert user.settings["newest"]["stored"] == "new"
    assert str(order[0]) == str(db.Books.timestamp.desc())


@pytest.mark.parametrize("sort_param", [
    "cc%ddesc; DROP TABLE books" % FLOAT_CC,
    "cc%d desc" % FLOAT_CC,
    "cc%ddesc--" % FLOAT_CC,
    "cc1 OR 1=1desc",
    "ratingdesc, (SELECT 1)",
    "rating",
    "ccdesc",
    "cc99999999999999999999desc",
])
def test_get_sort_function_invalid_parameter_is_not_used_for_sql(user, calibre_db, sort_param):
    order, __ = web.get_sort_function(sort_param, "newest")
    assert len(order) == 1
    assert str(order[0]) == str(db.Books.timestamp.desc())
    assert calibre_db.session.query(db.Books).count() == len(BOOKS)


def test_get_sort_function_stored_column_removed(user, config):
    web.get_sort_function("cc%ddesc" % FLOAT_CC, "newest")
    config.config_columns_to_ignore = "^Community"
    order, param = web.get_sort_function("stored", "newest")
    assert param == "new"
    assert str(order[0]) == str(db.Books.timestamp.desc())


@pytest.mark.parametrize("sort_param", ["new", "old", "abc", "zyx", "pubnew", "pubold", "authaz", "authza",
                                        "seriesasc", "seriesdesc"])
def test_get_sort_function_existing_sort_parameters_unchanged(user, sort_param):
    order, param = web.get_sort_function(sort_param, "newest")
    assert param == sort_param
    assert user.settings["newest"]["stored"] == sort_param
    assert "SELECT" not in str(order[0])


# ---------------------------------------------------------------- books list (web.list_books)

def list_books_order(calibre_db, monkeypatch, query_string):
    """Sort order web.list_books hands to the database for a request of the books table"""
    fake_db = MagicMock()
    fake_db.session.query.return_value.filter.return_value.count.return_value = len(BOOKS)
    fake_db.fill_indexpage_with_archived_books.return_value = ([], None, None)
    fake_db.get_numeric_sort_order.side_effect = calibre_db.get_numeric_sort_order
    monkeypatch.setattr(web, "calibre_db", fake_db)
    with Flask(__name__).test_request_context("/ajax/listbooks", query_string=query_string):
        response = web.list_books.__wrapped__()
    assert response.status_code == 200
    args = fake_db.fill_indexpage_with_archived_books.call_args[0]
    assert args[2] == query_string.get("limit", 3)
    return args[4]


@pytest.mark.parametrize("sort, direction, expected", [
    ("ratings", "desc", RATING_DESC),
    ("ratings", "asc", RATING_ASC),
    ("custom_column_%d" % FLOAT_CC, "desc", FLOAT_DESC),
    ("custom_column_%d" % FLOAT_CC, "asc", FLOAT_ASC),
    ("custom_column_%d" % INT_CC, "desc", INT_DESC),
    ("custom_column_%d" % INT_CC, "asc", INT_ASC),
    ("custom_column_%d" % FLOAT_CC, "desc; DROP TABLE books", FLOAT_DESC),
])
def test_list_books_sort(user, calibre_db, monkeypatch, sort, direction, expected):
    order = list_books_order(calibre_db, monkeypatch, {"sort": sort, "order": direction, "limit": 10})
    assert ids(calibre_db, order) == expected


@pytest.mark.parametrize("sort", [
    "custom_column_%d" % TEXT_CC,
    "custom_column_424242",
    "custom_column_%d; DROP TABLE books" % FLOAT_CC,
    "custom_column_",
])
def test_list_books_invalid_column_uses_default_order(user, calibre_db, monkeypatch, sort):
    order = list_books_order(calibre_db, monkeypatch, {"sort": sort, "order": "desc"})
    assert len(order) == 1
    assert str(order[0]) == str(db.Books.timestamp.desc())
