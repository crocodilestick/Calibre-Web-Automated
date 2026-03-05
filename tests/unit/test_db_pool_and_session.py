# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests proving the StaticPool -> QueuePool deadlock fix.

The claim: StaticPool shares a single DBAPI sqlite3.Connection across all
threads. When WorkerThread holds that connection (long query), gevent
greenlets block on the DBAPI connection's internal mutex, freezing the
web server. QueuePool gives each thread its own connection, eliminating
contention.

These tests prove this at the SQLAlchemy level (not raw sqlite3) to match
the actual CalibreDB usage pattern: scoped_session + engine + pool.
"""

import sqlite3
import threading
import time

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_files(tmp_path):
    """Create metadata.db and app.db with test data, mirroring CalibreDB's ATTACH targets."""
    metadata_db = tmp_path / "metadata.db"
    app_db = tmp_path / "app.db"

    con = sqlite3.connect(str(metadata_db))
    con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    for i in range(1, 101):
        con.execute("INSERT INTO books VALUES (?, ?)", (i, f"Book {i}"))
    con.execute("PRAGMA journal_mode=WAL")
    con.commit()
    con.close()

    con = sqlite3.connect(str(app_db))
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO settings VALUES (1, 'test')")
    con.commit()
    con.close()

    return str(metadata_db), str(app_db)


def _make_engine(poolclass, db_files, **pool_kwargs):
    """Create an engine mimicking CalibreDB.setup_db with the given pool class."""
    dbpath, app_db_path = db_files

    kwargs = dict(
        echo=False,
        isolation_level="SERIALIZABLE",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=poolclass,
    )
    kwargs.update(pool_kwargs)
    engine = create_engine("sqlite://", **kwargs)

    if poolclass is StaticPool:
        # StaticPool: one connection, ATTACH once (original CalibreDB pattern)
        with engine.begin() as connection:
            connection.execute(text(f"ATTACH DATABASE '{dbpath}' AS calibre"))
            connection.execute(text(f"ATTACH DATABASE '{app_db_path}' AS app_settings"))
            connection.execute(text("PRAGMA calibre.journal_mode=WAL"))
    else:
        # QueuePool: per-connection ATTACH via event listener (the PR's fix)
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, connection_record):
            dbapi_conn.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
            dbapi_conn.execute(f"ATTACH DATABASE '{app_db_path}' AS app_settings")
            dbapi_conn.execute("PRAGMA calibre.journal_mode=WAL")

    return engine


# ---------------------------------------------------------------------------
# Core proof: StaticPool shares one DBAPI connection, QueuePool doesn't
# ---------------------------------------------------------------------------

class TestConnectionSharing:
    """Prove that StaticPool gives the same DBAPI connection to different threads,
    while QueuePool gives each thread its own."""

    def test_staticpool_returns_same_dbapi_connection_to_different_threads(self, db_files):
        """Two threads using scoped_session over StaticPool get the SAME underlying
        sqlite3.Connection object. This is the root cause: Python's sqlite3 module
        has a per-connection mutex, so concurrent access serializes."""
        engine = _make_engine(StaticPool, db_files)
        factory = scoped_session(sessionmaker(bind=engine))

        dbapi_ids = {}

        def capture_conn_id(name):
            session = factory()
            conn = session.connection()
            dbapi_ids[name] = id(conn.connection.dbapi_connection)
            factory.remove()

        t1 = threading.Thread(target=capture_conn_id, args=("worker",))
        t2 = threading.Thread(target=capture_conn_id, args=("web",))
        t1.start(); t1.join()
        t2.start(); t2.join()

        assert dbapi_ids["worker"] == dbapi_ids["web"], \
            "StaticPool must return the same DBAPI connection to both threads"

        engine.dispose()

    def test_queuepool_returns_different_dbapi_connections_to_different_threads(self, db_files):
        """Two threads using scoped_session over QueuePool get DIFFERENT underlying
        sqlite3.Connection objects. No shared mutex = no contention."""
        engine = _make_engine(QueuePool, db_files, pool_size=2, max_overflow=0)
        factory = scoped_session(sessionmaker(bind=engine))

        dbapi_ids = {}
        barrier = threading.Barrier(2, timeout=5)

        def capture_conn_id(name):
            session = factory()
            conn = session.connection()
            dbapi_ids[name] = id(conn.connection.dbapi_connection)
            barrier.wait()  # Hold both connections open simultaneously
            factory.remove()

        t1 = threading.Thread(target=capture_conn_id, args=("worker",))
        t2 = threading.Thread(target=capture_conn_id, args=("web",))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        assert dbapi_ids["worker"] != dbapi_ids["web"], \
            "QueuePool must return different DBAPI connections to different threads"

        engine.dispose()


# ---------------------------------------------------------------------------
# Core proof: StaticPool causes thread contention, QueuePool doesn't
# ---------------------------------------------------------------------------

HOLD_SECONDS = 0.3


class TestThreadContention:
    """Prove the deadlock mechanism: when one thread holds the shared StaticPool
    connection, another thread's query blocks until it's released."""

    def test_staticpool_worker_blocks_web_thread(self, db_files):
        """Thread A holds the DBAPI connection via a slow custom SQLite function.
        Thread B's simple query is delayed by the full hold duration.
        This reproduces the production deadlock at the SQLAlchemy level."""
        engine = _make_engine(StaticPool, db_files)
        factory = scoped_session(sessionmaker(bind=engine))

        worker_started = threading.Event()
        results = {}

        def slow_func():
            worker_started.set()
            time.sleep(HOLD_SECONDS)
            return 1

        def worker_thread():
            session = factory()
            dbapi = session.connection().connection.dbapi_connection
            dbapi.create_function("slow_func", 0, slow_func)
            session.execute(text("SELECT slow_func()"))
            factory.remove()

        def web_thread():
            worker_started.wait(timeout=5)
            time.sleep(0.02)  # Ensure worker is mid-query
            t0 = time.monotonic()
            session = factory()
            session.execute(text("SELECT 1"))
            results["elapsed"] = time.monotonic() - t0
            factory.remove()

        tw = threading.Thread(target=worker_thread)
        tg = threading.Thread(target=web_thread)
        tw.start(); tg.start()
        tw.join(timeout=5); tg.join(timeout=5)

        assert results["elapsed"] >= HOLD_SECONDS * 0.5, (
            f"Web thread should be blocked for ~{HOLD_SECONDS}s by StaticPool "
            f"contention, but only waited {results['elapsed']:.3f}s"
        )

        engine.dispose()

    def test_queuepool_worker_does_not_block_web_thread(self, db_files):
        """Same scenario as above, but with QueuePool. Thread B's query completes
        instantly because it gets its own connection from the pool."""
        engine = _make_engine(QueuePool, db_files, pool_size=2, max_overflow=0)
        factory = scoped_session(sessionmaker(bind=engine))

        worker_started = threading.Event()
        results = {}

        def slow_func():
            worker_started.set()
            time.sleep(HOLD_SECONDS)
            return 1

        def worker_thread():
            session = factory()
            dbapi = session.connection().connection.dbapi_connection
            dbapi.create_function("slow_func", 0, slow_func)
            session.execute(text("SELECT slow_func()"))
            factory.remove()

        def web_thread():
            worker_started.wait(timeout=5)
            time.sleep(0.02)  # Ensure worker is mid-query
            t0 = time.monotonic()
            session = factory()
            session.execute(text("SELECT count(*) FROM books"))
            results["elapsed"] = time.monotonic() - t0
            factory.remove()

        tw = threading.Thread(target=worker_thread)
        tg = threading.Thread(target=web_thread)
        tw.start(); tg.start()
        tw.join(timeout=5); tg.join(timeout=5)

        assert results["elapsed"] < 0.1, (
            f"Web thread should NOT be blocked by worker with QueuePool, "
            f"but waited {results['elapsed']:.3f}s"
        )

        engine.dispose()


# ---------------------------------------------------------------------------
# QueuePool + event listener: ATTACH works on every pooled connection
# ---------------------------------------------------------------------------

class TestQueuePoolAttach:
    """Prove that the event listener pattern correctly ATTACHes databases
    on every new pooled connection, so all threads see the calibre schema."""

    def test_all_pooled_connections_see_attached_tables(self, db_files):
        """Multiple threads simultaneously query attached tables.
        Each gets its own connection with ATTACH applied by the event listener."""
        engine = _make_engine(QueuePool, db_files, pool_size=3, max_overflow=0)
        factory = scoped_session(sessionmaker(bind=engine))

        results = {}
        barrier = threading.Barrier(3, timeout=5)

        def query_thread(name):
            session = factory()
            count = session.execute(text("SELECT count(*) FROM books")).scalar()
            setting = session.execute(text("SELECT value FROM settings WHERE id=1")).scalar()
            conn_id = id(session.connection().connection.dbapi_connection)
            results[name] = {"count": count, "setting": setting, "conn_id": conn_id}
            barrier.wait()
            factory.remove()

        threads = [threading.Thread(target=query_thread, args=(f"t{i}",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == 3, "All 3 threads should complete"
        for name, data in results.items():
            assert data["count"] == 100, f"{name} should see all 100 books"
            assert data["setting"] == "test", f"{name} should see app_settings"

        conn_ids = {d["conn_id"] for d in results.values()}
        assert len(conn_ids) == 3, "Each thread should have its own connection"

        engine.dispose()

    def test_custom_functions_available_on_every_pooled_connection(self, db_files):
        """uuid4() and lower() registered in the event listener should be usable
        by any thread on any pooled connection."""
        from uuid import uuid4 as _uuid4

        dbpath, app_db_path = db_files
        engine = create_engine(
            "sqlite://", poolclass=QueuePool, pool_size=2, max_overflow=0,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, connection_record):
            dbapi_conn.execute(f"ATTACH DATABASE '{dbpath}' AS calibre")
            dbapi_conn.create_function("uuid4", 0, lambda: str(_uuid4()))
            dbapi_conn.create_function("lower", 1, lambda s: s.lower() if s else s)

        factory = scoped_session(sessionmaker(bind=engine))
        results = {}
        barrier = threading.Barrier(2, timeout=5)

        def use_functions(name):
            session = factory()
            uid = session.execute(text("SELECT uuid4()")).scalar()
            low = session.execute(text("SELECT lower('HELLO')")).scalar()
            results[name] = {"uuid": uid, "lower": low}
            barrier.wait()
            factory.remove()

        t1 = threading.Thread(target=use_functions, args=("t1",))
        t2 = threading.Thread(target=use_functions, args=("t2",))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        assert results["t1"]["lower"] == "hello"
        assert results["t2"]["lower"] == "hello"
        assert results["t1"]["uuid"] != results["t2"]["uuid"], "UUIDs should differ"

        engine.dispose()


# ---------------------------------------------------------------------------
# Worker session isolation: separate CalibreDB instances don't contend
# ---------------------------------------------------------------------------

class TestWorkerSessionIsolation:
    """Prove that worker tasks creating their own sessions (the second part of
    the PR's fix) actually get independent connections from the pool."""

    def test_independent_sessions_from_same_engine_get_different_connections(self, db_files):
        """Two sessionmaker instances bound to the same QueuePool engine should
        check out different connections — simulating web singleton + worker instance."""
        engine = _make_engine(QueuePool, db_files, pool_size=3, max_overflow=0)
        web_factory = scoped_session(sessionmaker(bind=engine))
        worker_factory = sessionmaker(bind=engine)  # Not scoped — one-off like worker tasks

        results = {}
        barrier = threading.Barrier(2, timeout=5)

        def web_greenlet():
            session = web_factory()
            results["web_conn"] = id(session.connection().connection.dbapi_connection)
            barrier.wait()
            web_factory.remove()

        def worker_thread():
            session = worker_factory()
            results["worker_conn"] = id(session.connection().connection.dbapi_connection)
            barrier.wait()
            session.close()

        tw = threading.Thread(target=web_greenlet)
        tg = threading.Thread(target=worker_thread)
        tw.start(); tg.start()
        tw.join(timeout=10); tg.join(timeout=10)

        assert results["web_conn"] != results["worker_conn"], \
            "Web and worker sessions should get different pooled connections"

        engine.dispose()

    def test_worker_long_query_does_not_block_web_with_separate_sessions(self, db_files):
        """Full simulation: worker runs slow query via its own session,
        web session queries concurrently without blocking. This is the
        end-to-end proof that the PR's approach works."""
        engine = _make_engine(QueuePool, db_files, pool_size=3, max_overflow=0)
        web_factory = scoped_session(sessionmaker(bind=engine))
        worker_factory = sessionmaker(bind=engine)

        worker_started = threading.Event()
        results = {}

        def slow_func():
            worker_started.set()
            time.sleep(HOLD_SECONDS)
            return 1

        def worker_thread():
            session = worker_factory()
            dbapi = session.connection().connection.dbapi_connection
            dbapi.create_function("slow_func", 0, slow_func)
            session.execute(text("SELECT slow_func()"))
            session.close()

        def web_greenlet():
            worker_started.wait(timeout=5)
            time.sleep(0.02)
            t0 = time.monotonic()
            session = web_factory()
            count = session.execute(text("SELECT count(*) FROM books")).scalar()
            results["elapsed"] = time.monotonic() - t0
            results["count"] = count
            web_factory.remove()

        tw = threading.Thread(target=worker_thread)
        tg = threading.Thread(target=web_greenlet)
        tw.start(); tg.start()
        tw.join(timeout=5); tg.join(timeout=5)

        assert results["elapsed"] < 0.1, (
            f"Web query should not be blocked by worker's slow query, "
            f"but waited {results['elapsed']:.3f}s"
        )
        assert results["count"] == 100

        engine.dispose()
