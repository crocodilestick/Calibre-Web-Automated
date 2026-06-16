"""Regression: the book-detail page exposes a single prominent "Read" CTA the
full width of the cover, and no longer carries a separate read icon in the
action row.

Operator ask #28: "in the detail view put a 'Read' button under the book that's
the width of the book's icon and serves as the entry for the book reader view.
remove the existing entry in the detail view to declutter that section."

The detail-page layout is styled + structured inline in cps/templates/detail.html,
so these are source-pins. They are RED on main (which ships the read action as a
small `Read in Browser` icon inside `.book-action-bar`, and has no
`.book-cover-column` / `.book-read-cta`) and GREEN on this branch. Paired with
live multi-viewport Playwright verification on the running container.
"""
import os

HERE = os.path.dirname(__file__)
DETAIL = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "templates", "detail.html")
)


def _src():
    with open(DETAIL, encoding="utf-8") as fh:
        return fh.read()


def test_read_cta_and_cover_column_exist():
    src = _src()
    # The new full-width primary Read CTA and the fixed-width cover column wrapper.
    assert 'class="book-read-cta"' in src
    assert 'class="book-cover-column"' in src


def test_read_cta_sits_inside_cover_column_under_the_cover():
    src = _src()
    col = src.index('class="book-cover-column"')
    cta = src.index('class="book-read-cta"')
    meta = src.index('class="book-detail-meta"')
    # CTA is rendered inside the cover column (so it stacks under the cover at the
    # cover's width), strictly before the metadata column begins.
    assert col < cta < meta, "Read CTA must live in the cover column, before the meta block"


def test_read_cta_targets_the_in_browser_reader():
    src = _src()
    cta = src.index('class="book-read-cta"')
    block = src[cta:src.index("</a>", cta)]
    # Same navigation semantics as the old icon: first readable format -> reader view.
    assert "url_for('web.read_book'" in block
    assert "reader_list[0]" in block


def test_read_cta_is_full_cover_width():
    src = _src()
    css = src.index(".book-read-cta {")
    block = src[css:src.index("}", css)]
    assert "width: 100%" in block, "Read CTA must fill the cover column (= cover width)"


def test_old_read_icon_removed_from_action_row():
    src = _src()
    # The only user of the `Read in Browser` label was the action-row icon we removed.
    assert "Read in Browser" not in src
