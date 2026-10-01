# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Convert Library must own its temp directory, must not fake success, and must
find the library when Calibre prints warnings into its JSON output.

1. `ingest_processor.py` ends each run with `shutil.rmtree()` on the shared temp
   conversion directory. Convert Library only ever wrote into that path, so after
   an ingest `ebook-convert` was handed an output path in a directory that no
   longer existed. A failed book also skipped the cleanup that recreated it, so
   one ingest overlapping a run failed every book after it.
2. Every command was a `subprocess.Popen` inside `except CalledProcessError`,
   which `Popen` never raises, so a failed command printed the success message.
3. Calibre prints some diagnostics to stdout with a bare print(), in the same
   stream as `calibredb list --for-machine`, so `json.loads()` on the whole
   stream failed and the run found no books.

Ported with the follow-up fixes from new-usemame/Calibre-Web-NextGen#2264.
"""

import atexit
import importlib
import importlib.util
import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")


@pytest.fixture(scope="module")
def convert_library(tmp_path_factory):
    """Import scripts/convert_library.py without its import-time side effects.

    At import the module opens /config/convert-library.log, looks up the abc
    user, chowns the log, scans /config/processed_books and takes a lock file.
    None of that exists outside the container, so each is stubbed for the
    import only. The lock is taken in a temp dir and released here instead of
    by the module's atexit hook, so a test run can never remove a real lock.
    """
    lock_dir = tmp_path_factory.mktemp("convert_library_lock")
    user = SimpleNamespace(pw_uid=os.getuid(), gr_gid=os.getgid())
    real_scandir = os.scandir

    def scandir(path="."):
        if str(path).startswith("/config"):
            return iter(())
        return real_scandir(path)

    # Its sibling imports (cwa_db, kindle_epub_fixer) resolve through sys.path,
    # but the module under test is loaded by path so another copy earlier on
    # sys.path can never stand in for it.
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    spec = importlib.util.spec_from_file_location("convert_library", Path(SCRIPTS_DIR) / "convert_library.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["convert_library"] = module
    with mock.patch("logging.FileHandler", lambda *a, **k: logging.NullHandler()), \
            mock.patch("pwd.getpwnam", return_value=user), \
            mock.patch("grp.getgrnam", return_value=user), \
            mock.patch("subprocess.run"), \
            mock.patch("os.scandir", scandir), \
            mock.patch("tempfile.gettempdir", return_value=str(lock_dir)):
        spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == (Path(SCRIPTS_DIR) / "convert_library.py").resolve()
    atexit.unregister(module.removeLock)
    yield module
    (lock_dir / "convert_library.lock").unlink(missing_ok=True)
    sys.modules.pop("convert_library", None)


@pytest.fixture
def log_lines(convert_library, monkeypatch):
    lines = []
    monkeypatch.setattr(convert_library, "print_and_log", lambda message, *a, **k: lines.append(str(message)))
    return lines


def _converter(convert_library, tmp_conversion_dir):
    """A LibraryConverter with only the attributes these paths touch.

    __init__ reads cwa.db and the Calibre library, neither of which exists in a
    unit-test environment.
    """
    converter = convert_library.LibraryConverter.__new__(convert_library.LibraryConverter)
    converter.verbose = False
    converter.current_book = 1
    converter.to_convert = []
    converter.tmp_conversion_dir = str(tmp_conversion_dir) + "/"
    return converter


def _write_tool(bin_dir, name, body):
    tool = bin_dir / name
    tool.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)


# --- temp directory ----------------------------------------------------------


def test_ensure_tmp_conversion_dir_creates_a_missing_directory(convert_library, tmp_path, log_lines):
    target = tmp_path / "cwa_conversion_tmp"
    _converter(convert_library, target).ensure_tmp_conversion_dir()
    assert target.is_dir()


def test_empty_tmp_con_dir_recreates_a_directory_removed_mid_run(convert_library, tmp_path, log_lines):
    target = tmp_path / "cwa_conversion_tmp"
    converter = _converter(convert_library, target)
    converter.ensure_tmp_conversion_dir()
    (target / "leftover.epub").write_text("x", encoding="utf-8")
    for child in target.iterdir():
        child.unlink()
    target.rmdir()  # what an ingest finishing mid-run does

    converter.empty_tmp_con_dir()

    assert target.is_dir()
    assert not any("error occurred while emptying" in line for line in log_lines)


# --- command running ---------------------------------------------------------


def test_run_streaming_raises_on_a_failed_command(convert_library, tmp_path, log_lines):
    converter = _converter(convert_library, tmp_path)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        converter._run_streaming(["sh", "-c", "echo boom; exit 3"])
    assert raised.value.returncode == 3
    assert "boom" in raised.value.output


def test_a_command_that_cannot_start_fails_the_book_not_the_run(convert_library, tmp_path, log_lines):
    converter = _converter(convert_library, tmp_path)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        converter._run_streaming([str(tmp_path / "no-such-tool")])
    assert raised.value.returncode == 127


def test_undecodable_command_output_does_not_abort_the_run(convert_library, tmp_path, log_lines):
    converter = _converter(convert_library, tmp_path)
    converter._run_streaming(["sh", "-c", r"printf 'caf\351\n'"])  # latin-1 byte, not UTF-8


def test_the_failure_log_keeps_only_the_tail_of_long_output(convert_library, tmp_path, log_lines):
    error = subprocess.CalledProcessError(1, ["x"], output="\n".join(f"line {n}" for n in range(500)))
    tail = convert_library.LibraryConverter._output_tail(error)
    assert tail.splitlines()[-1] == "line 499"
    assert "line 479" not in tail and "line 480" in tail


# --- the conversion loop -----------------------------------------------------


def test_a_failed_book_is_reported_and_the_next_book_still_converts(convert_library, tmp_path, monkeypatch, log_lines):
    """Book 1's ebook-convert fails after an ingest removed the temp directory
    (and a failed book skips the per-book cleanup). Book 1 must be reported as
    failed, and book 2 must still find a directory, convert and import."""
    converter = _converter(convert_library, tmp_path / "cwa_conversion_tmp")
    library = tmp_path / "library"
    books = []
    for number, title in ((1, "First"), (2, "Second")):
        folder = library / "Author" / f"{title} ({number})"
        folder.mkdir(parents=True)
        (folder / f"{title}.mobi").write_text("x", encoding="utf-8")
        books.append(str(folder / f"{title}.mobi"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_tool(bin_dir, "ebook-convert",
                'case "$1" in *First*) rm -rf "$(dirname "$2")"; echo "First.mobi is DRM locked"; exit 1;; esac\n'
                'echo converted > "$2" || exit 2\n')
    _write_tool(bin_dir, "calibredb", 'test -f "$3" || exit 3\n')

    converter.to_convert = books
    converter.target_format = "epub"
    converter.kindle_epub_fixer = False
    converter.library_dir = str(library) + "/"
    converter.calibre_env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    converter.cwa_settings = {"auto_backup_conversions": False, "auto_backup_imports": False}
    converter.db = SimpleNamespace(conversion_add_entry=lambda *a: None, import_add_entry=lambda *a: None)
    monkeypatch.setattr(converter, "set_library_permissions", lambda: None)
    converter.ensure_tmp_conversion_dir()

    converted = converter.convert_library()

    assert converted == 1, "the run summary must not count the failed book as converted"
    text = "\n".join(log_lines)
    assert "Conversion of First.mobi was unsuccessful" in text
    assert "DRM locked" in text, "the tool's own reason must reach the log file"
    assert "Conversion of First.mobi to epub format successful" not in text
    assert "Import of Second.epub successfully completed" in text, text


# --- the book list -----------------------------------------------------------

BOOKS = [
    {"formats": ["/calibre-library/Martha Wells/Queen Demon (7)/Queen Demon - Martha Wells.epub"], "id": 7},
    {"formats": ["/calibre-library/Sue Burke/Semiosis (1228)/Semiosis - Sue Burke.azw3"], "id": 1228},
]
WARNING = "No write access to /root/.config/calibre using a temporary dir instead"
EXPECTED = {7: BOOKS[0]["formats"], 1228: BOOKS[1]["formats"]}


def _converter_with_fake_calibredb(convert_library, tmp_path, stdout_text):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload = tmp_path / "calibredb-stdout.txt"
    payload.write_text(stdout_text, encoding="utf-8")
    _write_tool(bin_dir, "calibredb", 'exec cat "%s"\n' % payload)
    converter = _converter(convert_library, tmp_path)
    converter.library_dir = str(tmp_path / "library") + "/"
    converter.calibre_env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return converter


def test_warning_after_the_json_does_not_hide_the_library(convert_library, tmp_path, log_lines):
    stdout_text = json.dumps(BOOKS, indent=2) + WARNING + "\n" + WARNING + "\n"
    converter = _converter_with_fake_calibredb(convert_library, tmp_path, stdout_text)

    assert converter.get_library_book_formats() == EXPECTED
    assert any(WARNING in line for line in log_lines), "Calibre's warning should still reach the log"


def test_warning_before_the_json_does_not_hide_the_library(convert_library, tmp_path, log_lines):
    stdout_text = WARNING + "\n" + json.dumps(BOOKS, indent=2) + "\n"
    converter = _converter_with_fake_calibredb(convert_library, tmp_path, stdout_text)
    assert converter.get_library_book_formats() == EXPECTED


def test_a_bracketed_diagnostic_before_the_json_is_not_taken_for_the_list(convert_library, tmp_path, log_lines):
    stdout_text = "[1] " + WARNING + "\n" + json.dumps(BOOKS, indent=2) + "\n"
    converter = _converter_with_fake_calibredb(convert_library, tmp_path, stdout_text)
    assert converter.get_library_book_formats() == EXPECTED


def test_output_with_no_book_list_is_still_reported_unparseable(convert_library, tmp_path, log_lines):
    converter = _converter_with_fake_calibredb(convert_library, tmp_path, WARNING + "\n")
    assert converter.get_library_book_formats() == {}
    assert any("Failed to parse calibredb command output" in line for line in log_lines)


# --- kepub target ------------------------------------------------------------
# convert_library() passes Path(file).suffix (".epub", with the dot) and
# convert_to_kepub() compared it to "epub", so an epub source never took the
# direct path and always went through a redundant ebook-convert epub -> epub.


def _kepub_converter(convert_library, tmp_path, monkeypatch):
    converter = _converter(convert_library, tmp_path / "cwa_conversion_tmp")
    converter.ensure_tmp_conversion_dir()
    converter.target_format = "kepub"
    converter.to_convert = ["x"]
    converter.cwa_settings = {"auto_backup_conversions": False, "auto_backup_imports": False}
    converter.db = SimpleNamespace(conversion_add_entry=lambda *a: None)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    _write_tool(bin_dir, "ebook-convert", f'echo ebook-convert >> "{calls}"\n'
                'case "$1" in *Locked*) echo "Locked.mobi is DRM locked"; exit 1;; esac\n'
                'echo converted > "$2"\n')
    _write_tool(bin_dir, "kepubify", f'echo kepubify >> "{calls}"\n')
    converter.calibre_env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return converter, calls


def test_epub_source_goes_straight_to_kepubify(convert_library, tmp_path, monkeypatch, log_lines):
    converter, calls = _kepub_converter(convert_library, tmp_path, monkeypatch)
    book = tmp_path / "Book.epub"
    book.write_text("x", encoding="utf-8")
    ok, target = converter.convert_to_kepub(str(book), book.suffix)
    assert ok
    assert target.endswith("Book.kepub")
    assert calls.read_text().split() == ["kepubify"], "an epub must not be run through ebook-convert first"
    assert any("already in epub format" in line for line in log_lines)


def test_other_formats_still_convert_to_epub_first(convert_library, tmp_path, monkeypatch, log_lines):
    converter, calls = _kepub_converter(convert_library, tmp_path, monkeypatch)
    book = tmp_path / "Book.mobi"
    book.write_text("x", encoding="utf-8")
    ok, _ = converter.convert_to_kepub(str(book), book.suffix)
    assert ok
    assert calls.read_text().split() == ["ebook-convert", "kepubify"]


def test_failed_intermediate_conversion_logs_the_tools_reason(convert_library, tmp_path, monkeypatch, log_lines):
    converter, calls = _kepub_converter(convert_library, tmp_path, monkeypatch)
    book = tmp_path / "Locked.mobi"
    book.write_text("x", encoding="utf-8")
    ok, _ = converter.convert_to_kepub(str(book), book.suffix)
    assert not ok
    text = "\n".join(log_lines)
    assert "Intermediate conversion of Locked.mobi to epub was unsuccessful" in text
    assert "DRM locked" in text, "the tool's own reason must reach the log file"
    assert "kepubify" not in calls.read_text()
