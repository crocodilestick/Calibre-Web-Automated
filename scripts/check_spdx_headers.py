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
  python check_spdx_headers.py [files...]
If no files provided, it inspects staged git changes (added/copied/modified).

Exit codes:
  0 = all good
  1 = problems found / errors

Customize REQUIRED_SUBSTRINGS if needed.
"""
from __future__ import annotations

import subprocess
import sys
import pathlib
from typing import List

REQUIRED_SUBSTRINGS = [
    "Calibre-Web Automated",  # attribution line
    "SPDX-License-Identifier: GPL-3.0-or-later",
]

VALID_EXT = {".py", ".sh", ".js", ".ts", ".css", ".html"}

EXCLUDE_DIR = {"__pycache__", ".git", "dist", "build", "node_modules", "venv", ".venv"}


def staged_files() -> List[pathlib.Path]:
    try:
        out = subprocess.check_output([
            "git", "diff", "--cached", "--name-only", "--diff-filter=ACM"
        ], text=True)
    except Exception:
        return []
    files = []
    for line in out.splitlines():
        p = pathlib.Path(line.strip())
        if not p.exists():
            continue
        if any(part in EXCLUDE_DIR for part in p.parts):
            continue
        if p.suffix.lower() in VALID_EXT:
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
    if len(argv) > 1:
        targets = [pathlib.Path(a) for a in argv[1:]]
    else:
        targets = staged_files()

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
        print("Hint: run: python scripts/update_spdx_headers.py --apply")
        return 1
    print("All headers OK.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
