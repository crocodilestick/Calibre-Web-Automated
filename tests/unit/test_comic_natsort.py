# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Backport of janeczku/calibre-web #3504 (@lb803) — natural sort of
comic archive page names before cover extraction.

Background. ``cps/comic.py:_extract_cover_from_archive`` walks
``cf.namelist()`` for CBZ/CBT/CBR/CB7 archives and picks the first
entry with a known image extension as the cover. Two problems:

1. Stock CW + our fork iterated ``cf.namelist()`` in archive order,
   which for many tools is insertion order — i.e. arbitrary. If the
   page-001 image isn't first in the zip, the cover gets picked from
   some random interior page.
2. Even after switching to ``sorted(...)`` (janeczku commit
   ``ecc6e00b``, not in our main), lexicographic sort puts ``page10``
   before ``page2``. For most multi-digit comic series the picked
   cover is wrong.

Janeczku PR #3504 (@lb803) added ``natsort.natsorted`` as a sort
function with a ``sorted`` fallback when natsort can't be imported.
This file pins:

1. The natsort fallback import is registered.
2. All four archive-format branches (CBZ/CBT/CBR/CB7) use ``sort(...)``
   (the natsort-or-fallback alias), not bare iteration or bare
   ``sorted(...)``.
3. Picking the cover from a synthetic archive with ``page10.png`` and
   ``page2.png`` returns ``page2.png`` (natural-order would pick
   page2 first).

Natsort is already a hard dependency in ``requirements.txt`` (used by
``cps/web.py`` for the book listing). The fallback exists so a stripped-
down deployment that drops it still gets lexicographic-sorted covers,
which is strictly better than the unsorted status quo.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
COMIC_PY = REPO_ROOT / "cps" / "comic.py"


def _comic_source() -> str:
    return COMIC_PY.read_text()


def test_natsort_import_with_fallback():
    """The module must `try: from natsort import natsorted as sort`
    with a `sorted` fallback in the except branch."""
    src = _comic_source()
    assert re.search(
        r"try:\s*\n\s*from\s+natsort\s+import\s+natsorted\s+as\s+sort",
        src,
    ), (
        "cps/comic.py must `from natsort import natsorted as sort` "
        "in a try/except so the four `sort(cf.namelist())` callsites "
        "below resolve to natural sort when natsort is available."
    )
    # The except branch must alias `sort` to the stdlib `sorted` so
    # the rest of the file doesn't need to branch.
    sort_block = re.search(
        r"try:[^\n]*\n\s*from\s+natsort[^\n]+\n([\s\S]+?)(?:\ntry:|\nlog\b|\ndef\b|\Z)",
        src,
    )
    assert sort_block, "natsort try/except block not found"
    assert "sort = sorted" in sort_block.group(1), (
        "The except branch must fall back to `sort = sorted` so the "
        "four callsites below still produce a deterministic order "
        "even when natsort is not installed."
    )


def test_all_four_archive_loops_use_sort_alias():
    """CBZ uses `zipfile.namelist()`, CBT uses `tarfile.getnames()`,
    CBR uses `rarfile.namelist()`, CB7 uses `py7zr.getnames()`. All
    four must be wrapped in `sort(...)`."""
    src = _comic_source()
    # Loose contract: at least one `sort(cf.namelist())` and one
    # `sort(cf.getnames())`. Stricter: 4 total `sort(cf.*())` calls.
    sort_calls = re.findall(r"sort\(cf\.(?:namelist|getnames)\(\)\)", src)
    assert len(sort_calls) >= 4, (
        f"cps/comic.py must wrap all four CBZ/CBT/CBR/CB7 archive "
        f"iteration sites in `sort(cf.namelist())` or "
        f"`sort(cf.getnames())`. Found {len(sort_calls)}: {sort_calls}. "
        f"See janeczku PR #3504 (@lb803)."
    )
    # Negative pin: no bare `for name in cf.namelist():` or
    # `for name in cf.getnames():` should remain (they imply unsorted
    # iteration, the pre-fix state).
    bare = re.findall(
        r"for name in cf\.(?:namelist|getnames)\(\):",
        src,
    )
    assert not bare, (
        f"Found {len(bare)} bare `for name in cf.namelist()/getnames():` "
        f"iterations — each must be `for name in sort(cf...)` so the "
        f"cover extraction picks the right page. See #3504."
    )


def test_extract_cover_picks_page2_over_page10():
    """End-to-end behavioral test on a synthetic CBZ — without natural
    sort, lexicographic ordering picks ``page10.png`` before
    ``page2.png``. With natsort, ``page2.png`` wins."""
    pytest.importorskip("natsort")

    # Build a synthetic CBZ with page filenames inserted out of order
    # (page10, page2, page1) so neither insertion-order nor lex-sort
    # picks the right cover.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("page10.png", b"\x89PNG\r\n\x1a\nPAGE-10")
        zf.writestr("page2.png", b"\x89PNG\r\n\x1a\nPAGE-2")
        zf.writestr("page1.png", b"\x89PNG\r\n\x1a\nPAGE-1")

    # Write to a tmp file because _extract_cover_from_archive expects
    # a path.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".cbz", delete=False) as tf:
        tf.write(buf.getvalue())
        tf_path = tf.name

    try:
        from cps.comic import _extract_cover_from_archive
        cover_data, ext = _extract_cover_from_archive(".cbz", tf_path, "")
        assert ext == ".png", f"Expected .png extension, got {ext!r}"
        assert cover_data == b"\x89PNG\r\n\x1a\nPAGE-1", (
            f"Natural sort should pick page1.png as the cover. Got: "
            f"{cover_data!r}. If this gives PAGE-10 the sort is "
            f"lexicographic and the natsort wiring is broken; if it "
            f"gives some other page it's iterating in insertion order."
        )
    finally:
        import os
        os.unlink(tf_path)
