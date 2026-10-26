# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace

from cps import db, metadata_helper


class FakeSettings(dict):
    def get(self, key, default=None):
        return key == "auto_metadata_update_rating"


class FakeCwaDb:
    def get_cwa_settings(self):
        return FakeSettings()


class FakeQuery:
    def __init__(self, ratings):
        self.ratings = ratings
        self.value = None

    def filter(self, criterion):
        self.value = criterion.right.value
        return self

    def first(self):
        return next((r for r in self.ratings if r.rating == self.value), None)


class FakeSession:
    def __init__(self, ratings):
        self.ratings = ratings
        self.added = []

    def query(self, model):
        return FakeQuery(self.ratings)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass

    def rollback(self):
        pass


def apply_rating(monkeypatch, book, existing_ratings, rating):
    monkeypatch.setattr(metadata_helper, "CWA_DB", FakeCwaDb)
    session = FakeSession(existing_ratings)
    metadata = SimpleNamespace(title="", authors=[], description="", publisher="", rating=rating)
    updated = metadata_helper._apply_metadata_to_book(book, metadata, SimpleNamespace(session=session))
    return updated, session


def test_existing_rating_row_is_reused(monkeypatch):
    shared = db.Ratings(rating=8)
    book = SimpleNamespace(id=1, title="Book", ratings=[])

    updated, session = apply_rating(monkeypatch, book, [shared], 4)

    assert updated
    assert book.ratings == [shared]
    assert session.added == []


def test_shared_rating_row_is_not_modified(monkeypatch):
    shared_six = db.Ratings(rating=6)
    shared_eight = db.Ratings(rating=8)
    book = SimpleNamespace(id=1, title="Book", ratings=[shared_six])

    updated, session = apply_rating(monkeypatch, book, [shared_six, shared_eight], 4)

    assert updated
    assert shared_six.rating == 6
    assert book.ratings == [shared_eight]


def test_missing_rating_row_is_created(monkeypatch):
    book = SimpleNamespace(id=1, title="Book", ratings=[])

    updated, session = apply_rating(monkeypatch, book, [], 3)

    assert updated
    assert len(session.added) == 1
    assert session.added[0].rating == 6
    assert book.ratings == session.added
