# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Cancelling Convert Library must clean up its own files, not ingest's or a newer run's."""

import subprocess
import sys
import textwrap

import pytest

from cps import cwa_functions

pytestmark = pytest.mark.unit


def test_cancel_cleanup_removes_only_that_runs_dirs(tmp_path):
    shared = tmp_path / ".cwa_conversion_tmp"
    shared.mkdir()
    (shared / "ingest.epub").write_text("x", encoding="utf-8")
    mine = tmp_path / ".cwa_convert_library_4242_abc123"
    mine.mkdir()
    (mine / "half.epub").write_text("x", encoding="utf-8")
    newer = tmp_path / ".cwa_convert_library_5151_def456"
    newer.mkdir()

    cwa_functions.remove_convert_library_tmp_dirs(str(shared) + "/", 4242)

    assert not mine.exists()
    assert newer.exists(), "a run that started since keeps its dir"
    assert (shared / "ingest.epub").exists()


def test_cancel_cleanup_also_checks_the_system_temp_dir(tmp_path, monkeypatch):
    system_tmp = tmp_path / "systmp"
    system_tmp.mkdir()
    monkeypatch.setattr(cwa_functions.tempfile, "gettempdir", lambda: str(system_tmp))
    fallback = system_tmp / ".cwa_convert_library_4242_abc123"
    fallback.mkdir()
    cwa_functions.remove_convert_library_tmp_dirs(str(tmp_path / "shared") + "/", 4242)
    assert not fallback.exists()


SLOW_STOPPER = textwrap.dedent("""
    # A run that takes a moment to stop after SIGTERM
    import signal, sys, time
    def stop(signum, frame):
        time.sleep(1.5)
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    print("ready", flush=True)
    time.sleep(60)
""")


def test_cancel_waits_for_the_run_to_stop_before_cleaning_up(tmp_path, monkeypatch):
    system_tmp = tmp_path / "systmp"
    system_tmp.mkdir()
    monkeypatch.setattr(cwa_functions.tempfile, "gettempdir", lambda: str(system_tmp))
    monkeypatch.setattr(cwa_functions, "get_tmp_conversion_dir", lambda: str(tmp_path / "shared") + "/")

    proc = subprocess.Popen([sys.executable, "-c", SLOW_STOPPER], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        lock = system_tmp / "convert_library.lock"
        lock.write_text(str(proc.pid), encoding="utf-8")
        stopping = tmp_path / f".cwa_convert_library_{proc.pid}_x"
        stopping.mkdir()
        # The lock and folder must still be there while the run is stopping, which is
        # what keeps a new run from starting and deleting that folder.
        seen = []
        real_remove = cwa_functions.remove_convert_library_tmp_dirs

        def record(*args):
            seen.append(proc.poll())
            real_remove(*args)

        monkeypatch.setattr(cwa_functions, "remove_convert_library_tmp_dirs", record)
        cwa_functions.stop_convert_library(proc)
        assert seen and seen[0] is not None, "cleanup ran after the process had exited"
        assert not lock.exists()
        assert not stopping.exists()
    finally:
        proc.kill()
        proc.wait()


def test_cancel_leaves_a_lock_a_newer_run_has_taken(tmp_path, monkeypatch):
    system_tmp = tmp_path / "systmp"
    system_tmp.mkdir()
    monkeypatch.setattr(cwa_functions.tempfile, "gettempdir", lambda: str(system_tmp))
    monkeypatch.setattr(cwa_functions, "get_tmp_conversion_dir", lambda: str(tmp_path / "shared") + "/")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        lock = system_tmp / "convert_library.lock"
        lock.write_text("999999999", encoding="utf-8")
        cwa_functions.stop_convert_library(proc)
        assert lock.exists()
    finally:
        proc.kill()
        proc.wait()


def test_cancel_kills_a_run_that_does_not_stop_in_time(tmp_path, monkeypatch):
    monkeypatch.setattr(cwa_functions.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(cwa_functions, "get_tmp_conversion_dir", lambda: str(tmp_path / "shared") + "/")
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        cwa_functions.stop_convert_library(proc, wait_seconds=0.5)
        assert proc.poll() is not None
    finally:
        proc.kill()
        proc.wait()
