# -*- coding: utf-8 -*-
"""fork #470 (@sltvtr): the desktop Fetch-Metadata modal footer (Close button)
must stay inside the viewport on long result lists.

On the Edit Book page, the #metaModal results list (#meta-info) can fill its
scroll cap, and the caliBlur theme pushes the whole dialog down (60px padding
on #metaModal + a translateY(10%) transform on the dialog). That ~150px top
offset is larger than the 90px the theme reserves in modal-content's max-height,
so the bounded modal still extended past the bottom of a 907px-tall viewport and
the footer (the only Close button) scrolled off-screen. Zooming the page to 80%
was the user's workaround.

The fix lives in cps/static/css/meta-modal-fit.css: on desktop (>=768px) it
removes that excess top offset for #metaModal so the theme's existing
viewport-relative caps keep header + scrollable results + footer all on screen.

These are structural pin-checks. The behavioral proof (open the modal at
1917x907, search, observe the Close button inside the viewport) is the Playwright
e2e pass on the deployed container, not a unit test.

Critical invariant pinned here: the meta-modal-fit.css <link> must load AFTER
caliBlur.css in layout.html, otherwise the equal-specificity #metaModal
padding-top override loses the cascade and the fix silently regresses.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
CSS = REPO / "cps" / "static" / "css" / "meta-modal-fit.css"
LAYOUT = REPO / "cps" / "templates" / "layout.html"


def _css():
    return CSS.read_text(encoding="utf-8")


def _layout():
    return LAYOUT.read_text(encoding="utf-8")


def test_meta_modal_fit_css_exists_with_rules():
    assert CSS.is_file(), "meta-modal-fit.css must exist"
    src = _css()
    # desktop-scoped so mobile (#288 modal-body cap) is left untouched
    assert "@media (min-width: 768px)" in src, (
        "the fix must be desktop-scoped (>=768px) so mobile keeps the #288 "
        "scrollable-body behavior"
    )
    # removes the excess top offset that pushed the modal past its caps
    assert "#metaModal" in src and "padding-top: 0" in src, (
        "must zero #metaModal padding-top so the dialog isn't pushed down"
    )
    assert "transform: none" in src, (
        "must neutralize the theme's translateY transform on the dialog"
    )


def test_meta_modal_fit_scoped_to_metamodal_only():
    # every selector block must be scoped to #metaModal — no bare .modal rules
    # that would leak into other modals (upload, send-to-ereader, delete, etc.)
    src = _css()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.endswith("{") and not stripped.startswith(("/*", "*", "@")):
            assert "#metaModal" in stripped, (
                f"selector must be scoped to #metaModal, got: {stripped!r}"
            )


def test_layout_links_meta_modal_fit_after_caliblur():
    src = _layout()
    assert "meta-modal-fit.css" in src, "layout.html must link meta-modal-fit.css"
    cali_idx = src.find("caliBlur.css")
    fix_idx = src.find("meta-modal-fit.css")
    assert cali_idx != -1, "layout.html must link caliBlur.css"
    assert fix_idx > cali_idx, (
        "meta-modal-fit.css must be linked AFTER caliBlur.css so its "
        "equal-specificity #metaModal padding-top override wins the cascade "
        "(load order is the fix; reversing it silently regresses #470)"
    )
