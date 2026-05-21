# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #218 (@yodatak): reload embedded
metadata from disk after an external tool (grimmory etc.) edits the
EPUB. Adds a new endpoint:

  POST /admin/book/<int:book_id>/reload_metadata

@edit_required gate (admin OR edit role). Reads on-disk EPUB via
``cps.epub.get_epub_info``, then updates Calibre Books fields:
title, comments, publisher, pubdate, languages. Defers authors,
tags, series — relationship tables are better handled through the
full edit-book save path.

These tests pin the source shape so a future refactor doesn't
silently break the endpoint.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
EDITBOOKS_PY = REPO_ROOT / "cps" / "editbooks.py"


def _source() -> str:
    return EDITBOOKS_PY.read_text()


def test_reload_metadata_route_registered():
    """Route registered at the canonical path under the editbook
    blueprint with POST method."""
    src = _source()
    assert re.search(
        r'@editbook\.route\(\s*["\']/admin/book/<int:book_id>/reload_metadata["\']\s*,\s*methods=\["POST"\]\s*\)',
        src,
    ), (
        "POST /admin/book/<int:book_id>/reload_metadata route must be "
        "registered under the editbook blueprint. See fork #218."
    )


def test_reload_metadata_requires_edit_role():
    """@edit_required (admin OR edit role) — same gate as
    /admin/book/<id> POST. Don't allow viewer-only users to mutate
    the catalog via this endpoint."""
    src = _source()
    # Find the function definition and check the decorators above it.
    match = re.search(
        r"((?:@\w+(?:\([^)]*\))?\s*\n)+)def reload_metadata_from_disk",
        src,
    )
    assert match, "Could not locate reload_metadata_from_disk function + decorators"
    decorators = match.group(1)
    assert "@edit_required" in decorators, (
        "reload_metadata_from_disk must be guarded by @edit_required so "
        "viewer-only users can't mutate the catalog."
    )
    assert "@login_required_if_no_ano" in decorators, (
        "reload_metadata_from_disk must also be guarded by "
        "@login_required_if_no_ano so anonymous users can't hit it."
    )


def test_reload_metadata_404_when_book_missing():
    """The function must return JSON 404 when calibre_db.get_book returns
    None. Pin the shape so a future refactor doesn't accidentally
    propagate the None through to a 500."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    assert match, "Could not locate function body"
    body = match.group(0)
    assert re.search(r"if not book:", body), (
        "reload_metadata_from_disk must guard against `book is None` "
        "and return a clean 404."
    )
    assert "404" in body, (
        "reload_metadata_from_disk must return 404 when the book is "
        "missing — not a generic 500."
    )


def test_reload_metadata_uses_get_epub_info():
    """Must delegate parsing to the existing ``cps.epub.get_epub_info``
    helper — reusing the same parser the upload path already trusts
    avoids drift between ingest-time and reload-time metadata
    extraction."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    assert "get_epub_info" in body, (
        "reload_metadata_from_disk must call get_epub_info from cps.epub "
        "so the parsing logic stays consistent with the upload path."
    )


def test_reload_metadata_updates_via_existing_edit_helpers():
    """For comments, publisher, languages — must use the existing
    `edit_book_*` helpers so the relationship-table bookkeeping
    (modify_database_object etc.) stays consistent with the edit-book
    save path."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    for helper in ("edit_book_comments", "edit_book_publisher", "edit_book_languages"):
        assert helper in body, (
            f"reload_metadata_from_disk must call `{helper}` to update "
            f"that field — going direct would skip the relationship "
            f"bookkeeping the helpers do."
        )


def test_reload_metadata_writes_under_metadata_db_lock():
    """The actual mutation must run inside ``metadata_db_write_lock()`` —
    same coordination as other writers to prevent torn writes during
    concurrent ingest / convert / edit operations."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    assert "metadata_db_write_lock()" in body, (
        "reload_metadata_from_disk must guard its writes with "
        "metadata_db_write_lock() — concurrent ingest/edit can torn-write "
        "the metadata.db otherwise. Same pattern as other writers."
    )


def test_reload_metadata_returns_updated_fields_list():
    """The JSON response must include `updated_fields` (a list) so the
    UI can show the user which fields actually changed, not just a
    generic 'reloaded'."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    assert "updated_fields" in body, (
        "The JSON response must include `updated_fields` so the caller "
        "knows what actually changed (not just 'reloaded'). Useful for "
        "the UI toast + for any test/automation that calls this endpoint."
    )


def test_fork_218_anchor_comment_present():
    """A search anchor in the function docstring so future code
    archaeology finds the rationale for this endpoint (and the
    deliberately-deferred authors/tags/series)."""
    src = _source()
    assert "#218" in src or "fork issue #218" in src or "fork #218" in src, (
        "editbooks.py must reference fork #218 near the reload-metadata "
        "function so a future refactor can find the rationale."
    )


def test_reload_metadata_defers_authors_tags_series():
    """Verify the deferred-fields decision is documented in the
    function — those involve relationship-table bookkeeping that the
    full edit-book save path handles correctly. This test pins that
    we DON'T silently start updating them through this endpoint."""
    src = _source()
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\n\Z)",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    # No edit_book_authors or edit_book_tags or edit_book_series call.
    for forbidden in ("edit_book_authors(", "edit_book_tags(", "edit_book_series("):
        assert forbidden not in body, (
            f"reload_metadata_from_disk must NOT call `{forbidden}` — "
            f"those fields involve relationship-table bookkeeping that "
            f"is deliberately deferred to the full edit-book save path. "
            f"Updating them here without the full bookkeeping risks "
            f"orphaned tag rows / author_sort drift / series-index "
            f"clashes."
        )
