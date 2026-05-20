# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Backport of janeczku/calibre-web #3358 (@dotknott) — surface Subtitle
in Kobo sync metadata when the Calibre library has a custom column
labeled "subtitle".

Background. Many Calibre libraries (especially non-fiction and academic)
store a per-book subtitle in a custom column. Kobo's sync protocol has
a "Subtitle" key in its metadata block that the device renders under
the title. Stock CW + the fork never populated it, so the subtitle
column existed in Calibre but never made it to the Kobo device.

@dotknott's upstream PR added a `get_subtitle(book)` helper that
queries `db.CustomColumns` for a column labeled "subtitle" and reads
the value off `book.custom_column_<N>`. The upstream patch had three
null-handling bugs:

1. `.all()[0]` raises IndexError when no "subtitle" column exists —
   so libraries without a subtitle column would crash on every Kobo
   sync after the patch. The intended behavior (return empty string)
   never fires.
2. The `if (col): ... else: return ""` structure is unreachable — col
   is always truthy when we get past the `[0]` access; the else branch
   is dead code.
3. `if len(subtitleColumn)` raises TypeError when the attribute is
   None (e.g. the column exists but the book has no value).

This file pins the corrected behavior end-to-end:

1. `get_subtitle` returns "" when no custom column labeled "subtitle"
   exists in the library.
2. Returns "" when the column exists but the book has no value
   (empty list).
3. Returns "" when the column exists but the cell value is None.
4. Returns the value string when the book HAS a subtitle.
5. The metadata block emitted by `get_metadata` always carries a
   "Subtitle" key (Kobo device contract — the key must be present
   even when empty, otherwise some device firmware versions reject
   the entry).

These are source-pin tests + behavioral tests against the helper
function with a mocked book + custom-column shape.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
KOBO_PY = REPO_ROOT / "cps" / "kobo.py"


def _kobo_source() -> str:
    return KOBO_PY.read_text()


def test_get_subtitle_function_defined():
    """`get_subtitle` must exist alongside the other `get_*` helpers
    so the metadata builder can call it."""
    src = _kobo_source()
    assert re.search(r"^def get_subtitle\(book\):", src, re.MULTILINE), (
        "cps/kobo.py must define `def get_subtitle(book):` so the "
        "metadata block can populate the Kobo Subtitle field. See "
        "janeczku PR #3358 (@dotknott)."
    )


def test_get_metadata_emits_subtitle_key():
    """The metadata dict assembled in `get_metadata` must carry a
    `Subtitle` key. Some Kobo firmware versions reject sync entries
    that omit the key, so we always include it (empty string when
    there's no subtitle column or no value).
    """
    src = _kobo_source()
    # Source pin: the metadata dict literal must reference Subtitle.
    assert re.search(
        r"[\"']Subtitle[\"']\s*:\s*get_subtitle\(book\)",
        src,
    ), (
        "cps/kobo.py:get_metadata must include `\"Subtitle\": "
        "get_subtitle(book)` in the metadata dict literal so the Kobo "
        "device receives the subtitle every sync."
    )


def test_get_subtitle_returns_empty_when_column_missing():
    """When the library has no custom column labeled 'subtitle',
    `get_subtitle` must return `""` — not raise IndexError (which is
    what @dotknott's upstream patch did via `.all()[0]`)."""
    from cps import kobo

    # Patch the calibre_db.session.query chain to return no columns.
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None

    book = MagicMock()
    book.id = 42

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kobo.calibre_db, "session", fake_session, raising=True)
        result = kobo.get_subtitle(book)

    assert result == "", (
        f"get_subtitle must return empty string when no 'subtitle' "
        f"custom column exists. Got {result!r}. The upstream patch's "
        f"`.all()[0]` would have raised IndexError here."
    )


def test_get_subtitle_returns_empty_when_book_has_no_value():
    """When the column exists but the book has no value (the
    `custom_column_N` attribute returns an empty list), `get_subtitle`
    must return `""` — not raise."""
    from cps import kobo

    fake_col = MagicMock()
    fake_col.id = 7
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = fake_col

    book = MagicMock()
    # Empty list = "column exists but book has no value entered"
    book.custom_column_7 = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kobo.calibre_db, "session", fake_session, raising=True)
        result = kobo.get_subtitle(book)

    assert result == "", (
        f"get_subtitle must return empty string when the column exists "
        f"but the book has no subtitle value. Got {result!r}. The "
        f"upstream patch's `if len(subtitleColumn)` would have skipped "
        f"this correctly, but then fallen through to no return — "
        f"emitting `None` instead of `\"\"`."
    )


def test_get_subtitle_returns_value_when_book_has_subtitle():
    """Happy path: column exists + book has a value → return the value
    as a string."""
    from cps import kobo

    fake_col = MagicMock()
    fake_col.id = 7
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = fake_col

    # custom_column_7 returns a list-like with one entry whose `.value`
    # is the subtitle string. This matches the SQLAlchemy
    # `relationship('custom_column_N', uselist=True)` shape from cps/db.py.
    entry = MagicMock()
    entry.value = "A Study in Sherlock"
    book = MagicMock()
    book.custom_column_7 = [entry]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kobo.calibre_db, "session", fake_session, raising=True)
        result = kobo.get_subtitle(book)

    assert result == "A Study in Sherlock", (
        f"get_subtitle must return the cell value string when set. "
        f"Got {result!r}."
    )


def test_get_subtitle_returns_empty_when_attribute_missing():
    """Defense in depth: if for some reason the book row doesn't have
    a `custom_column_N` attribute at all (schema drift, lazy-load not
    yet triggered, etc.), `get_subtitle` must NOT raise AttributeError."""
    from cps import kobo

    fake_col = MagicMock()
    fake_col.id = 999
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = fake_col

    # `book` is a plain object — does NOT have `custom_column_999`.
    book = object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kobo.calibre_db, "session", fake_session, raising=True)
        result = kobo.get_subtitle(book)

    assert result == "", (
        f"get_subtitle must return empty string when the book row has "
        f"no `custom_column_N` attribute (schema drift, etc.). Got "
        f"{result!r}."
    )


def test_get_subtitle_returns_empty_when_value_is_none():
    """Defense in depth: if the cell exists but value is None, return ""."""
    from cps import kobo

    fake_col = MagicMock()
    fake_col.id = 7
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = fake_col

    entry = MagicMock()
    entry.value = None  # cell exists but no value
    book = MagicMock()
    book.custom_column_7 = [entry]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kobo.calibre_db, "session", fake_session, raising=True)
        result = kobo.get_subtitle(book)

    assert result == "", (
        f"get_subtitle must return empty string when the cell value "
        f"is None (Calibre allows NULL in custom column cells). Got "
        f"{result!r}."
    )


def test_get_subtitle_query_filters_on_subtitle_label():
    """The custom-column query must filter on `CustomColumns.label == 'subtitle'`
    (case-sensitive, matches Calibre's convention). Pinning this so a
    future refactor doesn't change the lookup label and silently break
    the wiring."""
    src = inspect.getsource(__import__("cps.kobo", fromlist=["get_subtitle"]).get_subtitle)
    assert re.search(
        r"CustomColumns\.label\s*==\s*[\"']subtitle[\"']",
        src,
    ), (
        "get_subtitle must filter `CustomColumns.label == 'subtitle'` "
        "so the lookup matches the Calibre convention. Source: "
        + repr(src)
    )
