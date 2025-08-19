#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Lightweight polling-based filesystem watcher fallback.

Purpose: When inotify runs out of watches (ENOSPC) on some platforms (e.g., Synology),
this script can be used to monitor a directory tree for new/updated files without
relying on inotify. It emits lines compatible with inotifywait's simple output:

  CLOSE_WRITE /absolute/path/to/file

Usage (mirrors inotifywait pipeline usage):
  python3 scripts/watch_fallback.py --path /watched/dir --interval 5 --exts epub,azw3,mobi,pdf,cbz,cbr

Notes:
  - Uses mtime and size to detect new or finished files. To avoid firing on partially
    written files, it requires two consecutive scans with a stable size/mtime, or an
    mtime older than a small stabilization window.
  - Keeps a small in-memory index; optionally persists a cache file if requested later.
  - Designed to be simple, low-risk, and only used as a fallback.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, Tuple


@dataclass(frozen=True)
class FileKey:
    path: str


@dataclass
class FileStat:
    size: int
    mtime_ns: int
    stable_count: int = 0  # how many consecutive scans with identical stat


def iter_files(root: str, recursive: bool = True, extensions: Optional[Set[str]] = None) -> Iterable[str]:
    if not recursive:
        try:
            for name in os.listdir(root):
                fp = os.path.join(root, name)
                if os.path.isfile(fp) and _match_ext(fp, extensions):
                    yield fp
        except FileNotFoundError:
            return
        return

    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            if _match_ext(fp, extensions):
                yield fp


def _match_ext(path: str, extensions: Optional[Set[str]]) -> bool:
    if not extensions:
        return True
    _, ext = os.path.splitext(path)
    return ext.lower().lstrip('.') in extensions


def get_stat(path: str) -> Optional[Tuple[int, int]]:
    try:
        st = os.stat(path)
        return st.st_size, getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))
    except FileNotFoundError:
        return None
    except PermissionError:
        return None


def print_event(event: str, path: str) -> None:
    # Emit in a format the shell while-read loop can parse: "EVENT PATH"
    sys.stdout.write(f"{event} {path}\n")
    sys.stdout.flush()


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Polling watcher fallback emitting inotify-like events")
    p.add_argument("--path", required=True, help="Directory to watch")
    p.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds (default: 5)")
    p.add_argument("--recursive", action="store_true", help="Recurse into subdirectories (default: true)")
    p.add_argument("--no-recursive", dest="recursive", action="store_false", help="Disable recursion")
    p.set_defaults(recursive=True)
    p.add_argument("--exts", default="", help="Comma-separated list of file extensions to include (no dots)")
    p.add_argument("--stabilize", type=float, default=1.5, help="Seconds a file must remain unchanged to fire (default: 1.5)")

    args = p.parse_args(list(argv) if argv is not None else None)

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        sys.stderr.write(f"[watch-fallback] Path is not a directory or does not exist: {root}\n")
        return 2

    exts = {e.strip().lower() for e in args.exts.split(',') if e.strip()} if args.exts else None

    index: Dict[FileKey, FileStat] = {}
    last_scan_at = 0.0

    # Prime the index once so we don't fire for everything immediately
    for fp in iter_files(root, args.recursive, exts):
        st = get_stat(fp)
        if st:
            size, mtime_ns = st
            index[FileKey(fp)] = FileStat(size=size, mtime_ns=mtime_ns, stable_count=1)

    try:
        while True:
            now = time.time()
            # Avoid drift accumulation when the loop body takes time.
            if last_scan_at and now - last_scan_at < args.interval:
                time.sleep(max(0.0, args.interval - (now - last_scan_at)))
            last_scan_at = time.time()

            seen: Set[FileKey] = set()
            for fp in iter_files(root, args.recursive, exts):
                fk = FileKey(fp)
                seen.add(fk)
                st = get_stat(fp)
                if not st:
                    continue
                size, mtime_ns = st
                prev = index.get(fk)
                if prev is None:
                    # New file observed; require stabilization before emitting
                    index[fk] = FileStat(size=size, mtime_ns=mtime_ns, stable_count=0)
                    continue

                if prev.size == size and prev.mtime_ns == mtime_ns:
                    prev.stable_count = min(prev.stable_count + 1, 2)
                else:
                    prev.size = size
                    prev.mtime_ns = mtime_ns
                    prev.stable_count = 0

                # If stable long enough (two scans) OR sufficiently old mtime, emit event
                if prev.stable_count >= 2 or (time.time() - (prev.mtime_ns / 1e9)) >= args.stabilize:
                    # Emit a close_write-style event
                    print_event("CLOSE_WRITE", fp)
                    # Reset stable_count so we don't fire repeatedly for unchanged files
                    prev.stable_count = -999999  # sentinel to avoid refire unless it changes again

            # Clean up removed files from index to keep memory small
            if len(index) > 0 and len(seen) < len(index):
                for fk in list(index.keys()):
                    if fk not in seen:
                        index.pop(fk, None)

    except KeyboardInterrupt:
        return 0
    except Exception as e:
        sys.stderr.write(f"[watch-fallback] Unexpected error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
