# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Tests for the StaticPool → QueuePool deadlock fix.

Verifies:
1. ATTACH pattern works with per-connection initialization (event listener model)
2. Multiple threads get independent SQLite connections (no shared-connection deadlock)
3. duplicates.py functions accept calibre_db parameter for session isolation
"""

import importlib.util
import inspect
import pathlib
import sqlite3
import sys
import threading
from types import ModuleType

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calibre_db_files(tmp_path):
    """Create minimal metadata.db and app.db for ATTACH testing."""
    metadata_db = tmp_path / "metadata.db"
    app_db = tmp_path / "app.db"

    con = sqlite3.connect(str(metadata_db))
    con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    con.execute("INSERT INTO books VALUES (1, 'Test Book')")
    con.commit()
    con.close()

    con = sqlite3.connect(str(app_db))
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO settings VALUES (1, 'test_value')")
    con.commit()
    con.close()

    return str(metadata_db), str(app_db)


# ---------------------------------------------------------------------------
# ATTACH pattern tests (pure sqlite3, no sqlalchemy needed)
# ---------------------------------------------------------------------------

class TestAttachPattern:
    """Verify the in-memory DB + ATTACH pattern used by CalibreDB."""

    def test_attach_makes_tables_visible(self, calibre_db_files):
        """An in-memory DB with ATTACH should see the attached tables."""
        dbpath, app_db_path = calibre_db_files

        conn = sqlite3.connect(":memory:")
        conn.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
        conn.execute(f"ATTACH DATABASE '{app_db_path}' AS app_settings")

        row = conn.execute("SELECT title FROM books WHERE id = 1").fetchone()
        assert row[0] == "Test Book"

        row = conn.execute("SELECT value FROM settings WHERE id = 1").fetchone()
        assert row[0] == "test_value"

        conn.close()

    def test_separate_connections_need_separate_attach(self, calibre_db_files):
        """Each new connection must run ATTACH independently — this is
        why StaticPool (one shared connection) couldn't work with multiple threads."""
        dbpath, app_db_path = calibre_db_files

        conn1 = sqlite3.connect(":memory:")
        conn1.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")

        conn2 = sqlite3.connect(":memory:")
        # conn2 does NOT have ATTACH — should fail
        with pytest.raises(sqlite3.OperationalError):
            conn2.execute("SELECT title FROM books WHERE id = 1")

        # After attaching, conn2 works too
        conn2.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
        row = conn2.execute("SELECT title FROM books WHERE id = 1").fetchone()
        assert row[0] == "Test Book"

        conn1.close()
        conn2.close()

    def test_custom_functions_registered_per_connection(self, calibre_db_files):
        """Custom SQLite functions (uuid4, lower) must be registered on each
        new connection — mirrors the _on_connect event listener in db.py."""
        dbpath, _ = calibre_db_files

        def _make_conn():
            conn = sqlite3.connect(":memory:")
            conn.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
            # Simulate _on_connect registrations
            from uuid import uuid4 as _uuid4
            conn.create_function('uuid4', 0, lambda: str(_uuid4()))
            conn.create_function("lower", 1, lambda s: s.lower() if s else s)
            return conn

        conn1 = _make_conn()
        conn2 = _make_conn()

        # Both connections can use the custom functions independently
        u1 = conn1.execute("SELECT uuid4()").fetchone()[0]
        u2 = conn2.execute("SELECT uuid4()").fetchone()[0]
        assert u1 != u2  # UUIDs should differ

        row = conn1.execute("SELECT lower('HELLO')").fetchone()
        assert row[0] == "hello"

        row = conn2.execute("SELECT lower('WORLD')").fetchone()
        assert row[0] == "world"

        conn1.close()
        conn2.close()


# ---------------------------------------------------------------------------
# Thread isolation tests (pure sqlite3 + threading)
# ---------------------------------------------------------------------------

class TestThreadIsolation:
    """Verify that independent connections in separate threads don't deadlock."""

    def test_concurrent_reads_on_separate_connections(self, calibre_db_files):
        """Two threads with their own connections should read concurrently."""
        dbpath, _ = calibre_db_files
        results = {}
        barrier = threading.Barrier(2, timeout=5)

        def reader(name):
            conn = sqlite3.connect(":memory:")
            conn.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
            row = conn.execute("SELECT title FROM books WHERE id = 1").fetchone()
            results[name] = row[0]
            barrier.wait()  # Both threads hold connections simultaneously
            conn.close()

        t1 = threading.Thread(target=reader, args=("t1",))
        t2 = threading.Thread(target=reader, args=("t2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results == {"t1": "Test Book", "t2": "Test Book"}

    def test_writer_does_not_block_reader_with_wal(self, calibre_db_files):
        """With WAL mode, a writer in one connection shouldn't block
        a reader in another — this is the core concurrency model we rely on."""
        dbpath, _ = calibre_db_files

        # Enable WAL on the database
        setup_conn = sqlite3.connect(dbpath)
        setup_conn.execute("PRAGMA journal_mode=WAL")
        setup_conn.close()

        reader_done = threading.Event()
        writer_done = threading.Event()
        results = {}

        def writer():
            conn = sqlite3.connect(dbpath, timeout=5)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO books VALUES (2, 'New Book')")
            # Hold the write lock while reader tries to read
            reader_done.wait(timeout=5)
            conn.execute("COMMIT")
            conn.close()
            writer_done.set()

        def reader():
            conn = sqlite3.connect(dbpath, timeout=5)
            # Small delay to let writer acquire lock first
            import time
            time.sleep(0.05)
            # With WAL, this should NOT block even though writer holds a lock
            row = conn.execute("SELECT title FROM books WHERE id = 1").fetchone()
            results["reader"] = row[0]
            reader_done.set()
            conn.close()

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start()
        tr.start()
        tr.join(timeout=10)
        tw.join(timeout=10)

        assert results.get("reader") == "Test Book", \
            "Reader should not be blocked by writer in WAL mode"


# ---------------------------------------------------------------------------
# Function signature tests (stubs, no Flask/sqlalchemy imports needed)
# ---------------------------------------------------------------------------

def _install_stub(name, attrs=None):
    module = ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_duplicates_module():
    """Load duplicates.py with minimal stubs (same approach as test_duplicates_timezone.py)."""
    # Save and clear any existing cps modules
    saved = {k: v for k, v in sys.modules.items() if k.startswith("cps")}
    for k in list(saved):
        del sys.modules[k]

    _install_stub("cps")
    _install_stub("cps.db")
    _install_stub("cps.calibre_db")

    class _Logger:
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    _install_stub("cps.logger", {"create": lambda: _Logger()})
    _install_stub("cps.ub", {"session": None, "DismissedDuplicateGroup": object()})
    _install_stub("cps.csrf", {"exempt": lambda f: f})
    _install_stub("cps.config")
    _install_stub("cps.helper")
    _install_stub("cps.services")
    _install_stub("cps.services.worker", {
        "WorkerThread": object, "STAT_FINISH_SUCCESS": 0,
        "STAT_FAIL": 1, "STAT_ENDED": 2, "STAT_CANCELLED": 3,
    })
    _install_stub("cps.admin", {"admin_required": lambda f: f})
    _install_stub("cps.usermanagement", {"login_required_if_no_ano": lambda f: f})
    _install_stub("cps.render_template", {"render_title_template": lambda *a, **k: ""})

    class _User:
        is_authenticated = False
        def role_admin(self): return False
        def role_edit(self): return False

    _install_stub("cps.cw_login", {"current_user": _User()})

    class _Blueprint:
        def __init__(self, *a, **k): pass
        def route(self, *a, **k):
            return lambda fn: fn

    _install_stub("flask", {
        "Blueprint": _Blueprint, "jsonify": lambda *a, **k: None,
        "request": object(), "abort": lambda *a, **k: None,
    })
    _install_stub("flask_babel", {"gettext": lambda t: t})
    _install_stub("sqlalchemy", {"func": object(), "and_": lambda *a, **k: None, "case": lambda *a, **k: None})
    _install_stub("sqlalchemy.sql")
    _install_stub("sqlalchemy.sql.expression", {"true": True, "false": False})
    _install_stub("sqlalchemy.orm", {"joinedload": lambda *a, **k: None})
    _install_stub("cwa_db", {"CWA_DB": type("CWA_DB", (), {"__init__": lambda s: None, "cwa_settings": {}})})

    if "cps.duplicates" in sys.modules:
        del sys.modules["cps.duplicates"]

    duplicates_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "duplicates.py"
    spec = importlib.util.spec_from_file_location("cps.duplicates", duplicates_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.duplicates"] = module
    spec.loader.exec_module(module)

    return module, saved


class TestDuplicatesFunctionSignatures:
    """Verify all 6 duplicates.py functions accept calibre_db parameter."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        self.module, self._saved = _load_duplicates_module()
        yield
        # Restore original modules
        for k in list(sys.modules):
            if k.startswith("cps"):
                del sys.modules[k]
        sys.modules.update(self._saved)

    @pytest.mark.parametrize("fn_name", [
        "find_duplicate_books",
        "find_duplicate_books_sql",
        "find_duplicate_books_python",
        "find_duplicate_candidate_ids_sql",
        "auto_resolve_duplicates",
        "merge_duplicate_group",
    ])
    def test_function_accepts_calibre_db_param(self, fn_name):
        fn = getattr(self.module, fn_name)
        sig = inspect.signature(fn)
        assert "calibre_db" in sig.parameters, \
            f"{fn_name} must accept calibre_db parameter"
        assert sig.parameters["calibre_db"].default is None, \
            f"{fn_name} calibre_db should default to None"
