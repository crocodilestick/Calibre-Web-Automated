# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pin the chmod-EPERM tolerance in `move_files_on_change`.

Reporter scenario (janeczku/calibre-web#3437): user uploads a book on a
restricted filesystem (CIFS, certain Docker bind mounts) where
`os.rename` returns Errno 18 ("Invalid cross-device link") because the
staging dir and library dir are on different devices. The existing
fallback at `helper.py:625` is `shutil.copy2 + os.remove`.

`shutil.copy2` does `copyfile` *then* `copystat`. On filesystems that
disallow `chmod` for the running uid (CIFS without explicit
file_mode/dir_mode, certain bind mounts with `nosuid,nodev,ro` semantics
on metadata bits), `copystat` raises `PermissionError([Errno 1]
Operation not permitted)`. Critically: **`copyfile` already succeeded
by the time `copystat` fails** — the file IS at the destination,
only the mode-preservation step blew up.

Before this fix, that EPERM bubbled all the way to the user: they saw
"Operation not permitted" in the UI, the DB row was created pointing
at the new path, but the source file was never removed and the user
saw their upload as "broken" even though the data was actually in
place.

The fix: in the copy+delete fallback path, if `copy2` raises
`PermissionError` *after* the destination file exists, log a warning
about the inability to preserve metadata and proceed with the delete.
Data integrity is preserved; mode preservation is best-effort on
filesystems that allow it.
"""

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helper: minimal localbook stand-in
# ---------------------------------------------------------------------------

def _make_localbook():
    """The function we test sets `localbook.path`; nothing else is read."""
    return SimpleNamespace(id=1, path="")


# ---------------------------------------------------------------------------
# Mock copy2 that mirrors the real failure mode:
#   1. copyfile succeeds — data IS written
#   2. copystat fails with PermissionError(EPERM)
# ---------------------------------------------------------------------------

def _copy2_with_chmod_eperm(src, dst, **kwargs):
    """Drop-in replacement for shutil.copy2 that writes data then errors."""
    shutil.copyfile(src, dst)
    raise PermissionError(1, "Operation not permitted", dst)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestMoveFilesChmodEperm:
    """Pin: chmod-EPERM after successful copyfile must not fail the move."""

    def test_chmod_eperm_after_copy_does_not_surface_as_error(self, tmp_path, monkeypatch):
        """If copy2's copystat fails after data is at dest, treat as success."""
        from cps.helper import move_files_on_change

        # Set up source and destination dirs on a "different filesystem"
        staging = tmp_path / "tmp" / "calibre_web"
        staging.mkdir(parents=True)
        library = tmp_path / "books"
        library.mkdir()

        src_file = staging / "abc123"
        src_file.write_bytes(b"%PDF-1.4 fake-pdf-bytes")

        def _raise_xdev(src, dst):
            raise OSError(18, "Invalid cross-device link", src)

        monkeypatch.setattr("cps.helper.shutil.move", _raise_xdev)
        monkeypatch.setattr("cps.helper.shutil.copy2", _copy2_with_chmod_eperm)

        result = move_files_on_change(
            calibre_path=str(library),
            new_author_dir="Test Author",
            new_titledir="Test Book (1)",
            localbook=_make_localbook(),
            db_filename="Test Book.pdf",
            original_filepath=str(src_file),
            path="",
        )

        assert result is None or result == False, \
            f"Expected no user-visible error, got: {result!r}"
        dest = library / "Test Author" / "Test Book (1)" / "Test Book.pdf"
        assert dest.exists(), "Destination file must exist after fallback"
        assert dest.read_bytes() == b"%PDF-1.4 fake-pdf-bytes", \
            "Destination contents must match source"
        assert not src_file.exists(), \
            "Source file must be removed after successful copy"

    def test_localbook_path_updated_on_chmod_eperm_success(self, tmp_path, monkeypatch):
        """The DB-write side effect (localbook.path) must still happen."""
        from cps.helper import move_files_on_change

        staging = tmp_path / "tmp"
        staging.mkdir()
        library = tmp_path / "books"
        library.mkdir()

        src_file = staging / "src"
        src_file.write_bytes(b"epub-data")

        def _raise_xdev(src, dst):
            raise OSError(18, "Invalid cross-device link", src)

        monkeypatch.setattr("cps.helper.shutil.move", _raise_xdev)
        monkeypatch.setattr("cps.helper.shutil.copy2", _copy2_with_chmod_eperm)

        book = _make_localbook()
        move_files_on_change(
            calibre_path=str(library),
            new_author_dir="A",
            new_titledir="B (1)",
            localbook=book,
            db_filename="B.epub",
            original_filepath=str(src_file),
            path="",
        )

        assert book.path == "A/B (1)", \
            f"localbook.path must be set on success, got: {book.path!r}"

    def test_copy_failure_before_data_still_raises(self, tmp_path, monkeypatch):
        """If both copy2 AND the data-only copyfile fallback fail (no
        data ever written), the error must still surface — we must not
        silently swallow ENOSPC / EACCES on the dst dir.

        After the CWA #3437 refactor, copy2 is no longer called
        directly from helper.py — it's wrapped in
        copy_with_metadata_fallback, which retries via copyfile on
        OSError. To simulate "data never written" we have to make BOTH
        copy2 and copyfile fail inside the helper.
        """
        from cps.helper import move_files_on_change

        staging = tmp_path / "tmp"
        staging.mkdir()
        library = tmp_path / "books"
        library.mkdir()

        src_file = staging / "src"
        src_file.write_bytes(b"data")

        def _raise_xdev(src, dst):
            raise OSError(18, "Invalid cross-device link", src)

        def _fail_before_copy(src, dst, **kw):
            # Simulate dest disk full or read-only — no data written.
            raise OSError(28, "No space left on device", dst)

        monkeypatch.setattr("cps.helper.shutil.move", _raise_xdev)
        # Hit the fallback helper's underlying calls. Both must fail to
        # simulate "data never written" (copy2 fails → copyfile retry
        # also fails).
        monkeypatch.setattr(
            "cps.services.file_move.shutil.copy2", _fail_before_copy
        )
        monkeypatch.setattr(
            "cps.services.file_move.shutil.copyfile", _fail_before_copy
        )

        result = move_files_on_change(
            calibre_path=str(library),
            new_author_dir="A",
            new_titledir="B (1)",
            localbook=_make_localbook(),
            db_filename="B.epub",
            original_filepath=str(src_file),
            path="",
        )

        assert isinstance(result, str) and result, \
            f"Real failure (no data at dest) must return an error string, got: {result!r}"
        assert src_file.exists(), \
            "Source file must remain when copy fails (no data loss)"
