# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Single-instance lock files for the scripts in this folder.

A lock holds its owner's PID. A run killed with SIGKILL (or by the OOM killer)
never reaches atexit, so its lock stays behind; a lock whose owner is no longer a
running instance (dead, empty, unreadable, or the PID now belongs to something
else) is treated as stale and taken over, instead of blocking every later run
until the container restarts.
"""

import os

try:
    import fcntl
except ImportError:  # not Linux
    fcntl = None


def owner_alive(path, names):
    """True if the lock names a running process whose command line contains one of names."""
    try:
        with open(path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read()
    except FileNotFoundError:
        return False
    except OSError:
        # No /proc (not Linux): fall back to "does that PID exist".
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return any(name.encode() in cmdline for name in names)


def _create(path):
    """Create path holding this process's PID, atomically: it is never visible empty.

    The PID goes into a staging file that is hard-linked into place, so a second
    starter that finds the lock always reads a complete PID. Returns False if path
    already exists.
    """
    staging = f"{path}.{os.getpid()}.tmp"
    try:
        with open(staging, "w") as f:
            f.write(str(os.getpid()))
        try:
            os.link(staging, path)
        except FileExistsError:
            return False
        except OSError:
            # No hard links on this filesystem: create it in place instead.
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                return False
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
        return True
    finally:
        try:
            os.remove(staging)
        except FileNotFoundError:
            pass


def acquire(path, names, on_stale=None):
    """Take the lock, clearing a stale one. False if a live owner holds it.

    on_stale, if given, is called with a message when a stale lock is removed.

    Starters take a flock on a guard file for the few steps of "look at the lock,
    remove it if stale, create it". Without it, two starters that both judge the
    same lock stale can each remove it and each create their own, or one can remove
    the lock the other has just taken. The kernel drops the flock when its holder
    dies, so the guard can't go stale. The guard file itself is never removed.
    """
    guard = None
    if fcntl is not None:
        try:
            guard = open(f"{path}.guard", "a")
            fcntl.flock(guard, fcntl.LOCK_EX)
        except OSError:
            if guard:
                guard.close()
            guard = None
    try:
        for _ in range(2):
            if _create(path):
                return True
            if owner_alive(path, names):
                return False
            if on_stale:
                on_stale(f"Removing a stale lock left by a run that was killed: {path}")
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        return False
    finally:
        if guard:
            guard.close()


def release(path):
    """Remove the lock, but only while it still holds this process's PID.

    The web UI's Cancel deletes a lock itself right after sending SIGTERM, and a
    new run may take it before this one has exited; that lock must be left alone.
    """
    try:
        with open(path) as f:
            if f.read().strip() != str(os.getpid()):
                return
        os.remove(path)
    except FileNotFoundError:
        pass
