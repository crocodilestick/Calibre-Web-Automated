# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 1 — a web-reader-created highlight fans out to enabled sync targets.

The Kobo PATCH path uses ``dispatch_annotation_sync`` (which upserts the
Annotation row from a payload first). Web-reader-created rows already exist, so
they need a sibling entry point — ``dispatch_existing_annotation_sync`` — that
pushes an existing row to each enabled handler and records the sync_target.
This is what lets a highlight made in the browser also reach Hardcover.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from cps import ub
from cps.services.annotation_sync import (
    register_handler,
    reset_registry_for_testing,
    dispatch_existing_annotation_sync,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


class StubHandler(AnnotationSyncTargetHandler):
    target_name = "stub"

    def __init__(self, enabled=True, push_result=None):
        self._enabled = enabled
        self.push_result = push_result or SyncResult(status="synced", target_record_id="r-42")
        self.calls = []

    def is_enabled(self, user):
        return self._enabled

    def push(self, annotation, book, user, payload=None):
        self.calls.append(annotation.annotation_id)
        return self.push_result

    def delete(self, sync_target, user):
        return SyncResult(status="tombstone")


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def patched_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="u", email="u@e.com", role=0, password="x", hardcover_token="t")
    s.add(user)
    s.commit()
    monkeypatch.setattr(ub, "session", s)
    monkeypatch.setattr(ub, "session_commit", lambda: s.commit())
    yield s, user
    s.close()


def _seed_web_row(session, user):
    row = ub.Annotation(
        user_id=user.id, book_id=7, annotation_id="cwn-web-xyz",
        source="webreader", highlighted_text="text", highlight_color="yellow",
    )
    session.add(row)
    session.commit()
    return row


def _book(book_id=7):
    from types import SimpleNamespace
    return SimpleNamespace(id=book_id, title="Book", uuid="uuid-7")


@pytest.mark.unit
def test_enabled_handler_creates_sync_target(patched_session):
    s, user = patched_session
    handler = StubHandler(enabled=True)
    register_handler(handler)
    row = _seed_web_row(s, user)

    dispatch_existing_annotation_sync(row, _book(), user)

    targets = s.query(ub.AnnotationSyncTarget).all()
    assert len(targets) == 1
    assert targets[0].target == "stub"
    assert targets[0].status == "synced"
    assert targets[0].target_record_id == "r-42"
    assert handler.calls == ["cwn-web-xyz"]


@pytest.mark.unit
def test_disabled_handler_creates_no_sync_target(patched_session):
    s, user = patched_session
    register_handler(StubHandler(enabled=False))
    row = _seed_web_row(s, user)

    dispatch_existing_annotation_sync(row, _book(), user)

    assert s.query(ub.AnnotationSyncTarget).count() == 0


@pytest.mark.unit
def test_tombstoned_target_not_repushed(patched_session):
    s, user = patched_session
    handler = StubHandler(enabled=True)
    register_handler(handler)
    row = _seed_web_row(s, user)
    # Pre-existing tombstone — terminal, must never be re-pushed.
    s.add(ub.AnnotationSyncTarget(
        annotation_id=row.id, target="stub", status="tombstone",
    ))
    s.commit()

    dispatch_existing_annotation_sync(row, _book(), user)

    assert handler.calls == []  # push never attempted
    tgt = s.query(ub.AnnotationSyncTarget).filter_by(annotation_id=row.id).one()
    assert tgt.status == "tombstone"
