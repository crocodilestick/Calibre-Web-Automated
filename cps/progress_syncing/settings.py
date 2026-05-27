# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for KOReader sync feature flags."""

import sys
import time

from .. import logger

# Access CWA_DB from scripts path (consistent with existing patterns)
sys.path.insert(1, '/app/calibre-web-automated/scripts/')

log = logger.create()

# Fork issue #312: rate-limit the "fail closed because cwa_settings
# unreadable" log so a misconfigured DB doesn't spam the log on every
# request. One line every five minutes is enough signal for an admin
# to notice without drowning the actual diagnostic content. The
# user-visible "sync is disabled" line lives in the gate at
# `_require_kosync_enabled()` and is emitted per-request.
_LAST_FAILED_READ_WARN = 0.0
_FAILED_READ_WARN_INTERVAL = 300.0


def is_koreader_sync_enabled() -> bool:
    """Return True if KOReader sync is enabled in CWA settings."""
    global _LAST_FAILED_READ_WARN
    try:
        from cwa_db import CWA_DB
        settings = CWA_DB().cwa_settings
        return bool(settings.get('koreader_sync_enabled', 0))
    except Exception as e:
        # Fail closed to avoid unexpected DB writes when setting is missing.
        # Log once per `_FAILED_READ_WARN_INTERVAL` so an unreadable
        # cwa.db surfaces a single line instead of one per request.
        now = time.monotonic()
        if now - _LAST_FAILED_READ_WARN >= _FAILED_READ_WARN_INTERVAL:
            log.warning(
                "KOReader sync: cwa_settings unreadable (%s) — "
                "treating sync as disabled (fail-closed)", e,
            )
            _LAST_FAILED_READ_WARN = now
        return False
