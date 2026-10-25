# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression coverage for upload names and named database validation."""
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cwa_db import CWA_DB
from original_uploads import GuardError, UploadIndex, clean_upload_filename, fingerprint

pytestmark = pytest.mark.unit


def test_generated_upload_prefix_is_removed_only_when_valid():
    assert clean_upload_filename(
        "new_1_20261025_143430_623751_Book.pdf") == "Book.pdf"
    for filename in (
        "Book.pdf", "new_1_Book.pdf", "new_1_20261025_143430_Book.pdf",
        "new_1_20261325_143430_623751_Book.pdf",
        "new_1_20261025_999999_623751_Book.pdf",
        "prefixed_new_1_20261025_143430_623751_Book.pdf",
    ):
        assert clean_upload_filename(filename) == filename
    with pytest.raises(GuardError):
        clean_upload_filename("../Book.pdf")


def test_retained_format_does_not_confirm_primary_import(tmp_path):
    import ingest_processor

    original_path = tmp_path / "incoming.mobi"
    original_path.write_bytes(b"original bytes")
    original = fingerprint(original_path)
    processor = object.__new__(ingest_processor.NewBookProcessor)
    processor.filepath = str(original_path)
    processor.original_upload = original
    processor.original_index = SimpleNamespace(record=Mock(return_value=True))
    processor.confirmed_import = False

    assert processor.record_original_upload([1], "MOBI", fingerprint(original_path).sha256,
                                            role="retained")
    assert not processor.confirmed_import
    assert not hasattr(processor, "confirmed_primary_id")


def test_original_upload_schema_is_named_and_initialization_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
    first = CWA_DB()
    columns = {row[1] for row in first.cur.execute(
        "PRAGMA table_info(cwa_original_uploads)").fetchall()}
    assert columns == {
        "library_uuid", "book_id", "book_uuid", "format", "original_sha256",
        "original_size", "original_ext", "output_sha256", "role", "created_at",
    }
    assert "cwa_original_uploads" not in first.stats_tables
    first.con.close()

    second = CWA_DB()
    assert {row[1] for row in second.cur.execute(
        "PRAGMA table_info(cwa_original_uploads)").fetchall()} == columns
    second.con.close()


def test_invalid_original_upload_schema_only_blocks_enabled_feature(tmp_path, monkeypatch):
    monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
    with sqlite3.connect(tmp_path / "cwa.db") as con:
        con.execute("CREATE TABLE cwa_original_uploads (legacy_column TEXT)")

    disabled = CWA_DB()
    disabled.cur.execute("UPDATE cwa_settings SET prevent_exact_duplicate_imports=1")
    disabled.con.commit()
    disabled.con.close()

    with pytest.raises(sqlite3.OperationalError, match="schema mismatch"):
        CWA_DB()


def test_additive_original_upload_column_survives_reinitialization(tmp_path, monkeypatch):
    monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
    first = CWA_DB()
    first.cur.execute("ALTER TABLE cwa_original_uploads ADD COLUMN future_field TEXT")
    first.con.commit()
    first.con.close()

    second = CWA_DB()
    columns = {row[1] for row in second.cur.execute(
        "PRAGMA table_info(cwa_original_uploads)").fetchall()}
    assert "future_field" in columns
    assert "library_uuid" in columns
    second.con.close()


def test_distinct_originals_sharing_output_survive_until_explicit_replacement(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    metadata_db = library / "metadata.db"
    with sqlite3.connect(metadata_db) as metadata:
        metadata.executescript("""
            CREATE TABLE library_id(uuid TEXT);
            CREATE TABLE books(id INTEGER PRIMARY KEY, uuid TEXT, path TEXT);
            CREATE TABLE data(book INTEGER, name TEXT, format TEXT);
            INSERT INTO library_id VALUES ('library-a');
            INSERT INTO books VALUES (1, 'book-a', 'Author/Book');
            INSERT INTO data VALUES (1, 'Book', 'EPUB');
        """)
    target = library / "Author" / "Book" / "Book.epub"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"shared converted output")

    connection = sqlite3.connect(":memory:")
    schema = Path(__file__).resolve().parents[2] / "scripts" / "cwa_schema.sql"
    connection.executescript(schema.read_text())
    index = UploadIndex(connection, metadata_db, library)
    incoming_a = tmp_path / "source-a.mobi"
    incoming_b = tmp_path / "source-b.mobi"
    incoming_c = tmp_path / "source-c.mobi"
    incoming_a.write_bytes(b"source A")
    incoming_b.write_bytes(b"source B")
    incoming_c.write_bytes(b"source C")
    output_hash = fingerprint(target).sha256

    assert index.record(fingerprint(incoming_a), 1, "EPUB", output_hash)
    assert index.record(fingerprint(incoming_b), 1, "EPUB", output_hash)
    assert index.find(fingerprint(incoming_a)) == 1
    assert index.find(fingerprint(incoming_b)) == 1

    assert index.record(fingerprint(incoming_c), 1, "EPUB", output_hash,
                        replace_existing=True)
    assert index.find(fingerprint(incoming_a)) is None
    assert index.find(fingerprint(incoming_b)) is None
    assert index.find(fingerprint(incoming_c)) == 1
    connection.close()


def test_configured_library_root_can_be_a_symlink(tmp_path):
    actual = tmp_path / "library"
    actual.mkdir()
    metadata_db = actual / "metadata.db"
    with sqlite3.connect(metadata_db) as metadata:
        metadata.executescript("""
            CREATE TABLE library_id(uuid TEXT);
            CREATE TABLE books(id INTEGER PRIMARY KEY, uuid TEXT, path TEXT);
            CREATE TABLE data(book INTEGER, name TEXT, format TEXT);
            INSERT INTO library_id VALUES ('library-a');
            INSERT INTO books VALUES (1, 'book-a', 'Author/Book');
            INSERT INTO data VALUES (1, 'Book', 'EPUB');
        """)
    target = actual / "Author" / "Book" / "Book.epub"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stored")
    link = tmp_path / "library-link"
    link.symlink_to(actual, target_is_directory=True)
    incoming = tmp_path / "incoming.epub"
    incoming.write_bytes(b"stored")

    connection = sqlite3.connect(":memory:")
    schema = Path(__file__).resolve().parents[2] / "scripts" / "cwa_schema.sql"
    connection.executescript(schema.read_text())
    index = UploadIndex(connection, metadata_db, link)
    assert index.find_current(fingerprint(incoming)) == 1
    connection.close()


def test_unsafe_stored_entry_is_skipped_without_masking_valid_entry(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    metadata_db = library / "metadata.db"
    with sqlite3.connect(metadata_db) as metadata:
        metadata.executescript("""
            CREATE TABLE library_id(uuid TEXT);
            CREATE TABLE books(id INTEGER PRIMARY KEY, uuid TEXT, path TEXT);
            CREATE TABLE data(book INTEGER, name TEXT, format TEXT);
            INSERT INTO library_id VALUES ('library-a');
            INSERT INTO books VALUES (1, 'bad-book', 'Escape');
            INSERT INTO books VALUES (2, 'good-book', 'Author/Book');
            INSERT INTO data VALUES (1, 'Book', 'EPUB');
            INSERT INTO data VALUES (2, 'Book', 'EPUB');
        """)
    (library / "Escape").symlink_to(outside, target_is_directory=True)
    valid = library / "Author" / "Book" / "Book.epub"
    valid.parent.mkdir(parents=True)
    valid.write_bytes(b"stored")
    incoming = tmp_path / "incoming.epub"
    incoming.write_bytes(b"stored")
    original = fingerprint(incoming)

    connection = sqlite3.connect(":memory:")
    schema = Path(__file__).resolve().parents[2] / "scripts" / "cwa_schema.sql"
    connection.executescript(schema.read_text())
    index = UploadIndex(connection, metadata_db, library)
    for book_id, book_uuid in ((1, "bad-book"), (2, "good-book")):
        connection.execute(
            "INSERT INTO cwa_original_uploads "
            "(library_uuid, book_id, book_uuid, format, original_sha256, original_size, "
            "original_ext, output_sha256, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("library-a", book_id, book_uuid, "EPUB", original.sha256, original.size,
             original.extension, original.sha256, "primary"))
    connection.commit()
    assert index.find(original) == 2
    assert index.find_current(original) == 2
    connection.close()
