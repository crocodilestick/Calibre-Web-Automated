# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Annotation backup — passive safety net for highlight + note loss
across H1's evolving write paths.

Every INSERT or UPDATE to ``kobo_annotation_sync`` is captured as a
per-`(user_id, book_id)` snapshot: a gzipped JSON dump of every
current annotation for that pair, written to disk under
``/config/annotation-backups/<user_id>/<book_id>/<UTC-iso>.json.gz``,
with rolling-3 retention. The index lives in the
``kobo_annotation_backup`` table so retention queries hit an index,
not the filesystem.

Triggering is automatic via a SQLAlchemy ``after_flush`` event on
``KoboAnnotationSync`` so every writer (Hardcover sync today, the
H1 import endpoint and web-reader create path tomorrow) gets the
same safety net without each caller having to remember.

Resource budget (per fork #240):

* Content-hash dedup — if the annotation set for `(user, book)`
  hashes to the same SHA-256 as the most recent backup, skip.
  Prevents identical-state re-writes from doubling disk usage.
* Background worker — a single daemon thread drains a per-key
  queue, never blocking the sync API or any HTTP handler.
* gzip — typical 100-highlight book is ~30 KB raw, ~5 KB gzipped.
* Rolling-3 — unlinks 4th-oldest after each write; index table
  rows go with it.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Schema version embedded in every JSON backup so a restore endpoint
# (future PR) can reject incompatible formats cleanly rather than
# loading garbage.
BACKUP_SCHEMA_VERSION = 2

# Number of snapshots retained per `(user_id, book_id)` pair.
RETENTION_COUNT = 3

# Worker drains items off the queue serially. One thread is plenty —
# backup work is I/O-bound and the content-hash dedup at backup time
# means duplicate keys are benign (second run hits the hash check and
# returns None without writing).
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_QUEUE: "queue.Queue[tuple[int, int]]" = queue.Queue()
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()

# Tests set this False so the collector exercises the enqueue path
# without spinning up a thread that tries to query the production DB.
WORKER_AUTOSTART = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_backup_root() -> Path:
    """Resolve ``/config/annotation-backups/``. Module-level lookup so
    tests can monkeypatch ``constants.CONFIG_DIR`` without re-importing."""
    from .. import constants
    return Path(constants.CONFIG_DIR) / "annotation-backups"


def schedule_backup(user_id: int, book_id: int) -> None:
    """Enqueue a backup for ``(user_id, book_id)``. Non-blocking;
    the actual work runs on the daemon worker. Duplicate keys are
    safe — the worker hits the content-hash dedup at backup time
    and short-circuits without writing a redundant file."""
    if user_id is None or book_id is None:
        return  # Nothing to back up; orphan rows handled elsewhere.
    key = (int(user_id), int(book_id))
    _WORKER_QUEUE.put(key)
    if WORKER_AUTOSTART:
        _ensure_worker_running()


def run_backup_now(user_id: int, book_id: int, session=None) -> Optional[Path]:
    """Synchronous backup — runs the dedup + write + retention path
    on the caller's thread. Tests pass a session explicitly so the
    work hits the same in-memory DB they assembled. The
    after_flush hook never calls this directly (always async via
    :func:`schedule_backup`)."""
    return _run_one(int(user_id), int(book_id), session=session)


def enqueue_baseline_for_user(user_id: int, session=None) -> int:
    """First-sync-after-upgrade trigger — enumerate every distinct
    ``book_id`` for which the user has annotations, schedule a
    backup for each. Returns the count scheduled. Idempotent: the
    worker's content-hash dedup ensures repeat calls don't waste
    disk if state hasn't changed.

    ``session`` defaults to the request-scoped ``ub.session`` —
    callers from within a Flask request can omit it. Tests pass
    their own.
    """
    from .. import ub
    s = session or ub.session
    book_ids = s.query(ub.Annotation.book_id).filter(
        ub.Annotation.user_id == user_id,
        ub.Annotation.book_id.isnot(None),
    ).distinct().all()
    scheduled = 0
    for (book_id,) in book_ids:
        if book_id is None:
            continue
        schedule_backup(user_id, book_id)
        scheduled += 1
    return scheduled


# ---------------------------------------------------------------------------
# Worker management
# ---------------------------------------------------------------------------


def _ensure_worker_running() -> None:
    """Lazily start the daemon thread on first enqueue. Daemon so it
    dies with the process; no clean shutdown needed."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_STOP.clear()
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop, name="annotation-backup-worker", daemon=True
        )
        _WORKER_THREAD.start()


def _worker_loop() -> None:
    """Drain the queue forever. Exceptions logged but never propagated
    — one bad row must not kill the worker."""
    while not _WORKER_STOP.is_set():
        try:
            key = _WORKER_QUEUE.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _run_one(*key)
        except Exception as e:
            log.error("annotation_backup worker: %s for key=%r", e, key)
        finally:
            _WORKER_QUEUE.task_done()


def stop_worker() -> None:
    """Signal the worker to exit. Idempotent. Used by tests."""
    _WORKER_STOP.set()


def reset_for_tests() -> None:
    """Tests can call this to reset module state between cases —
    drains the queue."""
    while True:
        try:
            _WORKER_QUEUE.get_nowait()
            _WORKER_QUEUE.task_done()
        except queue.Empty:
            break


# ---------------------------------------------------------------------------
# Core backup logic
# ---------------------------------------------------------------------------


def _run_one(user_id: int, book_id: int, session=None) -> Optional[Path]:
    """Materialize one backup. Returns the path written, or ``None``
    if the dedup short-circuited (no change since last backup).

    The worker thread calls this with ``session=None`` and we spin up
    a fresh thread-scoped session so we don't collide with any
    request thread's transaction. Tests pass an explicit session
    bound to their in-memory engine.
    """
    from .. import ub
    own_session = False
    if session is None:
        session = ub.init_db_thread()
        own_session = True
    try:
        rows = session.query(ub.Annotation).filter(
            ub.Annotation.user_id == user_id,
            ub.Annotation.book_id == book_id,
        ).order_by(ub.Annotation.id.asc()).all()

        if not rows:
            # User has no annotations for this book — could happen if
            # the only annotation was deleted between enqueue and run.
            # The previous backup (if any) is the last good state, which
            # is the correct semantics — don't write an empty snapshot.
            return None

        payload = _serialize(user_id, book_id, rows)
        content_hash = hashlib.sha256(
            _canonical_bytes(payload["annotations"])
        ).hexdigest()

        latest = (
            session.query(ub.KoboAnnotationBackup)
            .filter(
                ub.KoboAnnotationBackup.user_id == user_id,
                ub.KoboAnnotationBackup.book_id == book_id,
            )
            .order_by(ub.KoboAnnotationBackup.created_at.desc())
            .first()
        )
        if latest is not None and latest.content_hash == content_hash:
            # Content unchanged — preserve the existing backup, don't
            # write a redundant one.
            return None

        backup_dir = get_backup_root() / str(user_id) / str(book_id)
        backup_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        fname = now.strftime("%Y-%m-%dT%H-%M-%S-%fZ") + ".json.gz"
        fpath = backup_dir / fname

        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with gzip.open(fpath, "wb", compresslevel=6) as fh:
            fh.write(raw)
        size_bytes = fpath.stat().st_size

        backup_row = ub.KoboAnnotationBackup(
            user_id=user_id,
            book_id=book_id,
            created_at=now,
            content_hash=content_hash,
            file_path=str(fpath),
            size_bytes=size_bytes,
            annotation_count=len(rows),
        )
        session.add(backup_row)
        try:
            session.commit()
        except Exception as e:
            log.error("annotation_backup index write failed: %s", e)
            # File is on disk but not indexed — non-fatal; the orphan
            # will get swept by retention next run.
            session.rollback()

        _apply_retention(user_id, book_id, session=session)
        return fpath
    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                pass


def _serialize(user_id: int, book_id: int, rows: list) -> dict:
    """Build the JSON-serializable payload — every column on every
    annotation, plus envelope metadata."""
    annotations = []
    for r in rows:
        annotations.append({
            "id": r.id,
            "annotation_id": r.annotation_id,
            "highlighted_text": r.highlighted_text,
            "highlight_color": r.highlight_color,
            "note_text": r.note_text,
            "content_id": r.content_id,
            "start_container_path": r.start_container_path,
            "start_container_child_index": r.start_container_child_index,
            "start_offset": r.start_offset,
            "end_container_path": r.end_container_path,
            "end_container_child_index": r.end_container_child_index,
            "end_offset": r.end_offset,
            "context_string": r.context_string,
            "chapter_progress": r.chapter_progress,
            "cfi_range": r.cfi_range,
            "source": r.source,
            "hidden": bool(r.hidden) if r.hidden is not None else False,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_synced": r.last_synced.isoformat() if r.last_synced else None,
        })
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "user_id": user_id,
        "book_id": book_id,
        "annotation_count": len(annotations),
        "annotations": annotations,
    }


def _canonical_bytes(annotations: list[dict]) -> bytes:
    """Stable serialization for hashing — sort each dict's keys,
    sort the list by annotation_id. Two state-identical sets must
    hash equal regardless of insertion order."""
    sorted_anns = sorted(annotations, key=lambda a: (a.get("annotation_id") or "", a.get("id") or 0))
    return json.dumps(sorted_anns, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _apply_retention(user_id: int, book_id: int, session=None) -> int:
    """Keep top-N by ``created_at DESC`` for `(user, book)`. Unlinks
    the file + deletes the index row for each evicted entry.
    Returns the count evicted."""
    from .. import ub
    s = session or ub.session

    rows = (
        s.query(ub.KoboAnnotationBackup)
        .filter(
            ub.KoboAnnotationBackup.user_id == user_id,
            ub.KoboAnnotationBackup.book_id == book_id,
        )
        .order_by(ub.KoboAnnotationBackup.created_at.desc())
        .all()
    )
    if len(rows) <= RETENTION_COUNT:
        return 0

    evict = rows[RETENTION_COUNT:]
    evicted = 0
    for row in evict:
        try:
            p = Path(row.file_path)
            if p.is_file():
                p.unlink()
        except OSError as e:
            log.warning("annotation_backup retention: unlink %s failed: %s",
                        row.file_path, e)
        s.delete(row)
        evicted += 1
    try:
        s.commit()
    except Exception as e:
        log.error("annotation_backup retention commit failed: %s", e)
        s.rollback()
    return evicted


# ---------------------------------------------------------------------------
# SQLAlchemy after_flush hook — call site lives in cps/ub.py
# ---------------------------------------------------------------------------


def collect_annotation_writes(session, _flush_context) -> None:
    """SQLAlchemy ``after_flush`` callback. Walks the session's
    new + dirty sets, picks out ``KoboAnnotationSync`` instances,
    and stashes their ``(user_id, book_id)`` keys on a per-session
    attribute. The actual dispatch happens on ``after_commit`` so
    the worker thread doesn't race a not-yet-committed transaction.

    Hooked into ``cps/ub.py``'s session-level events so every writer
    captures automatically — Hardcover sync today, P3's import
    endpoint and P5's web-reader create path tomorrow.
    """
    from .. import ub
    import itertools
    pending = getattr(session, "_annotation_backup_pending", None)
    if pending is None:
        pending = set()
        session._annotation_backup_pending = pending
    for inst in itertools.chain(session.new, session.dirty):
        if isinstance(inst, ub.Annotation):
            if inst.user_id is None or inst.book_id is None:
                continue
            pending.add((int(inst.user_id), int(inst.book_id)))


def dispatch_pending_writes(session) -> None:
    """SQLAlchemy ``after_commit`` callback — drains the per-session
    pending set and schedules a backup for each key. Called only
    after the transaction is durable, so the worker reading from a
    fresh thread-session is guaranteed to see the just-committed
    state.
    """
    pending = getattr(session, "_annotation_backup_pending", None)
    if not pending:
        return
    for key in pending:
        schedule_backup(*key)
    pending.clear()


def discard_pending_writes(session) -> None:
    """SQLAlchemy ``after_rollback`` callback — drops the per-session
    pending set so a rolled-back transaction doesn't trigger a
    backup of state that never landed."""
    pending = getattr(session, "_annotation_backup_pending", None)
    if pending:
        pending.clear()
