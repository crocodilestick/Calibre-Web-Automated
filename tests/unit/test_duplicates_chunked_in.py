# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for the duplicate-scan SQLite bound-parameter limit.

A duplicate prefilter on a large library returned >100k candidate IDs, which
``Books.id.in_(ids)`` expanded into one statement with that many host
parameters. SQLite caps parameters at SQLITE_MAX_VARIABLE_NUMBER, so the scan
died with ``sqlite3.OperationalError: too many SQL variables``. The
after-import cache refresh hit the same error, so the incremental baseline
never persisted and the in-process worker churned full scans, starving the
web server. ``_fetch_books_in_chunks`` must batch the IN filter.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

# Reuse the stub loader from the sibling test without depending on the test
# package being importable (pytest's import mode makes that fragile).
_loader_path = pathlib.Path(__file__).with_name("test_duplicates_timezone.py")
_spec = importlib.util.spec_from_file_location("_dup_tz_loader", _loader_path)
_dup_tz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dup_tz)
_load_duplicates_module = _dup_tz._load_duplicates_module


class _FakeResult:
    def __init__(self, books):
        self._books = books

    def all(self):
        return self._books


class _FakeQuery:
    """Stand-in for a SQLAlchemy query.

    ``_fetch_books_in_chunks`` calls ``base_query.filter(<in_ clause>).all()``
    once per batch. Our ``db.Books.id.in_`` stub yields ``("IN", (ids...))``,
    so each ``filter`` call records the exact id chunk it received.
    """

    def __init__(self, by_id):
        self._by_id = by_id
        self.chunks = []

    def filter(self, clause):
        _, ids = clause
        self.chunks.append(tuple(ids))
        return _FakeResult([self._by_id[i] for i in ids])


@pytest.fixture
def duplicates(monkeypatch):
    module = _load_duplicates_module()
    fake_db = SimpleNamespace(
        Books=SimpleNamespace(
            id=SimpleNamespace(in_=lambda ids: ("IN", tuple(ids)))
        )
    )
    monkeypatch.setattr(module, "db", fake_db)
    return module


def test_chunk_size_is_safe_for_oldest_sqlite(duplicates):
    # Must stay under the 999 floor (pre-3.32 SQLITE_MAX_VARIABLE_NUMBER),
    # not just the modern 32766 ceiling.
    assert 0 < duplicates._SQLITE_IN_CHUNK <= 999


def test_empty_ids_make_no_query(duplicates):
    q = _FakeQuery({})
    assert duplicates._fetch_books_in_chunks(q, []) == []
    assert q.chunks == []


def test_large_id_set_is_batched_and_fully_covered(duplicates):
    # 170_231 == the production candidate count that triggered the crash.
    n = 170_231
    by_id = {i: f"book-{i}" for i in range(n)}
    ids = list(range(n))
    q = _FakeQuery(by_id)

    books = duplicates._fetch_books_in_chunks(q, ids)

    chunk = duplicates._SQLITE_IN_CHUNK
    # No batch may exceed the parameter cap.
    assert all(len(c) <= chunk for c in q.chunks)
    assert max(len(c) for c in q.chunks) == chunk
    # Every id queried exactly once, batched contiguously, order preserved.
    assert len(q.chunks) == (n + chunk - 1) // chunk
    assert [i for c in q.chunks for i in c] == ids
    assert books == [f"book-{i}" for i in ids]


def test_exact_multiple_of_chunk_size(duplicates):
    chunk = duplicates._SQLITE_IN_CHUNK
    ids = list(range(chunk * 2))
    q = _FakeQuery({i: i for i in ids})

    books = duplicates._fetch_books_in_chunks(q, ids)

    assert [len(c) for c in q.chunks] == [chunk, chunk]
    assert books == ids


def test_accepts_set_input_without_loss(duplicates):
    # candidate_ids reaches the helper as a set; every id must still be fetched.
    ids = set(range(duplicates._SQLITE_IN_CHUNK + 50))
    q = _FakeQuery({i: i for i in ids})

    books = duplicates._fetch_books_in_chunks(q, ids)

    assert sorted(books) == sorted(ids)
    assert sum(len(c) for c in q.chunks) == len(ids)
