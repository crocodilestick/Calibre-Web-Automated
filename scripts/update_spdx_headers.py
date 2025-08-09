#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
update_spdx_headers.py

Purpose:
  Normalize / insert concise GPL license + attribution headers with SPDX into source files.
  Designed for Calibre-Web Automated (fork of janeczku/calibre-web).

Behavior:
  * Scans files (default: **/*.py) excluding common vendor / build / translation dirs.
  * Detects existing legacy Calibre-Web header blocks and replaces them with the new short form.
  * Inserts header if none present.
  * Respects existing shebang (kept as first line).
  * Avoids duplicating if header already normalized.
  * Updates year range dynamically (current year) and fork start year (2024).
  * DEFAULT ROOT: When --paths is omitted the repository root is inferred as two directories up from this script (scripts/../).

Resulting header (example):
  # Calibre-Web Automated – fork of Calibre-Web
  # Copyright (C) 2018-2025 Calibre-Web contributors
  # Copyright (C) 2024-2025 Calibre-Web Automated contributors
  # SPDX-License-Identifier: GPL-3.0-or-later
  # See CONTRIBUTORS for full list of authors.

CLI:
  --apply              Write changes (default dry-run).
  --paths PATH [PATH]  Limit to specific paths/files.
  --ext .py,.sh        Comma separated list of extensions (default .py)
  --exclude PAT        Extra glob-style exclude (can repeat)
  --print              Print updated content to stdout (only valid when single file & --apply not set)
  --verbose            Verbose logging
  --quiet              Only errors
  --license-only       Only add SPDX line if missing (preserve existing header text otherwise)
  --force-year-start YEAR  Override upstream start year (default 2018)

Exit codes:
  0 success, 1 errors.

NOTE: Commit the CONTRIBUTORS file separately; headers reference it.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys
from typing import Iterable, List

UPSTREAM_START_DEFAULT = 2018
FORK_START = 2024
CURRENT_YEAR = datetime.date.today().year

LEGACY_PATTERNS = [
    re.compile(r"This file is part of the Calibre-Web", re.IGNORECASE),
    re.compile(r"GNU General Public License", re.IGNORECASE),
]

SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*GPL-3\.0-or-later")
HEADER_ALREADY_RE = re.compile(r"Calibre-Web Automated .*?SPDX-License-Identifier: GPL-3\.0-or-later", re.DOTALL)

SHEBANG_RE = re.compile(r"^#!.*\n")
CODING_RE = re.compile(r"^#.*coding[:=].*\n", re.IGNORECASE)

EXCLUDE_DIRS = {
    ".git", "__pycache__", "build", "dist", "venv", ".venv", "env", "node_modules",
    "translations", "locale", "docs/_build", "htmlcov"
}

DEFAULT_EXTS = [".py"]

HEADER_TEMPLATE = (
    "# Calibre-Web Automated – fork of Calibre-Web\n"
    "# Copyright (C) {upstream_start}-{year} Calibre-Web contributors\n"
    "# Copyright (C) {fork_start}-{year} Calibre-Web Automated contributors\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later\n"
    "# See CONTRIBUTORS for full list of authors.\n"
    "\n"
)


def parse_args():
    p = argparse.ArgumentParser(description="Normalize SPDX headers")
    p.add_argument("--apply", action="store_true", help="Write changes (default dry-run)")
    p.add_argument("--paths", nargs="*", help="Optional list of files/dirs to process")
    p.add_argument("--ext", default=",".join(DEFAULT_EXTS), help="Comma separated extensions")
    p.add_argument("--exclude", action="append", default=[], help="Additional directory/file exclude (glob contains)")
    p.add_argument("--print", action="store_true", help="Print updated content (only single file dry-run)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--license-only", action="store_true", help="Only inject SPDX if missing")
    p.add_argument("--force-year-start", type=int, default=UPSTREAM_START_DEFAULT)
    return p.parse_args()


def log(msg: str, *, verbose=False, quiet=False):
    if quiet:
        return
    if verbose:
        print(msg)


def collect_paths(paths: List[str] | None, exts: List[str], extra_excludes: List[str]) -> Iterable[pathlib.Path]:
    if not paths:
        roots = [pathlib.Path.cwd()]
    else:
        roots = [pathlib.Path(p).resolve() for p in paths]
    for root in roots:
        if root.is_file():
            if root.suffix in exts:
                yield root
            continue
        for p in root.rglob("*"):
            if p.is_dir():
                # skip excluded dirs
                if p.name in EXCLUDE_DIRS:
                    continue
                if any(x for x in extra_excludes if x and x in str(p)):
                    continue
                continue
            if p.suffix not in exts:
                continue
            if any(x for x in extra_excludes if x and x in str(p)):
                continue
            yield p


def has_legacy(text: str) -> bool:
    return any(p.search(text[:1000]) for p in LEGACY_PATTERNS)


def already_normalized(text: str) -> bool:
    return HEADER_ALREADY_RE.search(text[:400]) is not None


def build_header(upstream_start: int) -> str:
    return HEADER_TEMPLATE.format(upstream_start=upstream_start, fork_start=FORK_START, year=CURRENT_YEAR)


def extract_preamble(text: str):
    shebang = ""
    coding = ""
    rest = text
    m = SHEBANG_RE.match(rest)
    if m:
        shebang = m.group(0)
        rest = rest[len(shebang):]
    m2 = CODING_RE.match(rest)
    if m2:
        coding = m2.group(0)
        rest = rest[len(coding):]
    return shebang, coding, rest


LEGACY_BLOCK_RE = re.compile(
    r"^(?:#.*Calibre-Web.*\n)(?:#.*\n){0,40}#.*http.*gnu.*licenses.*\n", re.IGNORECASE | re.MULTILINE
)


def normalize(text: str, upstream_start: int, license_only: bool) -> str:
    if license_only:
        if SPDX_RE.search(text):
            return text  # nothing
        # append SPDX at top after any shebang/coding line
        shebang, coding, rest = extract_preamble(text)
        header = f"{shebang}{coding}# SPDX-License-Identifier: GPL-3.0-or-later\n"
        return header + rest

    if already_normalized(text):
        # Maybe year change? Replace years if outdated
        def repl_years(match: re.Match):
            return build_header(upstream_start)
        # Replace only first occurrence of our template block start
        return re.sub(r"^# Calibre-Web Automated .*?\n\n", repl_years, text, count=1, flags=re.DOTALL)

    shebang, coding, rest = extract_preamble(text)

    # Remove legacy if present
    new_rest = LEGACY_BLOCK_RE.sub("", rest, count=1) if has_legacy(rest) else rest

    new_header = build_header(upstream_start)
    return f"{shebang}{coding}{new_header}{new_rest.lstrip()}"


def process_file(path: pathlib.Path, upstream_start: int, license_only: bool, apply: bool, verbose: bool, quiet: bool) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        if not quiet:
            print(f"ERROR: Cannot read {path}: {e}", file=sys.stderr)
        return False
    updated = normalize(original, upstream_start, license_only)
    changed = updated != original
    if changed and apply:
        try:
            path.write_text(updated, encoding="utf-8")
        except Exception as e:
            if not quiet:
                print(f"ERROR: Cannot write {path}: {e}", file=sys.stderr)
            return False
    if changed:
        log(f"Updated: {path}", verbose=verbose, quiet=quiet)
    return True


def main() -> int:
    args = parse_args()
    exts = [e if e.startswith('.') else f'.{e}' for e in args.ext.split(',') if e.strip()]

    # Anchor default scan root to repository root (script directory's parent) if --paths omitted.
    if not args.paths:
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        default_paths = [str(repo_root)]
    else:
        default_paths = args.paths

    targets = list(collect_paths(default_paths, exts, args.exclude))
    if not targets:
        print("No matching files.")
        return 0

    ok = True
    for p in targets:
        if not process_file(p, args.force_year_start, args.license_only, args.apply, args.verbose, args.quiet):
            ok = False

    # Optional print (single file, dry run)
    if args.print and not args.apply and len(targets) == 1:
        path = targets[0]
        text = path.read_text(encoding='utf-8')
        print(normalize(text, args.force_year_start, args.license_only))

    if not ok:
        return 1
    if not args.apply:
        print("(dry-run) Use --apply to write changes.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
