# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork #222 verification-feedback follow-up
(@droM4X).

v4.0.91 removed the Switch Theme icon from the top bar but the
once-per-day flash banner ("Theme switching is temporarily disabled
until v5.0.0") kept firing on the first page load of the day. With
the icon gone, the banner became orphaned context — confused users
because there was nothing visible to be "disabled". droM4X confirmed
the icon removal worked but asked for the residual banner to go.

This fix turns ``theme_migration_notification`` into a no-op. The
function shape (no-arg, returns None) is preserved so the call site
in ``render_title_template`` doesn't change shape and the function
can be re-purposed for a future migration banner without rewiring.

Pins:

1. ``theme_migration_notification`` exists and is callable.
2. Calling it does NOT call ``flash(...)`` — no banner emission.
3. The function body does NOT contain ``flash(`` (source-pin so a
   future refactor that adds the call back would need an explicit
   policy decision).
4. The CWA fork comment marker is present so future code archaeology
   finds the rationale.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_PY = REPO_ROOT / "cps" / "render_template.py"


def _render_source() -> str:
    return RENDER_PY.read_text()


def _extract_fn_source(name: str) -> str:
    src = _render_source()
    match = re.search(
        rf"^def {name}\(.*?\n(?P<body>(?:[ \t].*\n)+)",
        src,
        re.MULTILINE,
    )
    assert match, f"Could not locate function {name}"
    return match.group("body")


def test_theme_migration_notification_is_noop_in_source():
    """The function body must not call ``flash(...)`` — that's the
    user-visible banner droM4X asked us to remove on fork #222."""
    body = _extract_fn_source("theme_migration_notification")
    assert "flash(" not in body, (
        f"theme_migration_notification must not call flash(). "
        f"Restoring the banner needs an explicit policy decision; "
        f"droM4X (fork #222) confirmed the icon removal but asked "
        f"for the residual banner to go. Body: {body!r}"
    )


def test_theme_migration_notification_anchor_comment_present():
    """A search anchor referencing fork #222 lets future code
    archaeology find the rationale for the no-op."""
    src = _render_source()
    # Find the immediate context above the def. The comment block
    # introducing the function must reference fork #222 + droM4X so a
    # future refactor knows why this is a no-op.
    match = re.search(
        r"(?P<comment>(?:^#.*\n){2,})def theme_migration_notification",
        src,
        re.MULTILINE,
    )
    assert match, "Expected leading comment block above theme_migration_notification"
    comment = match.group("comment")
    assert ("#222" in comment) or ("fork #222" in comment), (
        f"The comment above theme_migration_notification must reference "
        f"fork #222 so future code archaeology can find the rationale. "
        f"Got: {comment!r}"
    )


def test_theme_migration_notification_calling_emits_no_flash():
    """End-to-end exercise: import the function and confirm calling it
    inside a patched flash() context yields zero flash calls."""
    from cps import render_template

    with patch("cps.render_template.flash") as mock_flash:
        render_template.theme_migration_notification()
    assert mock_flash.call_count == 0, (
        f"theme_migration_notification must not emit any flash() — "
        f"got {mock_flash.call_count} call(s). See fork #222 droM4X "
        f"follow-up."
    )


def test_function_signature_preserved():
    """The function shape (zero args, returns None) is preserved so
    the call site in render_title_template doesn't need to change."""
    from cps import render_template

    sig = inspect.signature(render_template.theme_migration_notification)
    assert len(sig.parameters) == 0, (
        f"theme_migration_notification must remain zero-arg so the "
        f"call site in render_title_template stays unchanged. Got "
        f"params: {list(sig.parameters.keys())}"
    )
