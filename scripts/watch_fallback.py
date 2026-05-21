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


# Sentinel value for FileStat.stable_count meaning "we've already emitted CLOSE_WRITE
# for this file at its current size/mtime; don't re-emit until the stat changes."
# Without this guard the mtime-age fallback in the emit condition refires every poll
# cycle for any file older than --stabilize, causing infinite ingestion loops on
# polling-only setups (NETWORK_SHARE_MODE, Docker Desktop, inotify-ENOSPC fallback).
FIRED_SENTINEL = -999999


def print_event(event: str, path: str) -> None:
    # Emit in a format the shell while-read loop can parse: "EVENT PATH"
    sys.stdout.write(f"{event} {path}\n")
    sys.stdout.flush()


def _dir_mtime_signature(root: str, recursive: bool) -> Optional[Tuple[int, int]]:
    """Cheap "did anything change in `root`?" signature.

    Returns ``(mtime_ns, nlink_or_size)`` of the root directory (non-recursive)
    or of the parent + each immediate subdir (recursive). Linux + macOS bump
    a directory's mtime when a file is added or removed (rename counts as
    remove+add). They do NOT bump on file modification — but new-file
    detection is what the ingest path cares about, so this is the right
    granularity.

    Returns None on stat failure (root removed, permission denied) — the
    caller falls back to the full os.walk path.

    See CWA #1360 (Docker-Desktop polling on HDD-backed bind mounts).
    """
    try:
        st = os.stat(root)
        sig = (getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)), st.st_size)
    except OSError:
        return None
    if not recursive:
        return sig
    # Recursive mode: also fold in immediate subdir mtimes so we catch
    # files added inside subfolders without doing a full walk.
    try:
        with os.scandir(root) as it:
            sub_sigs = []
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        sub_st = entry.stat(follow_symlinks=False)
                        sub_sigs.append(getattr(sub_st, 'st_mtime_ns',
                                                int(sub_st.st_mtime * 1e9)))
                except OSError:
                    continue
        # Hash subdir mtimes into a single int alongside the root mtime.
        combined = sig[0] ^ sum(sub_sigs)
        return (combined, sig[1] + len(sub_sigs))
    except OSError:
        return sig


def scan_once(
    root: str,
    recursive: bool,
    extensions: Optional[Set[str]],
    index: Dict[FileKey, FileStat],
    stabilize: float,
    emit,
    last_dir_sig: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    """Run a single polling pass over `root`, mutating `index` in-place and
    calling `emit(event, path)` for files that should fire. Extracted from
    main() so tests can drive the state machine deterministically.

    CWA #1360 mtime-gate: if ``last_dir_sig`` is provided AND the current
    dir signature matches AND the index is non-empty (we've already done
    at least one full scan), short-circuit the os.walk — nothing has
    changed at the directory level since last poll, so no new files can
    have appeared. Massively reduces I/O on HDD-backed bind mounts in
    Docker Desktop polling mode (the reporter's scenario).

    Always returns the current dir signature so the caller can pass it
    back on the next iteration. Returns None if root stat failed; caller
    should treat that as "force full walk next time."
    """
    current_sig = _dir_mtime_signature(root, recursive)

    # mtime-gate: if we have a prior signature, the new one matches, and
    # we've already populated the index — skip the full walk. We still
    # need to honor the stabilize/emit path for files mid-flight, but
    # that's done via the index state, not via re-walking the tree.
    # Without this check we'd os.walk + os.stat every file every interval
    # even when nothing has changed — the exact HDD-thrashing pattern in
    # the upstream report.
    if (current_sig is not None and last_dir_sig is not None
            and current_sig == last_dir_sig and len(index) > 0):
        # Still emit for any indexed files that have hit the stabilize
        # threshold via the time.time() vs prev.mtime_ns comparison —
        # otherwise files that landed JUST before the previous poll
        # might never fire.
        now_sec = time.time()
        for fk, prev in index.items():
            if prev.stable_count == FIRED_SENTINEL:
                continue
            if (now_sec - (prev.mtime_ns / 1e9)) >= stabilize:
                emit("CLOSE_WRITE", fk.path)
                prev.stable_count = FIRED_SENTINEL
        return current_sig

    seen: Set[FileKey] = set()
    for fp in iter_files(root, recursive, extensions):
        fk = FileKey(fp)
        seen.add(fk)
        st = get_stat(fp)
        if not st:
            continue
        size, mtime_ns = st
        prev = index.get(fk)
        if prev is None:
            index[fk] = FileStat(size=size, mtime_ns=mtime_ns, stable_count=0)
            continue

        if prev.size == size and prev.mtime_ns == mtime_ns:
            if prev.stable_count != FIRED_SENTINEL:
                prev.stable_count = min(prev.stable_count + 1, 2)
        else:
            prev.size = size
            prev.mtime_ns = mtime_ns
            prev.stable_count = 0

        if prev.stable_count == FIRED_SENTINEL:
            continue

        if prev.stable_count >= 2 or (time.time() - (prev.mtime_ns / 1e9)) >= stabilize:
            emit("CLOSE_WRITE", fp)
            prev.stable_count = FIRED_SENTINEL

    if len(index) > 0 and len(seen) < len(index):
        for fk in list(index.keys()):
            if fk not in seen:
                index.pop(fk, None)

    return current_sig


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

    last_dir_sig: Optional[Tuple[int, int]] = None

    try:
        while True:
            now = time.time()
            # Avoid drift accumulation when the loop body takes time.
            if last_scan_at and now - last_scan_at < args.interval:
                time.sleep(max(0.0, args.interval - (now - last_scan_at)))
            last_scan_at = time.time()

            last_dir_sig = scan_once(root, args.recursive, exts, index,
                                     args.stabilize, print_event,
                                     last_dir_sig=last_dir_sig)

    except KeyboardInterrupt:
        return 0
    except Exception as e:
        sys.stderr.write(f"[watch-fallback] Unexpected error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
