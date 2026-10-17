# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sqlite3
import subprocess
from pathlib import Path
from unittest import mock

import pytest


pytestmark = pytest.mark.unit


class StubDb:
    def __init__(self):
        self.origins = []

    def import_add_entry(self, title, backup_enabled):
        pass

    def format_origin_set(self, book_id, book_format, original_format, source_filename=""):
        self.origins.append((book_id, book_format.upper(), original_format.upper(), source_filename))


@pytest.fixture
def ingest_processor(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("CWA_INGEST_BATCH_DIRTY_FILE", str(tmp_path / "batch_dirty"))
    import ingest_processor
    return ingest_processor


def build_processor(ingest_processor, tmp_path, automerge="new_record", existing_formats=()):
    metadata_db = tmp_path / "metadata.db"
    with sqlite3.connect(metadata_db) as con:
        con.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT)")
        con.executemany("INSERT INTO data (book, format) VALUES (?, ?)", existing_formats)

    processor = object.__new__(ingest_processor.NewBookProcessor)
    processor.target_format = "epub"
    processor.is_kindle_epub_fixer = False
    processor.cwa_settings = {
        "auto_ingest_automerge": automerge,
        "auto_backup_imports": False,
    }
    processor.metadata_db = str(metadata_db)
    processor.staging_dir = str(tmp_path / "staging")
    processor.calibre_env = {}
    processor.library_dir = str(tmp_path / "library")
    processor.last_added_book_id = None
    processor.last_added_book_ids = []
    processor.db = StubDb()
    processor.filepath = str(tmp_path / "ingest" / "Book.mobi")
    processor.filename = "Book.mobi"
    processor.tmp_conversion_dir = str(tmp_path / "conversion")
    Path(processor.staging_dir).mkdir()
    Path(processor.library_dir).mkdir()
    Path(processor.tmp_conversion_dir).mkdir()
    return processor


def run_import(ingest_processor, processor, tmp_path, calibredb_stdout, original_format):
    converted = tmp_path / "conversion" / "Book.epub"
    converted.write_bytes(b"book")
    result = subprocess.CompletedProcess(args=["calibredb"], returncode=0, stdout=calibredb_stdout, stderr="")
    with mock.patch.object(ingest_processor.subprocess, "run", return_value=result), \
        mock.patch.object(ingest_processor, "gdrive_sync_if_enabled"), \
        mock.patch.object(ingest_processor, "mark_ingest_batch_dirty"), \
        mock.patch.object(processor, "fetch_metadata_if_enabled"), \
        mock.patch.object(processor, "trigger_auto_send_if_enabled"), \
        mock.patch.object(processor, "generate_book_checksums"):
        processor.add_book_to_library(str(converted), original_format=original_format)


def test_converted_import_records_origin(ingest_processor, tmp_path):
    processor = build_processor(ingest_processor, tmp_path)
    run_import(ingest_processor, processor, tmp_path, "Added book ids: 7\n", "mobi")
    assert processor.db.origins == [(7, "EPUB", "MOBI", "Book.mobi")]


def test_unconverted_import_records_nothing(ingest_processor, tmp_path):
    processor = build_processor(ingest_processor, tmp_path)
    run_import(ingest_processor, processor, tmp_path, "Added book ids: 7\n", None)
    assert processor.db.origins == []


def test_merge_into_book_that_already_had_format_is_not_recorded(ingest_processor, tmp_path):
    # automerge=ignore: calibre keeps book 7's own EPUB and drops the converted one
    processor = build_processor(ingest_processor, tmp_path, automerge="ignore", existing_formats=[(7, "EPUB")])
    run_import(ingest_processor, processor, tmp_path, "Merged book ids: 7\n", "mobi")
    assert processor.db.origins == []


def test_merge_that_adds_a_new_format_is_recorded(ingest_processor, tmp_path):
    processor = build_processor(ingest_processor, tmp_path, automerge="ignore", existing_formats=[(7, "PDF")])
    run_import(ingest_processor, processor, tmp_path, "Merged book ids: 7\n", "mobi")
    assert processor.db.origins == [(7, "EPUB", "MOBI", "Book.mobi")]


def test_overwrite_merge_is_recorded(ingest_processor, tmp_path):
    processor = build_processor(ingest_processor, tmp_path, automerge="overwrite", existing_formats=[(7, "EPUB")])
    with mock.patch.object(processor, "_register_title_sort_function", return_value=False):
        run_import(ingest_processor, processor, tmp_path, "Merged book ids: 7\n", "mobi")
    assert processor.db.origins == [(7, "EPUB", "MOBI", "Book.mobi")]
