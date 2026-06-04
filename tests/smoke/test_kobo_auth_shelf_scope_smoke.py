# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for upstream issue crocodilestick/Calibre-Web-Automated#817.

Original symptom: visiting Profile -> Create/View Kobo Auth Token enqueued
a kepub conversion task for every EPUB in the library, regardless of
whether the book was on a Kobo Sync shelf. On large libraries (200k+
books) this flooded the worker queue, triggered a flood of `Skipping kepub
auto-conversion` warnings, and starved the actual /v1/library/sync calls
until the container was marked unhealthy.

The fix has gone through two phases:

1. Original (cps/kobo_auth.py): scope the auto-conversion to books on the
   user's Kobo Sync shelves only. Books outside those shelves were still
   converted on-demand at sync time by the existing Kobo flow.
2. PR #350 (Michael Shavit, CWA #1344): **delete** the auto-convert loop
   from `generate_auth_token` entirely. Defer kepub conversion to download
   time — `helper.get_download_link` for "kepub" format converts only the
   book the device is actively requesting, never walking the library.

This test pins the post-#350 invariants:

* `generate_auth_token` must NOT iterate books to convert kepubs (any
  query against db.Books at this layer would reintroduce the #817 regress).
* The conversion path must live in `helper.get_download_link`, scoped to a
  single book id at request time (the device's specific download).
"""

import ast
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KOBO_AUTH = REPO_ROOT / "cps" / "kobo_auth.py"
HELPER = REPO_ROOT / "cps" / "helper.py"


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} function not found in {path}"
    return ast.unparse(fn)


@pytest.mark.smoke
class TestNoUnboundedLibraryWalkInAuthToken:
    """Pin the post-#350 design: generate_auth_token never walks books to
    queue conversions. The #817 regression vector (library-wide convert
    on every visit) is structurally impossible if the loop is gone."""

    def test_no_books_query_in_auth_token(self):
        src = _function_source(KOBO_AUTH, "generate_auth_token")
        # The old loop did `calibre_db.session.query(db.Books)...`. Whether
        # scoped to shelves or not, ANY Books query at this layer is the
        # regression vector. The new design queries no books here.
        assert "db.Books" not in src, (
            "generate_auth_token must not query db.Books — the auto-convert "
            "loop was the #817 regression vector. PR #350 (CWA #1344) "
            "removes the loop and defers conversion to download time."
        )

    def test_no_convert_in_auth_token(self):
        src = _function_source(KOBO_AUTH, "generate_auth_token")
        assert "convert_book_format" not in src, (
            "generate_auth_token must not call convert_book_format. The "
            "auto-convert loop was the #817 regression vector and is now "
            "deferred to download time (PR #350)."
        )


@pytest.mark.smoke
class TestPerBookConversionScopedToRequestedDownload:
    """The on-demand replacement in helper.get_download_link must convert
    only the single book the device is actively requesting — never walk
    a shelf, library, or batch. That's what closes the #817 vector
    structurally instead of by scope filter."""

    def test_get_download_link_converts_one_book_per_call(self):
        src = _function_source(HELPER, "get_download_link")
        # The function takes a single book_id argument (its signature is
        # `def get_download_link(book_id, book_format, client)`). The
        # conversion happens against that exact book_id — no shelf
        # enumeration, no batch loop.
        assert "convert_book_format(book.id" in src, (
            "On-demand conversion in get_download_link must target the "
            "single requested book (book.id), not a batch."
        )

    def test_no_shelf_enumeration_in_get_download_link(self):
        src = _function_source(HELPER, "get_download_link")
        # Shelf enumeration in the download path would defeat the
        # per-request scope and re-introduce the #817 flood vector.
        assert "BookShelf" not in src, (
            "get_download_link must not enumerate shelves — the on-demand "
            "conversion is scoped strictly to the requested download."
        )
        assert "kobo_sync" not in src, (
            "get_download_link must not filter on Shelf.kobo_sync — the "
            "scoping is by request, not by shelf membership."
        )
