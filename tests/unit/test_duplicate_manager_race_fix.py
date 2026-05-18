# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for upstream CWA #1095 (fork PR #100) — Duplicate
Manager bulk delete/merge must batch cache invalidation to one call after
the loop instead of firing per-book, and the JS success-modal reload must
wait 800ms for background DB cleanup before navigating.

These are structural pin-checks: the function signatures + code shapes
that encode the fix. The full behavioral exercise (run a 60-book bulk
delete and observe no UI freeze) is the e2e Playwright pass on the
deployed instance, not a unit test.
"""

import inspect
import re
from pathlib import Path

import pytest

from cps.editbooks import delete_book_from_table


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.unit
class TestDeleteBookFromTableSignature:
    """Pin the new opt-in `skip_cache_invalidation` parameter."""

    def test_skip_cache_invalidation_param_present(self):
        sig = inspect.signature(delete_book_from_table)
        assert "skip_cache_invalidation" in sig.parameters, (
            "fork PR #100 requires `skip_cache_invalidation` kwarg on "
            "delete_book_from_table to enable batched bulk-deletion"
        )

    def test_skip_cache_invalidation_defaults_to_false(self):
        """Existing single-delete callers must keep their old behavior."""
        sig = inspect.signature(delete_book_from_table)
        param = sig.parameters["skip_cache_invalidation"]
        assert param.default is False, (
            "default must be False so single-delete paths still invalidate "
            "the duplicate cache; only bulk paths opt in to skip"
        )


@pytest.mark.unit
class TestEditbooksBatchedInvalidation:
    """Pin that delete_selected_books and merge_list_book both pass
    skip_cache_invalidation=True and invalidate the cache once after the
    loop, not per-book."""

    def _read_editbooks(self):
        return (REPO_ROOT / "cps" / "editbooks.py").read_text()

    def test_delete_selected_books_passes_skip_in_loop(self):
        src = self._read_editbooks()
        # Locate the delete_selected_books body up to its return.
        match = re.search(
            r"def delete_selected_books\(\).*?return\s+\"\"",
            src, re.DOTALL,
        )
        assert match is not None, "delete_selected_books not found"
        body = match.group(0)
        assert "skip_cache_invalidation=True" in body, (
            "delete_selected_books must pass skip_cache_invalidation=True "
            "inside the per-book loop to batch invalidation"
        )

    def test_delete_selected_books_invalidates_once_after_loop(self):
        """Pin: exactly ONE post-batch scan scheduling per delete_selected_books
        call. After CWA #1353 (PR #232) the mechanism switched from a direct
        `invalidate_duplicate_cache()` call to `_queue_duplicate_scan_after_change()`
        which queues a debounced incremental scan over the affected book IDs.
        The invariant is the same: one call after the loop, not per-book."""
        src = self._read_editbooks()
        match = re.search(
            r"def delete_selected_books\(\).*?return\s+\"\"",
            src, re.DOTALL,
        )
        body = match.group(0)
        n_calls = body.count("_queue_duplicate_scan_after_change(")
        assert n_calls == 1, (
            f"expected exactly 1 _queue_duplicate_scan_after_change() call in "
            f"delete_selected_books (one batched call after the loop); "
            f"found {n_calls}"
        )

    def test_merge_list_book_passes_skip_in_loop(self):
        src = self._read_editbooks()
        match = re.search(
            r"def merge_list_book\(\).*?return\s+\"\"",
            src, re.DOTALL,
        )
        assert match is not None, "merge_list_book not found"
        body = match.group(0)
        assert "skip_cache_invalidation=True" in body, (
            "merge_list_book must pass skip_cache_invalidation=True in its "
            "from_book deletion loop"
        )

    def test_merge_list_book_invalidates_once_after_loop(self):
        """Same invariant as delete_selected_books: exactly one post-batch
        scan scheduling per merge_list_book call (after CWA #1353 / PR #232
        the mechanism is `_queue_duplicate_scan_after_change`)."""
        src = self._read_editbooks()
        match = re.search(
            r"def merge_list_book\(\).*?return\s+\"\"",
            src, re.DOTALL,
        )
        body = match.group(0)
        n_calls = body.count("_queue_duplicate_scan_after_change(")
        assert n_calls == 1, (
            f"expected exactly 1 _queue_duplicate_scan_after_change() call in "
            f"merge_list_book (one batched call after the loop); "
            f"found {n_calls}"
        )

    def test_delete_book_from_table_guards_invalidation_on_param(self):
        """The internal cache-invalidation block must check `skip_cache_invalidation`
        so bulk callers don't trigger it. After CWA #1353 (PR #232) the guard
        was tightened to `if not skip_cache_invalidation and not refreshed_duplicate_cache`,
        avoiding a double-invalidate when the new indexed refresh already ran;
        the original PR #100 invariant (skip-flag honored) is preserved."""
        src = self._read_editbooks()
        match = re.search(
            r"def delete_book_from_table\(.*?\):.*?(?=\n(?:def |@)\w)",
            src, re.DOTALL,
        )
        assert match is not None, "delete_book_from_table not found"
        body = match.group(0)
        assert "skip_cache_invalidation" in body and "not skip_cache_invalidation" in body, (
            "delete_book_from_table must read `skip_cache_invalidation` to gate "
            "its invalidate-cache path; the bulk-delete optimization from "
            "fork PR #100 depends on this guard"
        )


@pytest.mark.unit
class TestDuplicatesJsReloadDelay:
    """The success-modal reload must give the server 800ms to finish
    background cleanup before navigating, otherwise the page reload races
    the in-flight cache invalidation."""

    def _read_duplicates_js(self):
        return (REPO_ROOT / "cps" / "static" / "js" / "duplicates.js").read_text()

    def test_success_modal_reload_uses_setTimeout(self):
        src = self._read_duplicates_js()
        match = re.search(
            r"#success_modal_ok.*?\}\);",
            src, re.DOTALL,
        )
        assert match is not None, "success_modal_ok handler not found"
        body = match.group(0)
        assert "setTimeout" in body, (
            "fork PR #100 requires the success-modal handler to setTimeout "
            "the window.location.reload() so background DB cleanup completes"
        )

    def test_success_modal_reload_delay_is_at_least_500ms(self):
        """Any value <500ms doesn't reliably let the server finish; pin a
        floor so future edits don't quietly drop it back to 0."""
        src = self._read_duplicates_js()
        match = re.search(
            r"#success_modal_ok.*?\}\);",
            src, re.DOTALL,
        )
        body = match.group(0)
        # extract numeric ms value from setTimeout(..., NUMBER)
        delay_match = re.search(r"setTimeout\([^,]+,\s*(\d+)\s*\)", body)
        assert delay_match is not None, (
            "could not extract setTimeout delay in success_modal_ok handler"
        )
        delay_ms = int(delay_match.group(1))
        assert delay_ms >= 500, (
            f"reload delay is {delay_ms}ms; <500ms reliably races the "
            f"server-side cache invalidation. Fork PR #100 ships 800ms."
        )
