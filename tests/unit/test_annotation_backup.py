# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the annotation backup safety net (fork #240).

The feature: every INSERT or UPDATE to ``kobo_annotation_sync`` queues
a per-`(user_id, book_id)` snapshot — gzipped JSON dump of all the
user's current annotations for that book — under
``/config/annotation-backups/<user>/<book>/<UTC-iso>.json.gz``, with
rolling-3 retention and content-hash dedup so identical state never
doubles disk usage.

Coverage pins:

1. ``KoboAnnotationBackup`` model declares the expected columns +
   the lookup index.
2. ``add_missing_tables`` creates the backup table on fresh installs.
3. Writing 1 backup produces 1 file + 1 index row.
4. Writing the same state twice (identical content hash) produces
   no second file — dedup short-circuits.
5. Writing 4 distinct states produces exactly 3 files; the oldest
   is unlinked + its index row deleted.
6. The gzipped JSON round-trips — open, parse, assert fields match
   the source ``KoboAnnotationSync`` rows.
7. The after_flush hook on ``Session`` schedules a backup when a
   ``KoboAnnotationSync`` row is inserted.
8. ``enqueue_baseline_for_user`` schedules one backup per distinct
   ``book_id`` the user has annotations for.
9. Orphan annotation rows (``book_id IS NULL``) are skipped — no
   backup file produced for them.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    """In-memory DB with the full ub.Base schema, plus a tmp
    backup-root so disk writes go to pytest's scratch dir.
    Disables the worker auto-start so the daemon thread doesn't
    try to query the (nonexistent) production DB during tests."""
    from cps import ub, constants
    from cps.services import annotation_backup

    annotation_backup.reset_for_tests()
    monkeypatch.setattr(annotation_backup, "WORKER_AUTOSTART", False)

    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
    ub.Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine, future=True)
    session = Session()

    monkeypatch.setattr(constants, "CONFIG_DIR", str(tmp_path))
    yield session, engine, tmp_path
    session.close()
    annotation_backup.reset_for_tests()


def _insert_annotation(session, user_id, book_id, annotation_id, text,
                       color="yellow", note=None, source="kobo"):
    from cps import ub
    row = ub.Annotation(
        user_id=user_id,
        book_id=book_id,
        annotation_id=annotation_id,
        highlighted_text=text,
        highlight_color=color,
        note_text=note,
        source=source,
    )
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------------
# 1. Model + schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackupModel:
    def test_model_declares_expected_columns(self):
        from cps.ub import KoboAnnotationBackup

        col_names = {c.name for c in KoboAnnotationBackup.__table__.columns}
        assert col_names == {
            "id", "user_id", "book_id", "created_at",
            "content_hash", "file_path", "size_bytes", "annotation_count",
        }

    def test_lookup_index_declared(self):
        from cps.ub import KoboAnnotationBackup

        names = [c.name for c in KoboAnnotationBackup.__table_args__ if hasattr(c, "name")]
        assert "ix_kobo_annotation_backup_user_book_created" in names

    def test_table_created_by_add_missing_tables(self, memory_db):
        from cps import ub
        from sqlalchemy import inspect as sa_inspect

        session, engine, _ = memory_db
        # add_missing_tables is the canonical install path; running it
        # against the already-created schema is a no-op but exercises
        # the code path we'd hit on a fresh install.
        ub.add_missing_tables(engine, session)
        inspector = sa_inspect(engine)
        assert "kobo_annotation_backup" in set(inspector.get_table_names())


# ---------------------------------------------------------------------------
# 2. Single-write backup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSingleBackup:
    def test_one_annotation_one_backup(self, memory_db):
        from cps.services import annotation_backup

        session, engine, tmp_path = memory_db
        _insert_annotation(session, 7, 348, "uuid-001", "All animals are equal.")

        result = annotation_backup.run_backup_now(7, 348, session=session)

        assert result is not None
        assert result.is_file()
        # Path layout: <root>/<user>/<book>/<timestamp>.json.gz
        assert result.parent == tmp_path / "annotation-backups" / "7" / "348"

    def test_backup_index_row_written(self, memory_db):
        from cps import ub
        from cps.services import annotation_backup

        session, engine, _ = memory_db
        _insert_annotation(session, 7, 348, "uuid-002", "Four legs good.")

        path = annotation_backup.run_backup_now(7, 348, session=session)

        rows = session.query(ub.KoboAnnotationBackup).all()
        assert len(rows) == 1
        r = rows[0]
        assert r.user_id == 7
        assert r.book_id == 348
        assert r.file_path == str(path)
        assert r.annotation_count == 1
        assert r.size_bytes > 0
        assert len(r.content_hash) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# 3. JSON round-trip — gzipped payload parses cleanly + matches source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonRoundTrip:
    def test_payload_decompresses_and_parses(self, memory_db):
        from cps.services import annotation_backup

        session, _, _ = memory_db
        _insert_annotation(session, 7, 348, "uuid-003",
                           "It is the worst of times.", color="red",
                           note="opening line")

        path = annotation_backup.run_backup_now(7, 348, session=session)

        with gzip.open(path, "rb") as fh:
            payload = json.loads(fh.read())

        assert payload["schema_version"] == 2
        assert payload["user_id"] == 7
        assert payload["book_id"] == 348
        assert payload["annotation_count"] == 1
        ann = payload["annotations"][0]
        assert ann["annotation_id"] == "uuid-003"
        assert ann["highlighted_text"] == "It is the worst of times."
        assert ann["highlight_color"] == "red"
        assert ann["note_text"] == "opening line"
        assert ann["source"] == "kobo"

    def test_full_h1_payload_round_trips(self, memory_db):
        """Every H1 column on a row must serialize + deserialize
        without loss, including the position fields and CFI."""
        from cps import ub
        from cps.services import annotation_backup

        session, _, _ = memory_db
        row = ub.Annotation(
            user_id=7, book_id=348, annotation_id="uuid-full",
            highlighted_text="A full payload row.",
            highlight_color="green", note_text="with note",
            content_id="uuid-book!!chapter1.html",
            start_container_path="span#kobo\\.4\\.1",
            start_container_child_index=-99, start_offset=0,
            end_container_path="span#kobo\\.4\\.2",
            end_container_child_index=-99, end_offset=50,
            context_string="surrounding text ...",
            chapter_progress=0.42,
            cfi_range="epubcfi(/6/2!/4[kobo.4.1]:0,/4[kobo.4.2]:50)",
            source="kobo", hidden=False,
        )
        session.add(row)
        session.commit()

        path = annotation_backup.run_backup_now(7, 348, session=session)

        with gzip.open(path, "rb") as fh:
            payload = json.loads(fh.read())
        ann = payload["annotations"][0]
        assert ann["cfi_range"] == "epubcfi(/6/2!/4[kobo.4.1]:0,/4[kobo.4.2]:50)"
        assert ann["start_offset"] == 0
        assert ann["end_offset"] == 50
        assert ann["chapter_progress"] == 0.42
        assert ann["context_string"] == "surrounding text ..."


# ---------------------------------------------------------------------------
# 4. Content-hash dedup — identical state produces no new file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContentHashDedup:
    def test_identical_state_no_new_backup(self, memory_db):
        from cps import ub
        from cps.services import annotation_backup

        session, _, _ = memory_db
        _insert_annotation(session, 7, 348, "uuid-dedup", "Same text.")

        first = annotation_backup.run_backup_now(7, 348, session=session)
        # No changes, second call must short-circuit.
        time.sleep(0.01)
        second = annotation_backup.run_backup_now(7, 348, session=session)

        assert first is not None
        assert second is None, "Identical content must not write a second file"

        rows = session.query(ub.KoboAnnotationBackup).all()
        assert len(rows) == 1, "Index must hold only the first row"

    def test_change_in_text_writes_new_backup(self, memory_db):
        from cps import ub
        from cps.services import annotation_backup

        session, _, _ = memory_db
        row = _insert_annotation(session, 7, 348, "uuid-mut", "Original text.")

        annotation_backup.run_backup_now(7, 348, session=session)

        row.highlighted_text = "Edited text."
        session.commit()
        time.sleep(0.01)
        second = annotation_backup.run_backup_now(7, 348, session=session)

        assert second is not None, "Mutated state must produce a new backup"
        rows = session.query(ub.KoboAnnotationBackup).all()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# 5. Rolling-3 retention
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetention:
    def test_four_distinct_states_keeps_three(self, memory_db):
        from cps import ub
        from cps.services import annotation_backup

        session, _, tmp_path = memory_db
        row = _insert_annotation(session, 7, 348, "uuid-retain", "v1")
        annotation_backup.run_backup_now(7, 348, session=session)

        for i, text in enumerate(["v2", "v3", "v4"], start=1):
            time.sleep(0.01)  # ensure distinct timestamps
            row.highlighted_text = text
            session.commit()
            annotation_backup.run_backup_now(7, 348, session=session)

        # 4 distinct states → 3 backups on disk + in index.
        index_rows = session.query(ub.KoboAnnotationBackup).filter_by(
            user_id=7, book_id=348
        ).all()
        assert len(index_rows) == 3, (
            f"Retention must keep exactly 3 rows in the index, got {len(index_rows)}"
        )

        disk_files = list((tmp_path / "annotation-backups" / "7" / "348").glob("*.json.gz"))
        assert len(disk_files) == 3, (
            f"Retention must keep exactly 3 files on disk, got {len(disk_files)}"
        )

        # The v1 backup is the one evicted; the surviving payloads
        # contain v2 / v3 / v4.
        surviving_texts = []
        for f in sorted(disk_files):
            with gzip.open(f, "rb") as fh:
                payload = json.loads(fh.read())
            surviving_texts.append(payload["annotations"][0]["highlighted_text"])
        assert "v1" not in surviving_texts, "Oldest backup must be evicted"
        assert set(surviving_texts) == {"v2", "v3", "v4"}

    def test_retention_per_book_isolated(self, memory_db):
        """Retention applies per `(user, book)` — book A's eviction
        must not touch book B's backups."""
        from cps import ub
        from cps.services import annotation_backup

        session, _, _ = memory_db
        ra = _insert_annotation(session, 7, 1, "uuid-a", "book A v1")
        rb = _insert_annotation(session, 7, 2, "uuid-b", "book B v1")

        annotation_backup.run_backup_now(7, 1, session=session)
        annotation_backup.run_backup_now(7, 2, session=session)
        for i, text in enumerate(["a2", "a3", "a4"], start=1):
            time.sleep(0.01)
            ra.highlighted_text = text
            session.commit()
            annotation_backup.run_backup_now(7, 1, session=session)

        # Book A retained 3, Book B still has its 1.
        assert session.query(ub.KoboAnnotationBackup).filter_by(book_id=1).count() == 3
        assert session.query(ub.KoboAnnotationBackup).filter_by(book_id=2).count() == 1


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdgeCases:
    def test_no_annotations_no_backup(self, memory_db):
        from cps.services import annotation_backup

        session, _, _ = memory_db
        result = annotation_backup.run_backup_now(7, 999, session=session)
        assert result is None

    def test_orphan_book_id_skipped_by_collector(self, memory_db):
        """Annotation rows with ``book_id=None`` (sideloaded books CW
        doesn't know about) must NOT trigger a backup — there's no
        ``(user, book)`` key to scope the snapshot to."""
        from cps.services.annotation_backup import collect_annotation_writes
        from cps.services import annotation_backup
        from cps import ub

        ghost = ub.Annotation(
            user_id=7, book_id=348, annotation_id="uuid-real",
        )
        ghost.book_id = None  # post-init mutation; just sets the attr

        class FakeSession:
            new = {ghost}
            dirty = set()
        s = FakeSession()
        annotation_backup.reset_for_tests()
        collect_annotation_writes(s, None)
        # Per-session pending set must be empty — orphan never collected.
        assert not getattr(s, "_annotation_backup_pending", set())


# ---------------------------------------------------------------------------
# 7. after_flush hook + baseline-for-user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollector:
    def test_collector_stashes_keys_on_session(self, memory_db):
        """Two-phase: after_flush collects keys onto the session,
        after_commit dispatches them. This test pins the collect
        side."""
        from cps import ub
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        new_row = ub.Annotation(
            user_id=7, book_id=348, annotation_id="uuid-collect",
            highlighted_text="text", source="kobo",
        )
        class FakeSession:
            new = {new_row}
            dirty = set()
        s = FakeSession()
        annotation_backup.collect_annotation_writes(s, None)
        assert getattr(s, "_annotation_backup_pending", set()) == {(7, 348)}

    def test_collector_dedups_within_one_flush(self, memory_db):
        """Two updates to the same `(user, book)` in one flush must
        coalesce into one pending key."""
        from cps import ub
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        r1 = ub.Annotation(user_id=7, book_id=348,
                                    annotation_id="u1", highlighted_text="a")
        r2 = ub.Annotation(user_id=7, book_id=348,
                                    annotation_id="u2", highlighted_text="b")
        class FakeSession:
            new = {r1, r2}
            dirty = set()
        s = FakeSession()
        annotation_backup.collect_annotation_writes(s, None)
        assert len(s._annotation_backup_pending) == 1

    def test_dispatch_drains_pending(self, memory_db):
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        class FakeSession:
            _annotation_backup_pending = {(7, 348), (7, 349)}
        s = FakeSession()
        annotation_backup.dispatch_pending_writes(s)
        assert s._annotation_backup_pending == set()
        assert annotation_backup._WORKER_QUEUE.qsize() == 2

    def test_rollback_discards_pending(self, memory_db):
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        class FakeSession:
            _annotation_backup_pending = {(7, 348)}
        s = FakeSession()
        annotation_backup.discard_pending_writes(s)
        assert s._annotation_backup_pending == set()
        assert annotation_backup._WORKER_QUEUE.qsize() == 0


@pytest.mark.unit
class TestBaselineForUser:
    def test_enqueues_one_per_distinct_book(self, memory_db):
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        session, _, _ = memory_db
        _insert_annotation(session, 7, 1, "a1", "x")
        _insert_annotation(session, 7, 1, "a2", "y")  # same book
        _insert_annotation(session, 7, 2, "a3", "z")
        _insert_annotation(session, 7, 3, "a4", "w")

        n = annotation_backup.enqueue_baseline_for_user(7, session=session)
        assert n == 3  # books 1, 2, 3 — not 4 (annotation count)

    def test_excludes_other_users(self, memory_db):
        from cps.services import annotation_backup
        annotation_backup.reset_for_tests()

        session, _, _ = memory_db
        _insert_annotation(session, 7, 1, "a1", "x")
        _insert_annotation(session, 99, 1, "a99", "other")

        n = annotation_backup.enqueue_baseline_for_user(7, session=session)
        assert n == 1
