# -*- coding: utf-8 -*-

#   This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#     Copyright (C) 2026 OzzieIsaacs
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program. If not, see <http://www.gnu.org/licenses/>.

import os
import socket
import subprocess
import sys
import threading
import time
from collections import namedtuple

from . import config, constants, logger

log = logger.create()

_process = None
_lock = threading.RLock()
_stopped_on_purpose = False

PROBE_TIMEOUT = 0.5
WATCH_INTERVAL = 5
QUIET_BEFORE_RELOAD = 30

# ``args`` extend a calibredb command line; ``stdin`` is the payload that
# command must be fed, or None. They are produced together because the password
# is passed as ``--password <stdin>`` and means nothing without the payload.
LibraryTarget = namedtuple("LibraryTarget", "args stdin")

NO_TARGET = LibraryTarget([], None)


def library_url():
    return "http://127.0.0.1:{}/#{}".format(
        config.config_calibre_server_port,
        os.path.basename(config.config_calibre_dir.rstrip("/")))


def _auth_enabled():
    return bool(not config.config_calibre_server_anonymous_writes
                and config.config_calibre_server_username
                and config.config_calibre_server_password_e)


def is_answering(timeout=PROBE_TIMEOUT):
    """True when something accepts connections on the content server port."""
    try:
        with socket.create_connection(("127.0.0.1", int(config.config_calibre_server_port)), timeout):
            return True
    except (OSError, ValueError):
        return False


def library_target():
    """How calibredb should address the library right now.

    Returns an empty target whenever the content server is disabled or is not
    answering, so callers fall back to the library path. That fallback is safe
    precisely because the server is down: nothing else is holding the library.
    It is what keeps ingest and metadata embedding working while Convert Library
    has the server stopped, and after the server has died.
    """
    if not config.config_calibre_server_enabled or not config.config_calibre_dir:
        return NO_TARGET
    if not is_answering():
        log.warning("Calibre content server is enabled but not answering on port %s, "
                    "addressing the library by path instead", config.config_calibre_server_port)
        return NO_TARGET
    args = ["--with-library", library_url()]
    if _auth_enabled():
        # calibredb reads the password from stdin for the literal value
        # "<stdin>", which keeps it out of the process table.
        args += ["--username", config.config_calibre_server_username, "--password", "<stdin>"]
        return LibraryTarget(args, config.config_calibre_server_password_e + "\n")
    return LibraryTarget(args, None)


def library_arguments():
    """Back-compat shim for callers that cannot feed stdin."""
    return library_target().args


def _db_mtime(db_path):
    mtime = None
    for path in (db_path, db_path + "-wal"):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if mtime is None or stamp > mtime:
            mtime = stamp
    return mtime


def _watch(process, db_path):
    """Keep the running content server honest about the library.

    Two things happen behind its back. calibre-server keeps the library in
    memory and never notices writes made directly to metadata.db (web UI edits,
    ingest, calibredb), so external changes stay invisible to its clients until
    it reloads; it is restarted once the database has changed and then been
    quiet, so it is never bounced in the middle of a burst of writes. The
    process can also die, in which case it is started again rather than left
    down with the setting still switched on.
    """
    last = None
    changed = None
    while True:
        time.sleep(WATCH_INTERVAL)
        with _lock:
            if _process is not process:
                return
            if process.poll() is not None:
                if _stopped_on_purpose:
                    return
                log.error("Calibre content server exited unexpectedly (code %s), restarting it",
                          process.returncode)
                _locked_start()
                return
        mtime = _db_mtime(db_path)
        if mtime is None:
            continue
        if last is None:
            last = mtime
        elif mtime != last:
            last = mtime
            changed = time.time()
        elif changed and time.time() - changed >= QUIET_BEFORE_RELOAD:
            log.info("Library database changed, reloading calibre content server")
            with _lock:
                if _process is process and process.poll() is None:
                    _locked_start()
            return


def server_binary():
    return os.path.join(config.config_binariesdir or "",
                        "calibre-server.exe" if sys.platform == "win32" else "calibre-server")


def debug_binary():
    return os.path.join(config.config_binariesdir or "",
                        "calibre-debug.exe" if sys.platform == "win32" else "calibre-debug")


def userdb_path():
    return os.path.join(constants.CONFIG_DIR, "content_server_users.sqlite")


def write_userdb(username, password, userdb=None, binary=None):
    """Create the single-user database calibre-server authenticates against.

    The password is written to the helper's stdin, never passed as an argument:
    /proc/<pid>/cmdline is world readable, so an argument is visible to every
    other process on the host for as long as the call runs. calibre stores the
    password in cleartext in the resulting sqlite file, so that file is made
    owner-only.
    """
    userdb = userdb or userdb_path()
    binary = binary or debug_binary()
    try:
        os.remove(userdb)
    except OSError:
        pass
    helper = os.path.join(constants.BASE_DIR, "scripts", "calibre_server_user.py")
    result = subprocess.run([binary, "-e", helper, "--", userdb, username],
                            input=password + "\n", capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Failed to create calibre content server user: %s", result.stderr)
        return False
    try:
        os.chmod(userdb, 0o600)
    except OSError as ex:
        log.warning("Could not restrict permissions on %s: %s", userdb, ex)
    return True


def server_arguments():
    """The calibre-server command line for the current configuration."""
    args = [server_binary(), "--port", str(config.config_calibre_server_port),
            "--listen-on", config.config_calibre_server_listen or "127.0.0.1",
            "--disable-fallback-to-detected-interface",
            "--enable-local-write"]
    if config.config_calibre_server_anonymous_writes:
        if config.config_calibre_server_trusted_ips:
            args += ["--trusted-ips", config.config_calibre_server_trusted_ips]
    elif _auth_enabled():
        args += ["--enable-auth", "--auth-mode", "basic", "--userdb", userdb_path()]
    args.append(config.config_calibre_dir)
    return args


def start():
    with _lock:
        _locked_start()


def _locked_start():
    global _process, _stopped_on_purpose
    _locked_stop()
    if not config.config_calibre_server_enabled or not config.config_calibre_dir:
        return
    if not os.path.isfile(server_binary()):
        log.error("calibre-server binary not found: %s", server_binary())
        return
    if _auth_enabled() and not write_userdb(config.config_calibre_server_username,
                                            config.config_calibre_server_password_e):
        return
    _stopped_on_purpose = False
    try:
        _process = subprocess.Popen(server_arguments())
    except OSError as ex:
        log.error("Failed to start calibre content server: %s", ex)
        _process = None
        return
    log.info("Calibre content server started on port %s", config.config_calibre_server_port)
    threading.Thread(target=_watch,
                     args=(_process, os.path.join(config.config_calibre_dir, "metadata.db")),
                     daemon=True).start()


def stop():
    with _lock:
        _locked_stop()


def _locked_stop():
    global _process, _stopped_on_purpose
    _stopped_on_purpose = True
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(10)
        except subprocess.TimeoutExpired:
            _process.kill()
        log.info("Calibre content server stopped")
    _process = None
