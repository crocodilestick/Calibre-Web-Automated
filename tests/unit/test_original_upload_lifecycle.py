# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute lifecycle entry points without initializing the Flask application."""

import ast
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


def _function(relative_path, name, namespace):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), relative_path, "exec"), namespace)  # noqa: S102 - execute one selected AST function in an isolated namespace
    return namespace[name]


class _Session:
    def __init__(self, events, fail_commit=False):
        self.events = events
        self.fail_commit = fail_commit

    def commit(self):
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def delete(self):
        self.events.append("delete-format")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        pass


def _environment(monkeypatch, events):
    module = ModuleType("original_uploads")
    module.forget_uploads = lambda *args: events.append(("forget", args))
    module.transfer_uploads = lambda *args: events.append(("transfer", args))
    monkeypatch.setitem(__import__("sys").modules, "original_uploads", module)
    logger = SimpleNamespace(**{name: lambda *args: None for name in (
        "warning", "error", "error_or_exception", "info", "debug",
    )})
    return {
        "os": os,
        "json": json,
        "log": logger,
        "config": SimpleNamespace(config_calibre_dir="/metadata", get_book_path=lambda: "/files"),
    }, module


def _delete(monkeypatch, events, success=True, fail_commit=False):
    env, provenance = _environment(monkeypatch, events)
    field = SimpleNamespace(book=0, format="EPUB")
    env.update(
        current_user=SimpleNamespace(role_delete_books=lambda: True),
        calibre_db=SimpleNamespace(
            get_book=lambda _id: SimpleNamespace(id=7, uuid="source-uuid"),
            session=_Session(events, fail_commit),
        ),
        helper=SimpleNamespace(delete_book=lambda *args, **kwargs: (success, "file failure" if not success else None)),
        delete_whole_book=lambda *args: events.append("delete-whole"),
        db=SimpleNamespace(Data=field),
        kobo_sync_status=SimpleNamespace(remove_synced_book=lambda *args: None),
        _refresh_duplicates_after_deletion=lambda *args: None,
        _invalidate_duplicate_cache=lambda: None,
        render_delete_book_result=lambda *args: "deleted",
        url_for=lambda *args, **kwargs: "/book",
        # Existing error responses include exception objects; isolate that unrelated behavior.
        json=SimpleNamespace(dumps=lambda value: json.dumps(value, default=str)),
    )
    return _function("cps/editbooks.py", "delete_book_from_table", env), provenance


@pytest.mark.parametrize("file_format", ["", "EPUB"])
def test_delete_forgets_only_after_metadata_commit(monkeypatch, file_format):
    events = []
    delete, _ = _delete(monkeypatch, events)
    assert delete(7, file_format, True) == "deleted"
    assert events[-2:] == ["commit", ("forget", ("/metadata/metadata.db", "source-uuid", file_format or None))]


@pytest.mark.parametrize("failure", ["files", "commit"])
def test_failed_delete_does_not_forget_original_upload(monkeypatch, failure):
    events = []
    delete, _ = _delete(monkeypatch, events, success=failure != "files", fail_commit=failure == "commit")
    delete(7, "", True)
    assert not any(isinstance(event, tuple) and event[0] == "forget" for event in events)


def test_provenance_failure_does_not_report_committed_delete_as_failed(monkeypatch):
    events = []
    delete, provenance = _delete(monkeypatch, events)
    provenance.forget_uploads = lambda *args: (_ for _ in ()).throw(RuntimeError("locked"))
    assert delete(7, "", True) == "deleted"
    assert "rollback" not in events


@pytest.mark.parametrize("entry_point", ["list", "duplicates"])
def test_merge_transfers_only_copied_formats_after_commit(monkeypatch, entry_point):
    events = []
    env, _ = _environment(monkeypatch, events)
    target = SimpleNamespace(id=1, uuid="target-uuid", title="Target", authors=[SimpleNamespace(name="Author")],
                             path="Author/Target", data=[SimpleNamespace(format="EPUB")])
    source = SimpleNamespace(id=2, uuid="source-uuid", path="Author/Source", data=[
        SimpleNamespace(format="EPUB", name="Existing", uncompressed_size=4),
        SimpleNamespace(format="PDF", name="Copied", uncompressed_size=8),
    ])
    env.update(
        calibre_db=SimpleNamespace(get_book=lambda book_id: {1: target, 2: source}[book_id], session=_Session(events)),
        helper=SimpleNamespace(get_valid_filename=lambda value, **kwargs: value),
        db=SimpleNamespace(Data=lambda *args: SimpleNamespace(format=args[1])),
        copyfile=lambda source, target: events.append("copy"),
        request=SimpleNamespace(get_json=lambda: {"Merge_books": [1, 2]}),
        delete_book_from_table=lambda *args, **kwargs: events.append("delete-source"),
        _refresh_duplicates_after_bulk_deletion=lambda *args: None,
        _queue_duplicate_scan_after_change=lambda *args: None,
    )
    if entry_point == "list":
        _function("cps/editbooks.py", "merge_list_book", env)()
    else:
        _function("cps/duplicates.py", "merge_duplicate_group", env)(target, [source])
    transfer = ("transfer", ("/metadata/metadata.db", "source-uuid", "target-uuid", ["PDF"]))
    assert transfer in events
    assert events.index("commit") < events.index(transfer)
    assert events.count("copy") == 1
    if entry_point == "list":
        assert events.index(transfer) < events.index("delete-source")


def test_duplicate_resolution_clears_provenance_after_commit(monkeypatch):
    events = []
    env, _ = _environment(monkeypatch, events)
    kept = SimpleNamespace(id=1, uuid="kept", title="Book", data=[], path="kept")
    removed = SimpleNamespace(id=2, uuid="removed", title="Book", data=[], path="removed")
    cps = ModuleType("cps")
    cps.helper = SimpleNamespace(delete_book=lambda *args, **kwargs: (True, None))
    modules = {
        "cps": cps,
        "cps.ub": SimpleNamespace(init_db_thread=lambda: None),
        "cps.editbooks": SimpleNamespace(delete_whole_book=lambda *args: events.append("delete")),
        "cps.duplicate_index": SimpleNamespace(delete_book_keys=lambda *args: None),
    }
    for name, module in modules.items():
        monkeypatch.setitem(__import__("sys").modules, name, module)
    env.update(
        os=SimpleNamespace(path=SimpleNamespace(join=os.path.join, exists=lambda path: False), makedirs=lambda *args, **kwargs: None),
        datetime=datetime,
        calibre_db=SimpleNamespace(get_book=lambda book_id: {1: kept, 2: removed}[book_id],
                                   session=_Session(events), ensure_session=lambda: None),
        CWA_DB=lambda: SimpleNamespace(scheduled_cancel_for_book=lambda *args: 0, log_duplicate_resolution=lambda **kwargs: None),
        select_book_to_keep=lambda *args: kept,
        validate_resolution_strategy=lambda *args: True,
        _refresh_duplicate_cache_after_resolution=lambda *args: None,
    )
    resolve = _function("cps/duplicates.py", "auto_resolve_duplicates", env)
    result = resolve(strategy="newest", duplicate_groups=[{
        "books": [kept, removed], "group_hash": "abcd", "title": "Book", "author": "Author",
    }])
    assert result["deleted_count"] == 1
    assert events[:3] == ["delete", "commit", ("forget", ("/metadata/metadata.db", "removed"))]


def test_committed_deletion_cleans_real_database_without_cross_library_deletion(monkeypatch, tmp_path):
    events = []
    delete, provenance = _delete(monkeypatch, events)
    module_path = ROOT / "scripts/original_uploads.py"
    spec = importlib.util.spec_from_file_location("lifecycle_original_uploads", module_path)
    real = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, real)
    spec.loader.exec_module(real)
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    metadata = metadata_dir / "metadata.db"
    with sqlite3.connect(metadata) as con:
        con.execute("CREATE TABLE library_id (uuid TEXT)")
        con.execute("INSERT INTO library_id VALUES ('library-one')")
    with sqlite3.connect(tmp_path / "cwa.db") as con:
        con.executescript((ROOT / "scripts/cwa_schema.sql").read_text())
        for lib_uuid in ("library-one", "library-two"):
            con.execute(
                "INSERT INTO cwa_original_uploads "
                "(library_uuid, book_id, book_uuid, format, original_sha256, original_size, "
                "original_ext, output_sha256, role) VALUES (?, 7, 'source-uuid', 'PDF', ?, 4, 'PDF', ?, 'primary')",
                (lib_uuid, "a" * 64, "b" * 64),
            )
    monkeypatch.setenv("CWA_DB_PATH", str(tmp_path))
    delete.__globals__["config"].config_calibre_dir = str(metadata_dir)
    provenance.forget_uploads = real.forget_uploads
    assert delete(7, "", True) == "deleted"
    with sqlite3.connect(tmp_path / "cwa.db") as con:
        assert con.execute("SELECT library_uuid FROM cwa_original_uploads").fetchall() == [("library-two",)]
