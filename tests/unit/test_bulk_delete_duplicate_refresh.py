# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bulk delete and merge (used by the Duplicate Manager) must refresh the duplicate
index once for the whole batch. Rebuilding the duplicate groups after every single
book blocked the web server for the whole operation (#1095).
"""

import inspect
import json
from types import SimpleNamespace

import pytest
from flask import Flask

import cps.editbooks as editbooks

pytestmark = pytest.mark.unit


@pytest.fixture
def calls(monkeypatch):
    recorded = SimpleNamespace(deletes=[], refreshes=[], remaining=set())

    def fake_delete(book_id, book_format, json_response, location="", refresh_duplicates=True):
        recorded.deletes.append((int(book_id), refresh_duplicates))

    monkeypatch.setattr(editbooks, "delete_book_from_table", fake_delete)
    monkeypatch.setattr(editbooks, "_refresh_duplicates_after_deletion",
                        lambda ids: recorded.refreshes.append(list(ids)))
    monkeypatch.setattr(editbooks, "_queue_duplicate_scan_after_change", lambda ids=None: None)
    # Books in `remaining` still exist after the delete (e.g. a failed deletion)
    monkeypatch.setattr(editbooks.calibre_db, "get_book",
                        lambda book_id: object() if int(book_id) in recorded.remaining else None)
    return recorded


def _call_route(view, payload):
    app = Flask(__name__)
    with app.test_request_context(method="POST", data=json.dumps(payload), content_type="application/json"):
        return inspect.unwrap(view)()


def test_bulk_delete_refreshes_duplicates_once(calls):
    _call_route(editbooks.delete_selected_books, {"selections": [3, 4, 5, 6]})

    assert calls.deletes == [(3, False), (4, False), (5, False), (6, False)]
    assert calls.refreshes == [[3, 4, 5, 6]]


def test_bulk_delete_only_drops_books_that_were_deleted(calls):
    calls.remaining = {4}

    _call_route(editbooks.delete_selected_books, {"selections": ["3", "4"]})

    assert calls.refreshes == [[3]]


def test_single_delete_still_refreshes_by_default():
    signature = inspect.signature(editbooks.delete_book_from_table)
    assert signature.parameters["refresh_duplicates"].default is True
