# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Tests for DESKTOP_COMPAT_MODE — the NullPool connection strategy that
releases the SQLite file lock after every request so calibre desktop can open
the same library between web requests.

Coverage:
  - Source pins: DESKTOP_COMPAT_MODE branch exists; NullPool is used; connect
    listener performs ATTACH for both databases; setup conn is closed at end.
  - Behavioural: NullPool engine with the ATTACH closure actually serves
    queries against an attached calibre database.
  - Behavioural: session.remove() fully releases the connection (the core
    property that makes calibre desktop coexistence possible).
  - Behavioural: busy_timeout is set on each new connection.
"""

import ast
import re
import sqlite3
import sys
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker, scoped_session


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_calibre_db(path: Path) -> None:
    """Write the bare minimum calibre schema into a SQLite file so ATTACH +
    SELECT queries work in tests without a full calibre installation."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Unknown',
            sort TEXT,
            author_sort TEXT,
            timestamp TIMESTAMP,
            pubdate TIMESTAMP,
            series_index TEXT NOT NULL DEFAULT '1.0',
            last_modified TIMESTAMP,
            path TEXT NOT NULL DEFAULT '',
            has_cover INTEGER DEFAULT 0,
            uuid TEXT
        );
        CREATE TABLE IF NOT EXISTS library_id (
            id  INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL
        );
        INSERT OR IGNORE INTO library_id VALUES (1, 'test-library-uuid');
        CREATE TABLE IF NOT EXISTS custom_columns (
            id INTEGER PRIMARY KEY,
            label TEXT,
            name TEXT,
            datatype TEXT,
            mark_for_delete INTEGER,
            editable INTEGER,
            display TEXT,
            is_multiple INTEGER,
            normalized INTEGER
        );
    """)
    con.commit()
    con.close()


def _minimal_app_db(path: Path) -> None:
    """Write a minimal app_settings (calibre-web user) schema."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY,
            nickname TEXT
        );
    """)
    con.commit()
    con.close()


def _build_nullpool_engine(dbpath: str, app_db_path: str):
    """Replicate what setup_db does in DESKTOP_COMPAT_MODE.

    Uses plain sqlite3 (no cps imports) so the test is self-contained and
    doesn't require the full Flask/SQLAlchemy stack to be installed locally.
    The UDF and _SerializedSqliteConnection aspects are covered by the
    existing test_sqlite_udf_registration_listener.py suite.

    Returns the engine. Caller is responsible for disposing.
    """
    from sqlalchemy.pool import NullPool

    _dbpath = dbpath
    _app_db_path = app_db_path

    def _attach_and_configure(dbapi_connection, _connection_record):
        cur = dbapi_connection.cursor()
        try:
            cur.execute("ATTACH DATABASE ? AS calibre", (_dbpath,))
            cur.execute("ATTACH DATABASE ? AS app_settings", (_app_db_path,))
            cur.execute("PRAGMA busy_timeout=60000")
        finally:
            cur.close()

    engine = sa.create_engine(
        "sqlite://",
        echo=False,
        isolation_level="SERIALIZABLE",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )
    sa.event.listen(engine, "connect", _attach_and_configure)
    return engine


# ---------------------------------------------------------------------------
# Source-level pins
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSourcePinDesktopCompatMode:
    """Pin the structural invariants of the DESKTOP_COMPAT_MODE branch in
    setup_db so a future refactor can't quietly remove the behaviour without
    a test failure.
    """

    def test_env_var_check_exists_in_setup_db(self):
        """setup_db must read DESKTOP_COMPAT_MODE from the environment."""
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert "DESKTOP_COMPAT_MODE" in src, (
            "DESKTOP_COMPAT_MODE env var check not found in cps/db.py"
        )

    def test_nullpool_imported_and_used_in_setup_db(self):
        """The desktop_compat branch must import NullPool and pass it as
        poolclass — that's the mechanism that releases the lock after each
        request.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert "NullPool" in src, "NullPool must be referenced in cps/db.py"
        assert "poolclass=NullPool" in src, (
            "poolclass=NullPool must be set in the DESKTOP_COMPAT_MODE branch"
        )

    def test_connect_listener_attaches_calibre_database(self):
        """The per-connection listener in the desktop_compat branch must
        ATTACH the calibre database — without this, every request-level
        connection would be a bare in-memory DB with no tables.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        # The ATTACH must reference 'calibre' as the schema name (same as
        # StaticPool branch) so all existing ORM queries keep working.
        assert re.search(r"ATTACH DATABASE.+AS calibre", src), (
            "The desktop_compat connect listener must ATTACH the calibre database"
        )

    def test_connect_listener_attaches_app_settings_database(self):
        """app_settings must also be ATTACHed per-connection — user data
        (ReadBook, ArchivedBook, etc.) lives there.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert re.search(r"ATTACH DATABASE.+AS app_settings", src), (
            "The desktop_compat connect listener must ATTACH app_settings"
        )

    def test_setup_conn_is_closed_in_desktop_compat_branch(self):
        """With NullPool the setup conn is not the shared persistent
        connection. It must be explicitly closed so the file lock is released
        before normal request handling begins.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        # Look for conn.close() inside a desktop_compat guard block.
        # We accept any of: conn.close() / try: conn.close() etc.
        assert "conn.close()" in src, (
            "setup_db must call conn.close() to release the NullPool setup "
            "connection before request handling begins (DESKTOP_COMPAT_MODE)"
        )

    def test_desktop_compat_busy_timeout_set_per_connection(self):
        """busy_timeout must be set in the per-connection listener so every
        request connection inherits it, not just the one-time setup conn.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        # The busy_timeout PRAGMA must appear inside the _attach_and_configure
        # closure (i.e. after the desktop_compat check and before the else
        # block for StaticPool). We verify it's present at all — the
        # behavioural test confirms it fires on each new connection.
        assert src.count("PRAGMA busy_timeout=60000") >= 2, (
            "busy_timeout=60000 must be set both in the StaticPool branch and "
            "inside the NullPool connect listener"
        )


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDesktopCompatModeConnectListener:
    """Verify the NullPool + ATTACH closure pattern actually works end-to-end
    against a real (minimal) calibre database file.
    """

    def test_calibre_tables_accessible_via_attached_schema(self, tmp_path):
        """Queries against calibre.books work when ATTACH fires on connect."""
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    sa.text("SELECT id FROM calibre.books")
                ).fetchall()
            # Empty is fine — we just need no OperationalError.
            assert isinstance(rows, list)
        finally:
            engine.dispose()

    def test_app_settings_tables_accessible_via_attached_schema(self, tmp_path):
        """Queries against app_settings.user work when ATTACH fires on connect."""
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    sa.text("SELECT id FROM app_settings.user")
                ).fetchall()
            assert isinstance(rows, list)
        finally:
            engine.dispose()

    def test_sql_scalar_functions_available_on_nullpool_connection(self, tmp_path):
        """SQL scalar functions work on each NullPool connection.

        _build_nullpool_engine omits _register_sqlite_udfs to stay self-contained,
        so this exercises SQLite's built-in lower() rather than the custom UDF.
        Custom UDF registration is covered by test_sqlite_udf_registration_listener.py.
        """
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    sa.text("SELECT lower('DESKTOP') AS r")
                ).scalar()
            assert result == "desktop"
        finally:
            engine.dispose()

    def test_busy_timeout_set_on_each_new_connection(self, tmp_path):
        """Each NullPool connection must have busy_timeout set — verify by
        reading the PRAGMA value back from two successive connections.
        """
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            for _ in range(2):
                with engine.connect() as conn:
                    timeout = conn.execute(
                        sa.text("PRAGMA busy_timeout")
                    ).scalar()
                assert timeout == 60000, (
                    f"Expected busy_timeout=60000, got {timeout!r}"
                )
        finally:
            engine.dispose()


@pytest.mark.unit
class TestDesktopCompatModeLockRelease:
    """The whole point of DESKTOP_COMPAT_MODE: the SQLite file lock is released
    after session.remove() so an external process (calibre desktop) can open
    the database between web requests.
    """

    def test_session_remove_releases_file_lock(self, tmp_path):
        """After scoped_session.remove(), a separate sqlite3 connection must
        be able to open the database in exclusive mode — proof that NullPool
        actually closed the connection and released the lock.
        """
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            session_factory = scoped_session(
                sessionmaker(autocommit=False, autoflush=True, bind=engine, future=True)
            )

            # Open a session and run a query (this acquires a connection).
            session = session_factory()
            session.execute(sa.text("SELECT 1"))

            # Connection is held — calibre desktop can't get in yet.
            # (We don't assert this half; the important half is after remove().)

            # Simulate Flask's teardown_appcontext: session_factory.remove()
            session_factory.remove()

            # With NullPool the connection is now fully closed. A new sqlite3
            # connection in exclusive mode must succeed immediately.
            probe = sqlite3.connect(str(dbpath), timeout=0.5)
            try:
                probe.execute("BEGIN EXCLUSIVE")
                probe.execute("COMMIT")
            finally:
                probe.close()

            # If we reach here, the lock was released — calibre desktop can
            # open the library between requests.
        finally:
            engine.dispose()

    def test_multiple_request_cycles_each_release_lock(self, tmp_path):
        """Simulate several request/teardown cycles — each must release the
        lock, not accumulate held connections.
        """
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        try:
            session_factory = scoped_session(
                sessionmaker(autocommit=False, autoflush=True, bind=engine, future=True)
            )

            for i in range(5):
                # Simulate a request.
                session = session_factory()
                session.execute(sa.text("SELECT 1"))
                # Simulate teardown_appcontext.
                session_factory.remove()

                # Verify lock is free after every cycle.
                probe = sqlite3.connect(str(dbpath), timeout=0.5)
                try:
                    probe.execute("BEGIN EXCLUSIVE")
                    probe.execute("COMMIT")
                finally:
                    probe.close()
        finally:
            engine.dispose()

    def test_concurrent_requests_do_not_leave_stale_connections(self, tmp_path):
        """Multiple threads each run a request cycle and call remove(). After
        all threads finish, the database must be unlocked.
        """
        dbpath = tmp_path / "metadata.db"
        app_db_path = tmp_path / "app_settings.db"
        _minimal_calibre_db(dbpath)
        _minimal_app_db(app_db_path)

        engine = _build_nullpool_engine(str(dbpath), str(app_db_path))
        errors = []

        try:
            session_factory = scoped_session(
                sessionmaker(autocommit=False, autoflush=True, bind=engine, future=True)
            )

            barrier = threading.Barrier(8)

            def request_cycle():
                try:
                    barrier.wait(timeout=5)
                    session = session_factory()
                    session.execute(sa.text("SELECT 1"))
                    session_factory.remove()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=request_cycle) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            assert not errors, f"Thread errors during request cycles: {errors}"

            # All threads done — database must be fully unlocked.
            probe = sqlite3.connect(str(dbpath), timeout=0.5)
            try:
                probe.execute("BEGIN EXCLUSIVE")
                probe.execute("COMMIT")
            finally:
                probe.close()
        finally:
            engine.dispose()
