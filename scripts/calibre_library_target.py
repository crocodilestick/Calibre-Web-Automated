# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the out-of-process scripts should address the Calibre library.

The app-side equivalent is ``cps.content_server.library_target``; this is the
same decision taken from app.db, for the ingest and enforcement scripts that do
not import the Flask app.
"""

import os
import socket
import sqlite3
import sys
from collections import namedtuple

try:
    from app_paths import app_db_path, config_dir
except ImportError:  # pragma: no cover - direct execution outside the app tree
    def app_db_path():
        return "/config/app.db"

    def config_dir():
        return "/config"

PROBE_TIMEOUT = 0.5

# ``args`` extend a calibredb command line; ``stdin`` is the payload that
# command must be fed, or None.
LibraryTarget = namedtuple("LibraryTarget", "args stdin")


def _path_target(library_dir):
    return LibraryTarget(["--library-path={}".format(library_dir)], None)


def _announce_fallback(reason):
    """Say why the library is being addressed by path despite the setting.

    Without this the fallback is silent, and an operator reading the ingest log
    cannot tell a run that went through the content server from one that did
    not."""
    print("[calibre-library-target] Content server is enabled but {}; "
          "addressing the library by path instead".format(reason), file=sys.stderr, flush=True)


def _read_settings():
    con = sqlite3.connect("file:{}?mode=ro".format(app_db_path()), uri=True, timeout=5)
    try:
        return con.execute(
            "select config_calibre_server_enabled, config_calibre_server_port, "
            "config_calibre_server_anonymous_writes, config_calibre_server_username, "
            "config_calibre_server_password_e from settings").fetchone()
    finally:
        con.close()


def _apply_env(port, username, password):
    """Apply the same CALIBRE_SERVER_* overrides cps.config_sql applies.

    Those are read into the running app's config and never written back to
    app.db, so a deployment that configures the content server purely through
    the environment leaves no credentials here to find.
    """
    env_port = os.environ.get("CALIBRE_SERVER_PORT")
    if env_port and env_port.isdigit():
        port = int(env_port)
    return (port,
            os.environ.get("CALIBRE_SERVER_USERNAME") or username,
            os.environ.get("CALIBRE_SERVER_PASSWORD") or password)


def _decrypt(token):
    """Decrypt an app.db ``_e`` column with the key Calibre-Web keeps beside it."""
    if not token:
        return ""
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        return ""
    try:
        with open(os.path.join(config_dir(), ".key"), "rb") as handle:
            key = handle.read()
        return Fernet(key).decrypt(token).decode()
    except (OSError, ValueError, InvalidToken):
        return ""


def _is_answering(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), PROBE_TIMEOUT):
            return True
    except (OSError, ValueError):
        return False


def library_target(library_dir):
    """Address the library through the content server when it is actually up.

    While calibre-server is running it caches the library in memory, so writes
    made straight to metadata.db stay invisible to its clients until it reloads;
    going through the server keeps it in step. When the server is disabled, has
    been stopped (Convert Library does that for the length of its run) or has
    died, this falls back to the library path, which is safe exactly because
    nothing is holding the library then.
    """
    try:
        row = _read_settings()
    except sqlite3.Error:
        return _path_target(library_dir)
    if not row or not row[0]:
        return _path_target(library_dir)
    _enabled, port, anonymous_writes, username, password_e = row
    port, username, password = _apply_env(port, username, _decrypt(password_e))
    if not _is_answering(port):
        _announce_fallback("it is not answering on port {}".format(port))
        return _path_target(library_dir)
    args = ["--with-library", "http://127.0.0.1:{}/#{}".format(
        port, os.path.basename(str(library_dir).rstrip("/")))]
    if anonymous_writes:
        return LibraryTarget(args, None)
    if not (username and password):
        _announce_fallback("no content server credentials are configured")
        return _path_target(library_dir)
    # calibredb reads the password from stdin for the literal value "<stdin>",
    # which keeps it out of the process table.
    args += ["--username", username, "--password", "<stdin>"]
    return LibraryTarget(args, password + "\n")


def library_arguments(library_dir):
    """Back-compat shim for callers that cannot feed stdin."""
    return library_target(library_dir).args
