# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the ingest watchers.

- tests/test_ingest_service_shell.sh sources cwa-ingest-service/run in test mode
  and exercises handle_event, the retry queue, post-batch follow-up and the
  startup sweep (books already in the ingest folder when the service starts).
- scripts/watch_fallback.py, the polling watcher used for NETWORK_SHARE_MODE,
  CWA_WATCH_MODE=poll and Docker Desktop, must report a file once, not on every scan.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ingest_service_shell_script():
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "tests" / "test_ingest_service_shell.sh")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def _run_watcher(folder, seconds, during=None):
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts" / "watch_fallback.py"),
         "--path", str(folder), "--interval", "0.3", "--stabilize", "0.5"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        if during:
            during()
        time.sleep(seconds)
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
    return [line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("CLOSE_WRITE ")]


def test_poll_watcher_reports_existing_file_once(tmp_path):
    book = tmp_path / "old book.epub"
    book.write_text("x")
    old = time.time() - 600
    os.utime(book, (old, old))

    events = _run_watcher(tmp_path, 3)

    assert events == [str(book)]


def test_poll_watcher_reports_changed_file_again(tmp_path):
    book = tmp_path / "book.epub"
    book.write_text("x")
    old = time.time() - 600
    os.utime(book, (old, old))

    def change_later():
        time.sleep(1.5)
        book.write_text("changed")

    events = _run_watcher(tmp_path, 3, during=change_later)

    assert events == [str(book), str(book)]
