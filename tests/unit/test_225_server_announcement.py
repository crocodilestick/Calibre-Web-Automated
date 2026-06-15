# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #225 (@froggybottomboys): admin
ability to contact users of the server.

Reporter runs a CWNG instance for ~10 friends in a book club and wants
to announce new books / server updates. Asked for either an admin
email broadcast OR a banner shown after login. Operator pushed back
on email (privacy, hard to self-host); the dismissible login banner
satisfies both the user request and the privacy concern.

## Design

- New `config_server_announcement` String column on the settings
  table (default empty). Admin sets it in /admin/config (Basic
  Configuration). Empty string = no banner.
- Banner renders in `layout.html` at the top of every authenticated
  page when the config value is non-empty.
- Per-user dismiss is client-side via localStorage, keyed by a hash
  of the announcement content. Updating the announcement (different
  hash) re-shows it. No server-side dismiss state needed.

## v2 follow-ups

Operator's push-notification preference for a richer signaling
channel is deferred (VAPID setup, ServiceWorker, browser permissions).
A timed-expiry / multi-announcement broadcaster is also v2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SQL = REPO_ROOT / "cps" / "config_sql.py"
UB_PY = REPO_ROOT / "cps" / "ub.py"
ADMIN_PY = REPO_ROOT / "cps" / "admin.py"
LAYOUT_HTML = REPO_ROOT / "cps" / "templates" / "layout.html"
# Fork #463: banner + custom CSS moved from Basic Configuration to the
# UI Configuration page (config_view_edit.html).
CONFIG_VIEW_EDIT_HTML = REPO_ROOT / "cps" / "templates" / "config_view_edit.html"


def test_config_column_defined():
    src = CONFIG_SQL.read_text()
    assert re.search(
        r"config_server_announcement\s*=\s*Column\(String,\s*default\s*=\s*[\"']{2}\)",
        src,
    ), (
        "cps/config_sql.py must define "
        "config_server_announcement = Column(String, default=\"\")"
    )


def test_migration_function_exists_and_wired():
    """ALTER TABLE migration must exist + be wired into migrate_config_table
    so legacy DBs gain the column on startup."""
    src = UB_PY.read_text()
    # Migration body within migrate_config_table — try/except OperationalError
    # pattern with a SELECT then ALTER for this column.
    assert "config_server_announcement" in src, (
        "cps/ub.py must reference config_server_announcement (migration to "
        "add the column to legacy settings tables)"
    )
    assert re.search(
        r"ALTER\s+TABLE\s+settings\s+ADD\s+column\s+['\"]?config_server_announcement",
        src, re.IGNORECASE,
    ), "must emit an ALTER TABLE settings ADD column DDL for the new column"


def test_admin_form_persists_announcement():
    """update_view_configuration must read config_server_announcement
    from the POSTed form and persist it via _config_string (fork #463 moved
    this off the Basic Configuration page / _configuration_update_helper)."""
    src = ADMIN_PY.read_text()
    match = re.search(
        r"def update_view_configuration\(\):(.*?)(?=\n(?:def \w|class \w|@admi))",
        src, re.DOTALL,
    )
    assert match, "update_view_configuration body not isolatable"
    body = match.group(1)
    assert re.search(
        r"_config_string\(to_save,\s*[\"']config_server_announcement[\"']\)",
        body,
    ), (
        "update_view_configuration must call "
        "_config_string(to_save, 'config_server_announcement')"
    )


def test_admin_form_field_in_template():
    """The UI Configuration page (config_view_edit.html) must surface a
    textarea for the announcement banner so admins can edit it (fork #463)."""
    src = CONFIG_VIEW_EDIT_HTML.read_text()
    assert "config_server_announcement" in src, (
        "config_view_edit.html must include an input/textarea named "
        "config_server_announcement"
    )


def test_layout_renders_banner_when_set():
    """layout.html must render the announcement banner when
    `server_announcement` (the template-context kwarg from
    render_title_template) is truthy. The Flask template global `config`
    is the app config dict, not cps.config — so the banner consumes a
    dedicated kwarg, populated from config.config_server_announcement
    at render time."""
    src = LAYOUT_HTML.read_text()
    assert re.search(
        r"\{%\s*if\s+server_announcement\s*%\}",
        src,
    ), "banner must be {% if server_announcement %} guarded"
    assert re.search(
        r"id=[\"']serverAnnouncementBanner[\"']",
        src,
    ), "banner must have id='serverAnnouncementBanner' for the dismiss JS to target"


def test_layout_banner_does_not_inherit_caliBlur_toast_alert_styles():
    """Fork #288 mobile-pass-1 regression: caliBlur.css styles every
    `.alert` element as a fixed-position toast that auto-hides after
    10s. The announcement banner must NOT use the Bootstrap `alert`
    class; otherwise on the dark theme it becomes invisible-then-broken
    on every page. Use a dedicated cwng-server-announcement class with
    inline styles that force flow-layout positioning."""
    src = LAYOUT_HTML.read_text()
    # The banner div must not carry the bootstrap alert class set.
    banner_match = re.search(
        r'<div\s+id=[\"\']serverAnnouncementBanner[\"\'][^>]*>',
        src,
    )
    assert banner_match, "banner element not found"
    opening_tag = banner_match.group(0)
    assert 'class="alert' not in opening_tag and "class='alert" not in opening_tag, (
        "banner must NOT use Bootstrap `alert` class — caliBlur.css hijacks "
        "every .alert into a fixed-position toast. Use a dedicated class instead."
    )
    # Must have explicit position (static or relative) — not the fixed/absolute
    # that caliBlur's .alert rule would otherwise impose.
    assert re.search(r"position:\s*(static|relative)\b", opening_tag), (
        "banner must force position: static or relative so it stays in flow "
        "regardless of what the theme stylesheet does to ambient `.alert` rules"
    )


def test_render_template_passes_server_announcement():
    """render_title_template must populate `server_announcement` from
    config.config_server_announcement (with a None-safe fallback)."""
    src = (REPO_ROOT / "cps" / "render_template.py").read_text()
    assert "server_announcement=" in src, (
        "render_template.py must pass server_announcement=... in the "
        "render_template kwargs"
    )
    assert "config_server_announcement" in src, (
        "render_template.py must source the kwarg from "
        "config.config_server_announcement"
    )


def test_layout_includes_client_dismiss_js():
    """Per-user dismiss is client-side via localStorage keyed by a hash
    of the announcement content."""
    src = LAYOUT_HTML.read_text()
    # Must reference localStorage + announcement banner element.
    assert "localStorage" in src, "must use localStorage for client-side dismiss"
    # Hash the content so admins editing the announcement re-show it.
    assert re.search(
        r"cwng_announcement_dismissed",
        src,
    ), "localStorage key must be 'cwng_announcement_dismissed' (content-hash suffixed)"
