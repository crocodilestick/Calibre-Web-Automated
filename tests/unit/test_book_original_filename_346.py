# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #346 (@BakaPhoenix, +1 @magdalar): show a book's original imported
filename. Ingest renames files to match their (possibly wrongly auto-matched)
metadata, so the as-imported name is the one stable reference for recognizing
misidentified books while fixing tags.

Three prongs, pinned here:
  1. Capture — ingest_processor snapshots the ingest-folder basename at
     processor construction (the filepath never mutates, but capturing at
     __init__ makes that immune to future refactors) and records it for
     every book id a successful add produced. Best-effort direct sqlite
     write to app.db (the processor's established pattern for app.db
     access) with ON CONFLICT(book_id) DO NOTHING — the CREATING import
     wins; later format additions never overwrite the original.
  2. Display — read-only on the book detail page and the edit page.
  3. Hygiene — delete_whole_book removes the row with the other ub
     book-scoped rows.
"""

import re
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UB_PY = REPO_ROOT / "cps" / "ub.py"
WEB_PY = REPO_ROOT / "cps" / "web.py"
EDITBOOKS = REPO_ROOT / "cps" / "editbooks.py"
INGEST = REPO_ROOT / "scripts" / "ingest_processor.py"
DETAIL = REPO_ROOT / "cps" / "templates" / "detail.html"
BOOK_EDIT = REPO_ROOT / "cps" / "templates" / "book_edit.html"


@pytest.mark.unit
class TestModel:
    def test_model_exists_with_expected_columns(self):
        src = UB_PY.read_text(encoding="utf-8")
        assert "class BookOriginalFilename(Base)" in src
        body = src.split("class BookOriginalFilename(Base)", 1)[1][:1500]
        assert "__tablename__ = 'book_original_filename'" in body
        assert "book_id" in body and "filename" in body and "created_at" in body

    def test_table_created_by_add_missing_tables(self):
        src = UB_PY.read_text(encoding="utf-8")
        body = src.split("def add_missing_tables(", 1)[1]
        body = body.split("\ndef ", 1)[0]
        assert "book_original_filename" in body, (
            "add_missing_tables must create book_original_filename so the "
            "table exists before the ingest processor's first write"
        )


@pytest.mark.unit
class TestIngestCapture:
    def test_basename_captured_at_init(self):
        src = INGEST.read_text(encoding="utf-8")
        init = src.split("class NewBookProcessor", 1)[1]
        init = init.split("def ", 2)[2] if False else init
        assert re.search(r"self\.original_filename\s*=\s*Path\(filepath\)\.name", init), (
            "NewBookProcessor must snapshot the ingest-folder basename at "
            "__init__ — before any conversion/rename can touch it"
        )

    def test_record_method_uses_on_conflict_do_nothing(self):
        src = INGEST.read_text(encoding="utf-8")
        assert "def record_original_filename" in src
        body = src.split("def record_original_filename", 1)[1]
        body = body.split("\n    def ", 1)[0]
        assert "ON CONFLICT(book_id) DO NOTHING" in body, (
            "the CREATING import wins; format additions must never "
            "overwrite the original filename"
        )
        assert "get_app_db_path()" in body, (
            "must resolve app.db the same way the processor's other "
            "app.db reads do"
        )

    def test_fallback_ids_never_recorded(self):
        """Adversarial-review finding: _fallback_last_added_book_id guesses
        the most-recently-modified book when calibredb output parsing
        fails — under concurrent ingest that can be ANOTHER processor's
        book. A wrong 'Imported as' is worse than none, so recording is
        gated on ids that came from parsed output."""
        src = INGEST.read_text(encoding="utf-8")
        body = src.split("def record_original_filename", 1)[1]
        body = body.split("\n    def ", 1)[0]
        assert "last_added_ids_are_fallback" in body, (
            "record_original_filename must skip fallback-inferred book ids"
        )
        fb = src.split("def _fallback_last_added_book_id", 1)[1]
        fb = fb.split("\n    def ", 1)[0]
        assert "last_added_ids_are_fallback = True" in fb, (
            "_fallback_last_added_book_id must mark its ids as guesses"
        )

    def test_record_called_after_successful_add(self):
        src = INGEST.read_text(encoding="utf-8")
        assert re.search(
            r"Added \{staged_path\.stem\} to Calibre database.*?self\.record_original_filename\(\)",
            src, re.DOTALL), (
            "record_original_filename must run after the calibredb add "
            "succeeds (both text and audiobook branches converge there)"
        )

    def test_insert_semantics_behavioral(self, tmp_path):
        """Run the real SQL against a real SQLite file: first write wins,
        second (format-add) is a no-op, different book id inserts."""
        db = tmp_path / "app.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE book_original_filename ("
            "book_id INTEGER PRIMARY KEY, filename VARCHAR NOT NULL, "
            "created_at DATETIME)"
        )
        sql = ("INSERT INTO book_original_filename (book_id, filename, created_at) "
               "VALUES (?, ?, datetime('now')) ON CONFLICT(book_id) DO NOTHING")
        con.execute(sql, (7, "fan_translation_v2_FINAL.epub"))
        con.execute(sql, (7, "renamed_by_format_add.kepub"))
        con.execute(sql, (8, "other.epub"))
        con.commit()
        rows = dict(con.execute(
            "SELECT book_id, filename FROM book_original_filename").fetchall())
        assert rows == {7: "fan_translation_v2_FINAL.epub", 8: "other.epub"}


@pytest.mark.unit
class TestDisplayAndHygiene:
    def test_show_book_passes_original_filename(self):
        src = WEB_PY.read_text(encoding="utf-8")
        assert "BookOriginalFilename" in src and "original_filename=" in src, (
            "show_book must query ub.BookOriginalFilename and pass "
            "original_filename to detail.html"
        )

    def test_detail_template_renders_it(self):
        tpl = DETAIL.read_text(encoding="utf-8")
        assert "original_filename" in tpl, (
            "detail.html must render the imported-as filename (read-only)"
        )

    def test_edit_template_renders_it(self):
        tpl = BOOK_EDIT.read_text(encoding="utf-8")
        assert "original_filename" in tpl, (
            "book_edit.html must render the imported-as filename (read-only)"
        )

    def test_edit_render_passes_it(self):
        src = EDITBOOKS.read_text(encoding="utf-8")
        assert src.count("original_filename=") >= 1 and "BookOriginalFilename" in src, (
            "render_edit_book must pass original_filename"
        )

    def test_delete_whole_book_cleans_row(self):
        src = EDITBOOKS.read_text(encoding="utf-8")
        body = src.split("def delete_whole_book(", 1)[1].split("\ndef ", 1)[0]
        assert "BookOriginalFilename" in body, (
            "delete_whole_book must remove the book_original_filename row "
            "alongside the other ub book-scoped rows"
        )
