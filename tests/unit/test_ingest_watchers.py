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
- The privilege drop at the top of cwa-ingest-service/run must not loop when abc is
  uid 0 (PUID=0), and must still happen when it is not (#1572).
"""

import os
import select
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


def _start_ingest_service(tmp_path, uid, abc_uid):
    """Run cwa-ingest-service/run as if started by s6, with `id` and `s6-setuidgid`
    stubbed. Returns (reached_startup_banner, setuidgid_calls)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "setuidgid.log"
    (bin_dir / "id").write_text(
        '#!/bin/sh\n'
        '[ "$1" = "-u" ] && [ "$2" = "abc" ] && { echo "$FAKE_ABC_UID"; exit 0; }\n'
        '[ "$1" = "-u" ] && { echo "$FAKE_UID"; exit 0; }\n'
        'exit 1\n'
    )
    # A real s6-setuidgid would exec the script again; record the call and stop, so a
    # loop shows up as "dropped privileges but never started" instead of hanging the test.
    (bin_dir / "s6-setuidgid").write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)

    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
        FAKE_UID=str(uid), FAKE_ABC_UID=str(abc_uid),
        CWA_INGEST_SERVICE_TEST_MODE="0",
        WATCH_FOLDER=str(tmp_path / "watch"),
        CWA_INGEST_PROCESSING_DIR=str(tmp_path / "processing"),
        CWA_INGEST_RECENT_DIR=str(tmp_path / "recent"),
        CWA_INGEST_RETRY_QUEUE=str(tmp_path / "retry_queue"),
        CWA_INGEST_STATUS_FILE=str(tmp_path / "status"),
        CWA_INGEST_BATCH_DIRTY_FILE=str(tmp_path / "batch_dirty"),
    )
    (tmp_path / "watch").mkdir()
    proc = subprocess.Popen(
        ["bash", str(REPO_ROOT / "root" / "etc" / "s6-overlay" / "s6-rc.d" / "cwa-ingest-service" / "run")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
        start_new_session=True,
    )
    started = False
    deadline = time.time() + 10
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break  # script exited
                if "STARTING CWA-INGEST SERVICE" in line:
                    started = True
                    break
    finally:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)
    return started, calls.read_text().splitlines() if calls.exists() else []


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ingest_service_starts_as_root_when_abc_is_root(tmp_path):
    """PUID=0 makes abc uid 0: dropping to abc changes nothing, so it must be skipped (#1572)."""
    started, calls = _start_ingest_service(tmp_path, uid=0, abc_uid=0)

    assert calls == []
    assert started


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ingest_service_drops_privileges_when_abc_is_not_root(tmp_path):
    started, calls = _start_ingest_service(tmp_path, uid=0, abc_uid=911)

    assert len(calls) == 1 and calls[0].startswith("abc ")
    assert not started
