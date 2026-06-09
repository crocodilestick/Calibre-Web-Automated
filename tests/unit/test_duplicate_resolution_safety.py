# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate-resolution data-safety regression pins.

The duplicate resolve/merge path is destructive (it deletes books). These pins
guard the data-safety invariants found in the 2026-06 audit
(notes/duplicate-detection-fix-plan.md). Behavioural reproduction of the live
flows runs on cwn-local against the real same-title pairs; these source-pins
lock the structural invariants so a refactor can't silently reintroduce a bug.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
DUP_SRC = (REPO_ROOT / "cps" / "duplicates.py").read_text()


def _func_src(name: str) -> str:
    """Slice a top-level function's source out of duplicates.py by text."""
    lines = DUP_SRC.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(f"def {name}(")), None)
    assert start is not None, f"def {name}( not found in duplicates.py"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(def |class |@)", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


class TestD1SharedSessionNotClosed:
    def test_auto_resolve_does_not_close_shared_session(self):
        # D1: auto_resolve_duplicates runs from request contexts (preview /
        # execute-resolution) AND the background TaskDuplicateScan thread. It must
        # NOT close the shared module-level calibre_db.session in a finally —
        # doing so detaches objects mid-operation for any concurrent context
        # (DetachedInstanceError) and can abort a delete partway through a group.
        src = _func_src("auto_resolve_duplicates")
        assert "calibre_db.session.close()" not in src, (
            "auto_resolve_duplicates must not close the shared scoped "
            "calibre_db.session — its lifecycle is owned by the Flask request "
            "teardown and by TaskDuplicateScan.run() (D1 data-safety)"
        )
