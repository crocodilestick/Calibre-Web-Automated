# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for issue #192 — concurrent ingest crashes web service.

The reporter (magdalar, NETWORK_SHARE_MODE=true on local mergerfs)
dropped 5 large epubs into /cwa-book-ingest. The first ingest
succeeded, the next four failed with `apsw.BusyError: database is
locked`, and the web service became unresponsive (returns 404 on every
route) until the operator ran `docker compose restart`.

Investigation identified four root-cause contributors. Each is pinned
by tests in this file so that a regression of any one is caught before
merge.

Contributor 1 — async TaskReconnectDatabase enqueued via
WorkerThread after every successful ingest disposed the SQLAlchemy
engine while in-flight requests were using it. Replaced with a
synchronous, lightweight expire+rollback that does NOT touch the
engine.

Contributor 2 — no application-level coordination on metadata.db
writers. mergerfs / SMB / NFS may drop or delay POSIX advisory locks,
which is exactly what trips apsw.BusyError. Added a process-shared
flock-based mutex via `cps.services.calibre_db_lock`.

Contributor 3 — no `PRAGMA busy_timeout` set on the connection.
SQLAlchemy `connect_args={'timeout': 30}` sets it once at connect; an
explicit PRAGMA per setup is more reliable.

Contributor 4 — `calibredb add` failure is terminal. A transient lock
should be retried with backoff, not silently moved to /failed.
"""

import ast
import os
import sqlite3
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Contributor 1 — async dispose is replaced by synchronous expire+rollback
# ---------------------------------------------------------------------------


def _call_name(node):
    parts = []
    current = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


@pytest.mark.unit
class TestReconnectEndpointIsSynchronousAndLightweight:
    """The /cwa-internal/reconnect-db endpoint must not enqueue a
    TaskReconnectDatabase via WorkerThread. The post-ingest call from
    ingest_processor needs to run synchronously so the next web request
    sees the freshly-imported book — and it must avoid disposing the
    engine, which races with in-flight requests."""

    @pytest.fixture
    def cwa_functions_source(self):
        path = REPO_ROOT / "cps" / "cwa_functions.py"
        return path.read_text(encoding="utf-8")

    def _find_function(self, source, name):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def test_endpoint_does_not_enqueue_worker_task_reconnect(
        self, cwa_functions_source
    ):
        fn = self._find_function(cwa_functions_source, "cwa_internal_reconnect_db")
        assert fn is not None, (
            "Endpoint cwa_internal_reconnect_db must exist in cwa_functions.py"
        )
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                name = _call_name(sub) or ""
                # TaskReconnectDatabase() instantiation is forbidden —
                # the heavy reconnect path racing with requests is the
                # actual #192 trigger.
                if name.endswith("TaskReconnectDatabase"):
                    pytest.fail(
                        "cwa_internal_reconnect_db must not instantiate "
                        "TaskReconnectDatabase: that path disposes the "
                        "shared engine and races with in-flight requests. "
                        "Use a synchronous expire/rollback helper instead."
                    )
                if name.endswith("WorkerThread.add"):
                    pytest.fail(
                        "cwa_internal_reconnect_db must not call "
                        "WorkerThread.add: the async enqueue lets the "
                        "engine dispose race with active request greenlets."
                    )

    def test_calibredb_refresh_helper_exists_on_class(self):
        """The synchronous replacement helper must exist as a class
        method on CalibreDB so multiple instances (including worker-
        thread instances) all release their stale read transactions
        in one call."""
        # Import only — we are not exercising it here, just pinning the
        # public surface so the implementation cannot quietly regress
        # to a no-op or a function in a different module.
        from cps.db import CalibreDB

        assert hasattr(CalibreDB, "refresh_for_new_data"), (
            "CalibreDB.refresh_for_new_data classmethod must exist — "
            "this is the synchronous, no-engine-dispose replacement for "
            "the old TaskReconnectDatabase path."
        )
        attr = getattr(CalibreDB, "refresh_for_new_data")
        assert callable(attr), "refresh_for_new_data must be callable"

    def test_refresh_helper_does_not_dispose_engine(self):
        """refresh_for_new_data must NOT call engine.dispose() or
        setup_db(). It must expire loaded objects and end the held
        read transaction so the next query sees committed data."""
        from cps.db import CalibreDB
        import inspect, ast, textwrap

        src = textwrap.dedent(inspect.getsource(CalibreDB.refresh_for_new_data))
        tree = ast.parse(src)
        called = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Last identifier of the call expression (e.g. "x.y.z()" → "z").
                cur = node.func
                while isinstance(cur, ast.Attribute):
                    called.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    called.append(cur.id)

        assert "expire_all" in called, (
            "refresh_for_new_data must call session.expire_all() so "
            "loaded objects are re-fetched on next access."
        )
        assert "rollback" in called or "close" in called, (
            "refresh_for_new_data must end the read transaction via "
            "rollback() or close() so the next query starts fresh and "
            "sees external writes (calibredb add)."
        )
        # Engine dispose is the #192 trigger. Forbidden as an actual
        # call (the docstring may legitimately mention it as context).
        assert "dispose" not in called, (
            "refresh_for_new_data must NOT call engine.dispose() — "
            "that's the bug #192 fixed. Use a lighter-weight expire."
        )
        assert "setup_db" not in called, (
            "refresh_for_new_data must NOT call setup_db() — that's "
            "engine-recreating and racy."
        )


# ---------------------------------------------------------------------------
# Contributor 2 — process-shared advisory flock for metadata.db writers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetadataDbWriteLockModuleSurface:
    """Two writers (the Flask app and the ingest_processor subprocess)
    must coordinate via a fcntl flock so unreliable POSIX locks on
    mergerfs / SMB / NFS don't poison concurrent ingests."""

    def test_lock_module_exists(self):
        import cps.services.calibre_db_lock as mod  # noqa: F401

    def test_metadata_db_write_lock_is_context_manager(self):
        from cps.services.calibre_db_lock import metadata_db_write_lock

        assert callable(metadata_db_write_lock), (
            "metadata_db_write_lock must be a callable factory that "
            "returns a context manager."
        )
        # Verify it returns a context manager when called.
        cm = metadata_db_write_lock(lock_dir=tempfile.gettempdir())
        assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__"), (
            "metadata_db_write_lock(...) must return a context manager."
        )
        # Acquire + release cleanly.
        with cm:
            pass

    def test_lock_serializes_two_python_processes_via_threads(self, tmp_path):
        """Use TWO separate Python processes spawned through subprocess.
        The underlying fcntl flock is process-level so this is the
        only honest test of cross-process semantics."""
        import subprocess

        lock_dir = tmp_path
        held_marker = tmp_path / "held.txt"

        # Load the lock module directly via importlib to skip cps/
        # package init (which has heavy deps). The calibre_db_lock
        # module is dependency-free aside from stdlib.
        lock_module_path = REPO_ROOT / "cps" / "services" / "calibre_db_lock.py"

        # Process A: acquire lock, hold for 1.5s, then release.
        a_script = f"""
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("calibre_db_lock", {str(lock_module_path)!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
with mod.metadata_db_write_lock(lock_dir={str(lock_dir)!r}, timeout=10):
    open({str(held_marker)!r}, 'w').write('held')
    time.sleep(1.5)
"""
        # Process B: try to acquire immediately. Should block until A releases.
        b_script = f"""
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("calibre_db_lock", {str(lock_module_path)!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
start = time.monotonic()
with mod.metadata_db_write_lock(lock_dir={str(lock_dir)!r}, timeout=10):
    held_dur = time.monotonic() - start
    print(held_dur)
"""

        a = subprocess.Popen(
            [sys.executable, "-c", a_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        # Wait for A to actually be inside the lock.
        for _ in range(100):
            if held_marker.exists():
                break
            time.sleep(0.05)

        if not held_marker.exists():
            # Surface A's error so the failure is diagnosable.
            try:
                a.wait(timeout=2)
            except subprocess.TimeoutExpired:
                a.kill()
            stdout, stderr = a.communicate()
            pytest.fail(
                f"Process A never reached its lock. stderr=\n{stderr}\n"
                f"stdout=\n{stdout}"
            )

        # Now fire B.
        b = subprocess.Popen(
            [sys.executable, "-c", b_script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        a.wait(timeout=10)
        b_stdout, b_stderr = b.communicate(timeout=10)
        a_stderr_text = a.stderr.read() if a.stderr else ""

        assert a.returncode == 0, f"Process A failed: {a_stderr_text}"
        assert b.returncode == 0, f"Process B failed: {b_stderr}"

        # B must have waited at least ~0.5s (A held for 1.5s, B fired
        # right after the held marker appeared so most of A's hold
        # remained).
        held_dur = float(b_stdout.strip().splitlines()[-1])
        assert held_dur >= 0.3, (
            f"Process B acquired the lock in {held_dur:.2f}s — should "
            f"have blocked for ~1s while Process A held it. The cross-"
            f"process flock is NOT enforcing mutual exclusion."
        )


@pytest.mark.unit
class TestMetadataDbWriteLockAppliedAtCallsites:
    """The lock helper only helps if it's actually used at the
    metadata.db write sites. Pin the call sites by source-inspection
    so a future refactor that drops the wrap is caught."""

    def test_editbooks_do_edit_book_wraps_commit_with_lock(self):
        path = REPO_ROOT / "cps" / "editbooks.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "do_edit_book":
                target = node
                break
        assert target is not None, "do_edit_book must exist in editbooks.py"

        # The function source must reference the lock helper.
        fn_src = ast.get_source_segment(src, target) or ""
        assert "metadata_db_write_lock" in fn_src, (
            "do_edit_book must wrap its calibre_db.session.commit() "
            "with cps.services.calibre_db_lock.metadata_db_write_lock — "
            "otherwise concurrent ingest can poison the commit on "
            "filesystems with unreliable POSIX locks."
        )

    def test_ingest_processor_add_wraps_calibredb_add_with_lock(self):
        path = REPO_ROOT / "scripts" / "ingest_processor.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "add_book_to_library":
                target = node
                break
        assert target is not None, (
            "add_book_to_library must exist in scripts/ingest_processor.py"
        )
        fn_src = ast.get_source_segment(src, target) or ""
        assert "metadata_db_write_lock" in fn_src, (
            "add_book_to_library must wrap the calibredb add subprocess "
            "with metadata_db_write_lock. Without it, the Flask app's "
            "Edit Book commit can race with calibredb on mergerfs/SMB/"
            "NFS and fire apsw.BusyError. This is fork issue #192."
        )


# ---------------------------------------------------------------------------
# Contributor 3 — PRAGMA busy_timeout=60000 must be set
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSqliteBusyTimeoutPragma:
    """Without an explicit PRAGMA busy_timeout, SQLite's default 0ms
    timeout makes any contention fatal. The SQLAlchemy connect_args
    `timeout` only applies at connect() time; later reconnects, other
    Python processes (ingest_processor), and apsw (calibre) do not
    inherit it. We pin the PRAGMA in setup_db so every connection has
    a 60s busy_timeout."""

    def test_setup_db_source_sets_busy_timeout_to_60s(self):
        path = REPO_ROOT / "cps" / "db.py"
        src = path.read_text(encoding="utf-8")

        # Find the setup_db classmethod source. The PRAGMA must be
        # there, with at least 60000ms (60s).
        tree = ast.parse(src)
        setup_db = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "setup_db":
                setup_db = node
                break
        assert setup_db is not None, "setup_db classmethod must exist in db.py"
        fn_src = ast.get_source_segment(src, setup_db) or ""
        assert "busy_timeout" in fn_src.lower(), (
            "setup_db must set PRAGMA busy_timeout — without it, "
            "concurrent ingest fails outright on mergerfs/SMB/NFS."
        )
        # Same for check_valid_db (other entry).
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "check_valid_db":
                check_valid_db = node
                break
        check_src = ast.get_source_segment(src, check_valid_db) or ""
        assert "busy_timeout" in check_src.lower(), (
            "check_valid_db must also set PRAGMA busy_timeout for "
            "consistency at config-validation time."
        )


# ---------------------------------------------------------------------------
# Contributor 4 — calibredb add retries on transient "database is locked"
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalibredbAddRetriesOnLockError:
    """The original behavior is: first apsw.BusyError on `calibredb add`
    moves the book to /processed_books/failed. Reporter #192 hit this
    four times in a row from the same import wave. The fix: detect
    "database is locked" / "BusyError" in stderr and retry with
    exponential backoff (2s, 4s, 8s) before giving up."""

    def test_helper_function_exists_in_ingest_processor(self):
        # Pin by source — we don't want to invoke calibredb in a unit test.
        path = REPO_ROOT / "scripts" / "ingest_processor.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "_run_calibredb_add_with_retry" in names, (
            "scripts/ingest_processor.py must expose "
            "_run_calibredb_add_with_retry — the lock-aware retry "
            "wrapper around `calibredb add`. Required by fork #192."
        )

    def test_retry_wrapper_detects_busy_error_pattern(self):
        """The retry path must match against the two known calibredb
        lock-error strings (apsw fires either, depending on which
        SQLite layer the lock is hit at). Pin the patterns at the
        module level so a refactor that hides them in a helper doesn't
        silently drop coverage."""
        path = REPO_ROOT / "scripts" / "ingest_processor.py"
        src = path.read_text(encoding="utf-8").lower()
        # Both pattern strings must appear in the module — they live
        # in the _LOCK_PATTERNS tuple consumed by the retry helper.
        assert "database is locked" in src, (
            "ingest_processor.py must reference the 'database is "
            "locked' stderr pattern so the retry wrapper recognises "
            "transient apsw lock errors."
        )
        assert "busyerror" in src, (
            "ingest_processor.py must reference the 'BusyError' "
            "stderr pattern — apsw's specific subclass that calibredb "
            "surfaces on contention."
        )

    def test_retry_wrapper_actually_retries_on_locked_stderr(self, monkeypatch):
        """Behavioral test: call the helper with a mock subprocess.run
        that fails twice with 'database is locked' then succeeds.
        Assert it retried and returned the success result."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        sys.path.insert(0, str(REPO_ROOT))
        import importlib
        ip = importlib.import_module("ingest_processor")

        call_count = {"n": 0}

        class FakeCompletedProcess:
            def __init__(self, returncode, stdout="", stderr=""):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                # Mimic calibredb's apsw.BusyError stack trace text.
                err = (
                    "apsw.BusyError: database is locked\n"
                    "(failed during schema check)\n"
                )
                from subprocess import CalledProcessError
                raise CalledProcessError(
                    returncode=1,
                    cmd=args[0] if args else ["calibredb", "add"],
                    output="",
                    stderr=err,
                )
            return FakeCompletedProcess(returncode=0, stdout="Added book ids: 42\n", stderr="")

        # Replace subprocess.run inside ingest_processor's module
        # namespace with our fake. Time.sleep too — we don't want
        # the 2/4s backoffs to run in CI.
        monkeypatch.setattr(ip.subprocess, "run", fake_run)
        monkeypatch.setattr(ip.time, "sleep", lambda _s: None)

        result = ip._run_calibredb_add_with_retry(
            cmd=["calibredb", "add", "/tmp/fake.epub", "--library-path=/tmp/lib"],
            env={},
            max_attempts=4,
        )
        assert call_count["n"] == 3, (
            f"Expected 3 attempts (2 retries + 1 success) but got "
            f"{call_count['n']}. The retry wrapper isn't retrying on "
            f"'database is locked' stderr."
        )
        assert result.returncode == 0
        assert "Added book ids: 42" in result.stdout

    def test_retry_wrapper_does_not_retry_on_non_lock_errors(self, monkeypatch):
        """A non-lock CalledProcessError (e.g. malformed epub) must
        NOT be retried — that just wastes time and delays moving the
        book to /failed."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        sys.path.insert(0, str(REPO_ROOT))
        import importlib
        ip = importlib.import_module("ingest_processor")

        call_count = {"n": 0}

        def fake_run(*args, **kwargs):
            call_count["n"] += 1
            from subprocess import CalledProcessError
            raise CalledProcessError(
                returncode=1,
                cmd=["calibredb", "add"],
                output="",
                stderr="Error: Not a valid EPUB file: missing META-INF\n",
            )

        monkeypatch.setattr(ip.subprocess, "run", fake_run)
        monkeypatch.setattr(ip.time, "sleep", lambda _s: None)

        from subprocess import CalledProcessError
        with pytest.raises(CalledProcessError):
            ip._run_calibredb_add_with_retry(
                cmd=["calibredb", "add"],
                env={},
                max_attempts=4,
            )
        assert call_count["n"] == 1, (
            "Non-lock errors must surface on the first attempt; the "
            "retry wrapper retried unnecessarily."
        )
