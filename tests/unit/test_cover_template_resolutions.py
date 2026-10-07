# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Regression guard for templates that render a single book cover without a
`srcset` fallback.

cps/templates/image.html's book_cover macro (used by the main library grid,
search, author, and shelf views) pairs a `resolution='og'` <img src> with a
`srcset` offering `sm`/`md`/`lg` -- browsers that support srcset (virtually
all of them) never fetch the src fallback at all, so `og` there is mostly
harmless.

The templates covered here have no such srcset, so if they ever regress to
requesting `resolution='og'` (COVER_THUMBNAIL_ORIGINAL, which is falsy) or
no resolution at all, every render hits get_book_cover_internal()'s
`if resolution:` check and falls back to serving the raw, uncached cover.jpg
on every single load. Checked as plain text rather than rendered -- no
Flask app/DB context needed, matching this project's other file-content
based unit tests.

Note: cps/templates/book_edit.html deliberately keeps `resolution='og'`
(see its own "Always use full-sized image for the book edit page" comment)
and is intentionally not covered here.
"""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "cps" / "templates"

# path -> (line-matching substring, required resolution)
EXPECTATIONS = {
    "shelf_order.html": ("entry['Books']['id']", "sm"),
    "listenmp3.html": ("id=\"detailcover\"", "lg"),
}


class TestCoverTemplateResolutions:
    """Guard against these templates regressing to an uncached cover request"""

    @pytest.mark.parametrize("filename,expected", EXPECTATIONS.items())
    def test_get_cover_call_requests_a_cacheable_resolution(self, filename, expected):
        marker, resolution = expected
        content = (TEMPLATES_DIR / filename).read_text(encoding="utf-8")

        matching_lines = [line for line in content.splitlines() if marker in line and "web.get_cover" in line]
        assert matching_lines, f"expected a web.get_cover call containing {marker!r} in {filename}"

        for line in matching_lines:
            assert f"resolution='{resolution}'" in line, (
                f"{filename}: expected resolution='{resolution}', got: {line.strip()}"
            )

    def test_detail_html_requests_large_resolution(self):
        content = (TEMPLATES_DIR / "detail.html").read_text(encoding="utf-8")

        og_image_lines = [line for line in content.splitlines() if "og:image" in line]
        cover_img_lines = [
            line for line in content.splitlines()
            if "web.get_cover" in line and "book-detail-cover" not in line and re.search(r'src="', line)
        ]

        assert og_image_lines, "expected an og:image meta tag in detail.html"
        assert any("resolution='lg'" in line for line in og_image_lines), (
            "detail.html og:image meta tag should request resolution='lg'"
        )

        assert cover_img_lines, "expected a displayed cover <img> in detail.html"
        assert any("resolution='lg'" in line for line in cover_img_lines), (
            "detail.html displayed cover <img> should request resolution='lg'"
        )

    def test_book_edit_html_intentionally_keeps_original_resolution(self):
        """book_edit.html has an explicit comment choosing full-sized/original
        images on purpose -- this test documents that choice so a future
        cleanup pass doesn't "fix" it by mistake."""
        content = (TEMPLATES_DIR / "book_edit.html").read_text(encoding="utf-8")

        assert "Always use full-sized image for the book edit page" in content
        assert "resolution='og'" in content


# ============================================================================
# Test Markers
# ============================================================================

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit
