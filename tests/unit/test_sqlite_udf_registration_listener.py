# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pin the SQLite UDF registration contract behind the CWA #1256 root-cause fix.

The deadlock pattern: ``StaticPool`` shares a single SQLite connection across
all threads. A worker thread mid-``func.lower`` query holds the SQLite mutex
while waiting for the Python GIL (to invoke the registered ``lower`` UDF that
SQLite calls back into Python for). A concurrent request handler calling
``conn.create_function(...)`` holds the GIL while waiting for the SQLite mutex.
Classic deadlock.

The fix moves UDF registration out of every request-handler hot path and into
a single ``connect`` event listener that fires once when SQLAlchemy opens the
connection. After this PR, ``conn.create_function`` is never called from a
request handler — the deadlock vector is structurally gone.

These tests pin the contract:
  1. Source-pin every request-handler module is free of ``calibre_db.create_functions``.
  2. Source-pin the engine ``connect`` event listener is registered in both
     ``check_valid_db`` and ``setup_db``.
  3. Source-pin ``init_session`` no longer calls ``create_functions``.
  4. Behavioural: a fresh engine + listener serves ``SELECT lower('FOO')``
     without any explicit per-Session/per-request UDF registration.
  5. Behavioural: ``title_sort`` reads the live ``CalibreDB.config`` so admin
     updates to ``config_title_regex`` take effect without re-registration.
  6. Behavioural: concurrent ``func.lower`` queries on the same StaticPool
     connection make forward progress (smoke test, not a deadlock proof).
"""

import ast
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSourcePinNoRequestHandlerCallsites:
    """Pin that the six request-handler modules are free of UDF re-registration."""

    REQUEST_HANDLER_PATHS = [
        "cps/web.py",
        "cps/editbooks.py",
        "cps/admin.py",
        "cps/helper.py",
        "cps/search.py",
    ]

    def test_no_calibre_db_create_functions_in_request_handlers(self):
        offenders = []
        for relpath in self.REQUEST_HANDLER_PATHS:
            src = _read(REPO_ROOT / relpath)
            for ln, line in enumerate(src.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                if "calibre_db.create_functions" in line:
                    offenders.append(f"{relpath}:{ln}: {stripped}")
        assert not offenders, (
            "calibre_db.create_functions must not be called from request handlers — "
            "it's the GIL+SQLite deadlock vector. Use the engine connect event "
            "listener instead. Offenders:\n  " + "\n  ".join(offenders)
        )

    def test_no_self_create_functions_in_internal_db_hot_paths(self):
        """Three internal db.py methods (get_typeahead, check_exists_book,
        search_query) used to call self.create_functions() before the
        func.lower SQL — same deadlock vector. They must not anymore.
        """
        src = _read(REPO_ROOT / "cps" / "db.py")
        tree = ast.parse(src)
        offenders = []
        target_methods = {"get_typeahead", "check_exists_book", "search_query"}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in target_methods:
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "create_functions"
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "self"
                    ):
                        offenders.append(f"{node.name} (line {sub.lineno})")
        assert not offenders, (
            "self.create_functions() must not be called inside hot-path db.py "
            "methods — UDFs are registered once per connection by the engine "
            "connect listener. Offenders: " + ", ".join(offenders)
        )


@pytest.mark.unit
class TestSourcePinConnectListener:
    """Pin that _register_sqlite_udfs is wired into both engines."""

    def test_module_level_register_function_exists(self):
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert re.search(
            r"^def _register_sqlite_udfs\(dbapi_connection, _connection_record\):",
            src,
            flags=re.MULTILINE,
        ), "module-level _register_sqlite_udfs(...) function must exist in cps/db.py"

    def test_main_engine_registers_listener(self):
        """``setup_db`` must register the listener on ``cls.engine``."""
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert re.search(
            r'event\.listen\(\s*cls\.engine\s*,\s*["\']connect["\']\s*,\s*_register_sqlite_udfs\s*\)',
            src,
        ), "event.listen(cls.engine, 'connect', _register_sqlite_udfs) must be wired in setup_db"

    def test_check_engine_registers_listener(self):
        """``check_valid_db`` builds a temp engine for DB validation — must
        also register the listener, otherwise the validation query crashes
        with `no such function: lower`."""
        src = _read(REPO_ROOT / "cps" / "db.py")
        assert re.search(
            r'event\.listen\(\s*check_engine\s*,\s*["\']connect["\']\s*,\s*_register_sqlite_udfs\s*\)',
            src,
        ), "event.listen(check_engine, 'connect', _register_sqlite_udfs) must be wired in check_valid_db"


@pytest.mark.unit
class TestSourcePinInitSession:
    """init_session must NOT call create_functions anymore — the listener does."""

    def test_init_session_does_not_call_create_functions(self):
        src = _read(REPO_ROOT / "cps" / "db.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "init_session":
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "create_functions"
                    ):
                        pytest.fail(
                            "init_session() must not call create_functions — "
                            "the engine connect event listener handles UDF registration"
                        )
                return
        pytest.fail("init_session method not found in cps/db.py")


@pytest.mark.unit
class TestEngineConnectListenerBehavior:
    """Behavioural: a fresh engine + listener serves func.lower/title_sort
    queries without any explicit per-Session UDF registration.
    """

    def _make_engine_with_listener(self):
        """Build an in-memory SQLite engine wired to the production listener."""
        # Reuse the production listener so any divergence is caught.
        import importlib
        import sys

        # Add scripts/ to sys.path because cps imports something that needs it.
        scripts_dir = REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from cps import db as cps_db

        engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        sa.event.listen(engine, "connect", cps_db._register_sqlite_udfs)
        return engine, cps_db

    def test_lower_udf_available_without_explicit_registration(self):
        engine, cps_db = self._make_engine_with_listener()
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT lower('FOOBAR') AS r")).scalar()
        assert result == "foobar", (
            f"lower('FOOBAR') UDF should be registered automatically; got {result!r}"
        )

    def test_uuid4_udf_available(self):
        engine, cps_db = self._make_engine_with_listener()
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT uuid4() AS r")).scalar()
        assert isinstance(result, str) and len(result) == 36 and result.count("-") == 4, (
            f"uuid4() UDF should return a UUID string; got {result!r}"
        )

    def test_title_sort_with_no_config_strips_whitespace(self):
        """When CalibreDB.config is None or has no regex, title_sort should
        still work as a graceful identity-strip (no exception).
        """
        engine, cps_db = self._make_engine_with_listener()
        prior_config = cps_db.CalibreDB.config
        cps_db.CalibreDB.config = None
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    sa.text("SELECT title_sort('  Hello World  ') AS r")
                ).scalar()
            assert result == "Hello World", (
                f"title_sort with no config should strip whitespace; got {result!r}"
            )
        finally:
            cps_db.CalibreDB.config = prior_config

    def test_title_sort_uses_live_config_regex(self):
        """Updating CalibreDB.config.config_title_regex at runtime should
        affect the next title_sort call (closure reads config at call time).
        """
        engine, cps_db = self._make_engine_with_listener()
        prior_config = cps_db.CalibreDB.config
        # Calibre's default title-sort regex: move leading 'The '/'A '/'An '
        # to the end as ", The".
        cps_db.CalibreDB.config = SimpleNamespace(
            config_title_regex=r"^(A|The|An)\s+"
        )
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    sa.text("SELECT title_sort('The Republic') AS r")
                ).scalar()
            assert result == "Republic, The", (
                f"title_sort('The Republic') should resort to 'Republic, The'; got {result!r}"
            )

            # Now change the regex — next call should use the new regex.
            cps_db.CalibreDB.config = SimpleNamespace(
                config_title_regex=r"^(Doctor)\s+"
            )
            with engine.connect() as conn:
                result = conn.execute(
                    sa.text("SELECT title_sort('Doctor Sleep') AS r")
                ).scalar()
            assert result == "Sleep, Doctor", (
                f"title_sort after config swap should use new regex; got {result!r}"
            )
        finally:
            cps_db.CalibreDB.config = prior_config

    def test_title_sort_handles_none_input(self):
        engine, cps_db = self._make_engine_with_listener()
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT title_sort(NULL) AS r")).scalar()
        assert result == "", (
            f"title_sort(NULL) should return empty string, not crash; got {result!r}"
        )

    def test_title_sort_handles_malformed_regex_gracefully(self):
        """If a future config update lands an invalid regex (typo), title_sort
        should not raise — just fall back to strip_whitespaces. Otherwise
        every query using title_sort breaks until the admin fixes the regex.
        """
        engine, cps_db = self._make_engine_with_listener()
        prior_config = cps_db.CalibreDB.config
        cps_db.CalibreDB.config = SimpleNamespace(
            config_title_regex=r"(unclosed["
        )
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    sa.text("SELECT title_sort('  Some Title  ') AS r")
                ).scalar()
            assert result == "Some Title", (
                f"title_sort with malformed regex should degrade gracefully; got {result!r}"
            )
        finally:
            cps_db.CalibreDB.config = prior_config


@pytest.mark.unit
class TestConcurrentLowerQueriesNoDeadlock:
    """Smoke test: many threads run SELECT lower(...) on the shared StaticPool
    connection concurrently, all complete within a generous timeout.

    NOTE: This does NOT prove the deadlock is gone — proving absence of a race
    is impossible. But it exercises the hot path the fix targets, and would
    fail if the listener didn't register correctly (e.g. some threads would
    OperationalError on 'no such function: lower').
    """

    def _make_engine(self):
        import sys
        scripts_dir = REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from cps import db as cps_db

        engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        sa.event.listen(engine, "connect", cps_db._register_sqlite_udfs)
        return engine

    def test_32_concurrent_lower_queries_all_succeed(self):
        engine = self._make_engine()
        errors = []
        results = []
        barrier = threading.Barrier(32)

        def worker(i):
            try:
                barrier.wait(timeout=5)
                with engine.connect() as conn:
                    r = conn.execute(
                        sa.text(f"SELECT lower('THREAD{i}') AS r")
                    ).scalar()
                    results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert not errors, f"errors during concurrent lower(): {errors[:5]}"
        assert len(results) == 32, f"expected 32 results, got {len(results)}"
        assert all(r.startswith("thread") for r in results), (
            f"some results did not lowercase: {results[:5]}"
        )
        assert elapsed < 30, (
            f"concurrent queries took {elapsed:.1f}s — possible deadlock or "
            f"unexpected contention"
        )

    def test_concurrent_lower_and_title_sort(self):
        """Mix of lower() and title_sort() queries — the two most common UDFs."""
        import sys
        scripts_dir = REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from cps import db as cps_db

        engine = self._make_engine()
        prior_config = cps_db.CalibreDB.config
        cps_db.CalibreDB.config = SimpleNamespace(
            config_title_regex=r"^(A|The|An)\s+"
        )
        try:
            errors = []
            results = []
            barrier = threading.Barrier(16)

            def lower_worker(i):
                try:
                    barrier.wait(timeout=5)
                    with engine.connect() as conn:
                        r = conn.execute(
                            sa.text(f"SELECT lower('MIX{i}') AS r")
                        ).scalar()
                        results.append(("lower", r))
                except Exception as e:
                    errors.append(e)

            def title_sort_worker(i):
                try:
                    barrier.wait(timeout=5)
                    with engine.connect() as conn:
                        r = conn.execute(
                            sa.text(f"SELECT title_sort('The Title {i}') AS r")
                        ).scalar()
                        results.append(("title_sort", r))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=lower_worker, args=(i,)) for i in range(8)] + \
                      [threading.Thread(target=title_sort_worker, args=(i,)) for i in range(8)]
            t0 = time.monotonic()
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            elapsed = time.monotonic() - t0

            assert not errors, f"errors during mixed UDF workload: {errors[:5]}"
            assert len(results) == 16, f"expected 16 results, got {len(results)}"
            assert elapsed < 30, (
                f"mixed UDF concurrent queries took {elapsed:.1f}s — possible deadlock"
            )
        finally:
            cps_db.CalibreDB.config = prior_config


@pytest.mark.unit
class TestCreateFunctionsBackwardsCompatShim:
    """The public ``create_functions(self, config=None)`` method is preserved
    as a no-op so any external caller (downstream plugin, tests) doesn't
    break. The contract: the method exists, accepts ``(self, config=None)``,
    is callable without error, and does NOT raise — it must not touch
    ``self.session`` or call ``conn.create_function`` anymore (those would
    re-introduce the deadlock vector this PR closes).
    """

    def test_shim_method_exists_with_compatible_signature(self):
        import sys
        scripts_dir = REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from cps import db as cps_db
        import inspect

        sig = inspect.signature(cps_db.CalibreDB.create_functions)
        params = list(sig.parameters.values())
        assert len(params) == 2, (
            f"expected (self, config=None); got {len(params)} params"
        )
        assert params[0].name == "self"
        assert params[1].name == "config"
        assert params[1].default is None, (
            "config parameter must default to None for backward compat"
        )

    def test_shim_source_does_not_call_create_function(self):
        """The shim must not call ``conn.create_function`` — that's the
        deadlock vector this PR closes. Source-pin via AST.
        """
        import ast
        src = _read(REPO_ROOT / "cps" / "db.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_functions":
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "create_function"
                    ):
                        pytest.fail(
                            "create_functions shim must not call "
                            "conn.create_function — UDFs are registered "
                            "by the engine connect listener"
                        )
                return
        pytest.fail("create_functions method not found in cps/db.py")

    def test_shim_source_does_not_touch_self_session(self):
        """The shim must not touch ``self.session`` — that was the old
        path that obtained the connection to register UDFs. The new model
        registers via the engine event listener at connection time.
        """
        import ast
        src = _read(REPO_ROOT / "cps" / "db.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "create_functions":
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Attribute)
                        and sub.attr == "session"
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"
                    ):
                        pytest.fail(
                            "create_functions shim must not access "
                            "self.session — the no-op shim must not touch "
                            "the connection"
                        )
                return
        pytest.fail("create_functions method not found")
