import subprocess
from pathlib import Path
from unittest import mock

import pytest


pytestmark = pytest.mark.unit


class StubImportDb:
    def __init__(self):
        self.entries = []

    def import_add_entry(self, title, backup_enabled):
        self.entries.append((title, backup_enabled))


def build_processor(ingest_processor, tmp_path):
    processor = object.__new__(ingest_processor.NewBookProcessor)
    processor.target_format = "epub"
    processor.is_kindle_epub_fixer = False
    processor.cwa_settings = {
        "auto_ingest_automerge": "ignore",
        "auto_backup_imports": False,
    }
    processor.metadata_db = str(tmp_path / "metadata.db")
    processor.staging_dir = str(tmp_path / "staging")
    processor.calibre_env = {}
    processor.library_dir = str(tmp_path / "library")
    processor.last_added_book_id = None
    processor.last_added_book_ids = []
    processor.db = StubImportDb()
    processor.filepath = str(tmp_path / "source.epub")
    processor.tmp_conversion_dir = str(tmp_path / "conversion")
    Path(processor.staging_dir).mkdir()
    Path(processor.library_dir).mkdir()
    Path(processor.tmp_conversion_dir).mkdir()
    return processor


def test_successful_import_marks_batch_dirty_without_hot_loop_http_calls(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("CWA_INGEST_BATCH_DIRTY_FILE", str(tmp_path / "batch_dirty"))
    monkeypatch.setenv("CWA_INGEST_BATCH_ACTIVE_FILE", str(tmp_path / "batch_active"))
    monkeypatch.setenv("CWA_METADATA_LOCK_DIR", str(tmp_path))

    import ingest_processor

    source = tmp_path / "source.epub"
    source.write_bytes(b"book")
    processor = build_processor(ingest_processor, tmp_path)

    result = subprocess.CompletedProcess(
        args=["calibredb"],
        returncode=0,
        stdout="Added book id: 7\n",
        stderr="",
    )

    requests_mock = mock.Mock()
    monkeypatch.setattr(ingest_processor, "requests", requests_mock)

    with mock.patch.object(ingest_processor.subprocess, "run", return_value=result) as run_mock, \
        mock.patch.object(ingest_processor, "gdrive_sync_if_enabled"), \
        mock.patch.object(processor, "fetch_metadata_if_enabled"), \
        mock.patch.object(processor, "trigger_auto_send_if_enabled"), \
        mock.patch.object(processor, "generate_book_checksums"), \
        mock.patch.object(ingest_processor, "wait_for_duplicate_full_scan_to_finish") as wait_mock:
        processor.add_book_to_library(str(source))

    wait_mock.assert_called_once()
    assert run_mock.call_args.args[0][:2] == ["calibredb", "add"]
    assert (tmp_path / "batch_dirty").exists()
    assert not (tmp_path / "batch_active").exists()
    assert processor.db.entries == [("source", "False")]

    called_urls = [call.args[0] for call in requests_mock.post.call_args_list if call.args]
    assert not any("/cwa-internal/reconnect-db" in url for url in called_urls)
    assert not any("/duplicates/invalidate-cache" in url for url in called_urls)
    assert not any("/cwa-internal/queue-duplicate-scan" in url for url in called_urls)


def test_failed_import_does_not_mark_batch_dirty(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("CWA_INGEST_BATCH_DIRTY_FILE", str(tmp_path / "batch_dirty"))
    monkeypatch.setenv("CWA_INGEST_BATCH_ACTIVE_FILE", str(tmp_path / "batch_active"))
    monkeypatch.setenv("CWA_METADATA_LOCK_DIR", str(tmp_path))

    import ingest_processor

    source = tmp_path / "source.epub"
    source.write_bytes(b"book")
    processor = build_processor(ingest_processor, tmp_path)

    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["calibredb", "add"],
        stderr="failed",
    )

    with mock.patch.object(ingest_processor.subprocess, "run", side_effect=error), \
        mock.patch.object(processor, "backup") as backup_mock:
        processor.add_book_to_library(str(source))

    assert not (tmp_path / "batch_dirty").exists()
    assert not (tmp_path / "batch_active").exists()
    backup_mock.assert_called_once()


def test_successful_add_format_marks_batch_dirty(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("CWA_INGEST_BATCH_DIRTY_FILE", str(tmp_path / "batch_dirty"))
    monkeypatch.setenv("CWA_INGEST_BATCH_ACTIVE_FILE", str(tmp_path / "batch_active"))
    monkeypatch.setenv("CWA_METADATA_LOCK_DIR", str(tmp_path))

    import ingest_processor

    source = tmp_path / "source.epub"
    source.write_bytes(b"book")
    processor = build_processor(ingest_processor, tmp_path)
    processor.filepath = str(source)

    result = subprocess.CompletedProcess(
        args=["calibredb", "add_format"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with mock.patch.object(processor, "_validate_book_exists", return_value=True), \
        mock.patch.object(ingest_processor.subprocess, "run", return_value=result) as run_mock, \
        mock.patch.object(ingest_processor, "gdrive_sync_if_enabled"), \
        mock.patch.object(ingest_processor, "wait_for_duplicate_full_scan_to_finish") as wait_mock:
        processor.add_format_to_book(7, str(source))

    wait_mock.assert_called_once()
    assert run_mock.call_args.args[0][:3] == ["calibredb", "add_format", "7"]
    assert (tmp_path / "batch_dirty").exists()
    assert not (tmp_path / "batch_active").exists()
