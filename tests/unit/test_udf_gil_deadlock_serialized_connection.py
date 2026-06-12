# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression pin for the GIL↔sqlite-mutex AB-BA deadlock.

With sqlite compiled in serialized mode (``sqlite3.threadsafety == 3`` — Linux
CPython builds, i.e. CI and the Docker image), every ``sqlite3_*`` call takes
the per-connection mutex internally, including the short calls pysqlite makes
while HOLDING the GIL (``create_function``, ``reset``, ``bind``, ``finalize``).
If thread B is mid-``step`` (mutex held, GIL released) inside a Python UDF
trampoline waiting for the GIL, and thread A holds the GIL while entering any
such short call on the same connection, the whole process freezes: A waits for
the mutex holding the GIL, B waits for the GIL holding the mutex. No Python
watchdog (pytest-timeout included) can fire — every thread starves.

Observed live as CI runs 27071666487 / 27074461288 (silent 10-minute step
walls) and reachable in production: web greenlets on the main OS thread vs
``WorkerThread``/APScheduler tasks on real threads, all sharing the calibre
StaticPool connection with UDFs registered.

The fix: ``cps.db._SerializedSqliteConnection`` — a per-connection RLock taken
(GIL released while waiting) before every C entry point, wired into both
calibre engines via ``connect_args['factory']``.

These tests drive the EXACT deadlock interleave in a child process (so a
regression can never freeze the test runner itself):
  - thread B steps a query through a slow Python UDF (mutex held for ~1.2s,
    trampoline GIL traffic guaranteed);
  - thread A calls ``create_function`` (the proven GIL-held short call) inside
    that window, then runs a short query.
With the guard factory the child must exit cleanly. Without it (control case,
serialized builds only) the child must freeze — proving the harness actually
detects the deadlock rather than passing vacuously.
"""

import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The deadlock needs sqlite's per-connection mutex, which only exists on
# serialized-mode builds (threadsafety == 3). macOS dev builds are typically
# multi-thread mode (== 1) where the interleave is harmless by construction.
SERIALIZED_BUILD = sqlite3.threadsafety == 3

CHILD_TEMPLATE = textwrap.dedent("""
    import sys
    import threading
    import time

    sys.path.insert(0, {repo_root!r})
    sys.path.insert(0, {scripts_dir!r})

    import sqlite3

    USE_GUARD = {use_guard!r}

    if USE_GUARD:
        from cps.db import _SerializedSqliteConnection
        conn = sqlite3.connect(
            ":memory:", check_same_thread=False,
            factory=_SerializedSqliteConnection)
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)

    WINDOW = 1.2

    def slow_udf():
        # Holds the connection mutex for the whole step; sleeps with the GIL
        # released so the registrar thread is guaranteed to run meanwhile.
        time.sleep(WINDOW)
        return 1

    conn.create_function("slow_udf", 0, slow_udf)

    def stepper():
        cur = conn.execute("SELECT slow_udf()")
        cur.fetchall()

    def registrar():
        time.sleep(0.3)  # let the stepper acquire the mutex first
        # The proven GIL-held short call (and, behind the guard, a wrapped one):
        conn.create_function("other", 0, lambda: 2)
        # ...followed by the everyday short-call path:
        conn.execute("SELECT other()").fetchall()

    t_step = threading.Thread(target=stepper)
    t_reg = threading.Thread(target=registrar)
    t_step.start(); t_reg.start()
    t_step.join(); t_reg.join()
    print("CHILD-OK", flush=True)
""")


def _run_child(use_guard, timeout):
    code = CHILD_TEMPLATE.format(
        repo_root=str(REPO_ROOT),
        scripts_dir=str(REPO_ROOT / "scripts"),
        use_guard=use_guard,
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.unit
class TestSerializedConnectionBreaksDeadlock:
    def test_guarded_connection_survives_the_deadlock_interleave(self):
        """With the factory, the exact AB-BA interleave completes cleanly.

        30s budget vs a ~1.5s happy path (plus cps import time): generous
        enough to never flake, tight enough that a reintroduced deadlock
        fails here as a NAMED test instead of a silent CI step wall.
        """
        try:
            result = _run_child(use_guard=True, timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "guarded child froze: the GIL↔sqlite-mutex deadlock is back "
                "despite _SerializedSqliteConnection — see "
                "notes/fix-udf-gil-deadlock-DESIGN.md"
            )
        assert result.returncode == 0, (
            f"guarded child failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "CHILD-OK" in result.stdout

    @pytest.mark.skipif(
        not SERIALIZED_BUILD,
        reason="deadlock needs serialized-mode sqlite (threadsafety==3); "
               "this build has no per-connection mutex to deadlock on",
    )
    def test_unguarded_connection_freezes_proving_harness_detects(self):
        """Control: WITHOUT the factory the same interleave must freeze.

        This proves the guarded test above passes because the fix works, not
        because the harness lost the ability to construct the deadlock
        (e.g. a future pysqlite releasing the GIL in create_function would
        make this control fail — at which point the guard can be retired).
        """
        try:
            result = _run_child(use_guard=False, timeout=8)
        except subprocess.TimeoutExpired:
            return  # frozen, as the deadlock predicts — harness is sharp
        pytest.fail(
            "unguarded control child exited (rc={}, stdout={!r}) — the "
            "deadlock interleave no longer reproduces, so the guarded test "
            "is not actually exercising the fix. Re-evaluate whether the "
            "platform changed (pysqlite GIL behavior?) before trusting "
            "this suite's coverage.".format(result.returncode, result.stdout)
        )


@pytest.mark.unit
class TestFactoryWiredIntoProductionEngines:
    """Source-pin: both calibre engines pass the guard factory."""

    def test_both_create_engine_sites_use_the_factory(self):
        """Arg-order-agnostic pin: count the calibre engine sites, then count
        connect_args dicts carrying the guard factory — both must be 2."""
        src = (REPO_ROOT / "cps" / "db.py").read_text(encoding="utf-8")
        engine_sites = re.findall(r"create_engine\('sqlite://'", src)
        assert len(engine_sites) == 3, (
            f"expected exactly 3 in-memory calibre engines in cps/db.py "
            f"(StaticPool, NullPool/DESKTOP_COMPAT_MODE, and app-settings), "
            f"found {len(engine_sites)} — update this pin if the architecture "
            f"changed"
        )
        guarded_connect_args = re.findall(
            r"connect_args=\{[^}]*'factory':\s*_SerializedSqliteConnection",
            src,
        )
        assert len(guarded_connect_args) == 3, (
            f"expected the deadlock-guard factory in all calibre engines' "
            f"connect_args, found {len(guarded_connect_args)} — a calibre "
            f"engine without _SerializedSqliteConnection reopens the "
            f"GIL↔sqlite-mutex freeze"
        )

    def test_wrapped_surface_covers_the_dbapi_calls_sqlalchemy_uses(self):
        """The guard only works if the wrapped surface stays complete."""
        from cps.db import _SerializedSqliteConnection, _SerializedSqliteCursor

        for name in ("execute", "executemany", "executescript", "commit",
                     "rollback", "close", "create_function", "cursor"):
            assert name in _SerializedSqliteConnection.__dict__, (
                f"_SerializedSqliteConnection must wrap {name}()"
            )
        for name in ("execute", "executemany", "fetchone", "fetchmany",
                     "fetchall", "__next__", "close"):
            assert name in _SerializedSqliteCursor.__dict__, (
                f"_SerializedSqliteCursor must wrap {name}()"
            )

    def test_default_cursor_factory_is_the_serialized_cursor(self):
        from cps.db import _SerializedSqliteConnection, _SerializedSqliteCursor

        conn = sqlite3.connect(
            ":memory:", check_same_thread=False,
            factory=_SerializedSqliteConnection)
        try:
            cur = conn.cursor()
            assert isinstance(cur, _SerializedSqliteCursor), (
                "cursor() must default to the lock-wrapped cursor class, "
                "otherwise fetch/step paths bypass the guard"
            )
            # And the wrapped surface actually works end-to-end:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        finally:
            conn.close()
