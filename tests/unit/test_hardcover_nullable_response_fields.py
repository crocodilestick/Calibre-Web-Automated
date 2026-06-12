# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #433 — Hardcover sync crashes with
"'NoneType' object has no attribute 'get'" when the GraphQL API returns
null for nullable fields.

Hardcover's GraphQL responses contain keys whose value is null (not absent):
a user_book with no edition selected serializes as ``"edition": null``, and
failed mutations return ``"user_book": null`` alongside an ``error`` string.
``dict.get(key, default)`` only falls back on *absent* keys, so every chained
``response.get(k, {}).get(...)`` in cps/services/hardcover.py raised
AttributeError on these shapes and the per-book sync died.
"""

from __future__ import annotations

from cps.services.hardcover import HardcoverClient


def make_client(responses):
    """Build a HardcoverClient with no network: execute() is replayed from
    (query-substring, response) pairs, recording every call."""
    client = HardcoverClient.__new__(HardcoverClient)
    client.privacy = 1
    client.endpoint = "http://hardcover.invalid/v1/graphql"
    client.headers = {}
    calls = []

    def fake_execute(query, variables=None):
        calls.append({"query": query, "variables": variables or {}})
        for substring, resp in responses:
            if substring in query:
                return resp
        raise AssertionError(f"unexpected GraphQL query: {query.strip()[:120]}")

    client.execute = fake_execute
    return client, calls


def _user_book(**overrides):
    book = {
        "id": 11,
        "status_id": 2,  # STATUS_READING
        "book_id": 173,
        "book": {"slug": "some-book", "title": "Title: After the Title"},
        "edition": {"id": 42, "pages": 300},
        "user_book_reads": [{"id": 5, "started_at": "2026-06-01",
                             "finished_at": None, "edition_id": 42,
                             "progress_pages": 10}],
    }
    book.update(overrides)
    return book


def test_edition_null_does_not_crash_progress_sync():
    """The reporter's shape: user_book exists but has edition: null.
    Must skip the page-count update gracefully instead of raising."""
    client, calls = make_client([
        ("user_books(where", {"me": [{"user_books": [_user_book(edition=None)]}]}),
    ])
    # On main this raised AttributeError: 'NoneType' object has no attribute 'get'
    client.update_reading_progress({"hardcover-id": "999"}, 25.04)
    assert all("update_user_book_read" not in c["query"] for c in calls)


def test_change_status_mutation_returning_null_keeps_old_book():
    """update_user_book: null (mutation rejected) must not crash; progress
    update still proceeds with the originally fetched user_book."""
    client, calls = make_client([
        ("user_books(where", {"me": [{"user_books": [_user_book(status_id=1)]}]}),
        ("update_user_book(", {"update_user_book": None}),
        ("update_user_book_read", {"update_user_book_read": {"id": 5}}),
    ])
    client.update_reading_progress({"hardcover-id": "999"}, 25.04)
    progress_calls = [c for c in calls if "update_user_book_read" in c["query"]]
    assert len(progress_calls) == 1
    assert progress_calls[0]["variables"]["pages"] == round(300 * 0.2504)


def test_add_book_returning_none_is_handled():
    """Book absent from library and only a slug identifier present: add_book
    returns None (needs hardcover-id) — caller must bail out, not crash."""
    client, calls = make_client([
        ("user_books(where", {"me": [{"user_books": []}]}),
    ])
    client.update_reading_progress({"hardcover-slug": "some-book"}, 25.04)
    assert all("update_user_book_read" not in c["query"] for c in calls)


def test_insert_user_book_null_user_book_is_handled():
    """insert_user_book returns user_book: null with an error string (e.g.
    duplicate row) — caller must bail out, not crash."""
    client, calls = make_client([
        ("user_books(where", {"me": [{"user_books": []}]}),
        ("insert_user_book(", {"insert_user_book": {"error": "duplicate",
                                                    "user_book": None}}),
    ])
    client.update_reading_progress({"hardcover-id": "999"}, 25.04)
    assert all("update_user_book_read" not in c["query"] for c in calls)


def test_me_null_or_empty_returns_no_user_book():
    """me: null / me: [] from get_user_book must read as 'not found', then
    flow into the add_book path instead of raising TypeError."""
    for me_value in (None, []):
        client, calls = make_client([
            ("user_books(where", {"me": me_value}),
            ("insert_user_book(", {"insert_user_book": {"error": None,
                                                        "user_book": None}}),
        ])
        client.update_reading_progress({"hardcover-id": "999"}, 25.04)
        assert any("insert_user_book(" in c["query"] for c in calls)


def test_started_at_null_defaults_to_today():
    """A read row with started_at: null must not send startedAt: null."""
    client, calls = make_client([
        ("user_books(where", {"me": [{"user_books": [
            _user_book(user_book_reads=[{"id": 5, "started_at": None,
                                         "finished_at": None, "edition_id": 42,
                                         "progress_pages": 10}]),
        ]}]}),
        ("update_user_book_read", {"update_user_book_read": {"id": 5}}),
    ])
    client.update_reading_progress({"hardcover-id": "999"}, 25.04)
    progress_calls = [c for c in calls if "update_user_book_read" in c["query"]]
    assert len(progress_calls) == 1
    assert progress_calls[0]["variables"]["startedAt"] is not None
