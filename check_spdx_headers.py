#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
check_spdx_headers.py

Lightweight checker to ensure each staged source file (or specified paths) contains
an SPDX identifier (GPL-3.0-or-later) and the Calibre-Web Automated attribution header.
Intended for use in a pre-commit hook.

Usage:
  python check_spdx_headers.py [--ext .py,.js] [files...]
If no files provided, it inspects staged git changes (added/copied/modified).

Exit codes:
  0 = all good
  1 = problems found / errors

File types checked default to update_spdx_headers.py DEFAULT_EXTS.
"""
from __future__ import annotations

import argparse
import importlib
import pathlib
import subprocess
import sys
from typing import List, Sequence

REQUIRED_SUBSTRINGS = [
    "Calibre-Web Automated",  # attribution line
    "SPDX-License-Identifier: GPL-3.0-or-later",
]

EXCLUDE_DIR = {"__pycache__", ".git", "dist", "build", "node_modules", "venv", ".venv"}


def resolve_update_module_exts() -> List[str]:
    """Try to import DEFAULT_EXTS from update_spdx_headers.py (scripts/ or repo root)."""
    candidates = [
        ("scripts.update_spdx_headers", "scripts/update_spdx_headers.py"),
        ("update_spdx_headers", "update_spdx_headers.py"),
    ]
    for mod_name, _ in candidates:
        try:
            mod = importlib.import_module(mod_name)
            exts = getattr(mod, "DEFAULT_EXTS", None)
            if isinstance(exts, (list, tuple)) and exts:
                # normalize to dot-prefixed lowercase
                return [e if e.startswith(".") else "." + e for e in map(str, exts)]
        except Exception:
            continue
    # Fallback to Python only
    return [".py"]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check SPDX/attribution headers on staged files")
    p.add_argument("files", nargs="*", help="Specific files to check (default: staged)")
    p.add_argument("--ext", default=",".join(resolve_update_module_exts()), help="Comma-separated extensions to check (default aligns with update_spdx_headers.py)")
    return p.parse_args(list(argv))


def staged_files(valid_ext: set[str]) -> List[pathlib.Path]:
    try:
        out = subprocess.check_output([
            "git", "diff", "--cached", "--name-only", "--diff-filter=ACM"
        ], text=True)
    except Exception:
        return []
    files: List[pathlib.Path] = []
    for line in out.splitlines():
        p = pathlib.Path(line.strip())
        if not p.exists():
            continue
        if any(part in EXCLUDE_DIR for part in p.parts):
            continue
        if p.suffix.lower() in valid_ext:
            files.append(p)
    return files


def check_file(path: pathlib.Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return [f"{path}: unable to read ({e})"]
    missing = [s for s in REQUIRED_SUBSTRINGS if s not in text]
    if missing:
        return [f"{path}: missing -> {', '.join(missing)}"]
    return []


def main(argv: List[str]) -> int:
    args = parse_args(argv[1:])
    exts = [e.strip() for e in args.ext.split(",") if e.strip()]
    valid_ext = {e if e.startswith('.') else '.' + e for e in exts}

    if args.files:
        targets = [pathlib.Path(a) for a in args.files if pathlib.Path(a).suffix.lower() in valid_ext]
    else:
        targets = staged_files(valid_ext)

    if not targets:
        print("No files to check.")
        return 0

    problems: List[str] = []
    for f in targets:
        problems.extend(check_file(f))

    if problems:
        print("SPDX / attribution header check failed:")
        for p in problems:
            print("  ", p)
        # Choose best hint path for updater
        updater = "scripts/update_spdx_headers.py" if pathlib.Path("scripts/update_spdx_headers.py").exists() else "update_spdx_headers.py"
        print(f"Hint: run: python {updater} --apply --ext {','.join(sorted(valid_ext))}")
        return 1
    print("All headers OK.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
