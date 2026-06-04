# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for upstream issue #1328 / fork issue #50.

Original symptom: Profile -> Create/View Kobo Auth Token returned a blank
page with `sqlite3.InterfaceError: bad parameter or other API misuse`
(cps/kobo_auth.py line ~104, lazy load of `book.data`).

Original root cause: `generate_auth_token` ran a per-Kobo-Sync-shelf-book
kepub auto-conversion loop. The query returned duplicate rows (one per
format), then `book.data` lazy-loaded again per row — N+1 queries on the
request-scoped session. When a worker thread crashed mid-request
(`worker:237 list index out of range` in the original report just above
the trace), subsequent lazy-loads hit a poisoned connection and raised the
SQLite InterfaceError, blanking the page.

The fix has gone through two phases:

1. Original fix (cps/kobo_auth.py): eager-load with `joinedload(db.Books.data)`
   so the lazy-load can't fan out; gate on `config.config_kepubifypath`;
   wrap each per-book convert in try/except so one bad book doesn't blank
   the page.
2. PR #350 (Michael Shavit, CWA #1344): **delete** the auto-convert loop
   from `generate_auth_token` entirely. Defer kepub conversion to download
   time — `helper.get_download_link` for "kepub" format checks if a KEPUB
   exists, falls back to converting from EPUB synchronously (blocking=True,
   120s timeout), and serves EPUB if conversion fails. The blank-page
   symptom is structurally eliminated: no auto-convert loop in
   `generate_auth_token` → no N+1 → no lazy-load on a poisoned connection.

This test file pins the post-#350 invariants:

* `generate_auth_token` must NOT contain a kepub-conversion loop at all
  (the regression vector is gone if the loop is gone).
* `get_download_link` must contain the on-demand kepub fallback path
  (the new design where conversion still happens, just lazily at download).
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
class TestGenerateAuthTokenNoAutoConvertLoop:
    """Post-#350 invariant: generate_auth_token must not iterate books to
    pre-convert kepubs. The loop was the regression vector for #1328 /
    fork #50 — its absence is what makes the blank-page symptom
    structurally impossible."""

    def test_no_kepub_conversion_loop_in_auth_token(self):
        src = _function_source(KOBO_AUTH, "generate_auth_token")
        assert "convert_book_format" not in src, (
            "generate_auth_token must not call convert_book_format. The "
            "auto-convert-at-token-generation loop was the regression "
            "vector for issue #1328 / fork #50 — deferring kepub conversion "
            "to download time eliminates the lazy-load-on-poisoned-connection "
            "blank-page symptom entirely (PR #350, CWA #1344)."
        )

    def test_no_books_data_walk_in_auth_token(self):
        src = _function_source(KOBO_AUTH, "generate_auth_token")
        # Walking book.data on a duplicated-row query was the exact lazy-load
        # pattern that crashed under a poisoned worker connection. If the
        # loop ever comes back, this pin should go red.
        assert "book.data" not in src and "data.format" not in src, (
            "generate_auth_token must not walk book.data — the lazy-load "
            "pattern that crashed under #1328 / fork #50 should not "
            "reappear. If a future change needs kepub gating at this layer "
            "again, write it with joinedload + a try/except guard and "
            "update this pin."
        )


@pytest.mark.smoke
class TestKepubDeferredToDownload:
    """Post-#350 invariant: kepub conversion still happens, but lazily —
    at download time, in `helper.get_download_link`, gated on
    `config.config_kepubifypath` and with EPUB fallback."""

    def test_get_download_link_has_kepub_fallback(self):
        src = _function_source(HELPER, "get_download_link")
        assert 'book_format == "kepub"' in src or "book_format == 'kepub'" in src, (
            "get_download_link must branch on the requested format being "
            "'kepub' so it can convert on demand when KEPUB is missing "
            "(PR #350 deferred design)."
        )
        assert "convert_book_format" in src, (
            "get_download_link must call convert_book_format on the "
            "missing-KEPUB path so the Kobo device still gets a kepub "
            "when one can be produced."
        )

    def test_kepub_conversion_gated_on_config(self):
        src = _function_source(HELPER, "get_download_link")
        assert "config.config_kepubifypath" in src, (
            "get_download_link must gate the on-demand kepub conversion on "
            "config.config_kepubifypath — without the helper binary there's "
            "nothing to convert with, and forging a convert call would "
            "crash the download."
        )

    def test_kepub_conversion_blocks_and_times_out(self):
        # blocking=True is what makes the synchronous-at-download design
        # work — without it the device would 404 before the conversion
        # finished. The convert_book_format helper itself caps at 120s.
        helper_src = HELPER.read_text()
        assert "blocking=True" in helper_src, (
            "get_download_link must call convert_book_format with "
            "blocking=True so the conversion completes before the response "
            "is served. Async conversion would 404 the device's request."
        )
