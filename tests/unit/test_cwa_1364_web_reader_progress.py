# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for CWA #1364 — web reader not saving progress.

Reporter (CWA upstream, today): "The web reader is not saving progress
for any book. Whenever I open a book it initially opens in the last
(correct) position, which is apparently cached in the browser, but
after a couple of seconds it sends me back to the beginning of the
book. ... book_read_link fields are never updated."

Reproduced on our build (cwn-local v4.0.107): bug exists on our code
path. Two distinct root causes:

(1) **localStorage corruption on early locationchange events.** The
``epub-progress.js`` locationchange handler called ``calculateProgress()``
unconditionally and wrote its return value to localStorage. Before
``epub.locations.generate()`` resolves, ``calculateProgress()`` returns 0
— because there are no locations to map the current CFI against. The
handler then wrote ``localStorage[key] = 0``, wiping the valid prior
value. The qFinished/restore path read ``localStorage = 0``, called
``display(cfiFromPercentage(0))``, and the user landed at the
beginning of the book — even though they were reading at 35%.

(2) **``book_read_link`` fields never bumped from the web reader.**
The Kobo + KOSync paths bump ``last_time_started_reading`` and
``times_started_reading``; the web reader's ``read_book`` route never
did. A user who only reads through the browser had no read history
recorded — ``/read``, ``/unread`` filters never reflected web-reader
activity.

These tests source-pin both fixes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "cps" / "static" / "js" / "reading" / "epub-progress.js"
WEB_PY = REPO_ROOT / "cps" / "web.py"


def _js_source() -> str:
    return JS_PATH.read_text()


def _web_source() -> str:
    return WEB_PY.read_text()


# --- Fix #1 source-pins -------------------------------------------------------


def test_locationchange_handler_guards_localstorage_save_on_locations_ready():
    """The localStorage.setItem in the locationchange handler must be
    gated on ``epub.locations._locations.length > 0``. Without the
    guard, an early locationchange (before locations.generate
    resolves) writes 0 to localStorage and corrupts the user's saved
    position."""
    src = _js_source()
    handler_match = re.search(
        r"window\.addEventListener\(['\"]locationchange['\"].*?\}\);",
        src,
        re.DOTALL,
    )
    assert handler_match, "Could not locate locationchange handler"
    body = handler_match.group(0)
    # The setItem call must be inside an `if (...)` that references
    # epub.locations._locations.length.
    assert "epub.locations._locations" in body, (
        "The locationchange handler must check `epub.locations._locations` "
        "before writing to localStorage — otherwise an early locationchange "
        "writes the (necessarily-zero) calculateProgress() result and wipes "
        "the user's prior position. See CWA #1364."
    )
    assert ".length" in body, (
        "Guard must check `epub.locations._locations.length` is non-zero "
        "before the localStorage save."
    )


def test_cwa_1364_anchor_comment_present_in_js():
    """Anchor comment so a future refactor doesn't unwittingly remove
    the locations-ready guard."""
    src = _js_source()
    assert "CWA #1364" in src, (
        "epub-progress.js must reference CWA #1364 so future code "
        "archaeology can find the rationale for the locations-ready "
        "guard around the localStorage save."
    )


# --- Fix #2 source-pins -------------------------------------------------------


def test_read_book_route_updates_book_read_link():
    """The /read/<book_id>/<book_format> route must UPSERT
    ``book_read_link`` for authenticated users — Kobo + KOSync already
    do this; the web reader was the only book-opening surface that
    never recorded a read event."""
    src = _web_source()
    # Locate the read_book function body.
    match = re.search(
        r"def read_book\(book_id, book_format\):.*?(?=\n(?:@web\.route|def \w))",
        src,
        re.DOTALL,
    )
    assert match, "Could not locate read_book function body"
    body = match.group(0)
    assert "ub.ReadBook" in body, (
        "read_book must query `ub.ReadBook` to UPSERT the user's "
        "read state. See CWA #1364."
    )
    assert "last_time_started_reading" in body, (
        "read_book must set `last_time_started_reading` on the book_read_link "
        "row so /read and /unread filters reflect web-reader activity."
    )
    assert "times_started_reading" in body, (
        "read_book must bump `times_started_reading` on the IN_PROGRESS "
        "transition (debounced — only when transitioning FROM a "
        "non-in-progress state, so refreshes don't inflate the count)."
    )
    assert "STATUS_IN_PROGRESS" in body, (
        "read_book must set `read_status = STATUS_IN_PROGRESS` when "
        "opening a not-yet-finished book."
    )


def test_read_book_debounces_times_started_reading_increment():
    """`times_started_reading` should only bump on transition INTO
    IN_PROGRESS — refresh / Back / Forward must not inflate the count.
    Source-pin the guard so a future refactor doesn't remove it."""
    src = _web_source()
    match = re.search(
        r"def read_book\(book_id, book_format\):.*?(?=\n(?:@web\.route|def \w))",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    # The increment must be inside a conditional that excludes
    # IN_PROGRESS (so refresh doesn't bump) and FINISHED (so re-opening
    # a finished book doesn't reset to in-progress and bump).
    assert re.search(
        r"prev_status\s*!=\s*ub\.ReadBook\.STATUS_IN_PROGRESS",
        body,
    ), (
        "read_book must guard the times_started_reading bump on "
        "`prev_status != STATUS_IN_PROGRESS` — refresh shouldn't count "
        "as a new reading session."
    )
    assert "STATUS_FINISHED" in body, (
        "read_book must also exclude STATUS_FINISHED from the bump path "
        "— re-opening a finished book shouldn't silently reset its "
        "status to in-progress."
    )


def test_read_book_handles_db_failure_gracefully():
    """The book_read_link UPSERT is best-effort; failing to record the
    read event must not break page rendering. Pin the try/except."""
    src = _web_source()
    match = re.search(
        r"def read_book\(book_id, book_format\):.*?(?=\n(?:@web\.route|def \w))",
        src,
        re.DOTALL,
    )
    body = match.group(0)
    # The book_read_link block must be inside a try/except.
    assert "Failed to record web reader open in book_read_link" in body, (
        "read_book's book_read_link UPSERT must be wrapped in try/except "
        "so a DB error doesn't break page rendering. The log message lets "
        "future debugging connect a missing book_read_link update to the "
        "exception class."
    )


def test_cwa_1364_anchor_comment_present_in_web_py():
    """Anchor comment in web.py near the book_read_link logic."""
    src = _web_source()
    assert "CWA #1364" in src, (
        "cps/web.py must reference CWA #1364 near the book_read_link "
        "UPSERT so future code archaeology can find the rationale."
    )


def test_datetime_timezone_imported_in_web_py():
    """The book_read_link UPSERT uses `datetime.now(timezone.utc)` —
    confirm both are importable at module level so the route doesn't
    NameError on first call."""
    src = _web_source()
    assert re.search(
        r"^from datetime import (?:.*\b)?datetime",
        src,
        re.MULTILINE,
    ), "cps/web.py must `from datetime import datetime` at module level."
    assert re.search(
        r"^from datetime import (?:.*\b)?timezone",
        src,
        re.MULTILINE,
    ), "cps/web.py must `from datetime import timezone` at module level."
