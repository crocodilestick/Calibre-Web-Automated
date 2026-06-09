# -*- coding: utf-8 -*-
"""fork #320 (@SpookyUSAF): the redesigned shelf-reorder page must not wear the
legacy ``shelforder`` body class.

caliBlur.css carries a block of rules for the OLD list-based reorder page, keyed
on ``body.shelforder``. One of them paints a decorative sort glyph as a
fixed-position pseudo-element on the layout wrapper itself::

    body.shelforder > div.container-fluid > div.row-fluid > div.col-sm-10:before {
        content: "\\e155";            /* glyphicon sort-by-attributes */
        font-size: 6vw;
        position: fixed; left: 240px; top: 180px;
    }

On the old page the content sat 20% from the left, so the glyph decorated the
empty gutter. The redesigned cover grid fills the full width, so the glyph — a
giant white "down arrow + lines" icon, 117px at a 1955px viewport — renders on
top of the first covers. (The reporter's screenshots: covers correctly 150x225,
shelf_reorder.css loading 200, and still a huge icon over the grid.)

The fix gives the redesigned page its own body class, ``shelfreorder``, so the
whole legacy caliBlur block is inert for it. These tests pin that:

* shelf.py renders the reorder page with ``page="shelfreorder"`` (layout.html
  emits ``page`` as the body class) and never with the legacy name;
* main.js's drag-upload background gates follow the rename (they suppress the
  upload drop-zone flash while dragging covers on this page);
* the legacy glyph rule still targets only ``body.shelforder`` — if a future
  caliBlur sync rewrites it to a selector the new page matches, this fails.
"""

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]


def _read(*parts):
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def test_reorder_route_uses_new_body_class():
    src = _read("cps", "shelf.py")
    assert 'page="shelfreorder"' in src, (
        "the reorder route must render with page=\"shelfreorder\" — the legacy "
        "\"shelforder\" class pulls in caliBlur's old-page rules, including the "
        "fixed 6vw sort glyph that covers the grid (#320)"
    )
    assert 'page="shelforder"' not in src, (
        "no route may use the legacy \"shelforder\" page class (#320)"
    )


def test_mainjs_upload_gates_follow_rename():
    src = _read("cps", "static", "js", "main.js")
    assert "hasClass('shelfreorder')" in src, (
        "main.js must gate the drag-upload background flash on the new "
        "'shelfreorder' body class (dragging covers is the page's own interaction)"
    )
    assert "hasClass('shelforder')" not in src, (
        "stale 'shelforder' gate in main.js — the body class was renamed (#320)"
    )


def test_legacy_glyph_rule_stays_scoped_to_old_class():
    css = _read("cps", "static", "css", "caliBlur.css")
    # Find every rule block whose declarations include the \e155 glyph.
    for match in re.finditer(r"([^{}]+)\{([^{}]*\\e155[^{}]*)\}", css):
        selector = match.group(1).strip().splitlines()[-1].strip()
        assert "shelforder" in selector and "shelfreorder" not in selector, (
            "the caliBlur \\e155 sort-glyph rule must stay keyed to the legacy "
            "body.shelforder class only — the redesigned grid page "
            "(body.shelfreorder) must never match it (#320): %r" % selector
        )
