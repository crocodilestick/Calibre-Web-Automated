# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the cwasync no-active-document guards (CWA #1074).

Backport of CWA #1074 by @SethMilliken. Prior behavior: the Push / Pull
menu entries and the auto-sync toggle stayed enabled whenever a password
was set, even when opened from the file browser with no document loaded.
Tapping them dereferenced `self.ui.document` and crashed the plugin.

The fix:

* Adds `hasActiveDocument()` (returns true only when `self.ui.document`
  is set) and uses it in the `enabled_func` of the Push / Pull menu items
  alongside the existing password check.
* Adds `statusTextIfActionUnavailable()` which appends a parenthetical
  reason — `(Password Not Set)` or `(No Active Document)` — to the menu
  label so users see *why* the entry is greyed out.
* Early-returns from the auto-sync toggle handler when no document is
  open, so flipping the switch from the file browser is a no-op rather
  than a crash.

The plugin itself is Lua and we don't run a Lua test runner in CI, so
these tests pattern-pin the load-bearing call sites against `main.lua`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_LUA = REPO_ROOT / "koreader" / "plugins" / "cwasync.koplugin" / "main.lua"


def _read() -> str:
    assert MAIN_LUA.exists(), f"missing file: {MAIN_LUA}"
    return MAIN_LUA.read_text(encoding="utf-8")


def test_has_active_document_helper_defined():
    body = _read()
    assert "function CWASync:hasActiveDocument()" in body, (
        "main.lua must define CWASync:hasActiveDocument() (CWA #1074)"
    )
    assert "(self.ui and self.ui.document) ~= nil" in body, (
        "hasActiveDocument must check both self.ui and self.ui.document — "
        "the file-browser entry point has self.ui but no document"
    )


def test_status_text_helper_defined():
    body = _read()
    assert "function CWASync:statusTextIfActionUnavailable()" in body, (
        "main.lua must define CWASync:statusTextIfActionUnavailable() (CWA #1074)"
    )
    assert '_(" (Password Not Set)")' in body, (
        "statusTextIfActionUnavailable must surface the missing-password reason"
    )
    assert '_(" (No Active Document)")' in body, (
        "statusTextIfActionUnavailable must surface the no-active-document reason"
    )


def test_push_menu_uses_status_text_and_active_document_guard():
    body = _read()
    assert (
        '_("Push progress from this device now") .. self:statusTextIfActionUnavailable()'
        in body
    ), "Push menu entry must append statusTextIfActionUnavailable() (CWA #1074)"
    # The enabled_func now combines the password check with hasActiveDocument().
    # We pin the exact predicate so a future edit that drops either side trips
    # this test.
    assert (
        "return self.settings.password ~= nil and self:hasActiveDocument()"
        in body
    ), "Push/Pull enabled_func must AND password presence with hasActiveDocument()"


def test_pull_menu_uses_status_text():
    body = _read()
    assert (
        '_("Pull progress from other devices now") .. self:statusTextIfActionUnavailable()'
        in body
    ), "Pull menu entry must append statusTextIfActionUnavailable() (CWA #1074)"


def test_auto_sync_toggle_early_returns_when_no_active_document():
    body = _read()
    # The auto-sync toggle handler now bails out before scheduling tasks if no
    # document is open. Pin the exact guard so a refactor doesn't quietly drop
    # the early return and revive the original crash path.
    assert "if not(self:hasActiveDocument()) then\n                        return" in body, (
        "auto-sync toggle must early-return when hasActiveDocument() is false (CWA #1074)"
    )
