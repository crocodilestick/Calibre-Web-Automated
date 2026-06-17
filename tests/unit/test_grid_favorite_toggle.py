"""Regression: interactive favorite/star toggle on grid covers — fork #33.

Builds on #27 (per-user favorites). Each book cover gets a top-right star button
(mirroring the existing read/edit/send cover quick-actions in caliBlur.js) that
POSTs to /ajax/togglefavorite/<id> and flips in place — so a book can be starred
directly from the main books page without opening its detail page. Injected on ALL
devices (the read/edit/send quick-actions are desktop-hover-only), so it's tappable
on phones too.

Source-pins on caliBlur.js + caliBlur.css. RED on main, GREEN here. Paired with
live Playwright verification (hover→appear→click→toggle without navigating; mobile
tappable).
"""
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_caliblur_js_injects_and_handles_favorite_toggle():
    js = _read("cps", "static", "js", "caliBlur.js")
    assert "favorite-toggle-btn" in js
    assert "function handleFavoriteToggle" in js
    assert "/ajax/togglefavorite/" in js
    # Must be in the click-handler teardown so re-init (resize) doesn't double-bind.
    assert ".send-ereader-btn, .favorite-toggle-btn').off('click.quickActions')" in js


def test_caliblur_css_styles_favorite_toggle_and_hides_static_badge():
    css = _read("cps", "static", "css", "caliBlur.css")
    assert ".favorite-toggle-btn {" in css
    assert ".favorite-toggle-btn.is-favorited" in css
    # The static cover_badges marker is superseded by the interactive toggle.
    assert ".cover-badge-favorite { display: none !important; }" in css
    # Tappable on touch devices (the read/edit/send actions are desktop-only).
    assert "@media (hover: none)" in css
