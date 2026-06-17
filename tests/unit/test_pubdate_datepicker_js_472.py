# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pin the Published-Date datepicker frontend for year-only input (issue #472).

The backend (``parse_partial_pubdate``) accepts "2020" / "2020-05", but a hand
-typed bare year never reaches the form unless bootstrap-datepicker stops
"force-parsing" it on blur. These checks guard the two frontend invariants that
make the feature actually work in the browser, so a future edit to
``edit_books.js`` can't silently revert the fix while the backend unit tests
stay green.
"""

from __future__ import annotations

import re
from pathlib import Path


def _edit_books_js() -> str:
    path = (
        Path(__file__).resolve().parents[2]
        / "cps" / "static" / "js" / "edit_books.js"
    )
    return path.read_text(encoding="utf-8")


def test_datepicker_disables_force_parse():
    # Without forceParse:false bootstrap-datepicker reformats/blanks a typed
    # bare year on blur, so it never submits.
    js = _edit_books_js()
    assert re.search(r"forceParse\s*:\s*false", js), (
        "edit_books.js must init the datepicker with forceParse:false so a "
        "hand-typed year survives blur (issue #472)"
    )


def test_mirror_regex_tolerates_partial_dates():
    # The localized #fake_pubdate mirror must accept year-only and year-month
    # values, not only full YYYY-MM-DD, so it doesn't go stale when a partial
    # date is typed. The old regex required all three groups unconditionally;
    # the new one makes month and day optional.
    js = _edit_books_js()
    assert "(\\d{1,2})?" in js or "(?:[-\\/\\\\](\\d{1,2})" in js, (
        "edit_books.js mirror regex must make the month/day groups optional "
        "so year-only input still updates the localized display (issue #472)"
    )
    # Defense in depth: the strict three-group regex that required a full date
    # must be gone.
    assert "/(\\d{4})[-\\/\\\\](\\d{1,2})[-\\/\\\\](\\d{1,2})/" not in js, (
        "the old full-date-only mirror regex must be replaced with the "
        "partial-tolerant one"
    )
