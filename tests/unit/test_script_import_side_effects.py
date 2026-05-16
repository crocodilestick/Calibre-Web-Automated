# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test pinning that importing scripts has NO side effects.

Background — pytest-xdist runs workers as separate Python processes
sharing /tmp. Three scripts (ingest_processor, kindle_epub_fixer,
convert_library) historically acquired their single-instance lockfile
at module-import time and called sys.exit(2) when another worker had
already taken the lock. That made `importlib.import_module(...)` in a
test exit the worker process with code 2, taking out unrelated tests.

The fix moves all lock-acquire calls and atexit-register calls into the
main() / __main__ path so importing the module is a pure load.

This test pins that behavior: importing any of these scripts in a
subprocess (a) succeeds with exit code 0, (b) does NOT create any
lockfile in /tmp, (c) does NOT register an atexit handler that would
remove a lockfile we didn't create.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _run_import(module_name: str, pre_existing_lockfile: str | None = None):
    """Spawn a fresh Python process that imports module_name.

    Returns (returncode, stdout, stderr, lockfiles_created).
    `lockfiles_created` is the set of lock filenames present in
    /tmp after the import that were not present before.
    """
    tmpdir = Path(tempfile.gettempdir())
    lockfiles_before = {p.name for p in tmpdir.glob("*.lock")}

    if pre_existing_lockfile:
        (tmpdir / pre_existing_lockfile).touch()

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{SCRIPTS_DIR}:{REPO_ROOT}"
        result = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    finally:
        if pre_existing_lockfile:
            (tmpdir / pre_existing_lockfile).unlink(missing_ok=True)

    lockfiles_after = {p.name for p in tmpdir.glob("*.lock")}
    lockfiles_created = lockfiles_after - lockfiles_before
    return result.returncode, result.stdout, result.stderr, lockfiles_created


class TestImportIsSideEffectFree:
    """Import-time side effects break test isolation under pytest-xdist."""

    @pytest.mark.parametrize("module", ["ingest_processor", "kindle_epub_fixer", "convert_library"])
    def test_import_succeeds_when_no_lockfile_present(self, module):
        rc, stdout, stderr, created = _run_import(module)
        assert rc == 0, (
            f"Importing {module} exited with {rc}. "
            f"stdout={stdout!r} stderr={stderr!r}. "
            "Module-import-time side effects break test isolation."
        )

    @pytest.mark.parametrize(
        "module,lockfile",
        [
            ("ingest_processor", "ingest_processor.lock"),
            ("ingest_processor", "kindle_epub_fixer.lock"),
            ("kindle_epub_fixer", "kindle_epub_fixer.lock"),
            ("convert_library", "convert_library.lock"),
            ("convert_library", "kindle_epub_fixer.lock"),
        ],
    )
    def test_import_succeeds_even_with_stale_lockfile(self, module, lockfile):
        rc, stdout, stderr, created = _run_import(module, pre_existing_lockfile=lockfile)
        assert rc == 0, (
            f"Importing {module} with pre-existing /tmp/{lockfile} "
            f"exited with {rc}. stdout={stdout!r} stderr={stderr!r}. "
            "Stale lockfile from another xdist worker must not crash import."
        )

    @pytest.mark.parametrize("module", ["ingest_processor", "kindle_epub_fixer", "convert_library"])
    def test_import_creates_no_lockfile(self, module):
        rc, stdout, stderr, created = _run_import(module)
        assert rc == 0
        assert not created, (
            f"Importing {module} created lockfiles {created} in /tmp. "
            "Lockfiles must be created only when the script runs as __main__."
        )


class TestSourcePins:
    """Source-level pins so a future refactor that re-introduces the bug
    is caught even if the import side-effect tests pass on a clean /tmp.
    """

    @pytest.mark.parametrize(
        "filename,lockfile_name",
        [
            ("scripts/ingest_processor.py", "ingest_processor.lock"),
            ("scripts/kindle_epub_fixer.py", "kindle_epub_fixer.lock"),
            ("scripts/convert_library.py", "convert_library.lock"),
        ],
    )
    def test_no_module_level_sys_exit_on_lock_collision(self, filename, lockfile_name):
        import ast

        source = (REPO_ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Collect line numbers of sys.exit(...) calls that appear at MODULE level
        # (i.e. not inside a FunctionDef / AsyncFunctionDef / ClassDef).
        module_level_sys_exit_lines = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If)):
                # If-blocks are visited only when they are NOT guarded by __name__ == "__main__"
                if isinstance(node, ast.If):
                    test_src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
                    if "__name__" in test_src:
                        continue
                else:
                    continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    if sub.func.attr == "exit" and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "sys":
                        module_level_sys_exit_lines.append(sub.lineno)

        assert not module_level_sys_exit_lines, (
            f"{filename} has module-level sys.exit() calls at lines "
            f"{module_level_sys_exit_lines}. These exit the import process "
            f"when the lockfile is held by another worker. Move them into "
            f"main() or under `if __name__ == \"__main__\":` instead."
        )

    @pytest.mark.parametrize(
        "filename,helper_name",
        [
            ("scripts/ingest_processor.py", "_acquire_process_lock_or_exit"),
            ("scripts/kindle_epub_fixer.py", "_acquire_lock_or_exit"),
            ("scripts/convert_library.py", "_acquire_lock_or_exit"),
        ],
    )
    def test_main_calls_lock_acquire_helper(self, filename, helper_name):
        """If the lock-acquire helper exists at module level but main() never
        calls it, the script silently loses its single-instance guard while
        all the import-side-effect tests still pass. This pins the wire-up.
        """
        import ast

        source = (REPO_ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)

        helper_defined = any(
            isinstance(n, ast.FunctionDef) and n.name == helper_name
            for n in tree.body
        )
        assert helper_defined, f"{filename} is missing module-level def {helper_name}()"

        main_func = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
            None,
        )
        assert main_func is not None, f"{filename} has no module-level main() function"

        calls_helper = any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == helper_name
            for sub in ast.walk(main_func)
        )
        assert calls_helper, (
            f"{filename}::main() never calls {helper_name}(). The helper "
            f"is defined but not wired up — running the script as __main__ "
            f"would skip single-instance protection and let two concurrent "
            f"invocations both proceed."
        )

    @pytest.mark.parametrize(
        "filename",
        [
            "scripts/ingest_processor.py",
            "scripts/kindle_epub_fixer.py",
            "scripts/convert_library.py",
        ],
    )
    def test_no_module_level_atexit_register(self, filename):
        import ast

        source = (REPO_ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # atexit.register at module level installs a handler the moment we
        # import — even when the lock was never acquired. That would let
        # an `import` followed by interpreter exit clean up a lockfile a
        # different process is relying on.
        module_level_atexit = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.If):
                test_src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
                if "__name__" in test_src:
                    continue
            # ast.Expr wrapping a Call
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "register"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "atexit"
                ):
                    module_level_atexit.append(call.lineno)

        assert not module_level_atexit, (
            f"{filename} has module-level atexit.register() at lines "
            f"{module_level_atexit}. Move into the lock-acquire helper "
            f"so the handler is only installed when the lock was actually taken."
        )
