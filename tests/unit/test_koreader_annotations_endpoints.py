# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 2 — KOReader-bridge server endpoints (pull/push core).

The Flask routes (GET/PUT /kosync/syncs/annotations) reuse kosync's
authenticate_user + get_book_by_checksum and are exercised over the wire; this
file pins the testable core:

  - build_pull_payload(user_id, book_id, session) → portable dicts for the
    device, INCLUDING hidden rows (so the device can delete locally).
  - apply_push(annotations, user, book, ...) → upsert each (create/update/
    soft-delete), fan out to enabled sync targets, return a counts summary.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace

from cps import ub
from cps.services.annotation_sync import (
    register_handler, reset_registry_for_testing,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult
from cps.progress_syncing.protocols.koreader_annotations import (
    build_pull_payload, apply_push,
)

pytestmark = pytest.mark.unit


class StubHandler(AnnotationSyncTargetHandler):
    target_name = "stub"

    def __init__(self):
        self.pushes = []
        self.deletes = []

    def is_enabled(self, user):
        return True

    def push(self, annotation, book, user, payload=None):
        self.pushes.append(annotation.annotation_id)
        return SyncResult(status="synced", target_record_id="r1")

    def delete(self, sync_target, user):
        self.deletes.append(sync_target.target_record_id)
        return SyncResult(status="tombstone")


@pytest.fixture(autouse=True)
def _reset():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    ub.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="kr", email="kr@e.com", role=0, password="x")
    s.add(user)
    s.commit()
    monkeypatch.setattr(ub, "session", s)
    monkeypatch.setattr(ub, "session_commit", lambda: s.commit())
    yield s, user


def _book():
    return SimpleNamespace(id=7, uuid="bk-7", title="Book")


def _seed(s, user, aid, book_id=7, hidden=False):
    s.add(ub.Annotation(
        user_id=user.id, annotation_id=aid, book_id=book_id, source="kobo",
        highlighted_text="t", highlight_color="yellow",
        start_container_path="span#kobo.1.1", start_offset=0,
        end_container_path="span#kobo.1.1", end_offset=4, hidden=hidden,
    ))
    s.commit()


# --- pull ------------------------------------------------------------------

def test_pull_returns_user_rows_including_hidden(env):
    s, user = env
    _seed(s, user, "a1")
    _seed(s, user, "a2", hidden=True)
    payload = build_pull_payload(user.id, 7, s)
    ids = {a["annotation_id"] for a in payload["annotations"]}
    assert ids == {"a1", "a2"}           # hidden included so device can delete
    assert payload["annotation_count"] == 2
    a2 = [a for a in payload["annotations"] if a["annotation_id"] == "a2"][0]
    assert a2["hidden"] is True


def test_pull_excludes_other_users_and_books(env):
    s, user = env
    other = ub.User(name="o", email="o@e.com", role=0, password="x")
    s.add(other); s.commit()
    _seed(s, user, "mine", book_id=7)
    _seed(s, user, "otherbook", book_id=99)
    _seed(s, other, "theirs", book_id=7)
    payload = build_pull_payload(user.id, 7, s)
    ids = {a["annotation_id"] for a in payload["annotations"]}
    assert ids == {"mine"}


# --- push ------------------------------------------------------------------

def test_push_creates_updates_deletes(env):
    s, user = env
    _seed(s, user, "existing")
    summary = apply_push([
        {"annotation_id": "new1", "color": "green", "start_kobospan": "kobo.2.1",
         "start_offset": 0, "end_kobospan": "kobo.2.1", "end_offset": 5,
         "content_id": "bk-7!!c.html", "device_origin_id": "bm-new1"},
        {"annotation_id": "existing", "color": "red"},   # update
        {"annotation_id": "new1-del", "hidden": True},    # delete (no prior row → still counts)
    ], user=user, book=_book(), session=s, commit=s.commit)
    assert summary["created"] == 1
    assert summary["updated"] == 1
    assert summary["deleted"] == 1
    # The created row is persisted with koreader source + device_origin_id.
    row = s.query(ub.Annotation).filter_by(user_id=user.id, annotation_id="new1").one()
    assert row.source == "koreader"
    assert row.device_origin_id == "bm-new1"
    # The updated row changed color.
    upd = s.query(ub.Annotation).filter_by(annotation_id="existing").one()
    assert upd.highlight_color == "red"


def test_push_fans_out_to_enabled_target(env):
    s, user = env
    handler = StubHandler()
    register_handler(handler)
    apply_push([
        {"annotation_id": "fan1", "color": "yellow", "start_kobospan": "kobo.1.1",
         "start_offset": 0, "end_kobospan": "kobo.1.1", "end_offset": 3},
    ], user=user, book=_book(), session=s, commit=s.commit)
    assert handler.pushes == ["fan1"]
    tgt = s.query(ub.AnnotationSyncTarget).one()
    assert tgt.target == "stub" and tgt.status == "synced"


def test_push_skips_rows_without_id(env):
    s, user = env
    summary = apply_push([{"color": "yellow"}], user=user, book=_book(),
                         session=s, commit=s.commit)
    assert summary["skipped"] == 1
