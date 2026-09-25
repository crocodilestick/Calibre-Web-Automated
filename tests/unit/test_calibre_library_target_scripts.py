# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Library addressing for the scripts that run outside the Flask app.

ingest_processor and cover_enforcer take the same decision as
cps.content_server, but from app.db rather than the loaded config. The cases
that matter are the ones where the two could disagree: credentials supplied
through the environment, and a content server that is switched on but not
running.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "calibre_library_target.py"
LIBRARY = "/calibre-library"
PASSWORD = "Sup3rSecret-PW-2026"

SETTINGS_COLUMNS = ("config_calibre_server_enabled", "config_calibre_server_port",
                    "config_calibre_server_anonymous_writes", "config_calibre_server_username",
                    "config_calibre_server_password_e")


def _make_app_db(path, enabled=1, port=7777, anonymous=0, username="ccsuser", password_e=None):
    con = sqlite3.connect(str(path))
    con.execute("create table settings ({})".format(", ".join(SETTINGS_COLUMNS)))
    con.execute("insert into settings values (?, ?, ?, ?, ?)",
                (enabled, port, anonymous, username, password_e))
    con.commit()
    con.close()


@pytest.fixture
def target_module(monkeypatch, tmp_path):
    for name in ("CALIBRE_SERVER_PORT", "CALIBRE_SERVER_USERNAME", "CALIBRE_SERVER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    app_db = tmp_path / "app.db"

    spec = importlib.util.spec_from_file_location("calibre_library_target_undertest", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "calibre_library_target_undertest", module)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "app_db_path", lambda: str(app_db))
    monkeypatch.setattr(module, "config_dir", lambda: str(tmp_path))
    monkeypatch.setattr(module, "_is_answering", lambda port: True)
    monkeypatch.setattr(module, "_decrypt", lambda token: PASSWORD if token else "")
    module.app_db = app_db
    return module


def test_disabled_server_addresses_the_library_path(target_module):
    _make_app_db(target_module.app_db, enabled=0)
    target = target_module.library_target(LIBRARY)
    assert target.args == ["--library-path=/calibre-library"]
    assert target.stdin is None


def test_enabled_server_is_addressed_with_credentials(target_module):
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    target = target_module.library_target(LIBRARY)
    assert target.args == ["--with-library", "http://127.0.0.1:7777/#calibre-library",
                           "--username", "ccsuser", "--password", "<stdin>"]
    assert target.stdin == PASSWORD + "\n"


def test_password_is_never_an_argument(target_module):
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    target = target_module.library_target(LIBRARY)
    assert not any(PASSWORD in argument for argument in target.args)


def test_anonymous_writes_need_no_credentials(target_module):
    _make_app_db(target_module.app_db, anonymous=1, username="", password_e=None)
    target = target_module.library_target(LIBRARY)
    assert target.args == ["--with-library", "http://127.0.0.1:7777/#calibre-library"]
    assert target.stdin is None


def test_environment_credentials_are_honoured(target_module, monkeypatch):
    """A deployment can configure the server purely through the environment.

    cps.config_sql applies CALIBRE_SERVER_* to the running config and never
    writes it back, so app.db holds no credentials and the scripts would
    otherwise fall back to the library path while the app runs an
    authenticating server.
    """
    _make_app_db(target_module.app_db, username="", password_e=None)
    monkeypatch.setenv("CALIBRE_SERVER_USERNAME", "envuser")
    monkeypatch.setenv("CALIBRE_SERVER_PASSWORD", "env-password")
    target = target_module.library_target(LIBRARY)
    assert target.args[2:] == ["--username", "envuser", "--password", "<stdin>"]
    assert target.stdin == "env-password\n"


def test_environment_port_overrides_the_database(target_module, monkeypatch):
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    monkeypatch.setenv("CALIBRE_SERVER_PORT", "9999")
    assert target_module.library_target(LIBRARY).args[1] == "http://127.0.0.1:9999/#calibre-library"


def test_a_server_that_is_not_running_falls_back_to_the_library_path(target_module, monkeypatch):
    """Convert Library stops the server for its run, and a server can die."""
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    monkeypatch.setattr(target_module, "_is_answering", lambda port: False)
    assert target_module.library_target(LIBRARY).args == ["--library-path=/calibre-library"]


def test_missing_credentials_fall_back_rather_than_fail_authentication(target_module):
    _make_app_db(target_module.app_db, username="", password_e=None)
    assert target_module.library_target(LIBRARY).args == ["--library-path=/calibre-library"]


def test_an_unreadable_app_db_falls_back_to_the_library_path(target_module, monkeypatch):
    monkeypatch.setattr(target_module, "app_db_path", lambda: "/nonexistent/app.db")
    assert target_module.library_target(LIBRARY).args == ["--library-path=/calibre-library"]


def test_library_id_is_the_directory_name(target_module):
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    assert target_module.library_target("/books/My Library/").args[1] == \
        "http://127.0.0.1:7777/#My Library"


def test_the_fallback_says_why_it_fell_back(target_module, monkeypatch, capsys):
    """An operator reading the ingest log can tell the two paths apart."""
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    monkeypatch.setattr(target_module, "_is_answering", lambda port: False)
    target_module.library_target(LIBRARY)
    message = capsys.readouterr().err
    assert "not answering on port 7777" in message
    assert "addressing the library by path instead" in message


def test_the_fallback_message_never_carries_the_password(target_module, monkeypatch, capsys):
    _make_app_db(target_module.app_db, password_e=b"encrypted")
    monkeypatch.setattr(target_module, "_is_answering", lambda port: False)
    target_module.library_target(LIBRARY)
    assert PASSWORD not in capsys.readouterr().err
