"""Regression: the Edit Metadata page puts the form first on phones — fork #32
(follow-up to #26).

The page is a two-column layout: a cover/convert/upload column (col-sm-3) and the
metadata form (col-sm-9, offset right on desktop via an inline margin-left). In DOM
order the cover column comes first, so on phones — where the columns stack — you had
to scroll past the cover to reach the title/author fields.

The two columns are now wrapped in `.cwa-editbook-layout`:
  - desktop: `display: flow-root` (contains the floated columns; no collapse, layout
    unchanged);
  - phones (<=767px): a flex column with the form pulled first (`order: -1`).

Source-pins. RED on main, GREEN here. Paired with live Playwright verification
(desktop layout unchanged; mobile form-first).
"""
import os

HERE = os.path.dirname(__file__)
EDIT = os.path.normpath(os.path.join(HERE, "..", "..", "cps", "templates", "book_edit.html"))


def _src():
    with open(EDIT, encoding="utf-8") as fh:
        return fh.read()


def test_layout_wrapper_present():
    src = _src()
    assert 'class="cwa-editbook-layout"' in src
    # Proper flexbox two-column layout, replacing the fragile margin-left: 40rem hack.
    assert ".cwa-editbook-layout { display: flex;" in src
    # The legacy Bootstrap float on the form's inner column is neutralized.
    assert "float: none !important;" in src


def test_form_pulled_first_on_phones():
    src = _src()
    assert "@media (max-width: 767px)" in src
    # On phones the form is pulled above the cover column.
    assert "order: -1;" in src


def test_wrapper_encloses_both_columns():
    src = _src()
    wrap = src.index('class="cwa-editbook-layout"')
    cover = src.index('class="editbook-cover-section')
    form = src.index('id="book_edit_frm"')
    # Wrapper opens before the cover column; DOM order is still cover-then-form
    # (the reorder is CSS-only), so the visual flip is purely the media query.
    assert wrap < cover < form
