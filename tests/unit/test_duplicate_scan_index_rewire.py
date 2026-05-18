# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from types import ModuleType, SimpleNamespace
import importlib.util
import pathlib
import sys


def _install_stub(name, attrs=None):
    module = ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(module, key, value)
    sys.modules[name] = module
    return module


class _Logger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _CalibreTask:
    def __init__(self, message):
        self.id = "task-id"
        self.message = message
        self.progress = 0
        self.stat = None
        self.success = False
        self.error = None

    def _handleSuccess(self):
        self.success = True

    def _handleError(self, message):
        self.error = message


class _TaskCwaDB:
    instances = []

    def __init__(self):
        self.cwa_settings = {
            "duplicate_auto_resolve_enabled": 0,
            "duplicate_auto_resolve_strategy": "newest",
            "duplicate_auto_resolve_cooldown_minutes": 0,
        }
        self.cache_updates = []
        self.cur = SimpleNamespace(
            execute=lambda *args, **kwargs: SimpleNamespace(fetchone=lambda: [None])
        )
        self.con = SimpleNamespace(commit=lambda: None)
        self.__class__.instances.append(self)

    def get_duplicate_cache(self):
        return {"last_scanned_book_id": 42, "scan_pending": False}

    def update_duplicate_cache(self, duplicate_groups, total_count, max_book_id=None):
        self.cache_updates.append((duplicate_groups, total_count, max_book_id))
        return True


def _clear_modules():
    for name in list(sys.modules):
        if (
            name == "cps"
            or name.startswith("cps.")
            or name == "cwa_db"
            or name == "sqlalchemy"
            or name.startswith("sqlalchemy.")
        ):
            sys.modules.pop(name, None)


def _load_duplicate_scan_module(monkeypatch, calls):
    _clear_modules()
    cps = _install_stub("cps")
    calibre_db = _install_stub(
        "cps.calibre_db",
        {
            "ensure_session": lambda: None,
            "session": SimpleNamespace(close=lambda: None),
        },
    )
    db = _install_stub("cps.db", {"Books": SimpleNamespace(id=object())})
    logger = _install_stub("cps.logger", {"create": lambda: _Logger()})
    cps.calibre_db = calibre_db
    cps.db = db
    cps.logger = logger

    def _rebuild(settings, progress_callback=None):
        calls.append(("rebuild", settings))
        if progress_callback:
            progress_callback(1, 3)
            progress_callback(3, 3)
        return {"max_book_id": 99, "indexed_count": 3, "fingerprint": "fp"}

    def _groups(settings, include_dismissed=False, user_id=None, candidate_book_ids=None):
        calls.append(("groups", include_dismissed, user_id, candidate_book_ids))
        return [{"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}]

    _install_stub(
        "cps.duplicate_index",
        {
            "rebuild_duplicate_index": _rebuild,
            "MAX_INCREMENTAL_BOOK_IDS": 1000,
            "get_effective_duplicate_criteria": lambda settings: {"title": True, "author": True},
            "get_duplicate_groups_from_index": _groups,
            "has_valid_duplicate_index_baseline": lambda settings, candidate_book_ids=None: True,
            "ingest_batch_follow_up_pending": lambda: False,
            "mark_duplicate_index_pending": lambda reason=None: True,
            "merge_affected_groups_into_cache": lambda candidate_book_ids, settings: {
                "updated": True,
                "pending": False,
                "merged_count": 1,
            },
        },
    )

    def _legacy_scan(*args, **kwargs):
        raise AssertionError("find_duplicate_books should not be used for full scans")

    auto_resolve_calls = []

    def _auto_resolve_duplicates(**kwargs):
        auto_resolve_calls.append(kwargs)
        return {"success": True, "resolved_count": 1, "kept_count": 1, "deleted_count": 1}

    duplicates = _install_stub(
        "cps.duplicates",
        {
            "find_duplicate_books": _legacy_scan,
            "find_duplicate_books_python": lambda *args, **kwargs: [],
            "find_duplicate_candidate_ids_sql": lambda *args, **kwargs: [],
            "find_duplicate_books_sql": lambda *args, **kwargs: [],
            "auto_resolve_duplicates": _auto_resolve_duplicates,
        },
    )
    cps.duplicates = duplicates
    _install_stub("cps.services")
    _install_stub(
        "cps.services.worker",
        {
            "CalibreTask": _CalibreTask,
            "STAT_CANCELLED": "cancelled",
            "STAT_ENDED": "ended",
        },
    )
    _install_stub("cps.ub", {"init_db_thread": lambda: None})
    _install_stub("flask_babel", {"lazy_gettext": lambda text, **kwargs: text % kwargs if kwargs else text})
    _install_stub("sqlalchemy", {"func": SimpleNamespace(max=lambda value: value)})
    _install_stub("cwa_db", {"CWA_DB": _TaskCwaDB})

    task_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "tasks" / "duplicate_scan.py"
    spec = importlib.util.spec_from_file_location("cps.tasks.duplicate_scan", task_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps.tasks"
    sys.modules["cps.tasks.duplicate_scan"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CWA_DB", _TaskCwaDB)
    return module, auto_resolve_calls


def test_full_duplicate_scan_rebuilds_index_and_updates_cache(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []

    task = module.TaskDuplicateScan(full_scan=True, trigger_type="scheduled", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 1
    assert calls == [
        ("rebuild", _TaskCwaDB.instances[0].cwa_settings),
        ("groups", False, 7, None),
        ("groups", True, None, None),
    ]
    assert _TaskCwaDB.instances[0].cache_updates == [
        ([{"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}], 1, 99)
    ]


def test_full_duplicate_scan_skips_when_ingest_active(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    monkeypatch.setattr(module, "ingest_batch_follow_up_pending", lambda: True)

    task = module.TaskDuplicateScan(full_scan=True, trigger_type="scheduled", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 0
    assert task.message == "Duplicate scan skipped: import in progress"
    assert calls == []


def test_scheduled_duplicate_scan_uses_global_unresolved_groups(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []

    task = module.TaskDuplicateScan(full_scan=True, trigger_type="scheduled")
    task.run(worker_thread=None)

    assert task.success is True
    assert ("groups", False, None, None) in calls
    assert ("groups", True, None, None) in calls


def test_full_duplicate_scan_passes_unresolved_groups_to_auto_resolution(monkeypatch):
    calls = []
    module, auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []

    task = module.TaskDuplicateScan(full_scan=True, trigger_type="manual", user_id=7)
    first_db = _TaskCwaDB()
    first_db.cwa_settings["duplicate_auto_resolve_enabled"] = 1
    monkeypatch.setattr(module, "CWA_DB", lambda: first_db)

    task.run(worker_thread=None)

    assert auto_resolve_calls
    assert auto_resolve_calls[0]["duplicate_groups"] == task.found_duplicate_groups
    assert auto_resolve_calls[0]["user_id"] is None
    assert auto_resolve_calls[0]["trigger_type"] == "automatic"


def _make_legacy_raise(module, monkeypatch):
    duplicates = sys.modules["cps.duplicates"]

    def _raise_legacy(*args, **kwargs):
        raise AssertionError("after_import must not call legacy duplicate scans")

    monkeypatch.setattr(duplicates, "find_duplicate_books", _raise_legacy)
    monkeypatch.setattr(duplicates, "find_duplicate_books_python", _raise_legacy)
    monkeypatch.setattr(duplicates, "find_duplicate_books_sql", _raise_legacy)
    if hasattr(module, "find_duplicate_candidate_ids_sql"):
        monkeypatch.setattr(module, "find_duplicate_candidate_ids_sql", lambda *args, **kwargs: [50, 51])


class _BookIdColumn:
    def __gt__(self, other):
        return ("book_id_gt", other)


class _BookIdQuery:
    def __init__(self, book_ids, max_book_id=None):
        self.book_ids = book_ids
        self.max_book_id = max_book_id if max_book_id is not None else max(book_ids or [0])

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, limit):
        self.book_ids = self.book_ids[:limit]
        return self

    def all(self):
        return [(book_id,) for book_id in self.book_ids]

    def scalar(self):
        return self.max_book_id


class _BookIdSession:
    def __init__(self, book_ids, max_book_id=None):
        self.book_ids = book_ids
        self.max_book_id = max_book_id

    def query(self, *args, **kwargs):
        return _BookIdQuery(self.book_ids, self.max_book_id)


def _stub_incremental_book_ids(module, book_ids, max_book_id=None):
    module.db.Books.id = _BookIdColumn()
    module.calibre_db.session = _BookIdSession(book_ids, max_book_id=max_book_id)


def test_after_import_valid_baseline_merges_index_without_legacy_scans(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []
    merge_calls = []

    baseline_calls = []

    def _baseline(settings, candidate_book_ids=None):
        baseline_calls.append((settings, list(candidate_book_ids or [])))
        indexed_count = 2
        library_count = 3
        return indexed_count + len(set(candidate_book_ids or [])) >= library_count

    _stub_incremental_book_ids(module, [50], max_book_id=50)
    monkeypatch.setattr(module, "has_valid_duplicate_index_baseline", _baseline)
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )
    monkeypatch.setattr(
        module,
        "merge_affected_groups_into_cache",
        lambda candidate_book_ids, settings: merge_calls.append((list(candidate_book_ids), settings))
        or {"updated": True, "pending": False, "merged_count": 1},
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 1
    assert pending_reasons == []
    assert baseline_calls == [(_TaskCwaDB.instances[0].cwa_settings, [50])]
    assert merge_calls == [([50], _TaskCwaDB.instances[0].cwa_settings)]
    assert ("groups", False, 7, [50]) in calls


def test_after_import_uses_provided_book_ids_without_candidate_lookup(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    merge_calls = []

    monkeypatch.setattr(module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: True)
    monkeypatch.setattr(
        module,
        "merge_affected_groups_into_cache",
        lambda candidate_book_ids, settings: merge_calls.append((list(candidate_book_ids), settings))
        or {"updated": True, "pending": False, "merged_count": 1},
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7, book_ids=[12, "13", 12])
    task.run(worker_thread=None)

    assert task.success is True
    assert merge_calls == [([12, 13], _TaskCwaDB.instances[0].cwa_settings)]
    assert ("groups", False, 7, [12, 13]) in calls


def test_after_import_missing_baseline_marks_pending_after_candidate_lookup(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []

    monkeypatch.setattr(
        module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: False
    )
    _stub_incremental_book_ids(module, [50], max_book_id=50)
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )
    _stub_incremental_book_ids(module, [50], max_book_id=50)

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 0
    assert pending_reasons == ["after_import without valid duplicate index baseline"]
    assert calls == []


def test_after_import_stale_fingerprint_marks_pending(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []

    monkeypatch.setattr(
        module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: False
    )
    _stub_incremental_book_ids(module, [50], max_book_id=50)
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.message == "Duplicate scan pending: manual scan required"
    assert pending_reasons == ["after_import without valid duplicate index baseline"]
    assert calls == []


def test_after_import_too_many_new_books_marks_pending(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []

    monkeypatch.setattr(module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: True)
    _stub_incremental_book_ids(module, list(range(1, module.MAX_INCREMENTAL_BOOK_IDS + 2)))
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 0
    assert pending_reasons == ["after_import incremental book set too large"]
    assert calls == []


def test_after_import_empty_candidate_set_does_not_merge_or_mark_pending(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []

    monkeypatch.setattr(module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: True)
    _stub_incremental_book_ids(module, [])
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )
    monkeypatch.setattr(
        module,
        "merge_affected_groups_into_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("merge should not run")),
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 0
    assert pending_reasons == []
    assert calls == []


def test_after_import_merge_failure_marks_pending(monkeypatch):
    calls = []
    module, _auto_resolve_calls = _load_duplicate_scan_module(monkeypatch, calls)
    _TaskCwaDB.instances = []
    _make_legacy_raise(module, monkeypatch)
    pending_reasons = []

    monkeypatch.setattr(module, "has_valid_duplicate_index_baseline", lambda settings, candidate_book_ids=None: True)
    _stub_incremental_book_ids(module, [50], max_book_id=50)
    monkeypatch.setattr(
        module, "mark_duplicate_index_pending", lambda reason=None: pending_reasons.append(reason) or True
    )
    monkeypatch.setattr(
        module,
        "merge_affected_groups_into_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("merge failed")),
    )

    task = module.TaskDuplicateScan(full_scan=False, trigger_type="after_import", user_id=7)
    task.run(worker_thread=None)

    assert task.success is True
    assert task.result_count == 0
    assert pending_reasons == ["after_import incremental duplicate merge failed"]
    assert calls == []


class _RouteCwaDB:
    instances = []
    cache_data = {"scan_pending": True, "duplicate_groups": [], "last_scanned_book_id": 0}

    def __init__(self):
        self.cwa_settings = {
            "duplicate_auto_resolve_enabled": 0,
            "duplicate_auto_resolve_strategy": "newest",
        }
        self.invalidated = False
        self.cache_updates = []
        self.__class__.instances.append(self)

    def invalidate_duplicate_cache(self):
        self.invalidated = True

    def get_duplicate_cache(self):
        return self.__class__.cache_data

    def update_duplicate_cache(self, duplicate_groups, total_count, max_book_id=None):
        self.cache_updates.append((duplicate_groups, total_count, max_book_id))
        return True


def _load_duplicates_route_module(
    monkeypatch,
    calls,
    baseline_valid=True,
    render_calls=None,
    library_has_books=True,
    ingest_pending=False,
):
    _clear_modules()
    _RouteCwaDB.cache_data = {"scan_pending": not baseline_valid, "duplicate_groups": [], "last_scanned_book_id": 55 if baseline_valid else 0}
    cps = _install_stub("cps")
    for name in ("db", "calibre_db", "ub", "config", "helper"):
        module = _install_stub(f"cps.{name}")
        setattr(cps, name, module)
    logger = _install_stub("cps.logger", {"create": lambda: _Logger()})
    csrf = _install_stub("cps.csrf", {"exempt": lambda fn: fn})
    cps.logger = logger
    cps.csrf = csrf

    class _WorkerThread:
        @staticmethod
        def add(*args, **kwargs):
            raise RuntimeError("queue unavailable")

    _install_stub("cps.services")
    _install_stub(
        "cps.services.worker",
        {
            "WorkerThread": _WorkerThread,
            "STAT_FINISH_SUCCESS": 0,
            "STAT_FAIL": 1,
            "STAT_ENDED": 2,
            "STAT_CANCELLED": 3,
        },
    )
    _install_stub("cps.admin", {"admin_required": lambda fn: fn})
    _install_stub("cps.usermanagement", {"login_required_if_no_ano": lambda fn: fn})
    def _render_title_template(*args, **kwargs):
        if render_calls is not None:
            render_calls.append((args, kwargs))
        return kwargs

    _install_stub("cps.render_template", {"render_title_template": _render_title_template})
    user = SimpleNamespace(
        id=7,
        name="tester",
        is_authenticated=True,
        role_admin=lambda: True,
        role_edit=lambda: True,
    )
    _install_stub("cps.cw_login", {"current_user": user})

    class _Blueprint:
        def __init__(self, *args, **kwargs):
            return None

        def route(self, *args, **kwargs):
            return lambda fn: fn

    _install_stub(
        "flask",
        {
            "Blueprint": _Blueprint,
            "jsonify": lambda payload=None, **kwargs: payload if payload is not None else kwargs,
            "request": object(),
            "abort": lambda *args, **kwargs: None,
        },
    )
    _install_stub("flask_babel", {"gettext": lambda text, **kwargs: text % kwargs if kwargs else text})
    _install_stub("sqlalchemy", {"func": object(), "and_": lambda *args, **kwargs: None, "case": lambda *args, **kwargs: None})
    _install_stub("sqlalchemy.sql")
    _install_stub("sqlalchemy.sql.expression", {"true": True, "false": False})
    _install_stub("sqlalchemy.orm", {"joinedload": lambda *args, **kwargs: None})
    _install_stub("cwa_db", {"CWA_DB": _RouteCwaDB})

    def _rebuild(settings):
        calls.append(("rebuild", settings))
        return {"max_book_id": 55, "indexed_count": 2, "fingerprint": "fp"}

    def _groups(settings, include_dismissed=False, user_id=None, candidate_book_ids=None):
        calls.append(("groups", include_dismissed, user_id, candidate_book_ids))
        if not library_has_books:
            return []
        return [{"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}]

    _install_stub(
        "cps.duplicate_index",
        {
            "rebuild_duplicate_index": _rebuild,
            "get_duplicate_groups_from_index": _groups,
            "duplicate_index_needs_manual_full_scan": lambda settings: not baseline_valid,
            "has_valid_duplicate_index_baseline": lambda settings, candidate_book_ids=None: baseline_valid,
            "library_has_books": lambda: library_has_books,
            "ingest_batch_follow_up_pending": lambda: ingest_pending,
        },
    )

    duplicates_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "duplicates.py"
    spec = importlib.util.spec_from_file_location("cps.duplicates", duplicates_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.duplicates"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CWA_DB", _RouteCwaDB)
    monkeypatch.setattr(module, "find_duplicate_books", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))
    return module


def test_duplicates_page_prompts_for_full_scan_when_index_baseline_missing(monkeypatch):
    calls = []
    render_calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, baseline_valid=False, render_calls=render_calls)

    response = module.show_duplicates()

    assert response["duplicate_index_needs_full_scan"] is True
    assert response["duplicate_groups"] == []
    assert calls == []
    assert render_calls


def test_duplicates_page_does_not_prompt_for_full_scan_when_library_empty(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, baseline_valid=False, library_has_books=False)

    response = module.show_duplicates()

    assert response["duplicate_index_needs_full_scan"] is False
    assert response["duplicate_groups"] == []
    assert calls == [("groups", False, 7, None)]


def test_duplicates_page_uses_index_when_baseline_exists(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, baseline_valid=True)

    response = module.show_duplicates()

    assert response["duplicate_index_needs_full_scan"] is False
    assert response["duplicate_groups"] == [
        {"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}
    ]
    assert calls == [("groups", False, 7, None)]


def test_duplicate_status_ignores_old_cache_when_index_baseline_missing(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, baseline_valid=False)
    _RouteCwaDB.cache_data = {
        "scan_pending": False,
        "duplicate_groups": [
            {"title": "Dune", "author": "Frank Herbert", "count": 2, "group_hash": "abc"},
        ],
        "last_scanned_book_id": 55,
    }

    response = module.get_duplicate_status()

    assert response["success"] is True
    assert response["count"] == 0
    assert response["preview"] == []
    assert response["cached"] is False
    assert response["stale"] is True
    assert response["needs_scan"] is True
    assert response["needs_full_scan"] is True


def test_duplicate_status_does_not_require_scan_when_library_empty(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, baseline_valid=False, library_has_books=False)
    _RouteCwaDB.cache_data = {
        "scan_pending": True,
        "duplicate_groups": [],
        "last_scanned_book_id": 0,
    }

    response = module.get_duplicate_status()

    assert response["success"] is True
    assert response["count"] == 0
    assert response["cached"] is True
    assert response["stale"] is True
    assert response["needs_scan"] is False
    assert response["needs_full_scan"] is False


def test_manual_trigger_sync_fallback_rebuilds_index_and_cache(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls)
    _RouteCwaDB.instances = []

    response = module.trigger_scan()

    assert response["success"] is True
    assert response["fallback"] is True
    assert response["count"] == 1
    assert calls == [
        ("rebuild", _RouteCwaDB.instances[0].cwa_settings),
        ("groups", False, 7, None),
        ("groups", True, None, None),
    ]
    assert _RouteCwaDB.instances[0].invalidated is True
    assert _RouteCwaDB.instances[0].cache_updates == [
        ([{"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}], 1, 55)
    ]


def test_manual_trigger_blocks_full_scan_while_ingest_pending(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, ingest_pending=True)
    _RouteCwaDB.instances = []

    response, status = module.trigger_scan()

    assert status == 409
    assert response["blocked"] is True
    assert response["reason"] == "ingest_in_progress"
    assert calls == []
    assert _RouteCwaDB.instances == []


def test_execute_resolution_blocks_while_ingest_pending(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls, ingest_pending=True)
    flask_module = sys.modules["flask"]
    flask_module.request = SimpleNamespace(json={"strategy": "newest"})
    auto_resolve_calls = []
    monkeypatch.setattr(
        module,
        "auto_resolve_duplicates",
        lambda **kwargs: auto_resolve_calls.append(kwargs) or {"success": True},
    )

    response, status = module.execute_resolution()

    assert status == 409
    assert response["blocked"] is True
    assert response["reason"] == "ingest_in_progress"
    assert "Import is in progress" in response["message"]
    assert auto_resolve_calls == []


def test_preview_resolution_uses_indexed_duplicate_groups(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls)
    flask_module = sys.modules["flask"]
    flask_module.request = SimpleNamespace(json={"strategy": "newest"})
    auto_resolve_calls = []
    expected_result = {
        "success": True,
        "resolved_count": 1,
        "kept_count": 1,
        "deleted_count": 1,
        "errors": [],
        "preview": [{"title": "Dune"}],
    }
    monkeypatch.setattr(
        module,
        "auto_resolve_duplicates",
        lambda **kwargs: auto_resolve_calls.append(kwargs) or expected_result,
    )

    response = module.preview_resolution()

    assert response == expected_result
    assert auto_resolve_calls
    assert auto_resolve_calls[0]["duplicate_groups"] == [
        {"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}
    ]
    assert auto_resolve_calls[0]["dry_run"] is True
    assert calls == [("groups", False, 7, None)]


def test_execute_resolution_uses_indexed_duplicate_groups(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls)
    flask_module = sys.modules["flask"]
    flask_module.request = SimpleNamespace(json={"strategy": "newest"})
    auto_resolve_calls = []
    monkeypatch.setattr(
        module,
        "auto_resolve_duplicates",
        lambda **kwargs: auto_resolve_calls.append(kwargs) or {"success": True},
    )

    response = module.execute_resolution()

    assert response["success"] is True
    assert auto_resolve_calls
    assert auto_resolve_calls[0]["duplicate_groups"] == [
        {"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}
    ]
    assert auto_resolve_calls[0]["dry_run"] is False
    assert calls == [("groups", False, 7, None)]


def test_manual_trigger_sync_fallback_passes_unresolved_groups_to_auto_resolution(monkeypatch):
    calls = []
    module = _load_duplicates_route_module(monkeypatch, calls)
    fallback_db = _RouteCwaDB()
    fallback_db.cwa_settings["duplicate_auto_resolve_enabled"] = 1
    auto_resolve_calls = []

    monkeypatch.setattr(module, "CWA_DB", lambda: fallback_db)
    monkeypatch.setattr(
        module,
        "auto_resolve_duplicates",
        lambda **kwargs: auto_resolve_calls.append(kwargs)
        or {"success": True, "resolved_count": 1, "kept_count": 1, "deleted_count": 1},
    )

    response = module.trigger_scan()

    assert response["success"] is True
    assert response["fallback"] is True
    assert [call[0] for call in calls] == ["rebuild", "groups", "groups", "rebuild", "groups", "groups"]
    assert auto_resolve_calls
    assert auto_resolve_calls[0]["duplicate_groups"] == [
        {"title": "Dune", "author": "Frank Herbert", "count": 2, "books": []}
    ]
    assert auto_resolve_calls[0]["user_id"] == 7
    assert auto_resolve_calls[0]["trigger_type"] == "manual"


_modules_snapshot: dict = {}


def setup_module(module):
    _modules_snapshot.clear()
    _modules_snapshot.update(sys.modules)


def teardown_module(module):
    for name in list(sys.modules):
        if name not in _modules_snapshot:
            sys.modules.pop(name, None)
    sys.modules.update(_modules_snapshot)
