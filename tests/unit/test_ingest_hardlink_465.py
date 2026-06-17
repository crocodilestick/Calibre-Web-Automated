# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #465 / CWA #1396 — ingest watcher does not
process hardlinked files in subdirectories.

Reporter (@stuhby, 2026-06-15): a download client (Readarr/Bookshelf via
qBittorrent) hardlinks a completed file into a subfolder of the ingest
tree on UnRAID. ``link()`` fires only ``IN_CREATE`` — no
``IN_CLOSE_WRITE``, because no file descriptor is ever opened, written, or
closed. The inotify watcher in ``cwa-ingest-service/run`` listened only for
``close_write`` and ``moved_to``, so the hardlink was silently dropped and
never ingested.

The fix has two halves, both pinned here:

  1. ``inotifywait`` now also watches ``-e create`` so the kernel actually
     delivers the hardlink event (static pin — RED on main because the
     watch line had no ``create``).

  2. ``handle_event`` is now event-type aware. Adding ``create`` would
     otherwise make the watcher act on the *early* ``CREATE`` a normal
     in-progress download fires (size still growing), ingesting a partial
     file. The gate distinguishes a completed hardlink — ``st_nlink > 1``
     with a non-zero, stable size — from a single-link download still being
     written (``nlink == 1``), which is left for its eventual
     ``close_write``.

The end-to-end "hardlink in a subdir gets ingested" path needs real
inotify + ``s6-setuidgid`` and is exercised in the live container; these
unit tests pin the decision logic and the watch configuration so a future
refactor cannot silently drop hardlink support or start ingesting partial
downloads.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "root" / "etc" / "s6-overlay" / "s6-rc.d" / "cwa-ingest-service" / "run"


# --------------------------------------------------------------------------
# Static pins on the watch configuration
# --------------------------------------------------------------------------

def _watch_line() -> str:
    text = RUN_SCRIPT.read_text()
    for line in text.splitlines():
        if "inotifywait" in line and "-r" in line and "close_write" in line:
            return line
    raise AssertionError("could not find the recursive inotifywait watch line")


def test_inotifywait_watches_create_events():
    """The recursive watcher must listen for `create` so the kernel delivers
    the hardlink event at all (RED on main — only close_write/moved_to)."""
    line = _watch_line()
    assert "-e create" in line, (
        "inotifywait must watch `create` events or hardlinked files "
        f"(fork #465) are never ingested. Watch line was:\n{line}"
    )
    # The pre-existing event coverage must be preserved.
    assert "-e close_write" in line
    assert "-e moved_to" in line


def test_event_type_threaded_into_handle_event():
    """Both read loops must forward the inotify event string to handle_event
    so the CREATE gate can run; passing only the path defeats the fix."""
    text = RUN_SCRIPT.read_text()
    # Every `handle_event "$filepath"` call inside a read loop must also pass
    # the captured `$events` field.
    bad = [
        ln.strip()
        for ln in text.splitlines()
        if "handle_event \"$filepath\"" in ln and "$events" not in ln
    ]
    assert not bad, (
        "handle_event must receive the event string ($events) in every "
        f"watch loop. Offending call(s): {bad}"
    )


# --------------------------------------------------------------------------
# Behavioural pins on the CREATE gate (driven through bash)
# --------------------------------------------------------------------------

@pytest.fixture
def harness(tmp_path):
    """Source the run script in TEST_MODE with a processor stub and return a
    callable that invokes handle_event with a synthesized event string."""
    if not RUN_SCRIPT.exists():
        pytest.skip("run script missing")

    watch = tmp_path / "watch"
    processing = tmp_path / "processing"
    recent = tmp_path / "recent"
    src = tmp_path / "src"
    for d in (watch, processing, recent, src):
        d.mkdir()

    processor_log = tmp_path / "processor.log"
    processor_log.write_text("")

    stub = tmp_path / "processor-stub.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$1" >> "$PROCESSOR_LOG"\n'
        "exit 0\n"
    )
    stub.chmod(0o755)

    post_batch_stub = tmp_path / "post-batch-stub.sh"
    post_batch_stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    post_batch_stub.chmod(0o755)

    env = {
        **os.environ,
        "WATCH_FOLDER": str(watch),
        "CWA_INGEST_SERVICE_TEST_MODE": "1",
        "CWA_INGEST_PROCESSING_DIR": str(processing),
        "CWA_INGEST_RECENT_DIR": str(recent),
        "CWA_INGEST_RETRY_QUEUE": str(tmp_path / "retry_queue"),
        "CWA_INGEST_STATUS_FILE": str(tmp_path / "status"),
        "CWA_INGEST_RECENT_EVENT_TTL": "120",
        "CWA_INGEST_BATCH_DIRTY_FILE": str(tmp_path / "batch_dirty"),
        "CWA_INGEST_BATCH_LAST_SUCCESS_FILE": str(tmp_path / "batch_success"),
        "CWA_INGEST_BATCH_QUIET_SECONDS": "1",
        "CWA_INGEST_POST_BATCH_CMD": str(post_batch_stub),
        "CWA_INGEST_PROCESSOR_CMD": str(stub),
        "PROCESSOR_LOG": str(processor_log),
        # Keep the stability probe fast for tests.
        "CWA_INGEST_STABLE_CHECKS": "2",
        "CWA_INGEST_STABLE_CONSEC_MATCH": "2",
        "CWA_INGEST_STABLE_INTERVAL": "0.05",
    }

    def run(path: str, events: str):
        script = textwrap.dedent(
            f"""
            set -euo pipefail
            source "{RUN_SCRIPT}" >/dev/null 2>&1
            handle_event "{path}" "{events}" >/dev/null 2>&1 || true
            """
        )
        subprocess.run(["bash", "-c", script], env=env, check=True)
        return processor_log.read_text().splitlines()

    run.watch = watch
    run.src = src
    run.processor_log = processor_log
    return run


def test_completed_hardlink_create_is_ingested(harness):
    """A hardlink (nlink>1, non-zero size) arriving as a bare CREATE must be
    ingested — that is the user-reported symptom."""
    src = harness.src / "book.epub"
    src.write_text("complete book content")
    dst = harness.watch / "Author Name"
    dst.mkdir()
    target = dst / "book.epub"
    os.link(src, target)  # hardlink: nlink becomes 2
    assert target.stat().st_nlink > 1

    processed = harness(str(target), "CREATE")
    assert str(target) in processed, (
        "completed hardlink delivered as CREATE was not ingested (fork #465)"
    )


def test_single_link_create_is_not_ingested(harness):
    """An ordinary in-progress download fires an early CREATE with nlink==1
    while the data is still being written. Processing it then would ingest a
    partial file — the gate must defer to close_write.

    RED on main: the event-blind handle_event ingests any existing file."""
    target = harness.watch / "downloading.epub"
    target.write_text("partial...")  # regular file, nlink == 1
    assert target.stat().st_nlink == 1

    processed = harness(str(target), "CREATE")
    assert str(target) not in processed, (
        "single-link CREATE was ingested; partial in-progress downloads "
        "must wait for close_write"
    )


def test_single_link_close_write_still_ingests(harness):
    """The deferred single-link file must still be ingested once its
    close_write arrives — the gate only filters CREATE, not the completion
    event."""
    target = harness.watch / "downloading.epub"
    target.write_text("now complete")

    processed = harness(str(target), "CLOSE_WRITE")
    assert str(target) in processed


def test_directory_create_is_ignored(harness):
    """`inotifywait -r` auto-watches new subfolders; a CREATE,ISDIR for a
    directory (even one whose name matches the ext regex) must never be fed
    to the processor."""
    target = harness.watch / "weird.epub"  # a *directory* named like a book
    target.mkdir()
    assert target.stat().st_nlink >= 2  # directories always have nlink >= 2

    processed = harness(str(target), "CREATE,ISDIR")
    assert str(target) not in processed


def test_close_write_path_unchanged_without_event_arg(harness):
    """Backward compatibility: callers that pass no event string (and the
    fallback CLOSE_WRITE path) still ingest a normal completed file."""
    target = harness.watch / "legacy.epub"
    target.write_text("done")

    # Empty event string -> gate is skipped, normal processing applies.
    processed = harness(str(target), "")
    assert str(target) in processed
