# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Regression coverage for issue #1256 / issuecomment-4188267348.

The reported freeze is caused by thumbnail generation being queued while the
metadata edit request is still using the Calibre SQLite session. The thumbnail
worker creates its own CalibreDB session and registers SQLite Python UDFs, which
can deadlock with in-flight metadata queries that also need those UDF callbacks.
"""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _call_name(node):
    """Return dotted call name for simple ast.Call nodes."""
    parts = []
    current = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _module_tree(relative_path):
    return ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _function_def(tree, name):
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_cover_thumbnail_refresh_is_not_queued_before_metadata_commit():
    """
    Cover thumbnail replacement must be deferred until after the Calibre metadata
    commit. Queueing it before commit lets the worker race the request thread and
    reproduce the SQLite/GIL deadlock described in issue #1256.
    """
    do_edit_book = _function_def(_module_tree("cps/editbooks.py"), "do_edit_book")

    thumbnail_lines = []
    commit_lines = []
    for node in ast.walk(do_edit_book):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node)
        if call_name == "helper.replace_cover_thumbnail_cache":
            thumbnail_lines.append(node.lineno)
        elif call_name == "calibre_db.session.commit":
            commit_lines.append(node.lineno)

    assert thumbnail_lines, "do_edit_book should refresh thumbnails after cover changes"
    assert commit_lines, "do_edit_book should commit Calibre metadata changes"

    first_thumbnail_refresh = min(thumbnail_lines)
    last_metadata_commit = max(commit_lines)

    assert first_thumbnail_refresh > last_metadata_commit, (
        "thumbnail refresh is queued before the metadata commit, allowing the "
        "thumbnail worker to initialize a CalibreDB session while the request "
        "thread is still executing SQLite metadata queries"
    )


def test_cover_thumbnail_refresh_passes_committed_book_snapshot():
    """
    The post-commit refresh should pass the book path and last_modified timestamp
    so single-book thumbnail generation does not need to reopen metadata.db.
    """
    do_edit_book = _function_def(_module_tree("cps/editbooks.py"), "do_edit_book")

    refresh_calls = [
        node for node in ast.walk(do_edit_book)
        if isinstance(node, ast.Call)
        and _call_name(node) == "helper.replace_cover_thumbnail_cache"
    ]

    assert len(refresh_calls) == 1
    keyword_names = {keyword.arg for keyword in refresh_calls[0].keywords}
    assert {"book_path", "last_modified"} <= keyword_names


def test_single_book_thumbnail_snapshot_path_avoids_calibre_db_query():
    """
    When a single-book refresh has a committed book_path snapshot, that branch
    must build a BookCoverSource directly instead of falling through to
    get_books_with_covers(), which opens a fresh CalibreDB session.
    """
    thumbnail_tree = _module_tree("cps/tasks/thumbnail.py")
    get_cover_sources = _function_def(thumbnail_tree, "get_cover_sources")

    snapshot_branch = get_cover_sources.body[0]
    assert isinstance(snapshot_branch, ast.If)

    snapshot_calls = {
        _call_name(node) for node in ast.walk(snapshot_branch)
        if isinstance(node, ast.Call)
    }
    assert "BookCoverSource" in snapshot_calls
    assert "self.get_books_with_covers" not in snapshot_calls

    fallback_calls = [
        node for node in ast.walk(get_cover_sources)
        if isinstance(node, ast.Call)
        and _call_name(node) == "self.get_books_with_covers"
    ]
    assert len(fallback_calls) == 1
    assert fallback_calls[0].lineno > snapshot_branch.lineno
