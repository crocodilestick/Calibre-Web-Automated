# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for CWA #1360 — polling watcher hammers HDD-backed
ingest folders.

Reporter (upstream, 2026-05-19): "On Docker Desktop, CWA appears to
fall back to polling for the metadata-change-detector and
cwa-ingest-service watchers... if the ingest folder is located on a
spinning HDD that stores a large collection, the container keeps
touching the folder repeatedly instead of sleeping on real file
events. The result is constant drive activity, extra seeks, and
sustained read load."

Reproduced in our code path: ``scripts/watch_fallback.py::scan_once``
unconditionally called ``iter_files(root, recursive=True)`` every poll
interval (default 5s), which does ``os.walk(root)`` over the entire
tree and ``os.stat(path)`` on every file. On a 3000-book HDD library,
that's thousands of disk seeks every 5 seconds — exactly the
reporter's symptom.

Fix: ``_dir_mtime_signature(root, recursive)`` produces a cheap
``(mtime_ns, size)`` tuple of the root + immediate subdir mtimes.
``scan_once`` short-circuits the full walk when the signature is
unchanged from the prior call AND the index is non-empty. Linux + macOS
bump directory mtime on add/remove (the events ingest cares about);
file MODIFICATION doesn't bump dir mtime but it doesn't matter for
ingest's "new file arrived" semantics.

These tests pin:

1. ``_dir_mtime_signature`` returns a tuple of two ints (sig is hashable
   for `==` comparison).
2. First ``scan_once`` call returns a non-None signature and walks the
   tree (index populated).
3. Second call with the same dir state (passing prior sig) does NOT
   re-walk the tree — verified by patching ``iter_files`` to count
   calls.
4. After a new file is added, the signature changes and the gate
   re-opens (next scan_once does the full walk + emits CLOSE_WRITE).
5. The stabilize-emit path still fires for files mid-flight even
   during a gated scan (e.g. a file dropped 0.5s before a prior scan
   that requires --stabilize=1.5s to fire — must fire on the next
   poll, not be silently lost).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

# Add scripts/ to path so we can import watch_fallback as a module without
# the full cps package init.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def watch_fallback():
    import watch_fallback
    return watch_fallback


def test_dir_mtime_signature_returns_2tuple_of_ints(tmp_path, watch_fallback):
    sig = watch_fallback._dir_mtime_signature(str(tmp_path), recursive=True)
    assert sig is not None
    assert isinstance(sig, tuple)
    assert len(sig) == 2
    assert all(isinstance(x, int) for x in sig)


def test_dir_mtime_signature_returns_none_on_missing_root(watch_fallback):
    sig = watch_fallback._dir_mtime_signature(
        "/nonexistent/path/should/never/exist", recursive=True
    )
    assert sig is None, (
        "_dir_mtime_signature must return None on stat failure so the "
        "caller falls back to the full os.walk path. See CWA #1360."
    )


def test_signature_unchanged_when_no_files_added(tmp_path, watch_fallback):
    """The signature must be stable when nothing changes. This is the
    core invariant the gate relies on — if the signature drifted on
    every call, the gate would never close."""
    sig1 = watch_fallback._dir_mtime_signature(str(tmp_path), recursive=True)
    sig2 = watch_fallback._dir_mtime_signature(str(tmp_path), recursive=True)
    assert sig1 == sig2, (
        f"Signature must be stable across calls when no fs change. "
        f"Got {sig1!r} then {sig2!r}."
    )


def test_signature_changes_when_file_added(tmp_path, watch_fallback):
    """Adding a file in the root bumps the dir mtime → signature changes
    → gate reopens."""
    sig_empty = watch_fallback._dir_mtime_signature(str(tmp_path), recursive=True)
    # Sleep > 10ms so mtime resolution catches the change reliably.
    time.sleep(0.05)
    (tmp_path / "book.epub").write_bytes(b"fake epub")
    sig_after_add = watch_fallback._dir_mtime_signature(str(tmp_path), recursive=True)
    assert sig_empty != sig_after_add, (
        f"Adding a file to root must change the signature. "
        f"Got {sig_empty!r} both before and after."
    )


def test_scan_once_first_call_walks_tree(tmp_path, watch_fallback):
    """First scan_once call (no prior sig) MUST do the full walk so the
    index gets populated. The gate is only an optimization for
    steady-state polls."""
    (tmp_path / "book.epub").write_bytes(b"fake epub")
    index = {}
    events = []
    sig = watch_fallback.scan_once(
        str(tmp_path), recursive=True, extensions={"epub"},
        index=index, stabilize=1.5,
        emit=lambda ev, p: events.append((ev, p)),
        last_dir_sig=None,
    )
    assert sig is not None
    assert len(index) == 1, (
        f"First scan_once call must populate index. Got {len(index)} entries."
    )


def test_scan_once_gate_skips_iter_files_on_unchanged_sig(tmp_path, watch_fallback):
    """The headline test: when the dir sig is unchanged between calls
    AND the index is populated, scan_once must NOT call iter_files
    (the os.walk that hammers the HDD). See CWA #1360."""
    (tmp_path / "book.epub").write_bytes(b"fake epub")
    index = {}
    # First call: full walk to populate the index.
    sig1 = watch_fallback.scan_once(
        str(tmp_path), recursive=True, extensions={"epub"},
        index=index, stabilize=1.5,
        emit=lambda *a: None,
        last_dir_sig=None,
    )
    assert sig1 is not None
    assert len(index) == 1
    # Second call: same sig — gate must short-circuit iter_files.
    with patch.object(watch_fallback, "iter_files") as mock_iter:
        sig2 = watch_fallback.scan_once(
            str(tmp_path), recursive=True, extensions={"epub"},
            index=index, stabilize=1.5,
            emit=lambda *a: None,
            last_dir_sig=sig1,
        )
    assert sig1 == sig2, "Sig must remain stable across no-change polls."
    assert mock_iter.call_count == 0, (
        f"scan_once must NOT call iter_files when dir sig is unchanged and "
        f"index is populated. Got {mock_iter.call_count} calls. This is the "
        f"HDD-hammering pattern in CWA #1360."
    )


def test_scan_once_gate_reopens_when_file_added(tmp_path, watch_fallback):
    """Adding a file in the root changes the dir signature, so the gate
    reopens — the next scan_once DOES call iter_files and finds the new
    file."""
    (tmp_path / "first.epub").write_bytes(b"first")
    index = {}
    sig1 = watch_fallback.scan_once(
        str(tmp_path), recursive=True, extensions={"epub"},
        index=index, stabilize=0.01,  # tiny stabilize so it fires fast
        emit=lambda *a: None,
        last_dir_sig=None,
    )
    # Sleep to ensure mtime resolution catches the next change.
    time.sleep(0.05)
    (tmp_path / "second.epub").write_bytes(b"second")
    with patch.object(watch_fallback, "iter_files",
                       wraps=watch_fallback.iter_files) as mock_iter:
        sig2 = watch_fallback.scan_once(
            str(tmp_path), recursive=True, extensions={"epub"},
            index=index, stabilize=0.01,
            emit=lambda *a: None,
            last_dir_sig=sig1,
        )
    assert sig1 != sig2, "Adding a file must bump the sig."
    assert mock_iter.call_count == 1, (
        f"After sig change, scan_once must call iter_files to find the new "
        f"file. Got {mock_iter.call_count} calls."
    )


def test_scan_once_gate_still_fires_stabilize_emit(tmp_path, watch_fallback):
    """Edge case: a file lands JUST before a poll. First scan adds it
    to the index with stable_count=0 and (mtime-age < stabilize), so
    no emit. Second poll with the same dir sig still needs to emit
    once the file's mtime-age crosses the stabilize threshold —
    otherwise files mid-flight at gate-close time are lost forever."""
    (tmp_path / "book.epub").write_bytes(b"fake epub")
    index = {}
    events = []
    emit = lambda ev, p: events.append((ev, p))
    # First call: brand-new file, mtime-age near zero, stable_count goes
    # to 0, no emit (stabilize threshold not crossed).
    sig1 = watch_fallback.scan_once(
        str(tmp_path), recursive=True, extensions={"epub"},
        index=index, stabilize=0.5,
        emit=emit, last_dir_sig=None,
    )
    assert events == [], "Brand-new file shouldn't emit on first scan."
    # Sleep > stabilize, then call again with the SAME sig. Even though
    # the gate is closed (sig unchanged), the stabilize-emit path must
    # still fire so the file isn't lost.
    time.sleep(0.7)
    sig2 = watch_fallback.scan_once(
        str(tmp_path), recursive=True, extensions={"epub"},
        index=index, stabilize=0.5,
        emit=emit, last_dir_sig=sig1,
    )
    assert sig1 == sig2, "Sig must be unchanged (no fs activity)."
    assert len(events) == 1, (
        f"Stabilize-emit path must fire from the gated branch too — "
        f"otherwise files dropped just before a gate-close poll are "
        f"never emitted. Got events: {events!r}"
    )
    assert events[0] == ("CLOSE_WRITE", str(tmp_path / "book.epub"))


def test_cwa_1360_anchor_present():
    """Source-pin the CWA #1360 anchor so a future refactor finds the
    rationale for the gate."""
    src = (SCRIPTS_DIR / "watch_fallback.py").read_text()
    assert "CWA #1360" in src, (
        "scripts/watch_fallback.py must reference CWA #1360 near the gate "
        "logic so future code archaeology can find the rationale."
    )
