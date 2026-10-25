# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Exercise original-byte provenance using real SQLite databases and files."""
import importlib
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from original_uploads import UploadIndex, fingerprint, quarantine

pytestmark = pytest.mark.unit


class Library:
    def __init__(self, root, library_uuid="library-a"):
        self.root = root
        root.mkdir()
        self.metadata = root / "metadata.db"
        with sqlite3.connect(self.metadata) as con:
            con.executescript("""
                CREATE TABLE library_id(uuid TEXT);
                CREATE TABLE books(id INTEGER PRIMARY KEY, uuid TEXT, path TEXT,
                                   timestamp TEXT, last_modified TEXT);
                CREATE TABLE data(book INTEGER, name TEXT, format TEXT);
            """)
            con.execute("INSERT INTO library_id VALUES (?)", (library_uuid,))

    def put(self, content, book_id=1, book_uuid="book-a", file_format="EPUB"):
        relative = f"Author/Book ({book_id})"
        target = self.root / relative / ("Book." + file_format.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        with sqlite3.connect(self.metadata) as con:
            con.execute("INSERT OR IGNORE INTO books VALUES (?, ?, ?, ?, ?)",
                        (book_id, book_uuid, relative, "2026-01-01", "2026-01-01"))
            con.execute("DELETE FROM data WHERE book=? AND format=?", (book_id, file_format))
            con.execute("INSERT INTO data VALUES (?, 'Book', ?)", (book_id, file_format))
        return target

    def execute(self, query, args=()):
        with sqlite3.connect(self.metadata) as con:
            con.execute(query, args)


@pytest.fixture
def state(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("CWA_DB_PATH", str(config))
    connection = sqlite3.connect(config / "cwa.db")
    schema = Path(__file__).resolve().parents[2] / "scripts" / "cwa_schema.sql"
    connection.executescript(schema.read_text())
    library = Library(tmp_path / "library")
    index = UploadIndex(connection, library.metadata, library.root)
    yield SimpleNamespace(config=config, con=connection, library=library, index=index,
                          tmp=tmp_path)
    connection.close()


def source(state, content=b"original book", name="source.epub"):
    path = state.tmp / name
    path.write_bytes(content)
    return path


def remember(state, incoming, stored, book_id=1, file_format="EPUB", role="primary"):
    original = fingerprint(incoming)
    assert state.index.record(original, book_id, file_format, fingerprint(stored).sha256, role)
    return original


def count_rows(state):
    return state.con.execute("SELECT COUNT(*) FROM cwa_original_uploads").fetchone()[0]


def test_repeat_original_survives_stored_metadata_rewrite_and_restart(state):
    incoming = source(state)
    stored = state.library.put(incoming.read_bytes())
    original = remember(state, incoming, stored)
    stored.write_bytes(b"metadata-enforced changed bytes")
    renamed = source(state, incoming.read_bytes(), "renamed.epub")
    restarted = UploadIndex(state.con, state.library.metadata, state.library.root)
    assert restarted.find(fingerprint(renamed)) == 1
    assert restarted.find_current(original) is None


@pytest.mark.parametrize("output_format", ["EPUB", "KEPUB"])
def test_converted_output_matches_original_input_hash(state, output_format):
    incoming = source(state, b"raw mobi bytes", "source.mobi")
    stored = state.library.put(b"converted output", file_format=output_format)
    original = remember(state, incoming, stored, file_format=output_format)
    stored.write_bytes(b"later metadata enforcement")
    assert state.index.find(original) == 1


def test_same_size_different_bytes_are_not_duplicates(state):
    incoming = source(state, b"first")
    stored = state.library.put(b"first")
    remember(state, incoming, stored)
    other = source(state, b"other", "other.epub")
    assert state.index.find(fingerprint(other)) is None
    assert state.index.find_current(fingerprint(other)) is None


@pytest.mark.parametrize("mutation", ["delete_book", "delete_format", "delete_file", "reuse_id"])
def test_stale_relationships_do_not_suppress_import(state, mutation):
    incoming = source(state)
    stored = state.library.put(incoming.read_bytes())
    original = remember(state, incoming, stored)
    if mutation == "delete_book":
        state.library.execute("DELETE FROM books WHERE id=1")
    elif mutation == "delete_format":
        state.library.execute("DELETE FROM data WHERE book=1")
    elif mutation == "delete_file":
        stored.unlink()
    else:
        state.library.execute("UPDATE books SET uuid='replacement-book' WHERE id=1")
    assert state.index.find(original) is None


def test_libraries_sharing_cwa_database_keep_separate_provenance(state):
    incoming = source(state)
    stored = state.library.put(incoming.read_bytes())
    original = remember(state, incoming, stored)
    other = Library(state.tmp / "other-library", "library-b")
    other.put(b"other book", book_uuid="book-a")
    other_index = UploadIndex(state.con, other.metadata, other.root)
    assert other_index.find(original) is None
    assert state.index.find(original) == 1


def test_ignore_result_with_different_stored_bytes_records_nothing(state):
    incoming = source(state)
    state.library.put(b"unrelated retained book")
    assert not state.index.record(fingerprint(incoming), 1, "EPUB", fingerprint(incoming).sha256)
    assert count_rows(state) == 0


def test_record_requires_existing_target_format(state):
    incoming = source(state)
    state.library.put(incoming.read_bytes())
    assert not state.index.record(fingerprint(incoming), 1, "MOBI", fingerprint(incoming).sha256)
    assert not state.index.record(fingerprint(incoming), 999, "EPUB", fingerprint(incoming).sha256)
    assert count_rows(state) == 0


def test_explicit_replacement_invalidates_previous_original(state):
    incoming = source(state)
    stored = state.library.put(incoming.read_bytes())
    old = remember(state, incoming, stored)
    replacement = source(state, b"replacement bytes", "replacement.epub")
    state.index.forget_format(1, "epub")
    assert state.index.find(old) is None
    stored.write_bytes(replacement.read_bytes())
    new = remember(state, replacement, stored, role="add_format")
    assert state.index.find(old) is None
    assert state.index.find(new) == 1
    assert count_rows(state) == 1


def test_failed_explicit_replacement_cannot_leave_false_positive(state):
    incoming = source(state)
    stored = state.library.put(incoming.read_bytes())
    old = remember(state, incoming, stored)
    state.index.forget_format(1, "EPUB")
    # The replacement command can now fail. Legacy matching still sees current bytes.
    assert state.index.find(old) is None
    assert state.index.find_current(old) == 1


def test_legacy_current_bytes_match_without_creating_original_provenance(state):
    incoming = source(state, b"legacy pdf", "renamed.pdf")
    state.library.put(incoming.read_bytes(), file_format="PDF")
    original = fingerprint(incoming)
    assert state.index.find(original) is None
    assert state.index.find_current(original) == 1
    assert count_rows(state) == 0


def test_legacy_scan_skips_missing_files(state):
    incoming = source(state)
    state.library.put(incoming.read_bytes()).unlink()
    state.library.put(incoming.read_bytes(), book_id=2, book_uuid="book-b")
    assert state.index.find_current(fingerprint(incoming)) == 2


def test_retained_original_and_converted_output_have_independent_lifetimes(state):
    incoming = source(state, b"raw source", "source.mobi")
    converted = state.library.put(b"converted", file_format="EPUB")
    retained = state.library.put(incoming.read_bytes(), file_format="MOBI")
    original = remember(state, incoming, converted)
    remember(state, incoming, retained, file_format="MOBI", role="retained")
    state.library.execute("DELETE FROM data WHERE format='EPUB'")
    assert state.index.find(original) == 1
    state.library.execute("DELETE FROM data WHERE format='MOBI'")
    assert state.index.find(original) is None


def test_quarantine_retains_bytes_under_unique_paths(state):
    incoming = source(state)
    first = Path(quarantine(incoming))
    assert not incoming.exists()
    assert first.read_bytes() == b"original book"
    incoming.write_bytes(first.read_bytes())
    second = Path(quarantine(incoming))
    assert second != first
    assert second.read_bytes() == first.read_bytes()
    assert first.is_relative_to(state.config / "processed_books" / "duplicates")


def test_quarantine_copy_failure_preserves_incoming(state, monkeypatch):
    incoming = source(state)
    monkeypatch.setattr(shutil, "copy2", Mock(side_effect=OSError("full disk")))
    with pytest.raises(OSError, match="full disk"):
        quarantine(incoming)
    assert incoming.read_bytes() == b"original book"


@pytest.fixture
def processor(state, monkeypatch):
    ingest = importlib.import_module("ingest_processor")
    obj = object.__new__(ingest.NewBookProcessor)
    incoming = source(state)
    obj.filepath = str(incoming)
    obj.filename = incoming.name
    obj.library_dir = str(state.library.root)
    obj.metadata_db = str(state.library.metadata)
    obj.staging_dir = str(state.tmp / "staging")
    Path(obj.staging_dir).mkdir()
    obj.tmp_conversion_dir = str(state.tmp / "conversion")
    Path(obj.tmp_conversion_dir).mkdir()
    obj.target_format = "epub"
    obj.is_kindle_epub_fixer = False
    obj.cwa_settings = {"auto_ingest_automerge": "new_record", "auto_backup_imports": False,
                        "prevent_exact_duplicate_imports": True}
    obj.calibre_env = {}
    obj.last_added_book_id = None
    obj.last_added_book_ids = []
    obj.original_index = None
    obj.original_upload = None
    obj.confirmed_import = False
    obj.db = SimpleNamespace(con=state.con, import_add_entry=Mock())
    for name in ["fetch_metadata_if_enabled", "trigger_auto_send_if_enabled", "generate_book_checksums",
                 "backup", "set_library_permissions"]:
        monkeypatch.setattr(obj, name, Mock())
    monkeypatch.setattr(obj, "_register_title_sort_function", lambda con: False)
    monkeypatch.setattr(ingest, "mark_ingest_batch_dirty", Mock())
    monkeypatch.setattr(ingest, "gdrive_sync_if_enabled", Mock())
    obj.prepare_original_upload()
    return ingest, obj


def test_ingest_records_original_before_optional_metadata_rewrite(state, processor, monkeypatch):
    ingest, obj = processor

    def add_command(args, **kwargs):
        state.library.put(Path(args[2]).read_bytes())
        return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    obj.fetch_metadata_if_enabled.side_effect = lambda **kwargs: state.library.put(b"rewritten metadata")
    obj.add_book_to_library(obj.filepath)
    assert obj.confirmed_import
    assert state.index.find(obj.original_upload) == 1
    assert count_rows(state) == 1


def test_ingest_does_not_use_latest_book_fallback_for_provenance(state, processor, monkeypatch):
    ingest, obj = processor
    state.library.put(Path(obj.filepath).read_bytes())
    monkeypatch.setattr(ingest.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "No new books added\n", ""))
    obj.add_book_to_library(obj.filepath)
    assert obj.last_added_book_id == 1  # Existing compatibility fallback still runs.
    assert not obj.confirmed_import
    assert count_rows(state) == 0


def test_failed_calibre_import_records_no_original(state, processor, monkeypatch):
    ingest, obj = processor
    monkeypatch.setattr(ingest.subprocess, "run", Mock(side_effect=
                        subprocess.CalledProcessError(1, ["calibredb"], stderr="failure")))
    obj.add_book_to_library(obj.filepath)
    assert count_rows(state) == 0
    assert not obj.confirmed_import
    assert Path(obj.filepath).exists()


def test_ingest_ignore_reported_id_does_not_associate_discarded_bytes(state, processor, monkeypatch):
    ingest, obj = processor
    state.library.put(b"old retained file")
    obj.cwa_settings["auto_ingest_automerge"] = "ignore"
    monkeypatch.setattr(ingest.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "Merged book ids: 1\n", ""))
    obj.add_book_to_library(obj.filepath)
    assert count_rows(state) == 0
    assert not obj.confirmed_import


def test_provenance_write_failure_preserves_original_for_retry(state, processor, monkeypatch):
    ingest, obj = processor

    def add_command(args, **kwargs):
        state.library.put(Path(args[2]).read_bytes())
        return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    monkeypatch.setattr(obj.original_index, "record", Mock(side_effect=sqlite3.OperationalError("disk full")))
    obj.add_book_to_library(obj.filepath)
    assert not obj.confirmed_import
    assert count_rows(state) == 0
    assert Path(obj.filepath).read_bytes() == b"original book"


def test_multiple_reported_ids_cannot_create_ambiguous_provenance(state, processor, monkeypatch):
    ingest, obj = processor
    state.library.put(Path(obj.filepath).read_bytes())
    monkeypatch.setattr(ingest.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, "Added book ids: 1, 2\n", ""))
    obj.add_book_to_library(obj.filepath)
    assert not obj.confirmed_import
    assert count_rows(state) == 0


@pytest.fixture
def main_processor(state, processor, monkeypatch):
    ingest, obj = processor
    obj.ingest_folder = str(state.tmp)
    obj.ingest_ignored_formats = []
    obj.is_target_format = True
    obj.auto_convert_on = False
    obj.can_convert = True
    obj.supported_audiobook_formats = {"m4b", "m4a", "mp4"}
    obj.input_format = "epub"
    obj.convert_ignored_formats = []
    obj.convert_retained_formats = []
    monkeypatch.setattr(obj, "is_file_in_use", lambda: True)
    monkeypatch.setattr(ingest, "initialize_runtime", lambda: True)
    monkeypatch.setattr(ingest, "NewBookProcessor", lambda filepath: obj)
    return ingest, obj


def test_main_quarantines_duplicate_without_calling_calibre(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    stored = state.library.put(Path(obj.filepath).read_bytes())
    remember(state, Path(obj.filepath), stored)
    run = Mock(side_effect=AssertionError("duplicate must not invoke Calibre"))
    monkeypatch.setattr(ingest.subprocess, "run", run)
    assert ingest.main(obj.filepath) == 0
    assert not Path(obj.filepath).exists()
    copies = list((state.config / "processed_books" / "duplicates").glob("*/*"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == b"original book"
    run.assert_not_called()
    assert stored.read_bytes() == b"original book"


def test_main_lookup_failure_preserves_input(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    monkeypatch.setattr(UploadIndex, "find", Mock(side_effect=sqlite3.OperationalError("locked")))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ingest.main(obj.filepath)
    assert Path(obj.filepath).read_bytes() == b"original book"
    assert count_rows(state) == 0


def test_main_hash_interruption_preserves_input(state, main_processor, monkeypatch):
    import original_uploads
    ingest, obj = main_processor
    monkeypatch.setattr(original_uploads, "fingerprint", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        ingest.main(obj.filepath)
    assert Path(obj.filepath).read_bytes() == b"original book"


def test_main_failed_import_uses_legacy_backup_and_cleanup(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    monkeypatch.setattr(ingest.subprocess, "run", Mock(side_effect=
                        subprocess.CalledProcessError(1, ["calibredb"], stderr="failed")))
    assert ingest.main(obj.filepath) == 0
    assert not Path(obj.filepath).exists()
    obj.backup.assert_called_once()
    assert obj.backup.call_args.kwargs["backup_type"] == "failed"
    assert count_rows(state) == 0


def test_main_staging_copy_failure_preserves_input(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    monkeypatch.setattr(ingest.shutil, "copy2", Mock(side_effect=OSError("staging disk full")))

    assert ingest.main(obj.filepath) == 1
    assert Path(obj.filepath).read_bytes() == b"original book"
    obj.backup.assert_called_once_with(obj.filepath, backup_type="failed")
    assert count_rows(state) == 0


@pytest.mark.parametrize("automerge", ["new_record", "ignore"])
def test_main_provenance_write_failure_preserves_successful_import_input(
        state, main_processor, monkeypatch, automerge):
    ingest, obj = main_processor
    obj.cwa_settings["auto_ingest_automerge"] = automerge

    def add_command(args, **kwargs):
        state.library.put(Path(args[2]).read_bytes())
        result = "Merged book ids: 1\n" if automerge == "ignore" else "Added book id: 1\n"
        return subprocess.CompletedProcess(args, 0, result, "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    monkeypatch.setattr(UploadIndex, "record", Mock(side_effect=sqlite3.OperationalError("disk full")))
    assert ingest.main(obj.filepath) == 1
    assert Path(obj.filepath).read_bytes() == b"original book"
    assert count_rows(state) == 0


@pytest.mark.parametrize("reported_id", [None, 1])
def test_main_ignore_success_keeps_legacy_cleanup_without_provenance(
        state, main_processor, monkeypatch, reported_id):
    ingest, obj = main_processor
    obj.cwa_settings["auto_ingest_automerge"] = "ignore"
    if reported_id is not None:
        state.library.put(b"preexisting different bytes")
        output = "Merged book ids: 1\n"
    else:
        output = "No new books added\n"
    monkeypatch.setattr(ingest.subprocess, "run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, output, ""))

    assert ingest.main(obj.filepath) == 0
    assert not Path(obj.filepath).exists()
    assert count_rows(state) == 0


@pytest.mark.parametrize("conversion", ["unsupported", "failed"])
def test_main_conversion_nonimports_keep_legacy_cleanup(state, main_processor, monkeypatch, conversion):
    ingest, obj = main_processor
    obj.is_target_format = False
    obj.auto_convert_on = True
    obj.input_format = "unknown" if conversion == "unsupported" else "mobi"
    obj.can_convert = conversion == "failed"
    if conversion == "failed":
        monkeypatch.setattr(obj, "convert_book", lambda: (False, None))

    assert ingest.main(obj.filepath) == 0
    assert not Path(obj.filepath).exists()
    assert count_rows(state) == 0


def test_main_retries_duplicate_after_stored_metadata_rewrite(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    original_path = Path(obj.filepath)
    original_bytes = original_path.read_bytes()
    stored_paths = []

    def add_command(args, **kwargs):
        stored_paths.append(state.library.put(Path(args[2]).read_bytes()))
        return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    assert ingest.main(str(original_path)) == 0
    stored = stored_paths[0]
    stored.write_bytes(b"rewritten by metadata enforcement")

    renamed = original_path.with_name("renamed-copy.epub")
    renamed.write_bytes(original_bytes)
    obj.filepath = str(renamed)
    obj.filename = renamed.name
    monkeypatch.setattr(ingest.subprocess, "run", Mock(side_effect=AssertionError("duplicate reached Calibre")))
    assert ingest.main(str(renamed)) == 0
    assert not renamed.exists()
    assert len(list((state.config / "processed_books" / "duplicates").glob("*/*"))) == 1


def test_main_overwrite_replaces_old_original_association(state, main_processor, monkeypatch):
    ingest, obj = main_processor
    old_original = source(state, b"original A", "old.mobi")
    stored = state.library.put(old_original.read_bytes())
    remember(state, old_original, stored)
    new_bytes = b"replacement B"
    Path(obj.filepath).write_bytes(new_bytes)
    new_original = fingerprint(obj.filepath)
    obj.cwa_settings["auto_ingest_automerge"] = "overwrite"

    def add_command(args, **kwargs):
        state.library.put(Path(args[2]).read_bytes())
        return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    assert ingest.main(obj.filepath) == 0
    assert state.index.find(fingerprint(old_original)) is None
    assert state.index.find(new_original) == 1
    rows = state.con.execute("SELECT original_sha256 FROM cwa_original_uploads").fetchall()
    assert rows == [(new_original.sha256,)]


def test_main_explicit_manifest_replacement_replaces_original_association(
        state, main_processor, monkeypatch):
    ingest, obj = main_processor
    old_original = source(state, b"old format", "old.epub")
    stored = state.library.put(old_original.read_bytes())
    remember(state, old_original, stored)
    new_bytes = b"new format"
    Path(obj.filepath).write_bytes(new_bytes)
    new_original = fingerprint(obj.filepath)
    obj.original_index = None
    obj.original_upload = None
    manifest = Path(obj.filepath + ".cwa.json")
    manifest.write_text('{"action":"add_format","book_id":1}', encoding="utf-8")

    def add_format(args, **kwargs):
        state.library.put(Path(args[3]).read_bytes(), file_format="EPUB")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_format)
    assert ingest.main(obj.filepath) == 0
    assert not manifest.exists()
    assert state.index.find(fingerprint(old_original)) is None
    assert state.index.find(new_original) == 1
    assert state.con.execute(
        "SELECT role FROM cwa_original_uploads WHERE original_sha256=?", (new_original.sha256,)
    ).fetchone() == ("add_format",)


def test_kindle_fixer_import_records_original_upload_hash(state, processor, monkeypatch):
    ingest, obj = processor
    original = fingerprint(obj.filepath)
    obj.target_format = "epub"
    obj.is_kindle_epub_fixer = True

    def fix(source_path, dest=None):
        output = Path(dest) / Path(source_path).name
        output.write_bytes(b"fixed epub output")

    monkeypatch.setattr(obj, "run_kindle_epub_fixer", fix)

    def add_command(args, **kwargs):
        state.library.put(Path(args[2]).read_bytes())
        return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")

    monkeypatch.setattr(ingest.subprocess, "run", add_command)
    assert obj.add_book_to_library(obj.filepath)
    assert obj.confirmed_import
    assert state.index.find(original) == 1


@pytest.mark.parametrize("target_format,retained", [("epub", False), ("kepub", False), ("epub", True)])
def test_main_captures_original_before_conversion_and_records_retained_output(
        state, main_processor, monkeypatch, target_format, retained):
    ingest, obj = main_processor
    old_path = Path(obj.filepath)
    original_path = old_path.with_suffix(".mobi")
    old_path.rename(original_path)
    obj.filepath = str(original_path)
    obj.filename = original_path.name
    obj.input_format = "mobi"
    obj.is_target_format = False
    obj.target_format = target_format
    obj.auto_convert_on = True
    obj.convert_retained_formats = ["mobi"] if retained else []
    original = fingerprint(original_path)

    def convert():
        assert obj.original_upload == original
        converted = Path(obj.tmp_conversion_dir) / ("converted." + target_format)
        converted.write_bytes(b"converted bytes differ from original")
        return True, str(converted)

    monkeypatch.setattr(obj, "convert_book", convert)
    monkeypatch.setattr(obj, "convert_to_kepub", convert)

    def calibre(args, **kwargs):
        if args[1] == "add":
            state.library.put(Path(args[2]).read_bytes(), file_format=target_format.upper())
            return subprocess.CompletedProcess(args, 0, "Added book id: 1\n", "")
        if args[1] == "add_format":
            state.library.put(Path(args[3]).read_bytes(), file_format="MOBI")
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    monkeypatch.setattr(ingest.subprocess, "run", calibre)
    assert ingest.main(obj.filepath) == 0
    assert not original_path.exists()
    assert state.index.find(original) == 1
    rows = state.con.execute("SELECT format, original_sha256 FROM cwa_original_uploads").fetchall()
    assert set(rows) == {(target_format.upper(), original.sha256)} | ({("MOBI", original.sha256)} if retained else set())
