# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #234.

Symptom: rendering the book grid during concurrent ingest crashed with
``AttributeError: 'NoneType' object has no attribute 'id'`` in
``cps.db.CalibreDB.order_authors``. The stack trace pointed at
``if r.id in ids:`` while the function was re-querying ``Authors`` by
``Books.author_sort`` and assuming every result row + every linked
``book.authors`` entry was a valid Authors object.

Pre-#234 behavior:
    - ``Books.author_sort.split('&')`` raised AttributeError when
      ``author_sort`` was NULL.
    - ``[a.id for a in entry.authors]`` raised AttributeError when
      the joined collection contained a None entry (concurrent
      ingest / delete tearing down the LEFT JOIN row).
    - The fallback ``.first()`` could append None to ordered_authors
      which propagated into the template render.

Post-#234 behavior:
    - ``order_authors`` uses the already-loaded ``book.authors``
      collection rather than re-querying ``Authors``. No new SQL
      during render = no session-state race window.
    - None entries in ``book.authors`` are filtered out.
    - None ``author_sort`` is treated as empty.
    - Stale sort entries log once and fall through to id-fallback.
    - The fallback never appends None.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cps import db as cps_db


def _author(id_, name, sort):
    return SimpleNamespace(id=id_, name=name, sort=sort)


def _instance():
    """Construct a CalibreDB without invoking __init__ (which wants a Flask
    app). The new ``order_authors`` doesn't touch ``self.session`` at all,
    but keep a stub there so the test would still surface a regression if
    that property comes back."""
    inst = cps_db.CalibreDB.__new__(cps_db.CalibreDB)
    inst.session = MagicMock()
    inst.ensure_session = lambda: None
    return inst


@pytest.mark.unit
class TestOrderAuthorsNoneGuard:

    def setup_method(self):
        cps_db._AUTHOR_SORT_DRIFT_WARNED.clear()

    def test_book_authors_collection_with_none_entry_does_not_crash(self):
        """The exact #234 repro: book.authors has a None entry from a
        torn-down join. Pre-fix this crashed at the
        ``[a.id for a in entry.authors]`` list comprehension or in the
        downstream ``for r in results: if r.id in ids:`` loop. Post-fix
        the None is silently dropped."""
        valid = _author(1, "Jane Alpha", "Alpha, Jane")
        book = SimpleNamespace(
            id=10,
            author_sort="Alpha, Jane",
            authors=[None, valid],
        )

        result = _instance().order_authors([book], list_return=True)

        assert result == [book]
        assert book.ordered_authors == [valid]

    def test_author_sort_is_none_does_not_crash(self):
        """Calibre allows NULL author_sort. Pre-fix this crashed at
        ``entry.author_sort.split('&')``."""
        linked = _author(1, "Jane Alpha", "Alpha, Jane")
        book = SimpleNamespace(
            id=11,
            author_sort=None,
            authors=[linked],
        )

        _instance().order_authors([book], list_return=True)

        # author_sort missing → fall back to linked authors so the book
        # still renders with its author list.
        assert book.ordered_authors == [linked]

    def test_stale_author_sort_falls_back_to_linked_authors(self):
        """``Books.author_sort`` references "Missing, Author" which no
        linked Author has. The unmatched sort entry should be skipped
        (drift warning) and the remaining sort + id-fallback paths
        should still place every linked Author into the order list."""
        linked_a = _author(1, "Jane Alpha", "Alpha, Jane")
        linked_b = _author(2, "Bob Beta", "Beta, Bob")
        book = SimpleNamespace(
            id=12,
            author_sort="Missing, Author & Alpha, Jane & Beta, Bob",
            authors=[linked_a, linked_b],
        )

        _instance().order_authors([book], list_return=True)

        # Both valid authors land in ordered_authors. Order: the sort
        # pass placed Alpha first, then Beta; the id-fallback would
        # then add anything missing, but everything's accounted for.
        assert book.ordered_authors == [linked_a, linked_b]
        # Drift dedup fired once for the missing sort string.
        assert "Missing, Author" in cps_db._AUTHOR_SORT_DRIFT_WARNED

    def test_all_sorts_stale_falls_back_to_linked_authors(self):
        """Defensive: if every entry in author_sort is stale, we don't
        return an empty ordered_authors — the book still renders with
        its linked authors so the user sees something."""
        linked = _author(1, "Jane Alpha", "Alpha, Jane")
        book = SimpleNamespace(
            id=13,
            author_sort="Stale, One & Stale, Two",
            authors=[linked],
        )

        _instance().order_authors([book], list_return=True)

        assert book.ordered_authors == [linked]

    def test_combined_entry_shape_works(self):
        """``combined=True`` path used by some callers — entry has a
        ``.Books`` attribute holding the actual Book row."""
        valid = _author(1, "Jane Alpha", "Alpha, Jane")
        book = SimpleNamespace(
            id=14,
            author_sort="Alpha, Jane",
            authors=[None, valid],
        )
        entry = SimpleNamespace(Books=book)

        result = _instance().order_authors([entry], list_return=True, combined=True)

        assert result == [entry]
        # In combined mode, the writes go onto book.authors (not
        # entry.ordered_authors). None has been filtered out.
        assert book.authors == [valid]

    def test_empty_book_authors_does_not_crash(self):
        """``book.authors`` is an empty list (book with no linked
        authors). Pre-fix this still worked but the id-fallback issued
        a useless SQL query. Post-fix it short-circuits gracefully."""
        book = SimpleNamespace(
            id=15,
            author_sort="Some, Sort",
            authors=[],
        )

        _instance().order_authors([book], list_return=True)

        assert book.ordered_authors == []

    def test_no_db_query_during_render(self):
        """Post-fix ``order_authors`` does not consult ``self.session``
        at all. Pin this so a future refactor can't silently bring
        back the render-time queries that caused the race."""
        valid_a = _author(1, "Alpha", "Alpha")
        valid_b = _author(2, "Beta", "Beta")
        book = SimpleNamespace(
            id=16,
            author_sort="Alpha & Beta",
            authors=[valid_a, valid_b],
        )

        inst = _instance()
        # session.query is a MagicMock; if order_authors calls it, we'd
        # see it in mock_calls. Assert empty.
        inst.order_authors([book], list_return=True)

        assert inst.session.query.call_count == 0, (
            f"order_authors should not consult self.session.query during "
            f"render — pre-#234 it did, which opened a race window during "
            f"concurrent ingest. mock_calls: {inst.session.mock_calls}"
        )

    def test_id_none_in_linked_author_is_tolerated(self):
        """Defensive: linked author with id=None (transient/uncommitted
        row?). Don't crash, don't include it in the id-keyed dict."""
        valid = _author(1, "Jane", "Jane")
        weird = _author(None, "Weird", "Weird")
        book = SimpleNamespace(
            id=17,
            author_sort="Jane",
            authors=[valid, weird],
        )

        _instance().order_authors([book], list_return=True)

        # Jane is ordered first by sort match. Weird has id=None, so
        # it's not in the id-fallback dict and doesn't appear.
        assert book.ordered_authors == [valid]
