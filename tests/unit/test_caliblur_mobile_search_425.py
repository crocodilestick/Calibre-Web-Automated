# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #425 (@getthething) — tapping the search icon did nothing on mobile
(iOS Safari); desktop worked.

The collapsed mobile search input ``#query`` (40px tap target in caliBlur's
``max-width: 767px`` block) is a sibling of the full-width ``.navbar-header``,
which painted over it — a real tap landed on ``.navbar-header`` and never
reached ``#query``, so the focus that adds ``.search-focus`` and expands the box
never fired. Fix: ``position: relative; z-index`` lifts the tap target above the
header. The input was also ``opacity: 0``, which iOS Safari will not focus on
tap (desktop will) — dropped in favour of transparent text/background so the
input stays invisible yet focusable.

Pinned by source so a future edit can't silently reintroduce ``opacity: 0`` on
the collapsed input or drop the stacking fix.
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(__file__)
CALIBLUR = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "static", "css", "caliBlur.css")
)


def _mobile_query_block():
    """Return the body of the collapsed-mobile ``#query`` rule (the one carrying
    ``width: 40px !important``), with CSS comments stripped so prose in a
    comment can't trip the property assertions."""
    with open(CALIBLUR, encoding="utf-8") as fh:
        css = fh.read()
    for m in re.finditer(r"#query\s*\{([^}]*)\}", css):
        body = m.group(1)
        if "width: 40px !important" in body:
            return re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    raise AssertionError("collapsed-mobile #query rule (width: 40px) not found")


def test_collapsed_search_is_stacked_above_navbar_header():
    body = _mobile_query_block()
    assert "z-index" in body, "#query must be stacked above .navbar-header"
    assert "position: relative" in body


def test_collapsed_search_is_not_opacity_zero():
    # opacity:0 makes iOS Safari refuse to focus the input on tap.
    body = _mobile_query_block()
    assert not re.search(r"opacity:\s*0\b", body), (
        "collapsed #query must not be opacity:0 (iOS cannot focus it on tap)"
    )
