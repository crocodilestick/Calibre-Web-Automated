# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #288 (@iroQuai) — the book-detail page cover overflowed its column and
sat off-center on phones.

caliBlur.css ships a global ``.container-fluid img { width: 100%; max-width:
26rem; }`` and loads after detail.html's inline ``<style>``. ``.book-detail-cover
img`` was equal specificity, so the cover image resolved its width against the
26rem cap and overflowed the (200px / max 70%) cover column on phones. The fix
raises specificity with ``.book-detail-main .book-detail-cover img`` so the
image can never exceed its own column, and symmetrizes caliBlur's asymmetric
``.discover`` padding inside the ≤768px media query so the column re-centers.

Template-only change; pinned by source so a future edit can't silently drop the
specificity bump or the centering rule.
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(__file__)
DETAIL = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "templates", "detail.html")
)


def _src():
    with open(DETAIL, encoding="utf-8") as fh:
        return fh.read()


def test_cover_img_specificity_beats_caliblur_container_img():
    src = _src()
    # The higher-specificity rule that caps the cover image to its own column.
    m = re.search(
        r"\.book-detail-main\s+\.book-detail-cover\s+img\s*\{([^}]*)\}", src
    )
    assert m, ".book-detail-main .book-detail-cover img rule is missing"
    body = m.group(1)
    assert "max-width: 100%" in body, "cover img must cap at 100% of its column"


def test_discover_padding_symmetrized_on_mobile():
    src = _src()
    # The mobile media query re-centers the detail column by symmetrizing
    # caliBlur's asymmetric .discover padding.
    assert "div.discover {" in src
    assert re.search(r"padding-left:\s*12px\s*!important", src)
    assert re.search(r"padding-right:\s*12px\s*!important", src)


def test_phone_stack_is_tightened():
    src = _src()
    # The ≤600px compaction pass that brings the description closer to the fold.
    assert "font-size: 2.2rem" in src, "phone title size not reduced"
