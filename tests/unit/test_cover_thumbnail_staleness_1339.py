# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for CWA issue #1339 (@Altycoder, +ragaskar).

Symptom: after a bulk ingest of a fresh library, thumbnails on the home
grid show the wrong covers — they belong to books from a previous
library install whose Calibre `book.id` values overlap with the new
content. Clicking into any individual book shows the correct cover.

Root cause: ``cps.ub.Thumbnail`` rows are keyed by ``entity_id =
book.id`` (no UUID, no content hash). When a library is wiped and
re-ingested, old Thumbnail records (and their files on disk under
``/config/.cache/...``) survive and continue to be served for the
re-used book ids. ``get_book_cover_internal`` only checked whether the
on-disk thumbnail file *existed* — it never compared
``book.last_modified`` against ``thumbnail.generated_at`` — so a stale
file passes the existence check and the wrong cover is served.

The book detail page uses the ``og`` resolution, which has no Thumbnail
rows and falls through to the canonical ``cover.jpg`` on disk (correct).
The home grid uses ``sm``/``md``/``lg`` via ``get_cover_srcset``, which
hit the stale rows.

Fix: in ``get_book_cover_internal``, treat thumbnails whose
``generated_at`` is older than the book's ``last_modified`` as missing.
That triggers the existing background-regenerate branch AND falls
through to serving the on-disk ``cover.jpg`` for the current request,
so the user sees the correct cover immediately and a fresh thumbnail is
written for subsequent loads.

These tests source-pin the staleness check in ``cps/helper.py``:

1. The ``get_book_cover_internal`` body references ``generated_at`` and
   compares it against ``last_modified`` (without this, the staleness
   detection isn't present).
2. The CWA #1339 anchor comment is present in the file so future
   refactors know not to drop the guard.
3. A small unit-level exercise of the inline ``_stale`` helper's
   semantics via direct execution.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PY = REPO_ROOT / "cps" / "helper.py"


def _helper_source() -> str:
    return HELPER_PY.read_text()


def test_helper_compares_book_last_modified_vs_thumbnail_generated_at():
    """The fix MUST compare ``book.last_modified`` against
    ``thumbnail.generated_at`` inside ``get_book_cover_internal``. Without
    this, stale-thumbnail content slips past the file-exists check.
    """
    src = _helper_source()
    # Find the body of get_book_cover_internal.
    match = re.search(
        r"def get_book_cover_internal\(.*?\n(?P<body>.*?)\n(?:def |class )",
        src,
        re.DOTALL,
    )
    assert match, "Could not locate get_book_cover_internal body"
    body = match.group("body")
    assert "generated_at" in body, (
        "get_book_cover_internal must reference `generated_at` to detect "
        "thumbnails that pre-date the current book content. See CWA #1339 "
        "(@Altycoder): otherwise a wiped+re-ingested library serves the "
        "previous content's thumbnails for the new book ids."
    )
    assert "last_modified" in body, (
        "get_book_cover_internal must consult `book.last_modified` "
        "alongside `thumbnail.generated_at` to detect content staleness."
    )


def test_cwa_1339_anchor_comment_present():
    """A search anchor in the file body lets future refactors find
    *why* the staleness guard exists. Without an in-code reference,
    the next refactor will likely remove the check thinking it's
    redundant with the per-book TaskGenerateCoverThumbnails source_newer
    branch (which only runs from the scheduled task, not on the read
    path)."""
    src = _helper_source()
    assert "CWA #1339" in src or "CWA#1339" in src, (
        "cps/helper.py must reference CWA #1339 near the staleness "
        "guard so future code archaeology can find the rationale."
    )


def test_stale_helper_returns_true_when_book_newer_than_thumbnail():
    """Exercise the staleness predicate end-to-end through the actual
    helper source — defines the predicate via exec and confirms the
    book-newer case returns True."""
    src = _helper_source()
    # Pull the inline _stale function out of the source. Use a permissive
    # regex anchored on its def + return that doesn't depend on exact
    # indentation under get_book_cover_internal.
    match = re.search(
        r"^\s*def _stale\(thumb, b\):.*?(?=^\s*if _stale\(webp_thumb)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "Could not extract inline _stale function from helper source"
    # Dedent + run in a sandbox namespace.
    raw = match.group(0)
    indent_match = re.match(r"^(\s+)", raw)
    indent = indent_match.group(1) if indent_match else ""
    dedented = "\n".join(
        line[len(indent):] if line.startswith(indent) else line
        for line in raw.splitlines()
    )
    ns = {}
    exec(dedented, ns)
    _stale = ns["_stale"]

    book_new = SimpleNamespace(
        last_modified=datetime.datetime(2026, 5, 20, 12, 0, 0)
    )
    thumb_old = SimpleNamespace(
        generated_at=datetime.datetime(2025, 1, 1, 0, 0, 0)
    )
    assert _stale(thumb_old, book_new) is True, (
        "Thumbnail generated_at older than book.last_modified must be "
        "treated as stale (otherwise wiped+re-ingested libraries serve "
        "the prior content's thumbnails)."
    )


def test_stale_helper_returns_false_when_thumbnail_current():
    """The other side: don't kill thumbnails that are current."""
    src = _helper_source()
    match = re.search(
        r"^\s*def _stale\(thumb, b\):.*?(?=^\s*if _stale\(webp_thumb)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    raw = match.group(0)
    indent_match = re.match(r"^(\s+)", raw)
    indent = indent_match.group(1) if indent_match else ""
    dedented = "\n".join(
        line[len(indent):] if line.startswith(indent) else line
        for line in raw.splitlines()
    )
    ns = {}
    exec(dedented, ns)
    _stale = ns["_stale"]

    book = SimpleNamespace(
        last_modified=datetime.datetime(2025, 1, 1, 0, 0, 0)
    )
    thumb_current = SimpleNamespace(
        generated_at=datetime.datetime(2026, 5, 20, 12, 0, 0)
    )
    assert _stale(thumb_current, book) is False, (
        "Thumbnail generated AFTER book.last_modified is current; "
        "must not be flagged stale (otherwise we regenerate on every "
        "single cover request)."
    )


def test_stale_helper_tolerates_tz_aware_book_last_modified():
    """Calibre's `book.last_modified` is tz-aware UTC; Thumbnail's
    `generated_at` is tz-naive (UTC by convention). The helper must
    normalize so a tz comparison doesn't raise."""
    src = _helper_source()
    match = re.search(
        r"^\s*def _stale\(thumb, b\):.*?(?=^\s*if _stale\(webp_thumb)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    raw = match.group(0)
    indent_match = re.match(r"^(\s+)", raw)
    indent = indent_match.group(1) if indent_match else ""
    dedented = "\n".join(
        line[len(indent):] if line.startswith(indent) else line
        for line in raw.splitlines()
    )
    ns = {}
    exec(dedented, ns)
    _stale = ns["_stale"]

    book = SimpleNamespace(
        last_modified=datetime.datetime(2026, 5, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
    )
    thumb = SimpleNamespace(
        generated_at=datetime.datetime(2025, 1, 1, 0, 0, 0)  # naive UTC
    )
    # Must not raise; must return True (book newer than thumb).
    assert _stale(thumb, book) is True


def test_stale_helper_returns_false_on_missing_data():
    """Missing thumbnail / missing generated_at / missing book
    last_modified MUST short-circuit to False — otherwise we'd evict
    perfectly good thumbnails just because a column was None."""
    src = _helper_source()
    match = re.search(
        r"^\s*def _stale\(thumb, b\):.*?(?=^\s*if _stale\(webp_thumb)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    raw = match.group(0)
    indent_match = re.match(r"^(\s+)", raw)
    indent = indent_match.group(1) if indent_match else ""
    dedented = "\n".join(
        line[len(indent):] if line.startswith(indent) else line
        for line in raw.splitlines()
    )
    ns = {}
    exec(dedented, ns)
    _stale = ns["_stale"]

    assert _stale(None, SimpleNamespace(last_modified=datetime.datetime.now())) is False
    book = SimpleNamespace(last_modified=datetime.datetime.now())
    assert _stale(SimpleNamespace(generated_at=None), book) is False
    assert _stale(SimpleNamespace(generated_at=datetime.datetime.now()),
                  SimpleNamespace(last_modified=None)) is False
