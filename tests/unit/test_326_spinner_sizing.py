# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the pure-CSS spinner introduced in PR #384.

Background: PR #326 proposed replacing loading-icon.gif with a larger
(250×250) gif. That was blocked because the bare <img> tags rendered at
native resolution. PR #384 replaces ALL loading gifs with a pure-CSS
.css-spinner ring: no image file involved, crisp at any DPI, theme-aware
via --color-primary, and prefers-reduced-motion aware.

These tests pin the CSS contract so a future change cannot silently
regress to a pixelated gif or an unsized element.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE_CSS  = REPO_ROOT / "cps" / "static" / "css" / "style.css"
MAIN_CSS   = REPO_ROOT / "cps" / "static" / "css" / "main.css"
VIEWER_CSS = REPO_ROOT / "cps" / "static" / "css" / "libs" / "viewer.css"
TEMPLATES  = REPO_ROOT / "cps" / "templates"


@pytest.fixture(scope="module")
def style_css() -> str:
    assert STYLE_CSS.exists(), f"missing {STYLE_CSS}"
    return STYLE_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_css() -> str:
    assert MAIN_CSS.exists(), f"missing {MAIN_CSS}"
    return MAIN_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def viewer_css() -> str:
    assert VIEWER_CSS.exists(), f"missing {VIEWER_CSS}"
    return VIEWER_CSS.read_text(encoding="utf-8")


def _spinner_block(css: str, selector: str) -> str:
    """Return the rule body for *selector* or '' if not found."""
    m = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.DOTALL)
    return m.group(1) if m else ""


@pytest.mark.unit
class TestCssSpinnerContract:
    """The .css-spinner ring must be correctly sized, coloured and animated
    in every stylesheet that has spinners."""

    def test_style_css_defines_css_spinner(self, style_css):
        body = _spinner_block(style_css, ".css-spinner")
        assert body, ".css-spinner rule is missing from style.css"

    def test_style_css_spinner_size_is_reasonable(self, style_css):
        body = _spinner_block(style_css, ".css-spinner")
        w = re.search(r"width:\s*(\d+)px", body)
        h = re.search(r"height:\s*(\d+)px", body)
        assert w and h, f".css-spinner must declare width and height; got: {body!r}"
        assert 16 <= int(w.group(1)) <= 96, f"width should be 16–96px; got {w.group(1)}px"
        assert 16 <= int(h.group(1)) <= 96, f"height should be 16–96px; got {h.group(1)}px"

    def test_style_css_spinner_self_centers(self, style_css):
        """The flash blocks (config_db / config_edit / cwa_settings) put the
        spinner inside `.text-center` parents, which only center INLINE
        content. A block-level .css-spinner therefore needs auto horizontal
        margins (or it hugs the alert's left edge)."""
        body = _spinner_block(style_css, ".css-spinner")
        centered = (
            re.search(r"margin-left:\s*auto", body)
            and re.search(r"margin-right:\s*auto", body)
        ) or re.search(r"margin:[^;]*auto", body) or "inline-block" in body
        assert centered, (
            f".css-spinner must self-center (auto margins or inline-block); got: {body!r}"
        )

    def test_style_css_spinner_uses_primary_color(self, style_css):
        body = _spinner_block(style_css, ".css-spinner")
        assert "border-top-color" in body and "--color-primary" in body, (
            ".css-spinner must set border-top-color to var(--color-primary…) "
            f"so it follows the theme; got: {body!r}"
        )

    def test_style_css_spinner_has_rotate_keyframe(self, style_css):
        assert "@keyframes css-spinner-rotate" in style_css, (
            "style.css must define @keyframes css-spinner-rotate"
        )

    def test_style_css_spinner_respects_reduced_motion(self, style_css):
        assert "prefers-reduced-motion" in style_css and "css-spinner" in (
            style_css.split("prefers-reduced-motion")[1][:200]
        ), "style.css must have a prefers-reduced-motion block for .css-spinner"

    def test_main_css_defines_css_spinner(self, main_css):
        """The reader page only loads main.css, not style.css."""
        body = _spinner_block(main_css, ".css-spinner")
        assert body, ".css-spinner rule is missing from main.css (required for the reader page)"

    def test_main_css_spinner_uses_primary_color(self, main_css):
        body = _spinner_block(main_css, ".css-spinner")
        assert "border-top-color" in body and "--color-primary" in body, (
            "main.css .css-spinner must follow --color-primary"
        )

    def test_main_css_spinner_respects_reduced_motion(self, main_css):
        assert "prefers-reduced-motion" in main_css and "css-spinner" in (
            main_css.split("prefers-reduced-motion")[1][:200]
        ), "main.css must have a prefers-reduced-motion block for .css-spinner"

    def test_viewer_css_pdf_spinner_uses_css(self, viewer_css):
        """PDF viewer page spinner must be CSS-based, not a gif."""
        assert "loadingIcon" in viewer_css, "PDF loading selector missing from viewer.css"
        assert "border-top-color" in viewer_css, (
            "PDF spinner in viewer.css should be a CSS ring (border-top-color), not a gif"
        )
        assert "--color-primary" in viewer_css, (
            "PDF spinner in viewer.css must follow --color-primary"
        )

    def test_viewer_css_pdf_spinner_respects_reduced_motion(self, viewer_css):
        # viewer.css may have several prefers-reduced-motion blocks; check
        # that at least one of them references loadingIcon.
        blocks = viewer_css.split("prefers-reduced-motion")
        has_block = any("loadingIcon" in part[:300] for part in blocks[1:])
        assert has_block, (
            "viewer.css must have a prefers-reduced-motion block for "
            ".pdfViewer .page.loadingIcon::after"
        )


@pytest.mark.unit
class TestNoGifSpinners:
    """No template should reference loading-icon.gif or loader.gif anymore.
    All spinners are now pure-CSS .css-spinner elements."""

    def test_no_templates_reference_loading_icon_gif(self):
        offenders = []
        for tpl in TEMPLATES.rglob("*.html"):
            body = tpl.read_text(encoding="utf-8", errors="ignore")
            if "loading-icon.gif" in body:
                offenders.append(str(tpl.relative_to(REPO_ROOT)))
        assert not offenders, (
            "These templates still reference loading-icon.gif — replace with "
            "<div class=\"css-spinner\">:\n  " + "\n  ".join(offenders)
        )

    def test_no_templates_reference_loader_gif(self):
        offenders = []
        for tpl in TEMPLATES.rglob("*.html"):
            body = tpl.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'src=["\'][^"\']*loader\.gif', body):
                offenders.append(str(tpl.relative_to(REPO_ROOT)))
        assert not offenders, (
            "These templates still reference loader.gif — replace with "
            "<div class=\"css-spinner\">:\n  " + "\n  ".join(offenders)
        )

    def test_no_templates_use_old_img_spinner_ids(self):
        """The old #img-spinner / #img-spinner2 ids were on <img> elements
        and are now gone; any reappearance is a regression."""
        offenders = []
        for tpl in TEMPLATES.rglob("*.html"):
            body = tpl.read_text(encoding="utf-8", errors="ignore")
            if 'id="img-spinner"' in body or 'id="img-spinner2"' in body:
                offenders.append(str(tpl.relative_to(REPO_ROOT)))
        assert not offenders, (
            "These templates still use the old #img-spinner / #img-spinner2 "
            "ids — replace with <div class=\"css-spinner\">:\n  "
            + "\n  ".join(offenders)
        )

    def test_spinner_templates_use_css_spinner_class(self):
        """Templates that previously had an <img> spinner must now use .css-spinner."""
        expected = {
            "cps/templates/admin.html",
            "cps/templates/config_db.html",
            "cps/templates/config_edit.html",
            "cps/templates/cwa_settings.html",
            "cps/templates/read.html",
        }
        missing = []
        for rel in expected:
            tpl = REPO_ROOT / rel
            if not tpl.exists():
                continue
            body = tpl.read_text(encoding="utf-8", errors="ignore")
            if "css-spinner" not in body:
                missing.append(rel)
        assert not missing, (
            "These templates are missing the .css-spinner element:\n  "
            + "\n  ".join(missing)
        )
