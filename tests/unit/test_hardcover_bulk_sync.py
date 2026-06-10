# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #381 regression tests — bulk shelf adds sync to Hardcover.

Adding a single book to a Kobo-synced shelf synced it to Hardcover inline;
all three bulk paths (search mass-add, multi-select, add-series) skipped
Hardcover entirely. Same user intent, different outcome per button.

The fix queues TaskHardcoverBulkSync (cps/tasks/hardcover_sync.py) on the
WorkerThread from every add path via one gate helper in cps/shelf.py
(queue_hardcover_sync). The single path stops blocking the HTTP response on
external API calls; the bulk paths gain the sync.

Behavioural tests load the task module standalone through a stub world
(cps imports Flask at package level); source pins hold the call sites.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import types

import pytest

pytestmark = pytest.mark.unit

_HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
SHELF_SRC = (REPO_ROOT / "cps" / "shelf.py").read_text()
TASK_SRC = (REPO_ROOT / "cps" / "tasks" / "hardcover_sync.py").read_text()


@pytest.fixture(autouse=True)
def _isolate_sys_modules():
    """Restore sys.modules after the stub harness (see D8 test for why)."""
    saved = sys.modules.copy()
    yield
    for name in list(sys.modules):
        if name not in saved:
            del sys.modules[name]
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module


# --- stub world -------------------------------------------------------------

class _StubLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _BooksIdColumn:
    def __eq__(self, other):  # `db.Books.id == book_id` -> the id itself
        return other

    def __hash__(self):
        return id(self)


class _Identifier:
    def __init__(self, id_type, val):
        self.type = id_type
        self.val = val


class _Book:
    def __init__(self, book_id, identifiers):
        self.id = book_id
        self.identifiers = [_Identifier(t, v) for t, v in identifiers]


class _Query:
    def __init__(self, books_by_id):
        self._books_by_id = books_by_id
        self._wanted = None

    def filter(self, arg):
        self._wanted = arg
        return self

    def one_or_none(self):
        return self._books_by_id.get(self._wanted)


class _Session:
    def __init__(self, books_by_id):
        self._books_by_id = books_by_id
        self.closed = False

    def query(self, _model):
        return _Query(self._books_by_id)

    def close(self):
        self.closed = True


class _RecordingClient:
    """get_user_book returns truthy for ids in `existing`; add_book records."""

    instances = []

    def __init__(self, token):
        self.token = token
        self.get_calls = []
        self.add_calls = []
        _RecordingClient.instances.append(self)

    def get_user_book(self, identifiers):
        self.get_calls.append(dict(identifiers))
        return {"id": 1} if identifiers.get("hardcover-id") in self.existing else None

    def add_book(self, identifiers):
        self.add_calls.append(dict(identifiers))
        return {"id": 2}

    existing = set()


def _load_task_module(books_by_id, client_cls=_RecordingClient):
    """Load cps/tasks/hardcover_sync.py against a stubbed cps world."""
    cps_pkg = types.ModuleType("cps")
    cps_pkg.__path__ = []

    logger_mod = types.ModuleType("cps.logger")
    logger_mod.create = lambda: _StubLogger()

    db_mod = types.ModuleType("cps.db")
    session = _Session(books_by_id)

    class _CalibreDB:
        last = None

        def __init__(self, **_kwargs):
            self.session = session
            _CalibreDB.last = self

    class _Books:
        id = _BooksIdColumn()

    db_mod.CalibreDB = _CalibreDB
    db_mod.Books = _Books

    services_pkg = types.ModuleType("cps.services")
    services_pkg.__path__ = []
    hardcover_mod = types.ModuleType("cps.services.hardcover")

    class MissingHardcoverToken(Exception):
        pass

    hardcover_mod.MissingHardcoverToken = MissingHardcoverToken
    hardcover_mod.HardcoverClient = client_cls
    services_pkg.hardcover = hardcover_mod

    worker_mod = types.ModuleType("cps.services.worker")
    worker_mod.STAT_WAITING = 0
    worker_mod.STAT_FAIL = 1
    worker_mod.STAT_FINISH_SUCCESS = 3
    worker_mod.STAT_ENDED = 4
    worker_mod.STAT_CANCELLED = 5

    class CalibreTask:
        def __init__(self, message):
            self.message = message
            self.stat = worker_mod.STAT_WAITING
            self.error = None
            self.progress = 0

        def _handleError(self, error_message):
            self.stat = worker_mod.STAT_FAIL
            self.error = error_message
            self.progress = 1

        def _handleSuccess(self):
            self.stat = worker_mod.STAT_FINISH_SUCCESS
            self.progress = 1

    worker_mod.CalibreTask = CalibreTask

    babel_mod = types.ModuleType("flask_babel")
    babel_mod.lazy_gettext = lambda text: text

    cps_pkg.db = db_mod
    cps_pkg.logger = logger_mod
    cps_pkg.services = services_pkg

    sys.modules["cps"] = cps_pkg
    sys.modules["cps.db"] = db_mod
    sys.modules["cps.logger"] = logger_mod
    sys.modules["cps.services"] = services_pkg
    sys.modules["cps.services.hardcover"] = hardcover_mod
    sys.modules["cps.services.worker"] = worker_mod
    sys.modules["flask_babel"] = babel_mod

    spec = importlib.util.spec_from_file_location(
        "_hardcover_sync_under_test", REPO_ROOT / "cps" / "tasks" / "hardcover_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.INTER_BOOK_DELAY = 0  # keep tests instant
    return module, session


def _books(*specs):
    """specs: (book_id, [(type, val), ...])"""
    return {book_id: _Book(book_id, idents) for book_id, idents in specs}


class TestBulkSyncBehaviour:
    def test_get_or_add_per_book_mirrors_single_semantics(self):
        _RecordingClient.instances = []
        _RecordingClient.existing = {"77"}
        books = _books((1, [("hardcover-id", "42")]),
                       (2, [("hardcover-id", "77")]),   # already on Hardcover
                       (3, [("hardcover-id", "99")]))
        module, session = _load_task_module(books)
        task = module.TaskHardcoverBulkSync("tok", [1, 2, 3], "My Shelf")
        task.run(None)
        client = _RecordingClient.instances[-1]
        assert [c["hardcover-id"] for c in client.get_calls] == ["42", "77", "99"]
        assert [c["hardcover-id"] for c in client.add_calls] == ["42", "99"], (
            "a book already in the user's Hardcover library must be left "
            "alone; the others must be added (single-add semantics, #381)"
        )
        assert (task.synced, task.already_synced) == (2, 1)
        assert task.stat == 3 and task.progress == 1
        assert session.closed, "the task must close its thread-local session"

    def test_books_without_hardcover_identifiers_skip_api(self):
        _RecordingClient.instances = []
        _RecordingClient.existing = set()
        books = _books((1, [("isbn", "9780000000001")]),
                       (2, [("hardcover-id", "42")]))
        module, _session = _load_task_module(books)
        task = module.TaskHardcoverBulkSync("tok", [1, 2], "S")
        task.run(None)
        client = _RecordingClient.instances[-1]
        assert len(client.get_calls) == 1, (
            "books with no hardcover-* identifiers must not cost API calls"
        )
        assert task.skipped_no_identifiers == 1 and task.synced == 1

    def test_one_failing_book_does_not_strand_the_batch(self):
        _RecordingClient.instances = []
        _RecordingClient.existing = set()

        class _FlakyClient(_RecordingClient):
            def get_user_book(self, identifiers):
                if identifiers.get("hardcover-id") == "boom":
                    raise RuntimeError("API exploded")
                return super().get_user_book(identifiers)

        books = _books((1, [("hardcover-id", "42")]),
                       (2, [("hardcover-id", "boom")]),
                       (3, [("hardcover-id", "99")]))
        module, _session = _load_task_module(books, client_cls=_FlakyClient)
        task = module.TaskHardcoverBulkSync("tok", [1, 2, 3], "S")
        task.run(None)
        assert task.synced == 2 and task.errors == 1
        assert task.stat == 3, (
            "per-book error tolerance: partial success is still success (#381)"
        )

    def test_all_errors_fail_the_task(self):
        _RecordingClient.instances = []

        class _DeadClient(_RecordingClient):
            def get_user_book(self, identifiers):
                raise RuntimeError("down")

        books = _books((1, [("hardcover-id", "42")]))
        module, _session = _load_task_module(books, client_cls=_DeadClient)
        task = module.TaskHardcoverBulkSync("tok", [1], "S")
        task.run(None)
        assert task.stat == 1 and task.errors == 1

    def test_missing_token_errors_without_touching_calibre(self):
        class _StrictClient:
            def __init__(self, token):
                raise sys.modules["cps.services.hardcover"].MissingHardcoverToken()

        module, session = _load_task_module({}, client_cls=_StrictClient)
        task = module.TaskHardcoverBulkSync(None, [1], "S")
        task.run(None)
        assert task.stat == 1
        assert not session.closed, "no calibre session should have been opened"

    def test_deleted_book_is_skipped(self):
        _RecordingClient.instances = []
        _RecordingClient.existing = set()
        module, _session = _load_task_module(_books((1, [("hardcover-id", "42")])))
        task = module.TaskHardcoverBulkSync("tok", [1, 999], "S")
        task.run(None)
        assert task.synced == 1 and task.skipped_no_identifiers == 1
        assert task.stat == 3

    def test_cancellation_stops_between_books(self):
        _RecordingClient.instances = []
        _RecordingClient.existing = set()

        class _CancellingClient(_RecordingClient):
            task = None

            def get_user_book(self, identifiers):
                result = super().get_user_book(identifiers)
                _CancellingClient.task.stat = 5  # STAT_CANCELLED
                return result

        books = _books((1, [("hardcover-id", "42")]),
                       (2, [("hardcover-id", "99")]))
        module, _session = _load_task_module(books, client_cls=_CancellingClient)
        task = module.TaskHardcoverBulkSync("tok", [1, 2], "S")
        _CancellingClient.task = task
        task.run(None)
        client = _RecordingClient.instances[-1]
        assert len(client.get_calls) == 1, "cancellation must stop the loop"

    def test_task_is_cancellable(self):
        module, _session = _load_task_module({})
        assert module.TaskHardcoverBulkSync("tok", [], "S").is_cancellable is True


class TestShelfCallSitePins:
    """Every add path must route through the single gate helper (#381)."""

    def test_helper_exists_with_full_gate(self):
        m = re.search(r"def queue_hardcover_sync\(shelf_obj, book_ids\):(.*?)\n@shelf", SHELF_SRC, re.S)
        assert m, "queue_hardcover_sync helper not found in cps/shelf.py"
        body = m.group(1)
        for fragment in ("kobo_sync", "config.config_hardcover_sync",
                         "hardcover_token", "WorkerThread.add",
                         "TaskHardcoverBulkSync"):
            assert fragment in body, f"gate helper must contain {fragment}"

    def test_single_add_uses_helper(self):
        m = re.search(r"def add_to_shelf\(shelf_id, book_id\):(.*?)\n@shelf", SHELF_SRC, re.S)
        assert m and "queue_hardcover_sync(shelf, [book_id])" in m.group(1)

    def test_search_massadd_syncs(self):
        m = re.search(r"def search_to_shelf\(shelf_id\):(.*?)\n@shelf", SHELF_SRC, re.S)
        assert m and "queue_hardcover_sync(shelf, books_for_shelf)" in m.group(1), (
            "search mass-add must queue Hardcover sync for the added books (#381)"
        )

    def test_add_series_syncs(self):
        m = re.search(r"def add_series_to_shelf\(shelf_id, series_id\):(.*?)\n@shelf", SHELF_SRC, re.S)
        assert m and "queue_hardcover_sync(shelf, [book.id for book in to_add])" in m.group(1), (
            "add-series must queue Hardcover sync for the added books (#381)"
        )

    def test_multi_select_syncs(self):
        m = re.search(r"def add_selected_to_shelf\(\):(.*?)\n@shelf", SHELF_SRC, re.S)
        assert m and "queue_hardcover_sync(shelf, added_ids)" in m.group(1), (
            "multi-select add must queue Hardcover sync for the added books (#381)"
        )

    def test_no_inline_client_left_in_routes(self):
        assert "HardcoverClient(" not in SHELF_SRC, (
            "shelf routes must not construct HardcoverClient inline — the "
            "request must not block on external API calls (#381)"
        )

    def test_task_creates_one_client_for_the_batch(self):
        assert TASK_SRC.count("hardcover.HardcoverClient(") == 1, (
            "the task must create one client per batch, not per book"
        )
