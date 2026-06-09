# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork #312 (custom-column subset) — the KOReader sync
read-status write must honor ``config.config_read_column``, mirroring the web
path ``helper.edit_book_read_status``.

Before the fix, ``update_book_read_status`` wrote only ``ub.ReadBook``. A user
who configured a Calibre custom column as their read marker (a stock
Calibre-Web option) got KOReader completions written to a ``ReadBook`` row their
detail page never reads, so the "read" checkmark stayed empty — the exact #312
symptom, re-introduced for the custom-column subset of users.

The behavioral red/green lives in the docker-integration suite (the custom-column
write needs real Calibre ``cc_classes`` reflection + metadata.db). These are
source pins: cheap CI-runnable invariants that fail RED if the mirror is dropped
or its sticky/guard semantics drift, so a future refactor can't silently undo
the fix while the slow integration test is path-skipped.
"""

import inspect
import sys

import pytest


def _kosync_module():
    """Return the kosync *module* (not the re-exported Blueprint).

    ``cps.progress_syncing.protocols.__init__`` does ``from .kosync import
    kosync``, binding the Blueprint object as ``protocols.kosync`` and shadowing
    the submodule attribute. The module itself stays in ``sys.modules``.
    """
    import cps.progress_syncing.protocols.kosync  # noqa: F401 — populate sys.modules
    return sys.modules["cps.progress_syncing.protocols.kosync"]


@pytest.fixture(scope="module")
def kosync():
    return _kosync_module()


class TestCustomReadColumnMirrorExists:
    def test_mark_custom_read_column_helper_defined(self, kosync):
        """A dedicated single-concern helper writes the custom read column."""
        assert hasattr(kosync, "_mark_custom_read_column"), (
            "kosync must define _mark_custom_read_column to mirror the web "
            "path's config_read_column branch for the KOReader sync path (#312)"
        )
        assert callable(kosync._mark_custom_read_column)

    def test_update_status_gates_mirror_on_read_column_and_finished(self, kosync):
        """update_book_read_status routes FINISHED completions to the column
        ONLY when config_read_column is set (default ReadBook path untouched),
        and only on FINISHED (sticky — a sync never clears the marker)."""
        src = inspect.getsource(kosync.update_book_read_status)
        assert "config.config_read_column" in src, (
            "update_book_read_status must branch on config.config_read_column; "
            "without it KOReader completions never reach a custom read column (#312)"
        )
        assert "_mark_custom_read_column" in src, (
            "update_book_read_status must call _mark_custom_read_column"
        )
        # Sticky semantics: the mirror is gated on FINISHED, so re-opening a
        # finished book in KOReader (a later <99% sync) cannot un-read it.
        assert "STATUS_FINISHED" in src
        gate = src[src.index("config.config_read_column"):]
        assert "STATUS_FINISHED" in gate, (
            "the custom-column mirror must be gated on STATUS_FINISHED (sticky "
            "mark-as-read), not fired on every status"
        )


class TestCustomReadColumnMirrorMatchesWebPath:
    """The mirror must use the same Calibre custom-column write idiom as
    helper.edit_book_read_status, so both surfaces stay consistent."""

    def test_uses_calibre_db_and_cc_classes(self, kosync):
        src = inspect.getsource(kosync._mark_custom_read_column)
        assert "calibre_db.get_book" in src, (
            "must read the book via the unfiltered calibre_db.get_book"
        )
        assert "calibre_db.get_filtered_book(" not in src, (
            "must NOT use get_filtered_book: kosync requests carry no flask-login "
            "user, so current_user is the ANONYMOUS user and get_filtered_book "
            "would apply anonymous content/language restrictions — filtering the "
            "book to None and silently dropping the read marker"
        )
        assert "custom_column_" in src, (
            "must address the custom column via getattr(book, 'custom_column_'+id)"
        )
        assert "cc_classes" in src, (
            "must create a missing column row via db.cc_classes[...] like the web path"
        )
        assert "calibre_db.session.commit" in src, (
            "must commit the metadata.db (calibre_db) session for the column write"
        )

    def test_guards_missing_column_and_db_errors(self, kosync):
        """Best-effort: a missing column / metadata.db error is logged, never
        raised, so a custom-column hiccup can't break progress sync."""
        src = inspect.getsource(kosync._mark_custom_read_column)
        for exc in ("KeyError", "AttributeError", "IndexError"):
            assert exc in src, f"missing-column guard must catch {exc}"
        for exc in ("OperationalError", "InvalidRequestError"):
            assert exc in src, f"metadata.db write guard must catch {exc}"
        assert "rollback" in src, (
            "must roll back calibre_db.session on a write error (mirror web path)"
        )

    def test_book_level_not_user_scoped(self, kosync):
        """Calibre custom read-columns are book-level, not per-user — the helper
        takes a book_id and no user, matching the web path which writes the
        column without a user filter."""
        sig = inspect.signature(kosync._mark_custom_read_column)
        params = list(sig.parameters)
        assert params == ["book_id"], (
            f"_mark_custom_read_column should take only book_id, got {params}"
        )
