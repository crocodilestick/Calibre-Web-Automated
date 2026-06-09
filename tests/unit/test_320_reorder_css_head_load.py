# -*- coding: utf-8 -*-
"""fork #320 (@SpookyUSAF): the shelf-reorder cover-sizing stylesheet must load
from the document HEAD, not the body.

The reorder grid's cover sizing lives in cps/static/css/shelf_reorder.css. It was
linked via a <link> placed inside the page's {% block body %}. A body-placed
stylesheet link is valid HTML and works in a plain browser, but the only difference
between it and the core stylesheets (cwa.css / caliBlur.css, which always applied for
the reporter) was head-vs-body placement — and some reverse proxies / security
middleware strip or ignore <link> elements found in the body as "injected", leaving
the covers unsized (oversized "large icon" style) on an otherwise-styled page. The
reporter saw oversized covers across v4.0.158 and v4.0.159 on caliBlur even though a
fresh local instance rendered them at the normal 150x225 thumbnail size — the tell
that the page-specific sheet wasn't reaching their browser.

This pins the fix: the link is declared in a {% block header %} (which layout.html
renders inside <head>) and NOT in the body, so it loads the same way as every other
stylesheet. See notes/fix-320-reproduction-attempts.md.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "cps" / "templates" / "shelf_order.html"


def _src():
    return TEMPLATE.read_text(encoding="utf-8")


def test_reorder_stylesheet_linked_in_header_block():
    src = _src()
    assert "{% block header %}" in src, "shelf_order.html must define a header block"
    header = src.split("{% block header %}", 1)[1].split("{% endblock %}", 1)[0]
    assert "shelf_reorder.css" in header, (
        "the shelf_reorder.css <link> must live in the {% block header %} so it loads "
        "from the document <head> (fork #320 — a body-placed link got stripped by some "
        "reverse proxies, leaving reorder covers oversized)"
    )


def test_reorder_stylesheet_not_in_body_block():
    src = _src()
    body = src.split("{% block body %}", 1)[1]
    assert "shelf_reorder.css" not in body, (
        "the shelf_reorder.css <link> must NOT be in {% block body %} — a body-placed "
        "stylesheet link can be dropped by reverse proxies / security middleware (#320)"
    )


def test_reorder_stylesheet_file_exists():
    css = REPO / "cps" / "static" / "css" / "shelf_reorder.css"
    assert css.is_file(), "shelf_reorder.css must exist"
    body = css.read_text(encoding="utf-8")
    assert "#reorder-grid .reorder-item .cover img" in body and "max-width" in body, (
        "shelf_reorder.css must still cap the reorder cover image width"
    )
