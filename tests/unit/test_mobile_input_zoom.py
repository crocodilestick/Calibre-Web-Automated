"""Regression: form inputs are pinned to 16px on phones so iOS Safari does not
auto-zoom the page when an input is focused (operator #25 — the navbar Search
box was the most visible offender).

iOS Safari zooms in on focus whenever the focused control's font-size is below
16px. caliBlur.css ships `.form-control { font-size: 13px !important }`, which is
under that threshold, so tapping Search zoomed the layout. `mobile-input-zoom.css`
overrides inputs to 16px on phones (<=767px) and MUST be linked after caliBlur.css
in layout.html so the override wins the cascade; `#query` is pinned by ID so the
navbar search wins regardless of later stylesheets.

Source-pins: RED on main (CSS file + link absent), GREEN on this branch.
"""
import os

HERE = os.path.dirname(__file__)
CSS = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "static", "css", "mobile-input-zoom.css")
)
LAYOUT = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "templates", "layout.html")
)


def test_css_pins_phone_inputs_to_16px():
    with open(CSS, encoding="utf-8") as fh:
        src = fh.read()
    assert "@media (max-width: 767px)" in src, "must be phone-only"
    # !important is required to beat caliBlur's `.form-control { font-size: 13px !important }`.
    assert "font-size: 16px !important" in src
    # The navbar search must be pinned by ID so it wins on specificity.
    assert "#query" in src
    # And cover the generic input surface, not just #query.
    assert ".form-control" in src


def test_layout_links_css_after_caliblur():
    with open(LAYOUT, encoding="utf-8") as fh:
        src = fh.read()
    assert "mobile-input-zoom.css" in src, "stylesheet must be linked in the base template"
    cb = src.index("caliBlur.css")
    miz = src.index("mobile-input-zoom.css")
    assert cb < miz, "mobile-input-zoom.css must load AFTER caliBlur.css to win the cascade"
