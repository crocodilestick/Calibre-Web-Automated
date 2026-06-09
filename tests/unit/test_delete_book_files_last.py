# -*- coding: utf-8 -*-
"""Whole-book delete is DB-commit-first, files-last (data-safety, D3-sibling).

`delete_book_from_table` (the normal delete path — the edit-book "Delete" button,
batch delete, ingest auto-merge) used to remove a book's files (`helper.delete_book`)
BEFORE committing the DB deletes (`delete_whole_book` + `calibre_db.session.commit`).
A failure in the DB phase then left the files gone but the `Books` row surviving — a
phantom book that still shows in the library and 404s when opened, unrecoverable
without the backup. This is the exact defect fixed in the duplicate-resolution path
(D3, #399); this pins the same fix for the normal delete path.

The whole-book branch now: commit the DB deletes first, then remove files last via a
plain-value stand-in (`_DeletedBookFileRef`) — never the now-detached ORM `book`
(`delete_whole_book`'s intermediate commits expire/detach it). A post-commit file
cleanup failure is logged + surfaced as a warning, not raised (the row is already
gone; orphaned files are reclaimable). The single-format branch is intentionally left
files-first (a failure orphans at most one format's row, and the format's on-disk path
is resolved from that Data row) — see notes/delete-ordering-d4-findings.md.

The behavioural proof is the live cwn-local repro (injected delete_whole_book failure ->
book row + files both survive). These source-pins lock the ordering.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
EDITBOOKS = REPO / "cps" / "editbooks.py"


def _func_src():
    src = EDITBOOKS.read_text(encoding="utf-8")
    body = src.split("def delete_book_from_table", 1)[1]
    return body.split("\ndef ", 1)[0]


def test_whole_book_db_commit_precedes_file_delete():
    body = _func_src()
    db_delete = body.find("delete_whole_book(deleted_book_id, book)")
    file_ref = body.find("_DeletedBookFileRef(deleted_book_id, deleted_book_path)")
    assert db_delete != -1, "whole-book branch must call delete_whole_book(deleted_book_id, book)"
    assert file_ref != -1, "whole-book file cleanup must use the _DeletedBookFileRef stand-in"
    commit = body.find("calibre_db.session.commit()", db_delete)
    assert db_delete < commit < file_ref, (
        "whole-book delete must commit the DB deletes (delete_whole_book + "
        "calibre_db.session.commit()) BEFORE removing files, so a DB failure can't "
        "leave a phantom book whose files are already gone (D3-sibling)"
    )


def test_whole_book_file_cleanup_uses_standin_not_orm_book():
    body = _func_src()
    # the whole-book files-last call must hand helper.delete_book the plain stand-in,
    # not the ORM `book` (detached/expired after delete_whole_book).
    assert "_DeletedBookFileRef(deleted_book_id, deleted_book_path)" in body
    assert "deleted_book_path = book.path" in body, (
        "book.path must be captured as a plain value before the DB delete"
    )


def test_whole_book_file_failure_is_logged_not_returned():
    body = _func_src()
    ref = body.find("_DeletedBookFileRef(deleted_book_id, deleted_book_path)")
    after = body[ref:]
    # after the DB is committed, a file-cleanup failure must be logged/warned, not
    # returned as a hard "danger" (that would falsely report the completed DB delete
    # as failed). The else: starts the single-format branch.
    whole_book_tail = after.split("\n                else:", 1)[0]
    assert "removed from the database but file" in whole_book_tail, (
        "whole-book file-cleanup failure must log a warning"
    )
    assert "return json.dumps" not in whole_book_tail, (
        "whole-book file-cleanup failure must NOT return a danger response — the DB "
        "delete already succeeded (D3-sibling)"
    )


def test_standin_class_defined():
    src = EDITBOOKS.read_text(encoding="utf-8")
    assert "class _DeletedBookFileRef:" in src
    assert '__slots__ = ("id", "path")' in src
