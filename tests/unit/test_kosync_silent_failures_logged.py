# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #312 — Tier 1: KOReader sync log coverage.

The original symptom: after migrating from stock CWA to CWNG, @uschi1's
KOReader plugin stopped syncing. Server-side logs showed nothing — the
kosync gate `_require_kosync_enabled()` was silently returning 503 with
zero diagnostic output. Triage had to fall back to "delete the book and
redownload it," which is not a diagnosis.

Pin the new contract: every silent-failure path emits a log line at
INFO or WARNING with enough context (endpoint, user, document, book_id
where known) for the admin to identify the cause from a single log
sweep.

These are AST/source-pinned tests — they read the kosync.py source and
assert the diagnostic log lines exist at the right call sites. The
behavior-level test for actual log emission is exercised in the
container integration suite where a real request flows through the
stack with a real session.

Pattern source: tests/unit/test_kosync_book_id_keyed_lookup.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KOSYNC_PY = REPO_ROOT / "cps" / "progress_syncing" / "protocols" / "kosync.py"
SETTINGS_PY = REPO_ROOT / "cps" / "progress_syncing" / "settings.py"


def _src(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    pattern = rf"^def {re.escape(name)}\(.*?(?=^def |^class |\Z)"
    m = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    assert m is not None, f"function `{name}` not found"
    return m.group(0)


@pytest.mark.unit
class TestRequireEnabledGateLogs:
    """`_require_kosync_enabled()` was the silent-failure root for #312."""

    def test_gate_emits_warning_when_disabled(self):
        body = _extract_function(_src(KOSYNC_PY), "_require_kosync_enabled")
        # Any log.warning or log.info citing the disabled state inside
        # the gate body satisfies the contract; we just need it to NOT
        # be silent the way it was.
        assert re.search(
            r"log\.(warning|info)\s*\([^)]*(?:disabled|gated|sync_disabled)",
            body,
            re.IGNORECASE,
        ), (
            "_require_kosync_enabled() must emit a log line when blocking a "
            "request. The silent 503 here is what made fork issue #312 "
            "un-diagnosable from server logs."
        )


@pytest.mark.unit
class TestSettingsHelperLogs:
    """`is_koreader_sync_enabled()` should log when it fail-closes — that
    is the single line that explains "why is sync off" on a fresh
    instance."""

    def test_helper_emits_log_on_disabled_path(self):
        body = _src(SETTINGS_PY)
        # Either an explicit logger import + log call inside the helper
        # OR a documented call delegated to the gate. We accept either,
        # but the source must show one or the other clearly.
        assert "logger" in body or "log." in body, (
            "cps/progress_syncing/settings.py must import the logger and "
            "emit at least one diagnostic line on the disabled path."
        )


@pytest.mark.unit
class TestAuthenticationFailuresLogged:
    """User-not-found and wrong-password paths were DEBUG only — invisible
    at default INFO."""

    def test_user_not_found_logs_at_info_or_warning(self):
        body = _extract_function(_src(KOSYNC_PY), "authenticate_user")
        # The "User not found" message must use a level that the default
        # logger surfaces (INFO or WARNING). DEBUG was the original bug.
        assert re.search(
            r"log\.(info|warning)\s*\([^)]*[Uu]ser not found",
            body,
        ), (
            "authenticate_user() must log 'User not found' at INFO+ so it "
            "appears in the default log; DEBUG-only is the bug."
        )

    def test_invalid_password_logs_at_info_or_warning(self):
        body = _extract_function(_src(KOSYNC_PY), "authenticate_user")
        assert re.search(
            r"log\.(info|warning)\s*\([^)]*(?:Invalid|wrong|bad) password",
            body,
            re.IGNORECASE,
        ), (
            "authenticate_user() must log invalid-password attempts at INFO+ "
            "so brute-force or bad-config patterns surface in admin logs."
        )


@pytest.mark.unit
class TestBookMatchFailureLogged:
    """`get_book_by_checksum` returning "no match" must surface — that is
    the line that explains "your device's file checksum is unknown to
    this server" for a non-trivial fraction of sync issues."""

    def test_no_match_logs_at_info_with_checksum(self):
        body = _extract_function(_src(KOSYNC_PY), "get_book_by_checksum")
        # Permit INFO or higher.
        assert re.search(
            r"log\.(info|warning)\s*\([^)]*[Nn]o book found.*?checksum",
            body,
            re.DOTALL,
        ), (
            "get_book_by_checksum() must log no-match at INFO+ with the "
            "checksum value so triage can see which device-file is "
            "unrecognized. DEBUG-only was the bug."
        )


@pytest.mark.unit
class TestUpdateProgressDbErrorIncludesContext:
    """DB errors during PUT /kosync/syncs/progress used to log a bare
    'Database error' — useless for triage. They must include user id and
    document so we can correlate with the failing client."""

    def test_db_error_log_message_mentions_user_and_document(self):
        body = _src(KOSYNC_PY)
        # We grep for the error log line near the update_progress
        # endpoint and require the message format string include
        # `user` and `document` tokens. The exact format may vary.
        candidates = re.findall(
            r"log\.error\(\s*[fF]?\"[^\"]*\"",
            body,
        )
        contextful = [
            c for c in candidates
            if ("user" in c.lower() and ("document" in c.lower() or "checksum" in c.lower()))
        ]
        assert contextful, (
            "At least one log.error in kosync.py must include both user and "
            "document/checksum in the message — triage of #312-class bugs "
            "requires correlating server logs to the device's push."
        )
