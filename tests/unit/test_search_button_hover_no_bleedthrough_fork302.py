# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance test for fork #302 — navbar search button text bleed-through.

Reporter @droM4X (v4.0.127) observed:

1. Hovering the navbar search button revealed the letters "CH" (tail of
   the word "SEARCH") in white behind the magnifying-glass icon. The
   button is meant to be icon-only.

2. The button label on `/advsearch` rendered as the title-case string
   "Search" while the navbar showed uppercase "SEARCH" (when the bleed-
   through made it visible). Inconsistent casing between the two pages.

Root cause: in ``cps/static/css/caliBlur.css``:

- The navbar submit button has ``color: transparent`` to hide its text
  so only the ``:before`` icon shows. On ``:hover`` the color flipped to
  ``#fff``, revealing the underlying "SEARCH" text glyphs that were
  meant to stay invisible.
- ``.btn { text-transform: uppercase }`` (global caliBlur rule) was
  overridden on the advanced search page by ``.advanced_search .btn {
  text-transform: none }``, so the same i18n string ``_('Search')``
  rendered uppercase in the navbar and title-case on /advsearch.

Fix:
- Hover rule keeps ``color: transparent`` so the text never leaks.
- Remove the ``.advanced_search .btn { text-transform: none }`` casing
  override so both pages render the button label with the same global
  uppercase rule. (Only the submit button on /advsearch shows text;
  the other ``.btn`` elements there are icon-only delete buttons, so
  the change is visually limited to the submit button casing.)
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CALIBLUR_CSS = REPO_ROOT / "cps" / "static" / "css" / "caliBlur.css"


def _css():
    return CALIBLUR_CSS.read_text(encoding="utf-8")


_NAVBAR_BUTTON_HOVER_RE = re.compile(
    r"body\s*>\s*div\.navbar\.navbar-default\.navbar-static-top\s*>\s*div\s*>\s*"
    r"form\s*>\s*div\s*>\s*span\s*>\s*button:hover\s*\{([^}]*)\}",
    re.IGNORECASE,
)


def test_navbar_search_button_hover_keeps_text_transparent():
    """The :hover rule on the navbar search button must keep the text
    transparent. The previous rule set ``color: #fff`` which revealed
    the underlying "SEARCH" text glyphs behind the magnifying-glass
    icon — that's exactly what @droM4X saw as "CH" in the screenshot.
    """
    css = _css()
    match = _NAVBAR_BUTTON_HOVER_RE.search(css)
    assert match is not None, (
        "Could not find the navbar search button :hover rule in "
        "caliBlur.css. Either the selector changed or the rule was "
        "removed entirely — if removed, the bleed-through on hover "
        "may have regressed via a different code path."
    )
    body = match.group(1)
    # The body must declare color: transparent (case-insensitive, with
    # optional !important). It must NOT declare color: #fff / white /
    # any visible value, which would re-introduce the bleed-through.
    assert re.search(r"color\s*:\s*transparent\b", body, re.IGNORECASE), (
        "The navbar search button :hover rule must keep `color: "
        "transparent` so the underlying 'SEARCH' text never leaks "
        "through the icon. (Fork issue #302, reporter @droM4X.)\n"
        f"Current rule body: {body!r}"
    )
    assert not re.search(r"color\s*:\s*(?:#[0-9a-f]{3,8}|white|rgb)", body, re.IGNORECASE), (
        "The navbar search button :hover rule must not set a visible "
        "color — that re-introduces the bleed-through that @droM4X "
        "reported in fork issue #302. The button is icon-only by "
        f"design; hover affordance lives elsewhere.\nRule body: {body!r}"
    )


_ADV_SEARCH_BTN_OVERRIDE_RE = re.compile(
    r"\.advanced_search\s+\.btn\s*\{[^}]*text-transform\s*:\s*none\b",
    re.IGNORECASE,
)


def test_advanced_search_page_does_not_override_btn_casing():
    """The page-scoped ``.advanced_search .btn { text-transform: none }``
    override is gone. With the global ``.btn { text-transform:
    uppercase }`` rule reaching the /advsearch submit button, both the
    navbar and the advanced-search page render the same i18n string
    with the same casing.

    Note: this is a casing-consistency pin. If a future refactor wants
    to ship lowercase button labels theme-wide, that change should
    update the global ``.btn`` rule, not re-introduce a page-scoped
    override that drifts from the navbar.
    """
    css = _css()
    match = _ADV_SEARCH_BTN_OVERRIDE_RE.search(css)
    assert match is None, (
        "Found `.advanced_search .btn { text-transform: none }` in "
        "caliBlur.css. This page-scoped override was the source of the "
        "casing inconsistency @droM4X reported in fork issue #302 — "
        "the navbar showed 'SEARCH' (theme-wide uppercase) while "
        "/advsearch showed 'Search' (override). Remove the override so "
        "both pages use the global uppercase rule, or relax the global "
        "rule if lowercase is the new direction. Don't drift the two."
    )
