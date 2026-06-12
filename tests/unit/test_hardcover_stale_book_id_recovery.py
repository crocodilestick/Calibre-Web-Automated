# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the fork #433 follow-up: after v4.0.161 fixed the
nullable-field crash, the reporter's log showed

    WARN Hardcover insert_user_book error: We weren't able to find that
         book. Was it deleted?
    WARN Book not on Hardcover and could not be added, skipping progress sync

Hardcover merges duplicate books and retires the old book id, so a
``hardcover-id`` stored in Calibre metadata can go stale. ``add_book`` now
re-resolves the current book id (edition first — editions are re-parented
to the canonical book on merge — then slug) and retries the insert once.
When nothing can be resolved it logs an actionable hint instead of only
the opaque API error.
"""

from __future__ import annotations

from unittest.mock import patch

from cps.services.hardcover import HardcoverClient, STATUS_READING

NOT_FOUND = "We weren't able to find that book. Was it deleted?"


def make_client(responders):
    """HardcoverClient with no network. ``responders`` is a list of
    (query-substring, responses) pairs where ``responses`` is a list popped
    from the front on each matching call — so the same mutation can answer
    differently on the retry. Records every call."""
    client = HardcoverClient.__new__(HardcoverClient)
    client.privacy = 1
    client.endpoint = "http://hardcover.invalid/v1/graphql"
    client.headers = {}
    calls = []

    def fake_execute(query, variables=None):
        calls.append({"query": query, "variables": variables or {}})
        for substring, responses in responders:
            if substring in query:
                assert responses, f"no responses left for {substring!r}"
                return responses.pop(0)
        raise AssertionError(f"unexpected GraphQL query: {query.strip()[:120]}")

    client.execute = fake_execute
    return client, calls


def _user_book():
    return {
        "id": 11, "status_id": STATUS_READING, "book_id": 990,
        "book": {"slug": "some-book", "title": "T"},
        "edition": {"id": 42, "pages": 300},
        "user_book_reads": [],
    }


def test_stale_id_recovers_via_edition():
    """The stored hardcover-id is dead but the edition still exists:
    add_book must re-resolve through editions->book_id and retry."""
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
            {"insert_user_book": {"error": None, "user_book": _user_book()}},
        ]),
        ("editions(where", [
            {"editions": [{"book_id": 990}]},
        ]),
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-edition": "42"})
    assert book is not None and book["book_id"] == 990
    inserts = [c for c in calls if "insert_user_book" in c["query"]]
    assert len(inserts) == 2
    assert inserts[0]["variables"]["object"]["book_id"] == 123
    assert inserts[1]["variables"]["object"]["book_id"] == 990
    # The (valid) edition id is preserved on the retry
    assert inserts[1]["variables"]["object"]["edition_id"] == 42


def test_stale_id_recovers_via_slug_when_no_edition():
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
            {"insert_user_book": {"error": None, "user_book": _user_book()}},
        ]),
        ("books(where", [
            {"books": [{"id": 990}]},
        ]),
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-slug": "some-book"})
    assert book is not None
    inserts = [c for c in calls if "insert_user_book" in c["query"]]
    assert [i["variables"]["object"]["book_id"] for i in inserts] == [123, 990]


def test_edition_resolution_preferred_over_slug():
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
            {"insert_user_book": {"error": None, "user_book": _user_book()}},
        ]),
        ("editions(where", [
            {"editions": [{"book_id": 990}]},
        ]),
        # NOTE: no books(where responder — a slug query would fail the test
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-edition": "42",
                            "hardcover-slug": "some-book"})
    assert book is not None
    assert not any("books(where" in c["query"] for c in calls)


def test_unresolvable_stale_id_warns_actionably(caplog=None):
    """No edition/slug to resolve through: returns None and tells the user
    how to fix it (refresh metadata), instead of only the opaque API error."""
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
        ]),
    ])
    with patch("cps.services.hardcover.log") as fake_log:
        book = client.add_book({"hardcover-id": "123"})
    assert book is None
    inserts = [c for c in calls if "insert_user_book" in c["query"]]
    assert len(inserts) == 1  # nothing to resolve through -> no blind retry
    warned = " | ".join(str(c.args[0]) for c in fake_log.warning.call_args_list)
    assert "Refresh the book's metadata" in warned


def test_resolution_returning_same_id_does_not_loop():
    """If re-resolution yields the SAME dead id, do not retry (would just
    fail identically) — warn actionably instead."""
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
        ]),
        ("editions(where", [
            {"editions": [{"book_id": 123}]},
        ]),
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-edition": "42"})
    assert book is None
    inserts = [c for c in calls if "insert_user_book" in c["query"]]
    assert len(inserts) == 1


def test_other_errors_do_not_trigger_resolution():
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": "Daily limit reached", "user_book": None}},
        ]),
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-edition": "42"})
    assert book is None
    assert not any("editions(where" in c["query"] for c in calls)
    assert not any("books(where" in c["query"] for c in calls)


def test_resolution_query_failure_degrades_gracefully():
    """A failing resolve query must not raise out of add_book."""
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": NOT_FOUND, "user_book": None}},
        ]),
        ("editions(where", [
            {"editions": None},  # null-normalized path
        ]),
    ])
    book = client.add_book({"hardcover-id": "123", "hardcover-edition": "42"})
    assert book is None


def test_successful_insert_unchanged():
    """Happy path must be byte-identical in behavior: one insert, no
    resolution queries."""
    client, calls = make_client([
        ("insert_user_book", [
            {"insert_user_book": {"error": None, "user_book": _user_book()}},
        ]),
    ])
    book = client.add_book({"hardcover-id": "990", "hardcover-edition": "42"})
    assert book is not None and book["id"] == 11
    assert len(calls) == 1
