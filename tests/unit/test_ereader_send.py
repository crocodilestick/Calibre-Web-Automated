# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork #276 (@magdalar): an admin relaying a book solely
to other users' eReaders must not record it as the admin's own download.

The decision lives in the pure helper `send_includes_own_address`; the route
`send_to_selected_ereaders` gates `ub.update_download` on it. We pin both: the
helper's set semantics, and (by source inspection) that the route keeps the
guard so a future refactor can't silently un-gate the self-download.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_ereader_send():
    """Load cps/services/ereader_send.py directly (no cps package side effects)."""
    module_path = REPO_ROOT / "cps" / "services" / "ereader_send.py"
    spec = importlib.util.spec_from_file_location("ereader_send_under_test", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ereader_send = _load_ereader_send()
send_includes_own_address = ereader_send.send_includes_own_address


@pytest.mark.parametrize(
    "own, selected, expected",
    [
        # The bug: admin relays only to other users -> NOT a self-download.
        ("admin@home.net", "kid@home.net", False),
        ("admin@home.net", "kid@home.net,spouse@home.net", False),
        # Sender included their own address -> IS a self-download.
        ("admin@home.net", "admin@home.net", True),
        ("admin@home.net", "kid@home.net,admin@home.net", True),
        # Case-insensitive + whitespace-tolerant matching.
        ("Admin@Home.net", "admin@home.net", True),
        (" admin@home.net ", "admin@home.net", True),
        ("admin@home.net", " ADMIN@HOME.NET ", True),
        # Multiple own addresses: any match counts.
        ("a@home.net, b@home.net", "b@home.net", True),
        ("a@home.net, b@home.net", "c@home.net", False),
        # No own address configured -> never a self-download.
        (None, "kid@home.net", False),
        ("", "kid@home.net", False),
        ("   ", "kid@home.net", False),
        # Empty selected set -> nothing sent to self.
        ("admin@home.net", "", False),
        ("admin@home.net", None, False),
    ],
)
def test_send_includes_own_address(own, selected, expected):
    assert send_includes_own_address(own, selected) is expected


def test_relay_only_send_is_distinct_from_self_send():
    """The two cases magdalar called out must give opposite answers."""
    relay_only = send_includes_own_address("admin@home.net", "kid@home.net,spouse@home.net")
    sent_to_self = send_includes_own_address("admin@home.net", "admin@home.net,kid@home.net")
    assert relay_only is False
    assert sent_to_self is True


def test_route_guards_update_download_with_helper():
    """Source-pin: send_to_selected_ereaders must keep update_download behind the
    send_includes_own_address guard so the self-download fix can't be silently
    refactored away."""
    web_src = (REPO_ROOT / "cps" / "web.py").read_text(encoding="utf-8")

    # Isolate the send_to_selected_ereaders function body.
    start = web_src.index("def send_to_selected_ereaders(")
    after = web_src[start:]
    # Next top-level def/route after this function bounds the body.
    next_def = re.search(r"\n@\w|\ndef ", after[1:])
    body = after[: next_def.start() + 1] if next_def else after

    assert "send_includes_own_address(" in body, (
        "send_to_selected_ereaders no longer references the self-download guard helper"
    )
    # The update_download call must be inside an `if send_includes_own_address(...)` block.
    guard = re.search(
        r"if send_includes_own_address\([^\n]*\):\s*\n\s*ub\.update_download\(",
        body,
    )
    assert guard is not None, (
        "ub.update_download is no longer guarded by send_includes_own_address in "
        "send_to_selected_ereaders — relay-only sends would wrongly record a self-download"
    )
