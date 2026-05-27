# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork PR #326 — the admin spinner gif must be
sized at the CSS layer so the bare `<img id="img-spinner">` tags don't
render at the gif's native dimensions.

Background: PR #326 (community contributor @jbelascoain) proposed
swapping `loading-icon.gif` from a 24×24 spinner to a 250×250 spinner
with a nicer animation, but didn't add width/height attributes to the
five `<img>` tags that reference it. Five templates would have rendered
a 250×250 spinner across admin Restart/Status modals, config_db,
config_edit, and cwa_settings — a visual regression.

Fix: pin `#img-spinner` and `#img-spinner2` to 48px in `style.css` so
the rendered size is constant regardless of the underlying gif's
native dimensions. Also drop any inherited `box-shadow` (the original
PR added inline `style="box-shadow: none;"` to admin.html — we
centralise it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE_CSS = REPO_ROOT / "cps" / "static" / "css" / "style.css"
TEMPLATES = REPO_ROOT / "cps" / "templates"


@pytest.fixture(scope="module")
def style_css() -> str:
    assert STYLE_CSS.exists(), f"missing {STYLE_CSS}"
    return STYLE_CSS.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSpinnerCssConstraints:
    def test_img_spinner_has_pinned_width_and_height(self, style_css):
        match = re.search(
            r"#img-spinner\s*,\s*#img-spinner2\s*\{[^}]*\}",
            style_css,
            re.DOTALL,
        )
        assert match, (
            "style.css must define a `#img-spinner, #img-spinner2 { … }` "
            "rule that pins the rendered spinner size. Without it, the "
            "bare <img> tags render at the gif's native dimensions (the "
            "PR #326 visual regression)."
        )
        body = match.group(0)
        assert "width:" in body, body
        assert "height:" in body, body
        # Sanity: pinned size should be small enough that a 250×250 gif
        # gets scaled down (not rendered at full size).
        width_match = re.search(r"width:\s*(\d+)px", body)
        height_match = re.search(r"height:\s*(\d+)px", body)
        assert width_match and int(width_match.group(1)) <= 96, (
            f"pinned width should be ≤96px to avoid the giant-spinner "
            f"regression; got {body!r}"
        )
        assert height_match and int(height_match.group(1)) <= 96, (
            f"pinned height should be ≤96px; got {body!r}"
        )

    def test_img_spinner_drops_inherited_box_shadow(self, style_css):
        """PR #326 added inline `style="box-shadow: none;"` to admin.html
        only. Centralise it on the id so all five callsites get the
        cleanup without inline-style maintenance burden."""
        match = re.search(
            r"#img-spinner\s*,\s*#img-spinner2\s*\{[^}]*\}",
            style_css,
            re.DOTALL,
        )
        assert match, "missing #img-spinner CSS rule"
        body = match.group(0)
        assert "box-shadow" in body and "none" in body.split("box-shadow")[1][:30], (
            f"#img-spinner rule should drop inherited box-shadow; got {body!r}"
        )


@pytest.mark.unit
class TestEveryCalliteCovered:
    """Source-pin: every template that references loading-icon.gif uses
    the #img-spinner / #img-spinner2 id so the CSS constraint applies.
    If a future template adds a bare class-less <img src=loading-icon>
    this test catches it and prompts adding the id (or a class)."""

    def test_all_loading_icon_imgs_use_a_pinned_id(self):
        offenders = []
        for tpl in TEMPLATES.rglob("*.html"):
            body = tpl.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"<img[^>]*loading-icon\.gif[^>]*>", body):
                tag = match.group(0)
                if 'id="img-spinner"' not in tag and 'id="img-spinner2"' not in tag:
                    offenders.append(f"{tpl.relative_to(REPO_ROOT)}: {tag}")
        assert not offenders, (
            "Every <img> tag referencing loading-icon.gif must carry "
            "id=\"img-spinner\" or id=\"img-spinner2\" so the CSS size "
            "constraint applies. Offenders:\n  " + "\n  ".join(offenders)
        )
