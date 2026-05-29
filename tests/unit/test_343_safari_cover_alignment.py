# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression test for fork issue #343 (@Oakwhisper).

On Safari/WebKit (desktop AND mobile) the book covers on the main books
grid overlapped the title text — there was no spacing between the bottom
of the cover art and the top of the title, and the hover-shading overlay
appeared misaligned. Chromium rendered the grid correctly.

Root cause: the cover anchor `#books > .cover > a` (and the random/isotope
variants) is `display: inline-block` with no `vertical-align`, so it
defaults to `baseline`. It wraps a block-level `<img>`. WebKit's baseline/
descender computation for an inline-block-wrapping-a-block places the
following `.meta` block ~7px too high, so the title overlaps the cover.
Chromium reserves +10px of spacing for the same markup.

Measured before the fix (cwn-local, Playwright):
  WebKit desktop  cover->title gap = -7px   (title overlaps cover)
  WebKit mobile   cover->title gap = -6px
  Chromium        cover->title gap = +10px  (correct)

Fix: add `vertical-align: top` to the cover-anchor inline-block rule.
After the fix all three engines/viewports measure +10px. Setting
vertical-align removes the baseline dependency that WebKit and Chromium
disagreed on.

This source-pin ties the fix to the exact rule. If a future refactor
drops `vertical-align` from the cover anchor, the Safari overlap returns
and this test trips. The behavioural proof is the cross-engine Playwright
measurement (documented in the PR + scripts/manual/measure_cover_grid.py);
this unit test is the CI-runnable guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CALIBLUR = REPO_ROOT / "cps" / "static" / "css" / "caliBlur.css"


@pytest.fixture(scope="module")
def caliblur() -> str:
    assert CALIBLUR.exists(), f"missing {CALIBLUR}"
    return CALIBLUR.read_text(encoding="utf-8")


def _rule_blocks(css: str):
    """Yield (selector, body) for each top-level rule block. Good enough
    for flat rules (no nested at-rules) which is all we inspect here."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.group(1).strip(), m.group(2).strip()


@pytest.mark.unit
class TestSafariCoverAnchorAlignment:
    def test_cover_anchor_inline_block_rule_sets_vertical_align_top(self, caliblur):
        """The rule that makes the cover anchor `display: inline-block`
        must also set `vertical-align: top`, otherwise it defaults to
        baseline and Safari overlaps the title over the cover (#343)."""
        candidates = []
        for selector, body in _rule_blocks(caliblur):
            # The cover anchor BOX rule targets `.cover > a`, declares the
            # inline-block, and sizes it (height:100%). Exclude the
            # pseudo rules (:before glyph, :after overlay, :hover) — those
            # also use inline-block but aren't the layout anchor.
            if ".cover > a" not in selector:
                continue
            if re.search(r":(before|after|hover)\b", selector):
                continue
            if "inline-block" in body and re.search(r"height\s*:\s*100%", body):
                candidates.append((selector, body))
        assert candidates, (
            "Could not find the cover-anchor `display: inline-block` rule "
            "(selector containing '.cover > a'). The grid markup or CSS "
            "structure changed — re-derive the #343 fix location."
        )
        # At least one such rule must declare vertical-align: top.
        offenders = [
            sel[:80] for sel, body in candidates
            if not re.search(r"vertical-align\s*:\s*top", body)
        ]
        assert not offenders, (
            "The cover-anchor inline-block rule(s) must declare "
            "`vertical-align: top` so Safari/WebKit doesn't overlap the "
            "title over the cover art (#343 @Oakwhisper). Without it the "
            "inline-block defaults to baseline and WebKit pulls the title "
            "~7px up into the cover. Offending rule(s):\n  "
            + "\n  ".join(offenders)
        )

    def test_no_regression_height_and_display_preserved(self, caliblur):
        """Defensive: the fix must ADD vertical-align, not replace the
        existing display:inline-block / height:100% that the layout
        depends on."""
        for selector, body in _rule_blocks(caliblur):
            if ".cover > a" in selector and "vertical-align" in body and "top" in body:
                assert "inline-block" in body, (
                    "cover-anchor rule lost its display:inline-block — "
                    "the grid layout depends on it"
                )
                assert re.search(r"height\s*:\s*100%", body), (
                    "cover-anchor rule lost height:100% — the hover "
                    "overlay sizing depends on it"
                )
                return
        pytest.fail(
            "No cover-anchor rule with vertical-align:top found — the "
            "#343 fix is missing (see test above)."
        )
