# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for cross-ownership filesystem upload fallback.

Pins the behavior shipped for janeczku/calibre-web#3437: when shutil.copy2
fails (typically EPERM on chmod when src and dst live on differently-owned
filesystems — common in LinuxServer-style PUID/PGID containers with bind
mounts), the upload path must still succeed by retrying with shutil.copyfile
(data only, no metadata).
"""

from __future__ import annotations

import ast
import errno
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def file_move():
    """Import the real `cps.services.file_move` module.

    Earlier versions of this fixture stubbed `cps` / `cps.services` /
    `cps.logger` via `types.ModuleType` to avoid triggering the full cps
    package init. That worked when these tests ran alone but polluted
    `sys.modules` for subsequent tests that imported `cps.helper` —
    they would resolve to the stubs and fail with "no attribute X".
    Importing the real module is fine; cps imports are already
    side-effected by anything else that touches the package.
    """
    from cps.services import file_move as fm
    return fm


class TestCopyWithMetadataFallback:
    """The data path itself."""

    def test_happy_path_uses_copy2_only(self, file_move, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("payload")
        with patch.object(file_move.shutil, "copy2") as mock_copy2, \
             patch.object(file_move.shutil, "copyfile") as mock_copyfile:
            file_move.copy_with_metadata_fallback(str(src), str(dst))
        mock_copy2.assert_called_once_with(str(src), str(dst))
        mock_copyfile.assert_not_called()

    def test_eperm_on_copy2_falls_back_to_copyfile(self, file_move, tmp_path):
        """Errno 1 (EPERM) on chmod step — the janeczku#3437 symptom."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("payload")
        with patch.object(
            file_move.shutil,
            "copy2",
            side_effect=OSError(errno.EPERM, "Operation not permitted"),
        ), patch.object(file_move.shutil, "copyfile") as mock_copyfile:
            file_move.copy_with_metadata_fallback(str(src), str(dst))
        mock_copyfile.assert_called_once_with(str(src), str(dst))

    def test_eacces_on_copy2_also_falls_back(self, file_move, tmp_path):
        """Errno 13 (EACCES) — what NFS / SMB shares often return for chmod denial."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("payload")
        with patch.object(
            file_move.shutil,
            "copy2",
            side_effect=OSError(errno.EACCES, "Permission denied"),
        ), patch.object(file_move.shutil, "copyfile") as mock_copyfile:
            file_move.copy_with_metadata_fallback(str(src), str(dst))
        mock_copyfile.assert_called_once_with(str(src), str(dst))

    def test_eperm_with_filename_arg_falls_back(self, file_move, tmp_path):
        """Match the actual exception shape produced by shutil.copy2 → copystat → chmod."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("payload")
        # shutil internals produce PermissionError with errno=EPERM + filename set
        err = PermissionError(errno.EPERM, "Operation not permitted", str(dst))
        with patch.object(file_move.shutil, "copy2", side_effect=err), \
             patch.object(file_move.shutil, "copyfile") as mock_copyfile:
            file_move.copy_with_metadata_fallback(str(src), str(dst))
        mock_copyfile.assert_called_once_with(str(src), str(dst))

    def test_copyfile_failure_propagates(self, file_move, tmp_path):
        """If the data copy itself fails (ENOSPC, EACCES on dir), bubble up."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("payload")
        with patch.object(
            file_move.shutil,
            "copy2",
            side_effect=OSError(errno.EPERM, "Operation not permitted"),
        ), patch.object(
            file_move.shutil,
            "copyfile",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        ):
            with pytest.raises(OSError) as exc_info:
                file_move.copy_with_metadata_fallback(str(src), str(dst))
        assert exc_info.value.errno == errno.ENOSPC

    def test_real_data_is_copied(self, file_move, tmp_path):
        """End-to-end smoke: actual bytes round-trip through the function."""
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        payload = b"\x00\x01\x02 calibre-web upload \xff\xfe\xfd"
        src.write_bytes(payload)
        file_move.copy_with_metadata_fallback(str(src), str(dst))
        assert dst.read_bytes() == payload

    def test_real_data_copied_even_with_eperm_simulated(self, file_move, tmp_path):
        """Simulate the production failure mode: copy2 fails, copyfile succeeds, bytes present."""
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        payload = b"upload payload from /tmp\x00\xff"
        src.write_bytes(payload)

        original_copy2 = file_move.shutil.copy2

        def copy2_fails_with_eperm(*_args, **_kwargs):
            raise OSError(errno.EPERM, "Operation not permitted")

        with patch.object(file_move.shutil, "copy2", side_effect=copy2_fails_with_eperm):
            file_move.copy_with_metadata_fallback(str(src), str(dst))

        assert dst.read_bytes() == payload
        # Ensure we didn't actually call the real copy2 (would have succeeded in tmp_path)
        assert original_copy2 is file_move.shutil.copy2  # patch restored


class TestHelperCallSitesUseFallback:
    """AST pin: every shutil.copy2 callsite in cps/helper.py should now route through
    copy_with_metadata_fallback. If a future edit reverts a callsite back to
    shutil.copy2(...) directly, this test fails."""

    @pytest.fixture
    def helper_source(self):
        helper_path = Path(__file__).resolve().parents[2] / "cps" / "helper.py"
        return helper_path.read_text()

    def test_helper_imports_copy_with_metadata_fallback(self, helper_source):
        assert "from .services.file_move import copy_with_metadata_fallback" in helper_source, (
            "cps/helper.py must import copy_with_metadata_fallback to route upload-path "
            "copies through the EPERM-aware fallback"
        )

    def test_no_direct_shutil_copy2_calls_in_helper(self, helper_source):
        tree = ast.parse(helper_source)
        direct_copy2_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "copy2"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "shutil"
                ):
                    direct_copy2_calls.append(node.lineno)
        assert direct_copy2_calls == [], (
            f"cps/helper.py still has direct shutil.copy2(...) calls at lines "
            f"{direct_copy2_calls}; these must use copy_with_metadata_fallback to "
            f"survive cross-ownership filesystem mounts (janeczku/calibre-web#3437)"
        )

    def test_helper_uses_fallback_helper_at_least_three_times(self, helper_source):
        # Three known fallback sites: rename_all_files_on_change,
        # move_files_on_change upload path, move_files_on_change merge loop.
        # Count paren-style call sites (excludes the bare-name `import`).
        call_count = helper_source.count("copy_with_metadata_fallback(")
        assert call_count >= 3, (
            f"Expected ≥3 copy_with_metadata_fallback(...) call sites in "
            f"helper.py (rename_all_files_on_change + 2 in "
            f"move_files_on_change); found {call_count}"
        )
        # And the import must be present (defense against forgetting to wire
        # after a refactor that removes a call but leaves the import alone).
        assert "from .services.file_move import copy_with_metadata_fallback" in helper_source, (
            "cps/helper.py must import copy_with_metadata_fallback alongside "
            "its call sites."
        )
