# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Parse user-entered publication dates that may omit month and/or day.

Calibre stores a full timestamp for a book's publication date, but most books
only carry a publication *year* (issue #472). Requiring a full ``YYYY-MM-DD``
forces users through a click-heavy date picker even when all they know is the
year. This helper accepts the partial forms a person can reasonably type and
fills the missing components with January 1st, matching how Calibre itself
normalises year-only dates.

The function is intentionally pure (no Flask, no DB) so it can be unit-tested in
isolation and reused by any caller that accepts a free-text publication date.
"""
from __future__ import annotations

from datetime import datetime

# Tried in order of decreasing specificity. ``strptime`` requires the whole
# string to match the format, so "2020-05-15" never sneaks through "%Y-%m"
# (the trailing "-15" leaves it unmatched and raises ValueError).
_ACCEPTED_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


def parse_partial_pubdate(raw):
    """Return a ``datetime`` for a publication date that may be year-only.

    Accepts these forms (surrounding whitespace is ignored):

    * ``"YYYY-MM-DD"`` -> that exact date
    * ``"YYYY-MM"``    -> first of that month  (day defaults to 01)
    * ``"YYYY"``       -> January 1st of that year (month/day default to 01)

    Raises ``ValueError`` on empty input or anything that is not one of the
    accepted forms, so callers can surface the same validation error they did
    when only full dates were allowed.
    """
    if raw is None:
        raise ValueError("empty publication date")
    text = raw.strip()
    if not text:
        raise ValueError("empty publication date")
    for fmt in _ACCEPTED_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(
        "Incorrect publication date; expected YYYY, YYYY-MM, or YYYY-MM-DD"
    )
