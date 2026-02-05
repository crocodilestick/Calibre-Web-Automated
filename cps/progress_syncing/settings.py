# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for KOReader sync feature flags."""

import sys

# Access CWA_DB from scripts path (consistent with existing patterns)
sys.path.insert(1, '/app/calibre-web-automated/scripts/')


def is_koreader_sync_enabled() -> bool:
    """Return True if KOReader sync is enabled in CWA settings."""
    try:
        from cwa_db import CWA_DB
        settings = CWA_DB().cwa_settings
        return bool(settings.get('koreader_sync_enabled', 0))
    except Exception:
        # Fail closed to avoid unexpected DB writes when setting is missing
        return False
