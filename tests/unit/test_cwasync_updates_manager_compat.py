# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for fork issue #400 — Updates Manager compatibility.

KOReader's Updates Manager plugin (advokatb/updatesmanager.koplugin) reads the
``version`` field from a plugin's ``_meta.lua`` and compares it against the
GitHub release tag of the configured repository. Two invariants make our
cwasync plugin distributable through it:

* ``_meta.lua`` MUST declare a ``version`` field. Without it Updates Manager
  shows the installed version as "unknown" and flags a (false) update on every
  check, even when the user already runs the latest build.
* The ``_meta.lua`` version and the ``main.lua`` version (shown in the
  plugin's own About dialog) must stay in lockstep — two version strings that
  drift produce contradictory answers to "what version am I running?".

The release-tag anchor itself is pinned by ``EXPECTED_PLUGIN_VERSION`` in
``test_kosync_plugin_no_book_handling.py``; this file only pins the
cross-file consistency plus the release-asset workflow that publishes the
``cwasync.koplugin.zip`` Updates Manager downloads.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "koreader" / "plugins" / "cwasync.koplugin"
META_LUA = PLUGIN_DIR / "_meta.lua"
MAIN_LUA = PLUGIN_DIR / "main.lua"
ASSET_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "plugin-release-asset.yml"

VERSION_RE = re.compile(r'version\s*=\s*"([^"]+)"')


def _meta_version() -> str | None:
    match = VERSION_RE.search(META_LUA.read_text())
    return match.group(1) if match else None


def _main_version() -> str | None:
    match = VERSION_RE.search(MAIN_LUA.read_text())
    return match.group(1) if match else None


def test_meta_lua_declares_version():
    assert _meta_version() is not None, (
        "_meta.lua must declare a `version = \"...\"` field — Updates Manager "
        "reads the installed version from _meta.lua, and without it every "
        "update check reports 'unknown' plus a false update notification"
    )


def test_meta_and_main_versions_match():
    assert _meta_version() == _main_version(), (
        f"_meta.lua version ({_meta_version()}) and main.lua version "
        f"({_main_version()}) must stay in lockstep — bump both when a "
        "release touches the plugin directory"
    )


def test_version_is_release_tag_shaped():
    version = _meta_version()
    assert version and re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"plugin version {version!r} must be the CWNG release tag without the "
        "leading 'v' (e.g. 4.0.162) so Updates Manager's semantic-version "
        "comparison against release tags works"
    )


def test_release_asset_workflow_publishes_plugin_zip():
    assert ASSET_WORKFLOW.exists(), (
        "plugin-release-asset.yml must exist — it attaches cwasync.koplugin.zip "
        "to every GitHub release, which is the artifact Updates Manager "
        "installs from"
    )
    body = ASSET_WORKFLOW.read_text()
    assert re.search(r"^on:\s*$.*?release:\s*$.*?types:.*published", body,
                     re.MULTILINE | re.DOTALL), \
        "asset workflow must trigger on release published"
    assert "cwasync.koplugin" in body and "cwasync.koplugin.zip" in body, (
        "asset workflow must zip the cwasync.koplugin folder into "
        "cwasync.koplugin.zip (Updates Manager expects the zip to contain the "
        "plugin folder itself)"
    )
