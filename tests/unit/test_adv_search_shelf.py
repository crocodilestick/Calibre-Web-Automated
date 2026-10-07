# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the shelf filters of the advanced search.

A book on several shelves must be dropped as soon as one of them is excluded,
even if the other shelf belongs to another user (port of upstream
janeczku/calibre-web@c5e9526, calibre-web#3515).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps import db, ub, search

pytestmark = pytest.mark.unit

SHELF_A, SHELF_B, OTHER_USER_SHELF = 1, 2, 3

# book id -> shelves it is on
LIBRARY = {
    1: [SHELF_A],
    2: [SHELF_B],
    3: [SHELF_A, SHELF_B],
    4: [SHELF_A, OTHER_USER_SHELF],
    5: [],
}


@pytest.fixture
def session(monkeypatch):
    # In production app.db is attached to the calibre connection, so both
    # tables are reachable from one session; a single in-memory db mirrors that.
    engine = create_engine("sqlite://")
    db.Books.__table__.create(engine)
    ub.BookShelf.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    session.execute(db.Books.__table__.insert(),
                    [{"id": book_id, "title": f"Book {book_id}"} for book_id in LIBRARY])
    session.execute(ub.BookShelf.__table__.insert(),
                    [{"book_id": book_id, "shelf": shelf}
                     for book_id, shelves in LIBRARY.items() for shelf in shelves])
    session.commit()
    monkeypatch.setattr(search.calibre_db, "session", session)
    yield session
    session.close()


def found_ids(session, include, exclude):
    q = search.adv_search_shelf(session.query(db.Books.id), include, exclude)
    return sorted(book_id for (book_id,) in q.all())


@pytest.mark.parametrize("include, exclude, expected", [
    ([], [], [1, 2, 3, 4, 5]),
    ([], [SHELF_A], [2, 5]),
    ([], [SHELF_B], [1, 4, 5]),
    ([SHELF_A], [], [1, 3, 4]),
    ([SHELF_A], [SHELF_B], [1, 4]),
    ([SHELF_A, SHELF_B], [], [1, 2, 3, 4]),
])
def test_adv_search_shelf(session, include, exclude, expected):
    assert found_ids(session, include, exclude) == expected
