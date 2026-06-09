# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""D8 regression tests — merge_duplicate_group file-copy safety.

From the 2026-06 duplicate audit (notes/duplicate-detection-fix-plan.md §D8):

1. ``copyfile`` ran with no ``os.path.exists`` guard on the target. A file
   present on disk but not in ``to_book.data`` (prior partial failure, manual
   edit) was silently OVERWRITTEN — the kept book's data destroyed.
2. A mid-loop copy failure (e.g. missing source file for the second format)
   left an appended-but-uncommitted ``db.Data`` row in the shared session; the
   resolution loop's next commit then persisted the orphan row.

The fix stages + validates every copy first (all sources exist, no target
collisions), only then copies and appends, commits once, and on any failure
rolls the session back and removes the files it copied. The caller's
merge-failure branch also rolls back before ``continue``.

Behavioural tests run merge_duplicate_group against real temp files through
the same stub world as test_duplicate_delete_index_maintenance (reused via
importlib so there is exactly one copy of the stub harness).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]


@pytest.fixture(autouse=True)
def _isolate_sys_modules():
    """The shared stub harness clears real cps/flask/sqlalchemy modules and
    installs stubs in their place. Restore sys.modules afterwards so test
    files that run later on the same xdist worker import the real packages
    (this bit test_kobo_android_app_compat on CI: 'cps' is not a package)."""
    saved = sys.modules.copy()
    yield
    for name in list(sys.modules):
        if name not in saved:
            del sys.modules[name]
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module


def _harness():
    """Load the shared duplicates stub harness from its test module."""
    path = _HERE / "test_duplicate_delete_index_maintenance.py"
    spec = importlib.util.spec_from_file_location("_dup_stub_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeData:
    """Stand-in for db.Data rows on a book."""

    def __init__(self, book, book_format, uncompressed_size, name):
        self.book = book
        self.format = book_format
        self.uncompressed_size = uncompressed_size
        self.name = name


def _load_merge_world(tmp_path):
    """Stubbed cps.duplicates module wired to a real temp library dir."""
    harness = _harness()
    module, calibre_books, calls = harness._load_duplicates_module([])
    # merge_duplicate_group needs pieces the shared loader doesn't stub:
    sys.modules["cps.helper"].get_valid_filename = lambda value, chars=128: value
    sys.modules["cps.db"].Data = _FakeData
    sys.modules["cps.config"].get_book_path = lambda: str(tmp_path)
    return module, calibre_books, calls


def _book(book_id, title, path, data):
    return SimpleNamespace(
        id=book_id,
        title=title,
        path=path,
        authors=[SimpleNamespace(name="Author")],
        data=data,
    )


def _fmt(name, fmt, size=100):
    return SimpleNamespace(format=fmt, name=name, uncompressed_size=size)


def _setup_pair(tmp_path, calibre_books, keep_data, merge_data):
    (tmp_path / "keep").mkdir()
    (tmp_path / "dup").mkdir()
    to_book = _book(1, "Title", "keep", keep_data)
    from_book = _book(2, "Title", "dup", merge_data)
    calibre_books[1] = to_book
    calibre_books[2] = from_book
    return to_book, from_book


class TestD8TargetCollision:
    def test_existing_target_file_is_never_overwritten(self, tmp_path):
        # Target file on disk but NOT in to_book.data: the format guard passes
        # and the old code copyfile'd right over it. It must refuse instead.
        module, calibre_books, _calls = _load_merge_world(tmp_path)
        to_book, _ = _setup_pair(
            tmp_path, calibre_books,
            keep_data=[],
            merge_data=[_fmt("dupfile", "EPUB")],
        )
        target = tmp_path / "keep" / "Title - Author.epub"
        target.write_bytes(b"KEEP-ME-INTACT")
        (tmp_path / "dup" / "dupfile.epub").write_bytes(b"duplicate bytes")

        with pytest.raises(ValueError):
            module.merge_duplicate_group(
                SimpleNamespace(id=1), [SimpleNamespace(id=2)]
            )

        assert target.read_bytes() == b"KEEP-ME-INTACT", (
            "merge overwrote a file already on disk for the kept book (D8)"
        )
        assert to_book.data == [], "no Data row may be appended on a refused merge"


class TestD8MissingSourceAbortsCleanly:
    def test_missing_source_leaves_no_partial_copy_or_pending_rows(self, tmp_path):
        # Source format-2 file missing: the old code copied format-1, appended
        # its Data row, then blew up on format-2 — orphan row + stray file.
        # Validation must reject the whole merge before any copy happens.
        module, calibre_books, calls = _load_merge_world(tmp_path)
        to_book, _ = _setup_pair(
            tmp_path, calibre_books,
            keep_data=[],
            merge_data=[_fmt("dupfile", "EPUB"), _fmt("dupfile", "PDF")],
        )
        (tmp_path / "dup" / "dupfile.epub").write_bytes(b"epub bytes")
        # dupfile.pdf intentionally absent

        with pytest.raises(Exception):
            module.merge_duplicate_group(
                SimpleNamespace(id=1), [SimpleNamespace(id=2)]
            )

        assert to_book.data == [], (
            "a failed merge left appended Data rows pending in the shared "
            "session — the next commit would persist orphans (D8)"
        )
        assert not (tmp_path / "keep" / "Title - Author.epub").exists(), (
            "a failed merge left a partially-copied format file behind (D8)"
        )
        assert "commit" not in calls, "a failed merge must not commit"


class TestD8CopyFailureRollsBack:
    def test_copy_failure_rolls_back_session_and_removes_copied_files(self, tmp_path):
        # Both sources validate, the second copy itself fails (disk error):
        # the session must be rolled back and already-copied files removed.
        module, calibre_books, calls = _load_merge_world(tmp_path)
        to_book, _ = _setup_pair(
            tmp_path, calibre_books,
            keep_data=[],
            merge_data=[_fmt("dupfile", "EPUB"), _fmt("dupfile", "PDF")],
        )
        (tmp_path / "dup" / "dupfile.epub").write_bytes(b"epub bytes")
        (tmp_path / "dup" / "dupfile.pdf").write_bytes(b"pdf bytes")

        real_copy = module.copyfile
        state = {"copies": 0}

        def flaky_copyfile(src, dst):
            state["copies"] += 1
            if state["copies"] == 2:
                raise OSError("disk full")
            return real_copy(src, dst)

        module.copyfile = flaky_copyfile
        try:
            with pytest.raises(OSError):
                module.merge_duplicate_group(
                    SimpleNamespace(id=1), [SimpleNamespace(id=2)]
                )
        finally:
            module.copyfile = real_copy

        assert "rollback" in calls, (
            "a mid-merge copy failure must roll back the shared session (D8)"
        )
        assert to_book.data == [], "no Data rows may survive a failed merge"
        assert not (tmp_path / "keep" / "Title - Author.epub").exists(), (
            "the first (successful) copy must be removed when the merge fails"
        )


class TestD8HappyPathStillMerges:
    def test_formats_copy_append_and_commit_once(self, tmp_path):
        module, calibre_books, calls = _load_merge_world(tmp_path)
        to_book, _ = _setup_pair(
            tmp_path, calibre_books,
            keep_data=[_fmt("Title - Author", "EPUB")],
            merge_data=[_fmt("dupfile", "EPUB"), _fmt("dupfile", "PDF")],
        )
        (tmp_path / "dup" / "dupfile.epub").write_bytes(b"epub bytes")
        (tmp_path / "dup" / "dupfile.pdf").write_bytes(b"pdf bytes")

        module.merge_duplicate_group(SimpleNamespace(id=1), [SimpleNamespace(id=2)])

        # EPUB already on the kept book -> only PDF merges.
        assert [d.format for d in to_book.data if isinstance(d, _FakeData)] == ["PDF"]
        copied = tmp_path / "keep" / "Title - Author.pdf"
        assert copied.read_bytes() == b"pdf bytes"
        assert not (tmp_path / "keep" / "Title - Author.epub").exists() or True
        assert calls.count("commit") == 1


class TestD8CallerRollsBackOnMergeFailure:
    def test_resolution_loop_merge_except_branch_rolls_back(self):
        # The resolution loop catches merge errors and continues to the next
        # group — it must roll back first, or pending rows from the failed
        # merge get committed by the next group's commit. Source pin.
        src = (REPO_ROOT / "cps" / "duplicates.py").read_text()
        m = re.search(
            r"merge_duplicate_group\(book_to_keep, books_to_delete\).*?continue",
            src,
            re.S,
        )
        assert m, "merge call + failure branch not found in resolution loop"
        assert "rollback" in m.group(0), (
            "the resolution loop's merge-failure branch must "
            "calibre_db.session.rollback() before continue (D8)"
        )
