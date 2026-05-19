# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance test for fork #222 — remove the disabled theme switcher link.

Reporter @droM4X observed that the header had a "Switch Theme" link
rendered with `class="disabled"` + reduced opacity + `cursor: not-allowed`
+ `onclick: return false` + a "Temporarily disabled until v5.0.0" tooltip.
Visually present but inert. It only added clutter and confused users.

This test pins that the `<li class="cwa-switch-theme">` block is gone
from ``cps/templates/layout.html``. The backend route in
``cps/cwa_functions.py`` and the supporting JS / CSS stay as dead code
for now (will be cleaned up when v5.0.0's theme system lands or never
— either way, they don't render anything user-visible).
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _layout_template():
    return (REPO_ROOT / "cps" / "templates" / "layout.html").read_text()


def test_layout_does_not_render_disabled_theme_switcher_link():
    """The `<li class="cwa-switch-theme">` wrapper around the disabled
    Switch Theme link must not be present in the navbar template.

    The previous markup had an `<a id="cwa-switch-theme" href="#"
    class="disabled" ...>Switch Theme</a>` that did nothing but confuse
    users. Reporter @droM4X surfaced it as visual noise.
    """
    src = _layout_template()
    assert 'class="cwa-switch-theme"' not in src, (
        "The disabled theme switcher `<li class=\"cwa-switch-theme\">` "
        "must be removed from cps/templates/layout.html — it was an "
        "inert UI element that only added clutter. (Reporter @droM4X, "
        "fork issue #222.)"
    )


def test_layout_does_not_render_switch_theme_anchor():
    """Belt-and-suspenders: the inert `<a id="cwa-switch-theme">` must
    also be gone. Some operators reuse `id` selectors via custom CSS;
    leaving the anchor would leave a visual breadcrumb.
    """
    src = _layout_template()
    assert 'id="cwa-switch-theme"' not in src, (
        "The inert `<a id=\"cwa-switch-theme\">` anchor must be removed "
        "from cps/templates/layout.html. If you're hiding it via CSS "
        "instead, undo that — the element should not render."
    )


def test_layout_does_not_emit_disabled_until_v5_tooltip():
    """The placeholder tooltip text 'Temporarily disabled until v5.0.0'
    is gone. Pinning it explicitly so a future refactor can't sneak the
    inert element back in under a different selector.
    """
    src = _layout_template()
    assert "Temporarily disabled until v5.0.0" not in src, (
        "The 'Temporarily disabled until v5.0.0' tooltip text must be "
        "removed. If the theme switcher returns, ship it as a working "
        "feature, not as a disabled placeholder."
    )


def test_navbar_does_not_render_switch_theme_label():
    """The `{{_('Switch Theme')}}` label inside the inert link is gone.

    Note: this asserts the LABEL inside the specific layout.html context
    (not the existence of the gettext string elsewhere) — checks that
    the disabled switch entry doesn't render its translated label.
    """
    src = _layout_template()
    # Scope the check to the navbar area — the previous element was
    # under the `<li class="cwa-switch-theme">` wrapper inside the top-
    # level <ul class="nav navbar-nav"> block.
    assert "{{_('Switch Theme')}}" not in src, (
        "The translated 'Switch Theme' label that lived in the inert "
        "header element must be removed. If theme switching ships in a "
        "later release, re-introduce the string via a working route."
    )
