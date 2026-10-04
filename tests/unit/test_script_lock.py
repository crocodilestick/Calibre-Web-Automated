# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Single-instance locks for the scripts (scripts/script_lock.py), and the EPUB fixer's use of it.

kindle_epub_fixer.py used to take its lock at import. convert_library.py and
ingest_processor.py import EPUBFixer, so they held it too: a Convert Library run
killed outright left it behind and the next run aborted, and an ingest needing the
fixer during a run exited at the import. It's now taken only when the fixer runs
as a script, and a lock left by a killed run is cleared.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import script_lock  # noqa: E402


def _sleeper(*extra):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra])


def test_live_owner_matching_any_name_is_respected(tmp_path):
    lock = tmp_path / "x.lock"
    owner = _sleeper("convert_library")
    try:
        lock.write_text(str(owner.pid))
        assert script_lock.owner_alive(str(lock), ("kindle_epub_fixer", "convert_library"))
        assert not script_lock.acquire(str(lock), ("kindle_epub_fixer", "convert_library"))
        assert not script_lock.owner_alive(str(lock), ("kindle_epub_fixer",)), "a different script is not this lock's owner"
    finally:
        owner.kill()
        owner.wait()


def test_stale_lock_is_reported_and_taken(tmp_path):
    lock = tmp_path / "x.lock"
    gone = _sleeper()
    gone.kill()
    gone.wait()
    lock.write_text(str(gone.pid))
    messages = []
    assert script_lock.acquire(str(lock), ("kindle_epub_fixer",), on_stale=messages.append)
    assert lock.read_text() == str(os.getpid())
    assert messages and "stale lock" in messages[0]


def test_release_leaves_someone_elses_lock(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text("999999999")
    script_lock.release(str(lock))
    assert lock.exists()
    lock.write_text(str(os.getpid()))
    script_lock.release(str(lock))
    assert not lock.exists()


def test_importing_the_epub_fixer_takes_no_lock(tmp_path):
    env = dict(os.environ, TMPDIR=str(tmp_path))
    lock = tmp_path / "kindle_epub_fixer.lock"
    # Check inside the importing process: an atexit hook would remove the lock
    # before a check from out here could see it.
    code = (f"import os, sys; sys.path.insert(0, {SCRIPTS_DIR!r}); import kindle_epub_fixer; "
            f"print('LOCKED' if os.path.exists({str(lock)!r}) else 'FREE')")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "FREE"


@pytest.fixture
def epub_fixer(tmp_path, monkeypatch):
    import kindle_epub_fixer
    registered = []
    monkeypatch.setattr(kindle_epub_fixer, "LOCK_PATH", str(tmp_path / "kindle_epub_fixer.lock"))
    monkeypatch.setattr(kindle_epub_fixer.atexit, "register", lambda *a: registered.append(a))
    monkeypatch.setattr(kindle_epub_fixer, "print_and_log", lambda *a, **k: None)
    return kindle_epub_fixer, Path(kindle_epub_fixer.LOCK_PATH), registered


def test_running_the_epub_fixer_clears_a_stale_lock(epub_fixer):
    module, lock, registered = epub_fixer
    lock.write_text("")
    module._acquire_lock_or_exit()
    assert lock.read_text() == str(os.getpid())
    assert registered, "the lock is released at exit"


def test_running_the_epub_fixer_while_one_runs_exits(epub_fixer):
    module, lock, _ = epub_fixer
    owner = _sleeper("kindle_epub_fixer")
    try:
        lock.write_text(str(owner.pid))
        with pytest.raises(SystemExit) as exit_info:
            module._acquire_lock_or_exit()
        assert exit_info.value.code == 2
    finally:
        owner.kill()
        owner.wait()


# --- several starters at once ------------------------------------------------

_RACER = """
# lockrace
import os, sys, time
sys.path.insert(0, {scripts!r})
import script_lock
lock, go, done, out = sys.argv[1:5]
while not os.path.exists(go):
    time.sleep(0.001)
won = script_lock.acquire(lock, ("lockrace",))
with open(out, "w") as f:
    f.write("1" if won else "0")
while not os.path.exists(done):
    time.sleep(0.01)
"""


def _race(tmp_path, racers=8):
    """Start racers that call acquire at the same moment; return how many got the lock."""
    lock, go, done = tmp_path / "x.lock", tmp_path / "go", tmp_path / "done"
    code = _RACER.format(scripts=SCRIPTS_DIR)
    procs, outs = [], []
    try:
        for i in range(racers):
            out = tmp_path / f"out{i}"
            outs.append(out)
            procs.append(subprocess.Popen([sys.executable, "-c", code, str(lock), str(go), str(done), str(out)]))
        yield lock
        go.touch()
        deadline = time.time() + 30
        while time.time() < deadline and not all(o.exists() and o.read_text() for o in outs):
            time.sleep(0.01)
        yield sum(int(o.read_text()) for o in outs)
    finally:
        done.touch()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.mark.parametrize("start", ["absent", "empty", "dead-pid"])
@pytest.mark.parametrize("round_", range(3))
def test_only_one_of_several_simultaneous_starters_gets_the_lock(tmp_path, start, round_):
    race = _race(tmp_path)
    lock = next(race)
    if start == "empty":
        lock.write_text("")
    elif start == "dead-pid":
        gone = _sleeper()
        gone.kill()
        gone.wait()
        lock.write_text(str(gone.pid))
    assert next(race) == 1
    race.close()


def test_the_lock_is_never_visible_without_a_pid(tmp_path, monkeypatch):
    """A second starter must not find the lock empty while the first is still writing it."""
    lock = tmp_path / "x.lock"
    seen = []
    real_link = os.link

    def link_and_look(src, dst):
        real_link(src, dst)
        seen.append(Path(dst).read_text())

    monkeypatch.setattr(script_lock.os, "link", link_and_look)
    assert script_lock.acquire(str(lock), ("x",))
    assert seen == [str(os.getpid())]


def test_acquire_leaves_no_staging_file_behind(tmp_path):
    lock = tmp_path / "x.lock"
    assert script_lock.acquire(str(lock), ("x",))
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".tmp") == []
