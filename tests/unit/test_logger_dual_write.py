# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #312 — Tier 1: logger dual-write.

When `cps.logger.setup()` is called with a regular file path, it must
attach BOTH a `StreamHandler` (for `docker logs`) AND a
`RotatingFileHandler` (so the admin → View Logs UI has content to
render). Before this change the logger replaced root with a single
handler, and `cps.config_sql` further force-reset every install's
`config_logfile` to `/dev/stdout`, which left the admin log viewer
permanently empty.

Pin the new contract:

* setup(<file path>) → 2 root handlers: stdout StreamHandler + RotatingFileHandler at the path
* setup(LOG_TO_STDOUT) → 1 root handler: stdout StreamHandler, no file
* rotation defaults: 5 MiB × 5 backups (was 100 KB × 2 — useless)
* setup() returns the path written to, or "" for default, or LOG_TO_STDOUT for stdout-only
"""

from __future__ import annotations

import logging
import os
import sys
from logging import StreamHandler
from logging.handlers import RotatingFileHandler

import pytest

import cps.logger as cwa_logger


@pytest.fixture
def reset_root():
    """Snapshot/restore the root logger handlers so tests don't leak."""
    root = logging.root
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def _file_handlers():
    return [h for h in logging.root.handlers if isinstance(h, RotatingFileHandler)]


def _stream_handlers_to_stdout():
    out = []
    for h in logging.root.handlers:
        if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler):
            stream = getattr(h, "stream", None)
            if stream is sys.stdout or getattr(h, "baseFilename", "") == cwa_logger.LOG_TO_STDOUT:
                out.append(h)
    return out


@pytest.mark.unit
class TestDualHandlerSetup:
    def test_file_path_attaches_both_stdout_and_file_handler(self, tmp_path, reset_root):
        path = tmp_path / "calibre-web.log"
        cwa_logger.setup(str(path), logging.INFO)
        files = _file_handlers()
        stdouts = _stream_handlers_to_stdout()
        assert files, (
            "expected a RotatingFileHandler so admin → View Logs has content; "
            f"root handlers were: {logging.root.handlers!r}"
        )
        assert stdouts, (
            "expected a stdout StreamHandler so `docker logs` keeps working; "
            f"root handlers were: {logging.root.handlers!r}"
        )

    def test_stdout_only_path_has_no_file_handler(self, reset_root):
        cwa_logger.setup(cwa_logger.LOG_TO_STDOUT, logging.INFO)
        assert _file_handlers() == [], (
            "LOG_TO_STDOUT must remain a single-handler stdout configuration; "
            f"root handlers were: {logging.root.handlers!r}"
        )
        assert _stream_handlers_to_stdout(), "must keep the stdout handler"

    def test_emitted_record_lands_in_the_file(self, tmp_path, reset_root):
        path = tmp_path / "calibre-web.log"
        cwa_logger.setup(str(path), logging.INFO)
        logging.getLogger("cps.unit_test").info("hello-from-test")
        # RotatingFileHandler buffers via the underlying stream — flush
        # by closing/reopening for read.
        for h in _file_handlers():
            h.flush()
        body = path.read_text(encoding="utf-8")
        assert "hello-from-test" in body, body

    def test_emitted_record_also_lands_on_stdout(self, tmp_path, reset_root, capsys):
        path = tmp_path / "calibre-web.log"
        cwa_logger.setup(str(path), logging.INFO)
        logging.getLogger("cps.unit_test").info("dual-write-marker")
        captured = capsys.readouterr()
        assert "dual-write-marker" in captured.out, (
            "stdout handler must mirror records so `docker logs` keeps working; "
            f"stdout was: {captured.out!r}"
        )


@pytest.mark.unit
class TestRotationDefaults:
    def test_rotation_uses_5mib_maxbytes_and_5_backups(self, tmp_path, reset_root):
        """100 KB × 2 backups was too small for any real debug session."""
        path = tmp_path / "calibre-web.log"
        cwa_logger.setup(str(path), logging.INFO)
        files = _file_handlers()
        assert files, "expected a file handler"
        fh = files[0]
        assert fh.maxBytes >= 5 * 1024 * 1024, (
            f"rotation maxBytes must be ≥5 MiB, got {fh.maxBytes!r}"
        )
        assert fh.backupCount >= 5, (
            f"backupCount must be ≥5 (≥30 MiB of retained logs), got {fh.backupCount!r}"
        )


@pytest.mark.unit
class TestSetupReturnContract:
    def test_default_path_returns_empty_string(self, tmp_path, reset_root, monkeypatch):
        # Point the default at a temp dir so we don't pollute /config
        monkeypatch.setattr(cwa_logger, "DEFAULT_LOG_FILE",
                            str(tmp_path / "calibre-web.log"))
        out = cwa_logger.setup("", logging.INFO)
        assert out == "", f"empty path should resolve to default and report empty; got {out!r}"

    def test_stdout_token_returns_stdout_token(self, reset_root):
        out = cwa_logger.setup(cwa_logger.LOG_TO_STDOUT, logging.INFO)
        assert out == cwa_logger.LOG_TO_STDOUT, (
            f"stdout token round-trips so callers can detect it; got {out!r}"
        )

    def test_custom_path_returns_absolute_custom_path(self, tmp_path, reset_root):
        path = tmp_path / "custom.log"
        out = cwa_logger.setup(str(path), logging.INFO)
        assert out == os.path.abspath(str(path)), (
            f"custom path should round-trip as absolute; got {out!r}"
        )
