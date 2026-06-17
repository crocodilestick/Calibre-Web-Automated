# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #468 — the Kobo two-way-sync deletion path must be
FAIL-SAFE: a transient magic-shelf membership query failure must never archive
books off the device.

Reporters (@Glennza1962, @bigbold1023): on Kobo shelf-sync mode a book they're
*currently reading* sometimes gets archived and has to be re-downloaded; "seems
random". Mechanism (cps/kobo.py): the deletion path archives
``synced_book_ids - allowed_book_ids`` where ``allowed`` includes magic-shelf
membership. ``get_book_ids_for_magic_shelf`` / ``get_books_for_magic_shelf``
swallowed a ``SQLAlchemyError`` as ``[], 0`` — so a failed membership query
looked identical to "the shelf is empty", dropping the in-progress book out of
``allowed`` and into the to-archive set.

Fix: ``get_magic_shelf_book_ids_for_kobo`` returns ``(ids, reliable)``;
``compute_kobo_books_to_archive`` returns an EMPTY set when membership is
unreliable; the deletion path is gated on that. These tests exercise the real
functions via AST extraction (no heavy ``cps.kobo`` import) + pin the wiring.
"""

import ast
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
KOBO_PY = REPO / "cps" / "kobo.py"
MAGIC_PY = REPO / "cps" / "magic_shelf.py"


def _load_func(path, name, glb=None):
    """Exec a single top-level function from `path` in an isolated namespace
    (with optional mocked globals) so we run the real source without importing
    the module's heavy dependency graph."""
    tree = ast.parse(path.read_text())
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if fn is None:
        raise AssertionError(f"{name} not found in {path} (RED on main = not implemented)")
    ns = dict(glb or {})
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


# --------------------------------------------------------------------------
# Pure fail-safe decision helper
# --------------------------------------------------------------------------

def test_archive_set_is_difference_when_reliable():
    f = _load_func(KOBO_PY, "compute_kobo_books_to_archive")
    assert f({1, 2, 3}, {1, 2}, True) == {3}


def test_archive_set_empty_when_membership_unreliable():
    """The #468 footgun: synced - allowed would be everything, but an unreliable
    (failed) membership query must archive NOTHING."""
    f = _load_func(KOBO_PY, "compute_kobo_books_to_archive")
    assert f({1, 2, 3}, set(), False) == set()


def test_reliable_empty_allowed_still_archives():
    """A *reliable* empty allowed set (user genuinely emptied their sync shelves)
    must still archive — only an UNRELIABLE empty set is suppressed."""
    f = _load_func(KOBO_PY, "compute_kobo_books_to_archive")
    assert f({1, 2, 3}, set(), True) == {1, 2, 3}


# --------------------------------------------------------------------------
# Reliability signal from the membership collector
# --------------------------------------------------------------------------

def _kobo_membership_globals(get_books_side_effect=None, get_books_return=None):
    config = mock.Mock()
    config.config_kobo_sync_magic_shelves = True
    shelf = mock.Mock()
    shelf.id = 11
    ub = mock.Mock()
    ub.session.query.return_value.filter_by.return_value.all.return_value = [shelf]
    magic_shelf = mock.Mock()
    if get_books_side_effect is not None:
        magic_shelf.get_books_for_magic_shelf.side_effect = get_books_side_effect
    else:
        magic_shelf.get_books_for_magic_shelf.return_value = get_books_return
    log = mock.Mock()
    log.isEnabledFor.return_value = False
    return {"config": config, "ub": ub, "magic_shelf": magic_shelf, "log": log,
            "logging": __import__("logging")}


def test_membership_unreliable_when_query_fails():
    f = _load_func(KOBO_PY, "get_magic_shelf_book_ids_for_kobo",
                   _kobo_membership_globals(get_books_side_effect=Exception("database is locked")))
    ids, reliable = f(1)
    assert ids == set()
    assert reliable is False


def test_membership_reliable_on_success():
    book = mock.Mock()
    book.id = 42
    f = _load_func(KOBO_PY, "get_magic_shelf_book_ids_for_kobo",
                   _kobo_membership_globals(get_books_return=([book], 1)))
    ids, reliable = f(1)
    assert ids == {42}
    assert reliable is True


def test_membership_calls_with_raise_on_error():
    """The Kobo collector must ask the shelf query to RAISE (not mask) errors,
    otherwise the reliability signal can never be False."""
    glb = _kobo_membership_globals(get_books_return=([], 0))
    f = _load_func(KOBO_PY, "get_magic_shelf_book_ids_for_kobo", glb)
    f(1)
    _, kwargs = glb["magic_shelf"].get_books_for_magic_shelf.call_args
    assert kwargs.get("raise_on_error") is True


# --------------------------------------------------------------------------
# Wiring pins
# --------------------------------------------------------------------------

def test_deletion_path_uses_failsafe_helper():
    src = KOBO_PY.read_text()
    assert "compute_kobo_books_to_archive(" in src, "deletion path must use the fail-safe helper"
    assert "books_to_delete_ids = synced_book_ids - allowed_book_ids" not in src, (
        "the bare set-difference (no reliability gate) must be gone — that was the #468 bug"
    )
    assert "magic_shelf_membership_reliable" in src


def test_magic_shelf_helpers_thread_raise_on_error():
    src = MAGIC_PY.read_text()
    assert src.count("raise_on_error") >= 4, (
        "raise_on_error must be a param on get_book_ids_for_magic_shelf + "
        "get_books_for_magic_shelf and threaded through + honored in except"
    )
