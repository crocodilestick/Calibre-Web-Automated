# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_duplicate_notifier_does_not_start_page_load_polling():
    script = (PROJECT_ROOT / "cps/static/js/duplicate-notifier.js").read_text(encoding="utf-8")
    init_body = script.split("function init()", 1)[1].split("document.addEventListener('visibilitychange'", 1)[0]

    assert "fetchDuplicateStatus().then(handleStatusResponse);" in init_body
    assert "startStatusPolling();" not in init_body


def test_duplicate_notifier_does_not_poll_stale_cache_status():
    script = (PROJECT_ROOT / "cps/static/js/duplicate-notifier.js").read_text(encoding="utf-8")
    handler_body = script.split("function handleStatusResponse(data)", 1)[1].split("function hideNotificationModal()", 1)[0]

    assert "data.needs_scan || data.stale" not in handler_body
    assert "if (data.enabled) {\n            startStatusPolling();" not in handler_body
