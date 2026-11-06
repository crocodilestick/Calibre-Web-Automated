# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import fcntl
import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def process_lock_cls(monkeypatch, tmp_path):
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    import ingest_processor

    return ingest_processor.ProcessLock


def test_failed_contender_keeps_owner_lock_file(process_lock_cls, tmp_path):
    owner = process_lock_cls("test_lock")
    contender = process_lock_cls("test_lock")
    third = process_lock_cls("test_lock")
    lock_path = tmp_path / "test_lock.lock"
    try:
        assert owner.acquire(timeout=1)
        owner_inode = os.fstat(owner.lock_file.fileno()).st_ino

        assert not contender.acquire(timeout=0.3)

        # The contender must not truncate the owner's PID or unlink the path.
        assert lock_path.exists()
        assert lock_path.stat().st_ino == owner_inode
        assert lock_path.read_text() == str(os.getpid())

        # So a third caller still contends on the owner's inode and fails.
        assert not third.acquire(timeout=0.3)

        owner.release()
        assert third.acquire(timeout=1)
        assert lock_path.stat().st_ino == owner_inode
    finally:
        for lock in (owner, contender, third):
            lock.release()


def test_contender_does_not_treat_non_pid_content_as_stale(process_lock_cls, tmp_path):
    # cps/admin.py holds this lock during a library restore and writes
    # "restore_calibre_db" into it instead of a PID.
    lock_path = tmp_path / "test_lock.lock"
    with open(lock_path, "w") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        holder.write("restore_calibre_db")
        holder.flush()

        contender = process_lock_cls("test_lock")
        assert not contender.acquire(timeout=0.3)
        assert lock_path.exists()
        assert lock_path.read_text() == "restore_calibre_db"


def test_unlocked_file_left_by_dead_process_is_reused(process_lock_cls, tmp_path):
    lock_path = tmp_path / "test_lock.lock"
    lock_path.write_text("999999999")

    lock = process_lock_cls("test_lock")
    try:
        assert lock.acquire(timeout=1)
        assert lock_path.read_text() == str(os.getpid())
    finally:
        lock.release()
    assert lock_path.read_text() == ""
