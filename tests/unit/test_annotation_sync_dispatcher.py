# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dispatcher tests — UPSERT semantics, race handling, tombstone terminal."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from cps import ub
from cps.services.annotation_sync import (
    register_handler,
    reset_registry_for_testing,
    dispatch_annotation_sync,
    dispatch_annotation_deletes,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


class StubHandler(AnnotationSyncTargetHandler):
    target_name = "stub"

    def __init__(self, push_result=None, delete_result=None, enabled=True):
        self.push_result = push_result or SyncResult(status="synced", target_record_id="r1")
        self.delete_result = delete_result or SyncResult(status="tombstone", target_record_id="r1")
        self._enabled = enabled
        self.calls = []

    def is_enabled(self, user):
        return self._enabled

    def push(self, annotation, book, user, payload=None):
        self.calls.append(("push", annotation.annotation_id))
        return self.push_result

    def delete(self, sync_target, user):
        self.calls.append(("delete", sync_target.target_record_id))
        return self.delete_result


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def patched_session(monkeypatch):
    """Replace ub.session + ub.session_commit with a fresh in-memory session."""
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="u", email="u@e.com", role=0, password="x", hardcover_token="t")
    s.add(user); s.commit()
    monkeypatch.setattr(ub, "session", s)
    monkeypatch.setattr(ub, "session_commit", lambda: s.commit())
    yield s, user
    s.close()


def _payload(annotation_id, text_="hi", color="yellow", note=None, progress=0.5):
    return {
        "id": annotation_id,
        "highlightedText": text_,
        "highlightColor": color,
        "noteText": note,
        "location": {"span": {"chapterProgress": progress}},
    }


def _book(book_id=7):
    from types import SimpleNamespace
    return SimpleNamespace(id=book_id, title=f"Book {book_id}")


def test_dispatch_creates_annotation_and_sync_target(patched_session):
    s, user = patched_session
    handler = StubHandler()
    register_handler(handler)
    dispatch_annotation_sync([_payload("uuid-a")], _book(), user)
    rows = s.query(ub.Annotation).all()
    assert len(rows) == 1
    assert rows[0].source == "kobo"
    targets = s.query(ub.AnnotationSyncTarget).all()
    assert len(targets) == 1
    assert targets[0].target == "stub"
    assert targets[0].status == "synced"
    assert targets[0].target_record_id == "r1"


def test_dispatch_updates_existing_annotation(patched_session):
    s, user = patched_session
    register_handler(StubHandler())
    dispatch_annotation_sync([_payload("uuid-a", text_="v1")], _book(), user)
    dispatch_annotation_sync([_payload("uuid-a", text_="v2")], _book(), user)
    rows = s.query(ub.Annotation).all()
    assert len(rows) == 1
    assert rows[0].highlighted_text == "v2"
    targets = s.query(ub.AnnotationSyncTarget).all()
    assert len(targets) == 1  # UPSERT, not duplicate


def test_dispatch_skips_disabled_handler(patched_session):
    s, user = patched_session
    h = StubHandler(enabled=False)
    register_handler(h)
    dispatch_annotation_sync([_payload("uuid-a")], _book(), user)
    assert s.query(ub.Annotation).count() == 1
    assert s.query(ub.AnnotationSyncTarget).count() == 0
    assert h.calls == []


def test_dispatch_records_failed_status(patched_session):
    s, user = patched_session
    h = StubHandler(push_result=SyncResult(status="failed", error_message="boom"))
    register_handler(h)
    dispatch_annotation_sync([_payload("uuid-a")], _book(), user)
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "failed"
    assert st.error_message == "boom"
    assert st.last_synced is None


def test_dispatch_retry_clears_error_on_success(patched_session):
    s, user = patched_session
    class Flaky(AnnotationSyncTargetHandler):
        target_name = "stub"
        def __init__(self): self.n = 0
        def is_enabled(self, user): return True
        def push(self, a, b, u, payload=None):
            self.n += 1
            if self.n == 1:
                return SyncResult(status="failed", error_message="net")
            return SyncResult(status="synced", target_record_id="r1")
        def delete(self, st, u): return SyncResult(status="tombstone")
    register_handler(Flaky())
    p = _payload("uuid-a")
    dispatch_annotation_sync([p], _book(), user)
    dispatch_annotation_sync([p], _book(), user)
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "synced"
    assert st.error_message is None
    assert st.target_record_id == "r1"


def test_dispatch_delete_transitions_to_tombstone(patched_session):
    s, user = patched_session
    register_handler(StubHandler())
    dispatch_annotation_sync([_payload("uuid-x")], _book(), user)
    assert s.query(ub.AnnotationSyncTarget).one().status == "synced"
    dispatch_annotation_deletes(["uuid-x"], user)
    assert s.query(ub.AnnotationSyncTarget).one().status == "tombstone"


def test_dispatch_delete_skips_tombstoned(patched_session):
    s, user = patched_session
    h = StubHandler()
    register_handler(h)
    dispatch_annotation_sync([_payload("uuid-x")], _book(), user)
    dispatch_annotation_deletes(["uuid-x"], user)
    h.calls.clear()
    dispatch_annotation_deletes(["uuid-x"], user)  # second delete attempt
    assert h.calls == []  # handler.delete NOT called twice


def test_tombstone_is_terminal_against_repeat_push(patched_session):
    s, user = patched_session
    register_handler(StubHandler())
    payload = _payload("uuid-x")
    dispatch_annotation_sync([payload], _book(), user)
    dispatch_annotation_deletes(["uuid-x"], user)
    dispatch_annotation_sync([payload], _book(), user)  # re-push
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "tombstone"  # NOT resurrected
