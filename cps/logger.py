# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import sys
import inspect
import logging
from logging import Formatter, StreamHandler
from logging.handlers import RotatingFileHandler

from .constants import CONFIG_DIR as _CONFIG_DIR


ACCESS_FORMATTER_GEVENT  = Formatter("%(message)s")
ACCESS_FORMATTER_TORNADO = Formatter("[%(asctime)s] %(message)s")

FORMATTER           = Formatter("[%(asctime)s] %(levelname)5s {%(name)s:%(lineno)d} %(message)s")
DEFAULT_LOG_LEVEL   = logging.INFO
DEFAULT_LOG_FILE    = os.path.join(_CONFIG_DIR, "calibre-web.log")
DEFAULT_ACCESS_LOG  = os.path.join(_CONFIG_DIR, "access.log")
LOG_TO_STDERR       = '/dev/stderr'
LOG_TO_STDOUT       = '/dev/stdout'

logging.addLevelName(logging.WARNING, "WARN")
logging.addLevelName(logging.CRITICAL, "CRIT")


class _Logger(logging.Logger):

    def error_or_exception(self, message, stacklevel=2, *args, **kwargs):
        is_debug = self.getEffectiveLevel() <= logging.DEBUG
        if sys.version_info > (3, 7):
            if is_debug:
                self.exception(message, stacklevel=stacklevel, *args, **kwargs)
            else:
                self.error(message, stacklevel=stacklevel, *args, **kwargs)
        else:
            if is_debug:
                self.exception(message, stack_info=True, *args, **kwargs)
            else:
                self.error(message, *args, **kwargs)

    def debug_no_auth(self, message, *args, **kwargs):
        message = message.strip("\r\n")
        if message.startswith("send: AUTH"):
            self.debug(message[:16], *args, **kwargs)
        else:
            self.debug(message, *args, **kwargs)


def get(name=None):
    return logging.getLogger(name)


def create():
    parent_frame = inspect.stack(0)[1]
    if hasattr(parent_frame, 'frame'):
        parent_frame = parent_frame.frame
    else:
        parent_frame = parent_frame[0]
    parent_module = inspect.getmodule(parent_frame)
    return get(parent_module.__name__)


def is_debug_enabled():
    return logging.root.level <= logging.DEBUG


def is_info_enabled(logger):
    return logging.getLogger(logger).level <= logging.INFO


def get_level_name(level):
    return logging.getLevelName(level)


def is_valid_logfile(file_path):
    if file_path == LOG_TO_STDERR or file_path == LOG_TO_STDOUT:
        return True
    if not file_path:
        return True
    if os.path.isdir(file_path):
        return False
    log_dir = os.path.dirname(file_path)
    return (not log_dir) or os.path.isdir(log_dir)


def _absolute_log_file(log_file, default_log_file):
    if log_file:
        if not os.path.dirname(log_file):
            log_file = os.path.join(_CONFIG_DIR, log_file)
        return os.path.abspath(log_file)
    return default_log_file


def get_logfile(log_file):
    return _absolute_log_file(log_file, DEFAULT_LOG_FILE)


def get_accesslogfile(log_file):
    return _absolute_log_file(log_file, DEFAULT_ACCESS_LOG)


# Default rotation: 5 MiB × 5 backups = up to 30 MiB of retained logs.
# The previous values (100 KB × 2) rotated within seconds on a busy
# instance and made the admin → View Logs page useless for diagnosing
# fork issue #312-class bugs (silent KOReader sync rejections).
ROTATION_MAX_BYTES = 5 * 1024 * 1024
ROTATION_BACKUP_COUNT = 5
ACCESS_ROTATION_MAX_BYTES = 2 * 1024 * 1024
ACCESS_ROTATION_BACKUP_COUNT = 3


def _make_file_handler(log_file, max_bytes=ROTATION_MAX_BYTES,
                       backup_count=ROTATION_BACKUP_COUNT,
                       default_path=DEFAULT_LOG_FILE):
    """Build a RotatingFileHandler at the requested path, falling back
    to the default location on IO/permission error (matches legacy
    fallback contract)."""
    try:
        h = RotatingFileHandler(log_file, maxBytes=max_bytes,
                                backupCount=backup_count, encoding='utf-8')
        return h, log_file
    except (IOError, PermissionError):
        if log_file == default_path:
            raise
        h = RotatingFileHandler(default_path, maxBytes=max_bytes,
                                backupCount=backup_count, encoding='utf-8')
        return h, ""


def _make_stream_handler(stream, token):
    h = StreamHandler(stream)
    h.baseFilename = token
    return h


def setup(log_file, log_level=None):
    """
    Configure the logging output.
    May be called multiple times.

    Always attaches a stdout handler so `docker logs` keeps streaming
    every record. When `log_file` is a real path (the default), ALSO
    attaches a RotatingFileHandler so the admin → View Logs UI has
    content to render. This dual-handler design replaces the prior
    single-handler behavior that left CWNG installs with an empty
    admin log viewer (fork issue #312).
    """
    log_level = log_level or DEFAULT_LOG_LEVEL
    logging.setLoggerClass(_Logger)
    logging.getLogger(__package__).setLevel(log_level)

    r = logging.root
    if log_level >= logging.INFO or os.environ.get('FLASK_DEBUG'):
        # avoid spamming the log with debug messages from libraries
        r.setLevel(log_level)

    # Decide whether to also attach a file handler. The legacy
    # stream-only tokens disable file logging; anything else resolves
    # to a real path (default: DEFAULT_LOG_FILE).
    if log_file == LOG_TO_STDERR:
        file_path = None
        stream_token = LOG_TO_STDERR
    elif log_file == LOG_TO_STDOUT:
        file_path = None
        stream_token = LOG_TO_STDOUT
    else:
        file_path = _absolute_log_file(log_file, DEFAULT_LOG_FILE)
        stream_token = LOG_TO_STDOUT

    new_handlers = []
    return_value = stream_token

    if stream_token == LOG_TO_STDERR:
        new_handlers.append(_make_stream_handler(sys.stderr, LOG_TO_STDERR))
    else:
        new_handlers.append(_make_stream_handler(sys.stdout, LOG_TO_STDOUT))

    if file_path is not None:
        try:
            fh, used_path = _make_file_handler(file_path)
            new_handlers.append(fh)
            return_value = used_path if used_path else ""
        except (IOError, PermissionError):
            # File handler unavailable (e.g. /config read-only). The
            # stdout handler alone still keeps the app observable.
            return_value = ""

    for h in new_handlers:
        h.setFormatter(FORMATTER)

    # Replace root handlers atomically.
    for h in list(r.handlers):
        r.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    for h in new_handlers:
        r.addHandler(h)
    logging.captureWarnings(True)

    if return_value == DEFAULT_LOG_FILE:
        return ""
    return return_value


def create_access_log(log_file, log_name, formatter):
    """
    One-time configuration for the web server's access log.
    """
    log_file = _absolute_log_file(log_file, DEFAULT_ACCESS_LOG)
    logging.debug("access log: %s", log_file)

    access_log = logging.getLogger(log_name)
    access_log.propagate = False
    access_log.setLevel(logging.INFO)
    file_handler, used_path = _make_file_handler(
        log_file,
        max_bytes=ACCESS_ROTATION_MAX_BYTES,
        backup_count=ACCESS_ROTATION_BACKUP_COUNT,
        default_path=DEFAULT_ACCESS_LOG,
    )

    file_handler.setFormatter(formatter)
    access_log.addHandler(file_handler)
    return access_log, used_path if used_path else ""


# Enable logging of smtp lib debug output
class StderrLogger(object):
    def __init__(self, name=None):
        self.log = get(name or self.__class__.__name__)
        self.buffer = ''

    def write(self, message):
        try:
            if message == '\n':
                self.log.debug(self.buffer.replace('\n', '\\n'))
                self.buffer = ''
            else:
                self.buffer += message
        except Exception:
            self.log.debug("Logging Error")


# default configuration, before application settings are applied
setup(LOG_TO_STDERR, logging.DEBUG if os.environ.get('FLASK_DEBUG') else DEFAULT_LOG_LEVEL)
