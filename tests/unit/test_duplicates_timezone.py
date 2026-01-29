# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime, timezone
from types import SimpleNamespace, ModuleType
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


def _load_duplicates_module():
    if "cps.duplicates" in sys.modules:
        return sys.modules["cps.duplicates"]

    _install_stub("cps")
    _install_stub("cps.db")
    _install_stub("cps.calibre_db")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

    _install_stub("cps.logger", {"create": lambda: _Logger()})
    _install_stub("cps.ub", {"session": None, "DismissedDuplicateGroup": object()})
    _install_stub("cps.csrf", {"exempt": lambda f: f})
    _install_stub("cps.config")
    _install_stub("cps.helper")

    _install_stub("cps.services")
    _install_stub(
        "cps.services.worker",
        {
            "WorkerThread": object,
            "STAT_FINISH_SUCCESS": 0,
            "STAT_FAIL": 1,
            "STAT_ENDED": 2,
            "STAT_CANCELLED": 3,
        },
    )

    _install_stub("cps.admin", {"admin_required": lambda f: f})
    _install_stub("cps.usermanagement", {"login_required_if_no_ano": lambda f: f})
    _install_stub("cps.render_template", {"render_title_template": lambda *args, **kwargs: ""})

    class _User:
        is_authenticated = False

        def role_admin(self):
            return False

        def role_edit(self):
            return False

    _install_stub("cps.cw_login", {"current_user": _User()})

    class _Blueprint:
        def __init__(self, *args, **kwargs):
            return None

        def route(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    _install_stub(
        "flask",
        {
            "Blueprint": _Blueprint,
            "jsonify": lambda *args, **kwargs: None,
            "request": object(),
            "abort": lambda *args, **kwargs: None,
        },
    )
    _install_stub("flask_babel", {"gettext": lambda text: text})
    _install_stub("sqlalchemy", {"func": object(), "and_": lambda *args, **kwargs: None, "case": lambda *args, **kwargs: None})
    _install_stub("sqlalchemy.sql")
    _install_stub("sqlalchemy.sql.expression", {"true": True, "false": False})
    _install_stub("sqlalchemy.orm", {"joinedload": lambda *args, **kwargs: None})

    class _CWA_DB:
        def __init__(self):
            self.cwa_settings = {}

    _install_stub("cwa_db", {"CWA_DB": _CWA_DB})

    duplicates_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "duplicates.py"
    spec = importlib.util.spec_from_file_location("cps.duplicates", duplicates_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.duplicates"] = module
    spec.loader.exec_module(module)
    return module


def _book(ts):
    return SimpleNamespace(timestamp=ts, data=[], tags=[], series=None, ratings=[], comments=[], publishers=[], pubdate=None, identifiers=[])


def test_select_book_to_keep_handles_naive_and_aware():
    duplicates = _load_duplicates_module()
    naive = datetime(2024, 1, 1, 12, 0, 0)
    aware = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    books = [_book(naive), _book(aware)]

    keep = duplicates.select_book_to_keep(books, "newest")
    assert keep.timestamp == aware


def test_timestamp_or_default_returns_aware_default():
    duplicates = _load_duplicates_module()
    assert duplicates._timestamp_or_default(None, duplicates._AWARE_MIN) == duplicates._AWARE_MIN
