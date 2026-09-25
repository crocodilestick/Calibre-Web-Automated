# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Argument construction and user-database creation for the Calibre content server.

The command lines are the whole interface to calibre here, and the configured
password travels along them, so both are pinned: what is built for each
configuration, and that the password never reaches a process argument or a log
record. /proc/<pid>/cmdline is world readable, so a password passed as an
argument is visible to every other process on the host for as long as the call
runs.
"""

import importlib.util
import logging
import os
import socket
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PASSWORD = "Sup3rSecret-PW-2026"
REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "cps" / "content_server.py"


class _Config:
    """Stand-in for cps.config carrying only the keys content_server reads."""

    def __init__(self, **overrides):
        self.config_calibre_server_enabled = True
        self.config_calibre_server_port = 7777
        self.config_calibre_server_listen = "127.0.0.1"
        self.config_calibre_server_anonymous_writes = False
        self.config_calibre_server_trusted_ips = ""
        self.config_calibre_server_username = "ccsuser"
        self.config_calibre_server_password_e = PASSWORD
        self.config_calibre_dir = "/calibre-library"
        self.config_binariesdir = "/usr/bin"
        self.__dict__.update(overrides)


@pytest.fixture
def content_server(monkeypatch, tmp_path):
    """Import cps.content_server with its module-level dependencies stubbed out."""
    for name in ("cps", "cps.content_server"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    records = []

    class _Log:
        def _capture(self, level):
            def emit(msg, *args):
                records.append(logging.LogRecord("cps.content_server", level, __file__, 0,
                                                 msg, args, None).getMessage())
            return emit

        def __getattr__(self, item):
            return self._capture(getattr(logging, item.upper(), logging.INFO))

    package = types.ModuleType("cps")
    package.__path__ = [str(REPO_ROOT / "cps")]
    package.config = _Config()
    package.constants = types.SimpleNamespace(
        CONFIG_DIR=str(tmp_path), BASE_DIR="/app/calibre-web-automated")
    package.logger = types.SimpleNamespace(create=lambda: _Log())
    monkeypatch.setitem(sys.modules, "cps", package)

    # Loaded from this checkout by path: the image under test carries its own
    # copy of the app, and a plain import resolves to that one instead.
    spec = importlib.util.spec_from_file_location("cps.content_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.content_server", module)
    spec.loader.exec_module(module)
    module.log_records = records
    return module


def _answering(module, monkeypatch, answering=True):
    monkeypatch.setattr(module, "is_answering", lambda *a, **k: answering)


# --------------------------------------------------------------------------
# calibredb target construction
# --------------------------------------------------------------------------

def test_disabled_server_yields_no_arguments(content_server, monkeypatch):
    content_server.config.config_calibre_server_enabled = False
    _answering(content_server, monkeypatch)
    assert content_server.library_target() == content_server.NO_TARGET


def test_unconfigured_library_yields_no_arguments(content_server, monkeypatch):
    content_server.config.config_calibre_dir = ""
    _answering(content_server, monkeypatch)
    assert content_server.library_target() == content_server.NO_TARGET


def test_authenticated_target_addresses_the_server(content_server, monkeypatch):
    _answering(content_server, monkeypatch)
    target = content_server.library_target()
    assert target.args == ["--with-library", "http://127.0.0.1:7777/#calibre-library",
                           "--username", "ccsuser", "--password", "<stdin>"]


def test_anonymous_target_carries_no_credentials(content_server, monkeypatch):
    content_server.config.config_calibre_server_anonymous_writes = True
    _answering(content_server, monkeypatch)
    target = content_server.library_target()
    assert target.args == ["--with-library", "http://127.0.0.1:7777/#calibre-library"]
    assert target.stdin is None


def test_library_id_is_the_directory_name_without_trailing_separator(content_server, monkeypatch):
    content_server.config.config_calibre_dir = "/books/My Library/"
    _answering(content_server, monkeypatch)
    assert content_server.library_target().args[1] == "http://127.0.0.1:7777/#My Library"


def test_a_server_that_is_not_answering_falls_back_to_the_library_path(content_server, monkeypatch):
    """Convert Library stops the server for its run, and a server can die.

    Callers substitute the library path for an empty target, so ingest and
    metadata embedding keep working instead of aiming at a closed port.
    """
    _answering(content_server, monkeypatch, answering=False)
    assert content_server.library_target() == content_server.NO_TARGET
    assert any("not answering" in record for record in content_server.log_records)


def test_probe_reports_a_closed_port_as_not_answering(content_server):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        content_server.config.config_calibre_server_port = probe.getsockname()[1]
    assert content_server.is_answering(timeout=0.2) is False


def test_probe_reports_an_open_port_as_answering(content_server):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        content_server.config.config_calibre_server_port = listener.getsockname()[1]
        assert content_server.is_answering(timeout=0.5) is True


# --------------------------------------------------------------------------
# calibre-server command line
# --------------------------------------------------------------------------

def test_authenticated_server_arguments(content_server):
    args = content_server.server_arguments()
    assert args[1:] == ["--port", "7777", "--listen-on", "127.0.0.1",
                        "--disable-fallback-to-detected-interface", "--enable-local-write",
                        "--enable-auth", "--auth-mode", "basic",
                        "--userdb", content_server.userdb_path(),
                        "/calibre-library"]


def test_anonymous_writes_pass_trusted_ips(content_server):
    content_server.config.config_calibre_server_anonymous_writes = True
    content_server.config.config_calibre_server_trusted_ips = "10.0.0.0/8,192.168.1.5"
    args = content_server.server_arguments()
    assert "--enable-local-write" in args
    assert args[args.index("--trusted-ips") + 1] == "10.0.0.0/8,192.168.1.5"
    assert "--enable-auth" not in args


def test_trusted_ips_are_omitted_when_empty(content_server):
    content_server.config.config_calibre_server_anonymous_writes = True
    assert "--trusted-ips" not in content_server.server_arguments()


def test_listen_address_defaults_to_loopback(content_server):
    content_server.config.config_calibre_server_listen = ""
    args = content_server.server_arguments()
    assert args[args.index("--listen-on") + 1] == "127.0.0.1"


# --------------------------------------------------------------------------
# user database creation
# --------------------------------------------------------------------------

@pytest.fixture
def userdb_call(content_server, monkeypatch, tmp_path):
    """Capture the subprocess the user-database creation would run."""
    calls = []
    userdb = tmp_path / "content_server_users.sqlite"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        userdb.write_bytes(b"sqlite")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(content_server.subprocess, "run", fake_run)
    content_server.write_userdb("ccsuser", PASSWORD, userdb=str(userdb), binary="/usr/bin/calibre-debug")
    return types.SimpleNamespace(command=calls[0][0], kwargs=calls[0][1], path=userdb,
                                 module=content_server)


def test_userdb_is_created_through_the_calibre_helper(userdb_call):
    assert userdb_call.command[:3] == ["/usr/bin/calibre-debug", "-e",
                                       os.path.join("/app/calibre-web-automated", "scripts",
                                                    "calibre_server_user.py")]
    assert userdb_call.command[-2:] == [str(userdb_call.path), "ccsuser"]


def test_userdb_password_is_supplied_on_stdin(userdb_call):
    assert userdb_call.kwargs["input"] == PASSWORD + "\n"


def test_userdb_password_never_reaches_a_command_argument(userdb_call):
    """The regression this file exists for: an argv password is world readable."""
    assert not any(PASSWORD in str(argument) for argument in userdb_call.command)


def test_userdb_is_not_readable_by_other_users(userdb_call):
    """calibre stores the password in cleartext in this file."""
    if os.name == "nt":
        pytest.skip("POSIX permission bits")
    assert userdb_call.path.stat().st_mode & 0o077 == 0


def test_userdb_failure_is_reported_without_the_password(content_server, monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="cannot open database")

    monkeypatch.setattr(content_server.subprocess, "run", fake_run)
    assert content_server.write_userdb("ccsuser", PASSWORD, userdb=str(tmp_path / "u.sqlite"),
                                       binary="/usr/bin/calibre-debug") is False
    assert any("Failed to create calibre content server user" in r for r in content_server.log_records)
    assert not any(PASSWORD in r for r in content_server.log_records)


# --------------------------------------------------------------------------
# the password stays out of argv and the log, whatever is built
# --------------------------------------------------------------------------

@pytest.mark.parametrize("anonymous", [False, True])
def test_no_built_command_line_carries_the_password(content_server, monkeypatch, anonymous):
    content_server.config.config_calibre_server_anonymous_writes = anonymous
    _answering(content_server, monkeypatch)
    for argument in content_server.server_arguments() + content_server.library_target().args:
        assert PASSWORD not in str(argument)


def test_the_password_is_only_ever_the_stdin_payload(content_server, monkeypatch):
    _answering(content_server, monkeypatch)
    target = content_server.library_target()
    assert target.stdin == PASSWORD + "\n"
    assert "--password" in target.args
    assert target.args[target.args.index("--password") + 1] == "<stdin>"


def test_no_log_record_carries_the_password(content_server, monkeypatch):
    _answering(content_server, monkeypatch, answering=False)
    content_server.library_target()
    content_server.config.config_calibre_server_enabled = False
    content_server.start()
    assert content_server.log_records
    assert not any(PASSWORD in record for record in content_server.log_records)
