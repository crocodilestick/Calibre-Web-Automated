# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for CW #3648 — Amazon metadata search returns no
results.

Reporter (upstream, today): "Steps to reproduce: 1) Go to Any book
and search for Metadata. 2) If Amazon or Google Books are selected.
3) No Result(s) found! Please try another keyword."

Reproduced in our build via direct ``requests.get`` from cwn-local:

  minimal headers {UA, Accept, Accept-Encoding}: status=503, body=2.6KB
  full browser headers (UA + Accept-Language + DNT + Sec-Fetch-* +
    Upgrade-Insecure-Requests): status=200, body=1.1MB with results

Root cause: ``cps/metadata_provider/amazon.py::Amazon.headers`` only
declared User-Agent + Accept + Accept-Encoding. Amazon's bot
detection requires the FULL browser-shape header set — a Firefox UA
alone isn't enough. The provider's empty result list propagated to
the modal as "No Result(s) found!"

(Note: an earlier hypothesis was that ``headers=self.headers`` was
commented out on the request line — that's also true, but moot
because ``session.headers`` is set at class definition. The real fix
is expanding the headers dict itself.)

These tests pin:

1. ``Amazon.headers`` includes ``Accept-Language`` — Amazon
   bot-detection signal.
2. ``Amazon.headers`` includes ``Sec-Fetch-Dest`` — modern browser
   metadata signal Amazon checks.
3. ``Amazon.headers`` includes ``Upgrade-Insecure-Requests`` — same.
4. ``Amazon.headers`` includes a Firefox/Mozilla User-Agent.
5. A CW #3648 anchor comment is present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
AMAZON_PY = REPO_ROOT / "cps" / "metadata_provider" / "amazon.py"


def _amazon_source() -> str:
    return AMAZON_PY.read_text()


def _headers_block() -> str:
    """Extract the ``headers = { ... }`` dict body from amazon.py."""
    src = _amazon_source()
    match = re.search(
        r"^\s*headers\s*=\s*\{(?P<body>.*?)\n\s*\}",
        src,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "Could not locate `headers = {...}` dict in amazon.py"
    return match.group("body")


def test_amazon_headers_includes_user_agent():
    body = _headers_block()
    assert re.search(r"['\"]User-Agent['\"]\s*:\s*['\"]Mozilla/", body), (
        "Amazon.headers must include a Mozilla-shaped User-Agent. "
        "Amazon serves 503 to `python-requests/X.Y.Z`. See CW #3648."
    )


def test_amazon_headers_includes_accept_language():
    body = _headers_block()
    assert re.search(r"['\"]Accept-Language['\"]\s*:", body), (
        "Amazon.headers must include `Accept-Language` — Amazon's bot "
        "detection 503s requests missing this. See CW #3648 cwn-local "
        "repro."
    )


def test_amazon_headers_includes_sec_fetch_dest():
    body = _headers_block()
    assert re.search(r"['\"]Sec-Fetch-Dest['\"]\s*:", body), (
        "Amazon.headers must include `Sec-Fetch-Dest` — modern browsers "
        "send this and Amazon checks for it. See CW #3648."
    )


def test_amazon_headers_includes_upgrade_insecure_requests():
    body = _headers_block()
    assert re.search(r"['\"]Upgrade-Insecure-Requests['\"]\s*:", body), (
        "Amazon.headers must include `Upgrade-Insecure-Requests` — "
        "another browser-shape signal Amazon's bot detection checks. "
        "See CW #3648."
    )


def test_amazon_session_headers_assigned_at_class_level():
    """``session.headers = headers`` at class definition is what makes
    every per-request `session.get` use the browser-shape headers
    without each call needing `headers=self.headers`. Pin this so a
    refactor that removes the class-level assignment also restores
    per-request headers or the bug returns."""
    src = _amazon_source()
    assert re.search(r"session\.headers\s*=\s*headers", src), (
        "amazon.py must set `session.headers = headers` at class "
        "definition (or pass `headers=` on every per-request call). "
        "Without one or the other, the session falls back to the "
        "default python-requests User-Agent and Amazon serves 503. "
        "See CW #3648."
    )


def test_cw_3648_anchor_comment_present():
    src = _amazon_source()
    assert "CW #3648" in src, (
        "amazon.py must reference CW #3648 near the headers dict so "
        "future refactors find the rationale for the full browser-shape "
        "set."
    )
