# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate-resolution data-safety regression pins.

The duplicate resolve/merge path is destructive (it deletes books). These pins
guard the data-safety invariants found in the 2026-06 audit
(notes/duplicate-detection-fix-plan.md). Behavioural reproduction of the live
flows runs on cwn-local against the real same-title pairs; these source-pins
lock the structural invariants so a refactor can't silently reintroduce a bug.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
DUP_SRC = (REPO_ROOT / "cps" / "duplicates.py").read_text()
DUP_INDEX_SRC = (REPO_ROOT / "cps" / "duplicate_index.py").read_text()


def _func_src(name: str) -> str:
    """Slice a top-level function's source out of duplicates.py by text."""
    lines = DUP_SRC.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(f"def {name}(")), None)
    assert start is not None, f"def {name}( not found in duplicates.py"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(def |class |@)", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


class TestD1SharedSessionNotClosed:
    def test_auto_resolve_does_not_close_shared_session(self):
        # D1: auto_resolve_duplicates runs from request contexts (preview /
        # execute-resolution) AND the background TaskDuplicateScan thread. It must
        # NOT close the shared module-level calibre_db.session in a finally —
        # doing so detaches objects mid-operation for any concurrent context
        # (DetachedInstanceError) and can abort a delete partway through a group.
        src = _func_src("auto_resolve_duplicates")
        assert "calibre_db.session.close()" not in src, (
            "auto_resolve_duplicates must not close the shared scoped "
            "calibre_db.session — its lifecycle is owned by the Flask request "
            "teardown and by TaskDuplicateScan.run() (D1 data-safety)"
        )


class TestD7IncompleteMetadataNotGrouped:
    def test_build_duplicate_key_guards_missing_required_fields(self):
        # D7: build_book_key_parts substitutes "untitled"/"unknown" sentinels for
        # missing fields, so two distinct books that both lack a title (or author)
        # would collapse to the same duplicate_key and auto-resolve could DELETE
        # one. build_duplicate_key must give such incomplete-metadata books a
        # per-book-unique key instead (keyed on book id), so they never group.
        m = re.search(
            r"def build_duplicate_key\(book, settings(?:, parts=None)?\):(.*?)\ndef ",
            DUP_INDEX_SRC,
            re.S,
        )
        assert m, "build_duplicate_key not found in duplicate_index.py"
        body = m.group(1)
        assert "incomplete-no-title" in body and "incomplete-no-author" in body, (
            "build_duplicate_key must give a book missing a required enabled "
            "criterion a unique key (D7) so metadata-less books aren't grouped + "
            "auto-deleted"
        )
        assert "book" in body and "id" in body, (
            "the incomplete-book key must incorporate the book id to be unique"
        )

    def test_author_guard_detects_the_unknown_sentinel(self):
        # The guard must not be `not _primary_author(book)`: _primary_author
        # returns the literal "unknown" sentinel (never falsy), so that condition
        # can never fire. Detect the empty-authors case or the sentinel directly.
        m = re.search(
            r"def build_duplicate_key\(book, settings(?:, parts=None)?\):(.*?)\ndef ",
            DUP_INDEX_SRC,
            re.S,
        )
        body = m.group(1)
        assert "not _primary_author(book)" not in body, (
            "author guard must not key off `not _primary_author(book)` — it "
            "returns 'unknown' (truthy) and so never fires"
        )
        assert 'getattr(book, "authors"' in body or '== "unknown"' in body, (
            "author guard must detect empty authors / the 'unknown' sentinel"
        )

    def test_index_writers_use_the_guarded_key_function(self):
        # CRITICAL: the guard only matters if the index WRITERS use it. Both
        # upsert_book_keys and rebuild_duplicate_index must compute duplicate_key
        # via build_duplicate_key, not the raw _hash_json(_enabled_key_values(...)).
        for writer in ("upsert_book_keys", "rebuild_duplicate_index"):
            m = re.search(rf"def {writer}\([^)]*\):(.*?)\n(?:def |\Z)", DUP_INDEX_SRC, re.S)
            assert m, f"{writer} not found"
            wbody = m.group(1)
            assert "build_duplicate_key(book, settings" in wbody, (
                f"{writer} must compute duplicate_key via build_duplicate_key so "
                f"the D7 incomplete-metadata guard is on the actual write path"
            )
            assert "duplicate_key = _hash_json(_enabled_key_values(parts" not in wbody, (
                f"{writer} must not bypass build_duplicate_key with a raw key compute"
            )


class TestD7BehaviouralDistinctKeys:
    """Behavioural proof (runs in CI; skipped locally where `cps` can't import).

    Directly addresses the security-review request: two distinct books that both
    lack a title (or both lack an author) must get DIFFERENT duplicate_keys so
    they never group + get auto-deleted.
    """

    def test_incomplete_books_get_distinct_unique_keys(self):
        di = pytest.importorskip("cps.duplicate_index")
        from unittest import mock

        class StubBook:
            def __init__(self, id, title=None, authors=None):
                self.id = id
                self.title = title
                self.authors = authors if authors is not None else []

        crit = {
            "title": True, "author": True, "language": False,
            "series": False, "publisher": False, "format": False,
        }
        with mock.patch.object(di, "get_effective_duplicate_criteria", return_value=crit):
            # two distinct title-less books -> distinct keys (not grouped)
            assert di.build_duplicate_key(StubBook(1, title=None), settings=None) \
                != di.build_duplicate_key(StubBook(2, title=None), settings=None)
            # two distinct author-less books -> distinct keys (the guard that the
            # broken version could never reach)
            assert di.build_duplicate_key(StubBook(3, title="X", authors=[]), settings=None) \
                != di.build_duplicate_key(StubBook(4, title="X", authors=[]), settings=None)


class TestD2ResolutionSerialized:
    """D2 (data-safety): concurrent execute-resolution (HTTP request) and the
    background-scan auto-resolve (TaskDuplicateScan worker thread) on the SAME
    stale group must not double-delete the loser.

    The per-book re-fetch in auto_resolve_duplicates (calibre_db.get_book ->
    None for an already-deleted book -> skip) is a correct current-state
    idempotency check, but on its own it is a TOCTOU window: both runs can pass
    the re-fetch before either commits its delete, then delete the same loser
    twice / fight over the keeper. CWA is single-process (gevent WSGIServer or
    tornado; the worker is an in-process thread), so a module-level
    threading.Lock around the dry_run=False loop genuinely serializes the two
    entrants — under gevent it is monkey-patched to a greenlet-aware lock. We do
    NOT key idempotency on group_hash (it is unstable per D5 and an over-eager
    skip would drop a genuinely-new duplicate); serialization + the existing
    re-fetch is the mis-fire-proof fix.

    Behavioural proof is the live cwn-local concurrent repro on the real
    "Crime and Punishment" pair (single survivor, no orphaned audit rows);
    these pins lock the structural invariant so a refactor can't reopen the race.
    """

    def test_module_defines_a_resolution_lock(self):
        assert re.search(r"_AUTO_RESOLVE_LOCK\s*=\s*threading\.(?:R?Lock)\(\)", DUP_SRC), (
            "duplicates.py must define a module-level threading lock to serialize "
            "the destructive auto-resolution body (D2 double-delete)"
        )

    def test_acquire_is_non_blocking_and_guarded_by_not_dry_run(self):
        src = _func_src("auto_resolve_duplicates")
        # Acquire only on the destructive path, and NON-BLOCKING (blocking=False)
        # so a contended acquire on the gevent hub greenlet can't stall the loop.
        assert re.search(
            r"if not dry_run:\s*\n\s*lock_held\s*=\s*_AUTO_RESOLVE_LOCK\.acquire\(blocking=False\)",
            src,
        ), (
            "auto_resolve_duplicates must acquire _AUTO_RESOLVE_LOCK non-blockingly "
            "(blocking=False) only on the not-dry_run path — a blocking acquire on "
            "the gevent hub greenlet would stall every in-flight HTTP request (D2)"
        )

    def test_declines_cleanly_when_lock_already_held(self):
        src = _func_src("auto_resolve_duplicates")
        # If another resolution holds the lock, return early (decline) rather than
        # block or fall through into the delete loop — one resolution at a time,
        # no double-delete, no UI freeze (D2).
        m = re.search(r"if not lock_held:(.*?)\n\s*for group in duplicate_groups:", src, re.S)
        assert m, "the could-not-acquire branch must be handled before the delete loop"
        decline = m.group(1)
        assert "return" in decline and "in_progress" in decline, (
            "a contended resolution must return early with an in_progress marker, "
            "not block or fall through into the destructive loop (D2)"
        )

    def test_lock_acquired_before_the_destructive_loop(self):
        src = _func_src("auto_resolve_duplicates")
        acq = src.find("_AUTO_RESOLVE_LOCK.acquire(")
        loop = src.find("for group in duplicate_groups:")
        assert acq != -1 and loop != -1, "acquire + the resolution loop must both exist"
        assert acq < loop, (
            "the lock must be acquired BEFORE the per-book re-fetch + delete loop "
            "so every re-fetch reflects post-lock DB state and a serialized later "
            "run skips already-deleted losers (D2 TOCTOU)"
        )

    def test_lock_released_exactly_once_in_finally(self):
        src = _func_src("auto_resolve_duplicates")
        assert "finally:" in src, "auto_resolve_duplicates must keep its try/finally"
        finally_zone = src.split("finally:", 1)[1]
        assert "if lock_held:" in finally_zone and "_AUTO_RESOLVE_LOCK.release()" in finally_zone, (
            "the lock must be released in finally guarded by lock_held, so an "
            "exception mid-loop can't strand it and deadlock every future "
            "resolution (D2)"
        )
        assert src.count("_AUTO_RESOLVE_LOCK.release()") == 1, (
            "release must happen exactly once (in finally); a stray second "
            "release on an unlocked lock raises RuntimeError"
        )


class TestD3FilesDeletedAfterDbCommit:
    """D3/D11 (data-safety): the resolution loop must commit the DB deletes
    (delete_whole_book + calibre_db.session.commit) BEFORE removing files
    (helper.delete_book). The old order deleted files first, so a DB-commit
    failure left a phantom book — the Books row survives but its files are gone,
    so it shows in the library and 404s on open, unrecoverable without the
    backup. The behavioural proof is the live cwn-local repro (clean run: no
    DetachedInstanceError from the post-commit file delete, files+rows gone;
    injected commit failure: book fully intact). These pins lock the ordering.
    """

    def _body(self):
        return _func_src("auto_resolve_duplicates")

    def test_db_commit_precedes_file_delete(self):
        src = self._body()
        commit = src.find("calibre_db.session.commit()")
        file_del = src.find("helper.delete_book(")
        assert commit != -1 and file_del != -1, "commit + file-delete must both exist in the loop"
        assert commit < file_del, (
            "delete_whole_book + calibre_db.session.commit() must run BEFORE "
            "helper.delete_book, so a DB failure can't leave a phantom book whose "
            "files are already gone (D3/D11)"
        )

    def test_file_cleanup_uses_plain_standin_not_orm_object(self):
        src = self._body()
        # delete_whole_book runs intermediate commits (custom-column deletes) +
        # a bulk Books.delete() that expire/detach `book`; passing it to the
        # files-last cleanup raises DetachedInstanceError on custom-column
        # libraries (Greptile #399). Hand the cleanup a plain stand-in instead.
        assert "helper.delete_book(book," not in src, (
            "files-last cleanup must NOT pass the ORM `book` — it is detached/"
            "expired after delete_whole_book on custom-column libraries (D3)"
        )
        assert "_DeletedBookFileRef(deleted_book_id, deleted_book_path)" in src, (
            "the cleanup must receive a plain-value stand-in (id + path)"
        )
        assert "deleted_book_path = book.path" in src, (
            "book.path must be captured as a plain value before the DB delete"
        )

    def test_no_orm_book_access_after_the_db_delete(self):
        src = self._body()
        after = src.split("delete_whole_book(deleted_book_id, book)", 1)[1]
        assert "book.id" not in after, (
            "no `book.id` (ORM access on the now-detached/expired object) is "
            "allowed after delete_whole_book — use the captured deleted_book_id "
            "(D3, Greptile #399)"
        )

    def test_file_cleanup_failure_is_logged_not_raised(self):
        src = self._body()
        assert 'raise Exception(f"Delete failed' not in src, (
            "a post-DB-commit file cleanup failure must be logged, not raised — "
            "raising would falsely report the already-completed DB delete as failed "
            "and skip the audit bookkeeping (D3)"
        )
        assert "removed from the database but file" in src, (
            "the files-last path must log a warning on a file-cleanup failure"
        )
