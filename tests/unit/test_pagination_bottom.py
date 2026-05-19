# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for fork #256 — pagination at end of book list.

Reporter @droM4X: book listing pages render the paginator at the top
of the screen (caliBlur CSS positions ``.pagination`` as
``position: fixed; top: 4.15em; right: 0``). After scrolling to the
bottom of a long list, the user has to scroll back up to navigate.

Fix: render a second copy of the paginator at the end of the list in
normal document flow. The bottom copy carries a ``.pagination-bottom``
class so it can override the fixed positioning via CSS.

These tests pin:
1. Both paginators exist in `cps/templates/layout.html`.
2. The bottom one carries the `pagination-bottom` modifier.
3. The CSS override for `.pagination-bottom` is present in caliBlur.css.
4. The CSS override actually undoes the `position: fixed`.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _layout_template():
    return (REPO_ROOT / "cps" / "templates" / "layout.html").read_text()


def _caliblur_css():
    return (REPO_ROOT / "cps" / "static" / "css" / "caliBlur.css").read_text()


def test_layout_renders_two_pagination_blocks():
    """Both the top (fixed via CSS) and bottom (in-flow) paginators
    must exist in the layout template.
    """
    src = _layout_template()
    # Count opening `<div class="pagination` occurrences inside the body
    # section. Both top + bottom variants begin with this prefix.
    count = src.count('<div class="pagination')
    assert count >= 2, (
        f"Expected at least 2 `<div class=\"pagination...\">` blocks in "
        f"cps/templates/layout.html (top + bottom paginator). Found "
        f"{count}. See fork issue #256 (@droM4X)."
    )


def test_layout_has_pagination_bottom_class():
    """The bottom paginator must carry the `pagination-bottom` class so
    its CSS can override the fixed-top positioning of the default
    `.pagination` rule.
    """
    src = _layout_template()
    assert "pagination-bottom" in src, (
        "cps/templates/layout.html must include `class=\"pagination "
        "pagination-bottom\"` on the bottom paginator block so the CSS "
        "can scope the `position: static` override to that copy only. "
        "Without the modifier, the override would apply to the top "
        "paginator too and break the fixed-top behavior."
    )


def test_caliblur_overrides_pagination_bottom_position():
    """The CSS must include a `.pagination-bottom` (or
    `.pagination.pagination-bottom`) rule that undoes the
    `position: fixed` of the default `.pagination` rule, so the bottom
    paginator flows with the document.
    """
    src = _caliblur_css()
    # Look for a CSS rule that targets pagination-bottom AND sets position
    # to something other than fixed (static / relative / unset / auto).
    # Loose match: the modifier name must appear in a selector somewhere.
    assert "pagination-bottom" in src, (
        "cps/static/css/caliBlur.css must include a `.pagination-bottom` "
        "or `.pagination.pagination-bottom` rule that overrides the "
        "default `.pagination { position: fixed }` so the bottom "
        "paginator flows with the document instead of stacking on top "
        "of the fixed-position paginator."
    )
    # Find a rule block that mentions pagination-bottom and confirm it
    # sets position to static.
    pb_idx = src.find("pagination-bottom")
    rule_chunk = src[pb_idx:pb_idx + 400]
    assert "position:" in rule_chunk and "static" in rule_chunk, (
        f"The `.pagination-bottom` rule in caliBlur.css must set "
        f"`position: static` (or similar) to undo the fixed positioning. "
        f"Current rule chunk: {rule_chunk!r}"
    )
