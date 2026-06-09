from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
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

    def error_or_exception(self, *args, **kwargs):
        return None


class _Field:
    def __eq__(self, other):
        return ("eq", other)


class _Query:
    def __init__(self, calls):
        self.calls = calls

    def filter(self, *args, **kwargs):
        return self

    def delete(self):
        self.calls.append("format-delete")
        return 1


class _Session:
    def __init__(self, calls):
        self.calls = calls

    def query(self, *args, **kwargs):
        return _Query(self.calls)

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


class _CwaDB:
    instances = []

    def __init__(self):
        self.invalidated = False
        self.cache_updates = []
        self.cwa_settings = {"duplicate_detection_enabled": 1}
        self.resolutions = []
        self.scheduled_cancelled = []
        self.__class__.instances.append(self)

    def invalidate_duplicate_cache(self):
        self.invalidated = True
        return True

    def update_duplicate_cache(self, duplicate_groups, total_count, max_book_id=None):
        self.cache_updates.append((duplicate_groups, total_count, max_book_id))
        return True

    def close(self):
        return None

    def log_duplicate_resolution(self, **kwargs):
        self.resolutions.append(kwargs)

    def scheduled_cancel_for_book(self, book_id):
        self.scheduled_cancelled.append(book_id)
        return 0


def _clear_modules():
    for name in list(sys.modules):
        if (
            name == "cps"
            or name.startswith("cps.")
            or name == "cwa_db"
            or name == "flask"
            or name == "flask_babel"
            or name == "sqlalchemy"
            or name.startswith("sqlalchemy.")
            or name == "werkzeug"
            or name.startswith("werkzeug.")
        ):
            sys.modules.pop(name, None)


def _decorator(func=None, *args, **kwargs):
    if func is None:
        return lambda wrapped: wrapped
    return func


def _install_common_web_stubs():
    class _Blueprint:
        def __init__(self, *args, **kwargs):
            return None

        def route(self, *args, **kwargs):
            return lambda wrapped: wrapped

    _install_stub(
        "flask",
        {
            "Blueprint": _Blueprint,
            "request": SimpleNamespace(form=SimpleNamespace(to_dict=lambda: {}), headers={}, files={}),
            "flash": lambda *args, **kwargs: None,
            "redirect": lambda location: location,
            "url_for": lambda endpoint, **kwargs: f"/{endpoint}",
            "abort": lambda code: (_ for _ in ()).throw(RuntimeError(code)),
            "Response": lambda body=None, **kwargs: body,
            "jsonify": lambda *args, **kwargs: {"args": args, "kwargs": kwargs},
        },
    )
    _install_stub(
        "flask_babel",
        {
            "gettext": lambda text, **kwargs: text % kwargs if kwargs else text,
            "lazy_gettext": lambda text, **kwargs: text % kwargs if kwargs else text,
            "get_locale": lambda: "en",
        },
    )
    _install_stub("werkzeug")
    _install_stub("werkzeug.utils", {"secure_filename": lambda value: value})


def _load_editbooks_module(delete_key_calls):
    _clear_modules()
    _install_common_web_stubs()

    cps = _install_stub("cps")
    logger = _install_stub("cps.logger", {"create": lambda: _Logger()})
    helper = _install_stub("cps.helper", {"delete_book": lambda *args, **kwargs: (True, None)})
    config = _install_stub("cps.config", {"get_book_path": lambda: "/library"})
    calls = []
    calibre_db = _install_stub(
        "cps.calibre_db",
        {"get_book": lambda book_id: SimpleNamespace(id=book_id), "session": _Session(calls)},
    )
    data_cls = SimpleNamespace(book=_Field(), format=_Field())
    db = _install_stub("cps.db", {"Data": data_cls})
    current_user = SimpleNamespace(role_delete_books=lambda: True)

    cps.logger = logger
    cps.helper = helper
    cps.config = config
    cps.calibre_db = calibre_db
    cps.db = db

    for name in ("constants", "isoLanguages", "gdriveutils", "uploader"):
        module = _install_stub(f"cps.{name}")
        setattr(cps, name, module)

    _install_stub("cps.ub")
    _install_stub(
        "cps.user_book_data",
        {"migrate_user_book_data": lambda *a, **k: None,
         "purge_user_book_data": lambda *a, **k: None},
    )
    _install_stub(
        "cps.kobo_sync_status",
        {
            "remove_synced_book": lambda *args, **kwargs: calls.append("kobo"),
            "change_archived_books": lambda *args, **kwargs: None,
        },
    )
    _install_stub("cps.clean_html", {"clean_string": lambda value: value})
    _install_stub("cps.services")
    _install_stub("cps.services.worker", {"WorkerThread": SimpleNamespace(get_instance=lambda: None)})

    from contextlib import contextmanager

    @contextmanager
    def _noop_lock(*args, **kwargs):
        yield

    _install_stub("cps.services.calibre_db_lock", {"metadata_db_write_lock": _noop_lock})
    _install_stub("cps.tasks")
    _install_stub("cps.tasks.upload", {"TaskUpload": object})
    _install_stub("cps.render_template", {"render_title_template": lambda *args, **kwargs: ""})
    _install_stub("cps.redirect", {"get_redirect_location": lambda location, endpoint: location or f"/{endpoint}"})
    _install_stub("cps.file_helper", {"validate_mime_type": lambda *args, **kwargs: True})
    _install_stub("cps.cwa_functions", {"get_ingest_dir": lambda: "/ingest"})
    _install_stub(
        "cps.usermanagement",
        {"user_login_required": _decorator, "login_required_if_no_ano": _decorator},
    )
    _install_stub("cps.string_helper", {"strip_whitespaces": lambda value: value.strip()})
    _install_stub("cps.cw_login", {"current_user": current_user, "login_required": _decorator})
    _install_stub(
        "cps.duplicate_index",
        {
            "delete_book_keys": lambda ids: delete_key_calls.append(list(ids)),
            "get_duplicate_groups_from_index": lambda settings, include_dismissed=False: [],
            "_current_max_book_id": lambda: 1,
        },
    )
    _install_stub("cwa_db", {"CWA_DB": _CwaDB})
    _install_stub(
        "sqlalchemy.exc",
        {
            "OperationalError": Exception,
            "IntegrityError": Exception,
            "InterfaceError": Exception,
            "InvalidRequestError": Exception,
        },
    )
    _install_stub("sqlalchemy.orm")
    _install_stub("sqlalchemy.orm.exc", {"StaleDataError": Exception})
    _install_stub("sqlalchemy.sql")
    _install_stub("sqlalchemy.sql.expression", {"func": SimpleNamespace()})

    editbooks_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "editbooks.py"
    spec = importlib.util.spec_from_file_location("cps.editbooks", editbooks_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.editbooks"] = module
    spec.loader.exec_module(module)
    module.render_delete_book_result = lambda *args, **kwargs: "deleted"
    module.delete_whole_book = lambda book_id, book: calls.append(("whole", book_id))
    return module, calls


def _load_duplicates_module(delete_key_calls):
    _clear_modules()
    _install_common_web_stubs()

    cps = _install_stub("cps")
    logger = _install_stub("cps.logger", {"create": lambda: _Logger()})
    calls = []
    session = _Session(calls)
    calibre_books = {}
    calibre_db = _install_stub(
        "cps.calibre_db",
        {
            "ensure_session": lambda: calls.append("ensure-session"),
            "get_book": lambda book_id: calibre_books.get(book_id),
            "session": session,
        },
    )
    helper = _install_stub("cps.helper", {"delete_book": lambda *args, **kwargs: (True, None)})
    config = _install_stub(
        "cps.config",
        {"config_calibre_dir": "/library", "get_book_path": lambda: "/library"},
    )
    db = _install_stub("cps.db", {"Books": SimpleNamespace(id=_Field())})
    current_user = SimpleNamespace(is_authenticated=True, id=9, role_admin=lambda: True, role_edit=lambda: True)

    cps.logger = logger
    cps.calibre_db = calibre_db
    cps.helper = helper
    cps.config = config
    cps.db = db

    _install_stub("cps.ub", {"init_db_thread": lambda: calls.append("init-db-thread"),
                             "session_commit": lambda *a, **k: None})
    _install_stub(
        "cps.user_book_data",
        {"migrate_user_book_data": lambda *a, **k: None,
         "purge_user_book_data": lambda *a, **k: None},
    )
    _install_stub("cps.csrf", {"exempt": _decorator})
    _install_stub("cps.admin", {"admin_required": _decorator})
    _install_stub("cps.usermanagement", {"login_required_if_no_ano": _decorator})
    _install_stub("cps.render_template", {"render_title_template": lambda *args, **kwargs: ""})
    _install_stub("cps.cw_login", {"current_user": current_user})
    _install_stub(
        "cps.services.worker",
        {
            "WorkerThread": SimpleNamespace(get_instance=lambda: None),
            "STAT_FINISH_SUCCESS": "success",
            "STAT_FAIL": "fail",
            "STAT_ENDED": "ended",
            "STAT_CANCELLED": "cancelled",
        },
    )
    _install_stub("cps.services")
    _install_stub("cps.editbooks", {"delete_whole_book": lambda book_id, book: calls.append(("whole", book_id))})
    _install_stub(
        "cps.duplicate_index",
        {
            "delete_book_keys": lambda ids: delete_key_calls.append(list(ids)),
            "get_duplicate_groups_from_index": lambda settings, include_dismissed=False: [],
            "_current_max_book_id": lambda: 1,
        },
    )
    _install_stub("cwa_db", {"CWA_DB": _CwaDB})
    _install_stub(
        "sqlalchemy",
        {
            "func": SimpleNamespace(),
            "and_": lambda *args: args,
            "or_": lambda *args: args,
            "case": lambda *args, **kwargs: ("case", args, kwargs),
        },
    )
    _install_stub("sqlalchemy.sql")
    _install_stub("sqlalchemy.sql.expression", {"true": lambda: True, "false": lambda: False})
    _install_stub("sqlalchemy.orm", {"joinedload": lambda *args, **kwargs: None})

    duplicates_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "duplicates.py"
    spec = importlib.util.spec_from_file_location("cps.duplicates", duplicates_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.duplicates"] = module
    spec.loader.exec_module(module)
    return module, calibre_books, calls


def test_delete_book_from_table_whole_book_deletes_duplicate_keys_and_refreshes_cache():
    _CwaDB.instances = []
    delete_key_calls = []
    module, calls = _load_editbooks_module(delete_key_calls)

    result = module.delete_book_from_table(12, "", True)

    assert result == "deleted"
    assert ("whole", 12) in calls
    assert "commit" in calls
    assert delete_key_calls == [[12]]
    assert _CwaDB.instances[-1].cache_updates == [([], 0, 1)]
    assert _CwaDB.instances[-1].invalidated is False


def test_delete_book_from_table_format_only_keeps_duplicate_keys_and_invalidates_cache():
    _CwaDB.instances = []
    delete_key_calls = []
    module, calls = _load_editbooks_module(delete_key_calls)

    result = module.delete_book_from_table(12, "EPUB", True)

    assert result == "deleted"
    assert "format-delete" in calls
    assert "commit" in calls
    assert delete_key_calls == []
    assert _CwaDB.instances[-1].invalidated is True


def test_auto_resolve_duplicates_deletes_duplicate_keys_and_refreshes_cache():
    _CwaDB.instances = []
    delete_key_calls = []
    module, calibre_books, calls = _load_duplicates_module(delete_key_calls)
    kept = SimpleNamespace(
        id=1,
        title="Dune",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        data=[],
        path="Dune",
    )
    deleted = SimpleNamespace(
        id=2,
        title="Dune",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        data=[],
        path="Dune Copy",
    )
    calibre_books[1] = kept
    calibre_books[2] = deleted

    with patch("os.path.exists", return_value=False), patch("os.makedirs"):
        result = module.auto_resolve_duplicates(
            strategy="newest",
            duplicate_groups=[
                {
                    "group_hash": "abc123",
                    "title": "Dune",
                    "author": "Frank Herbert",
                    "books": [kept, deleted],
                }
            ],
        )

    assert result["success"] is True
    assert result["deleted_count"] == 1
    assert ("whole", 2) in calls
    assert delete_key_calls == [[2]]
    assert _CwaDB.instances[-1].cache_updates == [([], 0, 1)]
    assert _CwaDB.instances[-1].invalidated is False


def test_auto_resolve_dry_run_does_not_invalidate_duplicate_cache():
    _CwaDB.instances = []
    delete_key_calls = []
    module, _calibre_books, calls = _load_duplicates_module(delete_key_calls)
    kept = SimpleNamespace(
        id=1,
        title="Dune",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        data=[],
        path="Dune",
    )
    deleted = SimpleNamespace(
        id=2,
        title="Dune",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        data=[],
        path="Dune Copy",
    )

    result = module.auto_resolve_duplicates(
        strategy="newest",
        dry_run=True,
        duplicate_groups=[
            {
                "group_hash": "abc123",
                "title": "Dune",
                "author": "Frank Herbert",
                "books": [kept, deleted],
            }
        ],
    )

    assert result["success"] is True
    assert result["deleted_count"] == 1
    assert result["preview"]
    assert ("whole", 2) not in calls
    assert delete_key_calls == []
    assert _CwaDB.instances[-1].invalidated is False


_modules_snapshot: dict[str, "ModuleType"] = {}


def setup_module(module):
    """Snapshot sys.modules so teardown can restore real modules that the
    test file's stubs would otherwise overwrite. Without this, downstream
    test files (e.g. test_helper.py) would either find stubbed packages
    in sys.modules or re-trigger SQLAlchemy mapper registration with
    conflicting table state."""
    _modules_snapshot.clear()
    _modules_snapshot.update(sys.modules)


def teardown_module(module):
    """Restore the pre-test sys.modules. Anything added is removed; anything
    replaced (a stub overwriting a real package) is put back to the real one."""
    for name in list(sys.modules):
        if name not in _modules_snapshot:
            sys.modules.pop(name, None)
    sys.modules.update(_modules_snapshot)
