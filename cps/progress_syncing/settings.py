# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for KOReader sync feature flags."""

import os
import sqlite3
import sys

# Access CWA_DB from scripts path (consistent with existing patterns)
sys.path.insert(1, '/app/calibre-web-automated/scripts/')


def _read_setting_directly():
    """Read the flag with one query. CWA_DB() reconciles the whole cwa.db schema
    each time it is created, which is too heavy for every download/sync request."""
    db_file = os.path.join(os.environ.get("CWA_DB_PATH", "/config"), "cwa.db")
    con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, timeout=5)
    try:
        row = con.execute("SELECT koreader_sync_enabled FROM cwa_settings LIMIT 1").fetchone()
    finally:
        con.close()
    return bool(row[0]) if row else False


def is_koreader_sync_enabled() -> bool:
    """Return True if KOReader sync is enabled in CWA settings."""
    try:
        return _read_setting_directly()
    except sqlite3.Error:
        pass  # missing file/column (e.g. before first CWA_DB init): use the full path below
    try:
        from cwa_db import CWA_DB
        settings = CWA_DB().cwa_settings
        return bool(settings.get('koreader_sync_enabled', 0))
    except Exception:
        # Fail closed to avoid unexpected DB writes when setting is missing
        return False
