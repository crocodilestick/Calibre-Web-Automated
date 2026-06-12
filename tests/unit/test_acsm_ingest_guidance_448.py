# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #448: dropping a .acsm file into ingest used to fail with only
Calibre's raw "No plugin to handle input format: acsm" traceback plus a
generic CON_ERROR line — nothing telling the user that an .acsm is an
Adobe fulfillment ticket (not a book) or what their actual options are.

Pinned behavior:
  1. conversion_failure_guidance() maps 'acsm' (case-insensitive) to a
     plain-English explanation naming both recovery paths — the ACSM
     Input plugin via CWA_CALIBRE_USER_PLUGINS, or fulfilling the ticket
     in Adobe Digital Editions / Calibre desktop — and returns None for
     formats with no special advice.
  2. convert_book()'s failure branch prints that guidance for .acsm and
     stays quiet about it for other formats.
  3. The CON_ERROR line no longer prints a literal "None" where stderr
     would be (ebook-convert output is not captured; it streams to the
     service log above the CON_ERROR line).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = str(REPO_ROOT / "scripts")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import ingest_processor  # noqa: E402


def _failing_processor(tmp_path, input_format, filename):
    nbp = object.__new__(ingest_processor.NewBookProcessor)
    nbp.filepath = str(tmp_path / filename)
    nbp.filename = filename
    nbp.input_format = input_format
    nbp.target_format = "epub"
    nbp.tmp_conversion_dir = str(tmp_path) + os.sep
    nbp.calibre_env = os.environ.copy()
    nbp.cwa_settings = {"auto_backup_conversions": False}
    nbp.backup = lambda *args, **kwargs: None
    return nbp


class TestGuidanceHelper:
    def test_acsm_guidance_names_both_recovery_paths(self):
        text = ingest_processor.conversion_failure_guidance("acsm", "x.acsm")
        assert text is not None
        assert "Adobe" in text
        assert "CWA_CALIBRE_USER_PLUGINS" in text
        assert "ACSM Input" in text
        assert "Adobe Digital Editions" in text
        assert "x.acsm" in text

    def test_lookup_is_case_insensitive(self):
        assert ingest_processor.conversion_failure_guidance("ACSM", "x.ACSM")

    @pytest.mark.parametrize("fmt", ["mobi", "epub", "pdf", "", None])
    def test_no_guidance_for_ordinary_formats(self, fmt):
        assert ingest_processor.conversion_failure_guidance(fmt, "x.bin") is None


class TestConvertBookFailurePath:
    def _run_failing_convert(self, tmp_path, monkeypatch, capsys, fmt, name):
        nbp = _failing_processor(tmp_path, fmt, name)

        def _raise(cmd, *args, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(ingest_processor.subprocess, "run", _raise)
        ok, path = nbp.convert_book()
        assert ok is False and path == ""
        return capsys.readouterr().out

    def test_acsm_failure_prints_guidance(self, tmp_path, monkeypatch, capsys):
        out = self._run_failing_convert(
            tmp_path, monkeypatch, capsys, "acsm", "Ticket.acsm")
        assert "CON_ERROR" in out
        assert "Adobe" in out
        assert "CWA_CALIBRE_USER_PLUGINS" in out
        assert "Adobe Digital Editions" in out

    def test_non_acsm_failure_prints_no_acsm_guidance(
            self, tmp_path, monkeypatch, capsys):
        out = self._run_failing_convert(
            tmp_path, monkeypatch, capsys, "mobi", "Book.mobi")
        assert "CON_ERROR" in out
        assert "Adobe" not in out

    def test_con_error_does_not_print_literal_none_stderr(
            self, tmp_path, monkeypatch, capsys):
        out = self._run_failing_convert(
            tmp_path, monkeypatch, capsys, "mobi", "Book.mobi")
        assert "\nNone" not in out, (
            "CON_ERROR printed e.stderr from an uncaptured subprocess — "
            "that is always None and reads as a literal 'None' in the log"
        )
