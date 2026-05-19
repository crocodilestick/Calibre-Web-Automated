# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #108 — Books.author_sort drift in
`cps.db.CalibreDB.order_authors` was logging at ERROR level on every page
render, with no dedup. Three Hungarian author names spammed Docker logs
every 30 seconds because the OPDS / index page fired the lookup repeatedly.

Pre-fix: log.error(...) on every miss, no dedup, `break` on first miss
(meaning OTHER authors on the same book that DID have valid sort fell
through to id-order too).

Post-fix:
- Module-level `_AUTHOR_SORT_DRIFT_WARNED` set rate-limits one warn per
  process per drifted sort string.
- Level demoted to WARNING (the situation is data drift, not an error;
  the function gracefully recovers via the id-based fallback loop).
- `continue` instead of `break` so other authors on the same book that
  DO have valid sort entries still get correctly ordered.

These tests pin all three guarantees. They use a stub session so we
exercise the actual `order_authors` method, not just AST shape.
"""

import ast
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest


DB_PY = (Path(__file__).resolve().parent.parent.parent / "cps" / "db.py")


@pytest.mark.unit
class TestAuthorSortDriftDedupSourcePins:
    """Static pins on cps/db.py — these catch refactors that drop the
    dedup or revert level/break semantics without a behavioral test
    needing to import cps."""

    def test_db_py_present(self):
        assert DB_PY.is_file(), f"missing: {DB_PY}"

    def test_module_level_drift_warned_set_exists(self):
        src = DB_PY.read_text()
        assert "_AUTHOR_SORT_DRIFT_WARNED" in src, (
            "Expected module-level set _AUTHOR_SORT_DRIFT_WARNED for "
            "rate-limiting author-sort drift warnings (fork #108). If "
            "this rename is intentional, update this test too."
        )
        # Must be a set (not dict / list) — the dedup contract is set.add(auth)
        # / 'auth in set'. Walk the AST to find the assignment and check.
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == "_AUTHOR_SORT_DRIFT_WARNED":
                # `_AUTHOR_SORT_DRIFT_WARNED: set = set()`
                found = True
                assert isinstance(node.value, ast.Call), \
                    "expected set() initializer"
                assert isinstance(node.value.func, ast.Name) and \
                    node.value.func.id == "set", \
                    "expected initializer to be set()"
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "_AUTHOR_SORT_DRIFT_WARNED":
                        found = True
        assert found, "_AUTHOR_SORT_DRIFT_WARNED initializer not found at module level"

    def test_order_authors_uses_continue_not_break_after_drift(self):
        """Original code used `break` — meaning one drifted author short-
        circuited the rest of the book's authors into id-order. Fork #108
        replaced this with `continue`."""
        src = DB_PY.read_text()
        tree = ast.parse(src)
        # Find the order_authors method body
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "order_authors":
                src_segment = ast.get_source_segment(src, node) or ""
                # The handler for the empty-results case should be a
                # `continue` keyword, not `break`. Look at every Continue
                # and Break inside this function and assert the dedup
                # block ends with continue.
                continues = [n for n in ast.walk(node) if isinstance(n, ast.Continue)]
                breaks = [n for n in ast.walk(node) if isinstance(n, ast.Break)]
                assert continues, (
                    "order_authors should `continue` after warning about "
                    "drift, so other authors on the same book still get "
                    "ordered correctly. Found no Continue node."
                )
                # The fix should NOT have a `break` left over from the
                # pre-fix code — break would short-circuit the rest of the
                # author loop.
                assert not breaks, (
                    f"order_authors still contains a `break` statement: "
                    f"{[ast.dump(b) for b in breaks]}. The fix for fork "
                    f"#108 replaced break with continue so a single drifted "
                    f"author doesn't short-circuit the rest of the book."
                )
                return
        pytest.fail("order_authors method not found in cps/db.py")

    def test_warning_level_not_error_level(self):
        """ERROR was wrong — it implies actionable failure, but the
        function recovers gracefully. WARNING is the right level for
        recoverable drift diagnostics."""
        src = DB_PY.read_text()
        # The original error string has been intentionally rephrased to
        # be more useful. Check the new wording uses log.warning (not
        # log.error) for the drift-detected path.
        assert "log.warning(" in src, "expected log.warning(...) for drift"
        # And the old log.error spam string should be gone.
        assert "Author '{}' not found to display name in right order" not in src, (
            "old ERROR-level log line still present; fork #108 demotes it to "
            "log.warning with rate-limited dedup"
        )


@pytest.mark.unit
class TestAuthorSortDriftDedupBehavioral:
    """Functional pin — instantiate a stub CalibreDB-like object with a
    fake session and verify the dedup behavior across multiple
    invocations. Importing cps.db is heavy (pulls SQLAlchemy app +
    blueprints); use spec_from_file_location to load just the module
    machinery we need."""

    def test_drift_warned_set_grows_and_dedupes(self):
        """The behavioral pin that matters: across many invocations with the
        same drifted sort string, the set grows by exactly one entry per
        unique drift name. (Log-volume assertions via caplog are flaky
        because cps installs its own handler chain; the dedup-set state is
        the actual contract this fix makes.)"""
        from cps import db as cps_db

        cps_db._AUTHOR_SORT_DRIFT_WARNED.clear()

        instance = cps_db.CalibreDB.__new__(cps_db.CalibreDB)
        fake_query = MagicMock()
        fake_query.filter.return_value.all.return_value = []  # no Authors hit
        fake_query.filter.return_value.first.return_value = None
        instance.session = MagicMock()
        instance.session.query.return_value = fake_query
        instance.ensure_session = lambda: None

        class _StubBook:
            def __init__(self, sort_str, ids):
                self.author_sort = sort_str
                self.authors = [MagicMock(id=i) for i in ids]

        # Reproduce the exact #108 set: 3 distinct drifted authors,
        # invoked many times to simulate the per-30s page render storm.
        for _ in range(10):
            instance.order_authors([
                _StubBook("Esterházy Péter", []),
                _StubBook("Molnár, Ferenc", []),
                _StubBook("Örkény István", []),
            ], list_return=True, combined=False)

        # Set should contain exactly the three drifted names — no growth
        # past distinct-input cardinality regardless of invocation count.
        assert cps_db._AUTHOR_SORT_DRIFT_WARNED == {
            "Esterházy Péter", "Molnár, Ferenc", "Örkény István"
        }, (
            f"expected dedup set to contain exactly the three Hungarian "
            f"drift names from fork #108; got {cps_db._AUTHOR_SORT_DRIFT_WARNED}"
        )

        # And a fresh drift name on the 11th call should grow the set by 1.
        instance.order_authors([
            _StubBook("Kosztolányi Dezső", []),
        ], list_return=True, combined=False)
        assert "Kosztolányi Dezső" in cps_db._AUTHOR_SORT_DRIFT_WARNED
        assert len(cps_db._AUTHOR_SORT_DRIFT_WARNED) == 4

    def test_continue_preserves_other_authors_ordering_for_same_book(self):
        """A book with TWO linked authors — one whose sort is referenced
        by Books.author_sort, one whose sort is NOT — should still get the
        matched one ordered first. Pre-fix #108 `break` would dump BOTH
        into id-order; post-#108 only the unmatched one falls through.

        Re-shaped for fork #234: the post-#234 implementation consults
        the already-loaded `book.authors` collection instead of issuing
        SQL queries during render, so this test exercises the
        in-memory lookup path directly (no session.query mocks needed)."""
        from types import SimpleNamespace
        from cps import db as cps_db

        cps_db._AUTHOR_SORT_DRIFT_WARNED.clear()

        instance = cps_db.CalibreDB.__new__(cps_db.CalibreDB)
        instance.session = MagicMock()
        instance.ensure_session = lambda: None

        # Book.author_sort contains a stale entry ("UnknownDrift") that no
        # linked author has, plus a valid one ("Valid") that the second
        # linked author does have.
        drift_id = 13
        valid_id = 42
        unmatched = SimpleNamespace(id=drift_id, name="Unmatched", sort="UnmatchedSort")
        valid_author = SimpleNamespace(id=valid_id, name="Valid", sort="Valid")

        book = SimpleNamespace(
            author_sort="UnknownDrift & Valid",
            authors=[unmatched, valid_author],
        )

        instance.order_authors([book], list_return=True, combined=False)

        ordered_ids = [a.id for a in book.ordered_authors]
        # The valid author MUST appear in ordered_authors; pre-fix break
        # would have bailed before reaching it.
        assert valid_id in ordered_ids, (
            f"valid author (id={valid_id}) missing from ordered_authors "
            f"{ordered_ids}; the post-#108 `continue` should let the loop "
            f"reach 'Valid' after skipping 'UnknownDrift'"
        )
        # And valid_author should appear BEFORE the id-fallback unmatched
        # author — the sort-order pass placed it; the id pass appends the
        # unmatched author after.
        assert ordered_ids.index(valid_id) < ordered_ids.index(drift_id), (
            f"valid author should be ordered first (it had a matching "
            f"sort); got {ordered_ids}. Pre-fix `break` regressed this "
            f"to drift-id order for the whole book."
        )
        # Drift dedup fired for the stale sort entry.
        assert "UnknownDrift" in cps_db._AUTHOR_SORT_DRIFT_WARNED
