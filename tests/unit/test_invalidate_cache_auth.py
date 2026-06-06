# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for fork issue #370 — /duplicates/invalidate-cache was
missing authentication decorators, leaving it open to unauthenticated POST
requests on internet-facing deployments.

These are structural pin-checks: verify that the decorator lines immediately
preceding ``invalidate_cache`` include both ``@login_required_if_no_ano``
and ``@admin_or_edit_required``, matching the pattern on ``trigger_scan``
directly below it in the same file.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DUPLICATES_SRC = (REPO_ROOT / "cps" / "duplicates.py").read_text()


def _decorator_block_for(fn_name: str, source: str) -> str:
    """Return the decorator lines immediately before `def <fn_name>(`."""
    pattern = rf"((?:^[ \t]*@[^\n]+\n)+)[ \t]*def {fn_name}\("
    match = re.search(pattern, source, re.MULTILINE)
    assert match, f"could not find 'def {fn_name}(' in duplicates.py"
    return match.group(1)


@pytest.mark.unit
class TestInvalidateCacheAuth:
    """Pin that /duplicates/invalidate-cache requires authentication (issue #370)."""

    def test_login_required_decorator_present(self):
        decorators = _decorator_block_for("invalidate_cache", DUPLICATES_SRC)
        assert "@login_required_if_no_ano" in decorators, (
            "invalidate_cache must be decorated with @login_required_if_no_ano "
            "to prevent unauthenticated access (issue #370)"
        )

    def test_admin_or_edit_required_decorator_present(self):
        decorators = _decorator_block_for("invalidate_cache", DUPLICATES_SRC)
        assert "@admin_or_edit_required" in decorators, (
            "invalidate_cache must be decorated with @admin_or_edit_required "
            "to restrict access to privileged users (issue #370)"
        )

    def test_auth_decorators_match_trigger_scan(self):
        """Both endpoints should share the same auth posture."""
        invalidate_decorators = _decorator_block_for("invalidate_cache", DUPLICATES_SRC)
        trigger_decorators = _decorator_block_for("trigger_scan", DUPLICATES_SRC)
        for decorator in ("@login_required_if_no_ano", "@admin_or_edit_required"):
            assert decorator in trigger_decorators, (
                f"baseline broken: trigger_scan is missing {decorator}"
            )
            assert decorator in invalidate_decorators, (
                f"invalidate_cache is missing {decorator} (issue #370)"
            )
