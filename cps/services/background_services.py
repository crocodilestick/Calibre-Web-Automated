# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Starts CWA background services as subprocesses managed by the Flask app.
"""

import atexit
import logging
import os
import signal
import subprocess
import threading
import time

log = logging.getLogger("cwa.background_services")

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVICES_DIR = os.path.join(APP_DIR, "scripts", "services")

_processes = []


def _popen(script_name):
    """Start a service script as a detached subprocess."""
    script = os.path.join(SERVICES_DIR, script_name)
    if not os.path.isfile(script):
        log.warning("[background_services] %s not found, skipping", script_name)
        return None
    cmd = ["/bin/bash", script]
    log.info("[background_services] Starting %s", script_name)
    proc = subprocess.Popen(cmd, start_new_session=True)
    _processes.append(proc)
    return proc


def _cleanup(_signum=None, _frame=None):
    """Terminate all managed subprocesses gracefully, then force-kill stragglers."""
    # Send SIGTERM to every process group
    for p in _processes:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass

    # Give processes up to 5 seconds to exit gracefully
    gone, alive = [], list(_processes)
    deadline = time.monotonic() + 5
    while alive and time.monotonic() < deadline:
        for p in alive:
            if p.poll() is not None:
                gone.append(p)
        alive = [p for p in alive if p not in gone]
        if alive:
            time.sleep(0.1)

    # Force-kill anything still running
    for p in alive:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass


def start_all():
    """
    Start all background services.  Call once during application startup,
    before the web server starts.
    """
    log.info("Starting CWA background services...")

    atexit.register(_cleanup)

    # One-shot services (block briefly, must complete before watchers start)
    for script in (
        "cwa-init.sh",
        "calibre-binaries-setup.sh",
        "cwa-process-recovery.sh",
        "cwa-auto-library.sh",
    ):
        path = os.path.join(SERVICES_DIR, script)
        if os.path.isfile(path):
            log.info("[background_services] Running one-shot: %s", script)
            try:
                subprocess.run(["/bin/bash", path], timeout=120, check=False)
            except Exception as exc:
                log.warning("[background_services] %s failed: %s", script, exc)

    # Long-running services (subprocesses)
    _popen("cwa-ingest-service.sh")
    _popen("metadata-change-detector.sh")
    _popen("cwa-auto-zipper.sh")

    # Deferred one-shot: checksum backfill (wait for app to be ready)
    def _deferred():
        time.sleep(15)
        path = os.path.join(SERVICES_DIR, "cwa-checksum-backfill.sh")
        if os.path.isfile(path):
            try:
                subprocess.run(["/bin/bash", path], timeout=600, check=False)
            except Exception as exc:
                log.warning(
                    "[background_services] cwa-checksum-backfill failed: %s", exc
                )

    threading.Thread(
        target=_deferred, name="cwa-checksum-backfill", daemon=True
    ).start()

    log.info("All background services started")
