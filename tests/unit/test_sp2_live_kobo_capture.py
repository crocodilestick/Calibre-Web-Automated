# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sub-project (2) — live Kobo annotation capture independent of Hardcover.

Pins:
  1. Annotation rows are persisted with FULL position fields from the PATCH
     payload (content_id, start_container_path, start_offset, end_container_path,
     end_offset, context_string), not just text/note/color/chapter_progress.
  2. Annotation persistence happens even when no sync target is enabled
     (no Hardcover token, config off, etc.).
  3. DELETE PATCH soft-deletes the local row (hidden=True) regardless of
     whether any sync handler is registered or enabled.
  4. A subsequent re-create PATCH for a previously hidden annotation un-hides it.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from cps import ub
from cps.services.annotation_sync import (
    dispatch_annotation_sync,
    dispatch_annotation_deletes,
    register_handler,
    reset_registry_for_testing,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


@pytest.fixture(autouse=True)
def _registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def session(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/app.db")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="u", email="u@e.com", role=0, password="x")
    s.add(user); s.commit()
    monkeypatch.setattr(ub, "session", s)
    monkeypatch.setattr(ub, "session_commit", lambda: s.commit())
    yield s, user
    s.close()


def _book(book_id=7, uuid="f5bf555e-ab63-4649-8430-38449747cace"):
    return SimpleNamespace(id=book_id, title=f"Book {book_id}", uuid=uuid)


def _full_payload(annotation_id):
    """Realistic Kobo PATCH payload with location.span fully populated."""
    return {
        "id": annotation_id,
        "highlightedText": "There is no such thing as a moral or an immoral book.",
        "noteText": "Iconic opening line.",
        "highlightColor": "yellow",
        "location": {
            "span": {
                "chapterFilename": "OEBPS/chapter-01.html",
                "chapterProgress": 0.05,
                "chapterTitle": "Chapter I",
                "startPath": "/span[@id='kobo.1.1']/text()",
                "endPath": "/span[@id='kobo.1.5']/text()",
                "startChar": 0,
                "endChar": 50,
                "contextString": "...around the highlight...",
            }
        },
    }


# ---- (2.1) Annotation persists with NO handler registered ----

def test_persists_annotation_with_no_handler_registered(session):
    s, user = session
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    rows = s.query(ub.Annotation).all()
    assert len(rows) == 1
    assert rows[0].source == "kobo"
    # No sync_target rows because no handler is registered.
    assert s.query(ub.AnnotationSyncTarget).count() == 0


def test_persists_annotation_with_disabled_handler(session):
    s, user = session
    class DisabledHandler(AnnotationSyncTargetHandler):
        target_name = "hardcover"
        def is_enabled(self, user): return False
        def push(self, *a, **kw): return SyncResult(status="failed")
        def delete(self, *a, **kw): return SyncResult(status="failed")
    register_handler(DisabledHandler())
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    assert s.query(ub.Annotation).count() == 1
    assert s.query(ub.AnnotationSyncTarget).count() == 0


# ---- (2.2) Position fields fully populated ----

def test_full_position_fields_captured(session):
    s, user = session
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    ann = s.query(ub.Annotation).one()
    assert ann.highlighted_text == "There is no such thing as a moral or an immoral book."
    assert ann.note_text == "Iconic opening line."
    assert ann.highlight_color == "yellow"
    assert ann.chapter_progress == 0.05
    # The new sub-project (2) bits — position fields:
    assert ann.content_id == "f5bf555e-ab63-4649-8430-38449747cace!!OEBPS/chapter-01.html"
    assert ann.start_container_path == "/span[@id='kobo.1.1']/text()"
    assert ann.end_container_path == "/span[@id='kobo.1.5']/text()"
    assert ann.start_offset == 0
    assert ann.end_offset == 50
    assert ann.context_string == "...around the highlight..."


def test_partial_payload_doesnt_overwrite_existing_fields(session):
    """An UPDATE PATCH that only changes color must preserve position fields."""
    s, user = session
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    update = {"id": "kobo-1", "highlightColor": "red"}
    dispatch_annotation_sync([update], _book(), user)
    ann = s.query(ub.Annotation).one()
    assert ann.highlight_color == "red"
    assert ann.content_id == "f5bf555e-ab63-4649-8430-38449747cace!!OEBPS/chapter-01.html"
    assert ann.start_offset == 0  # preserved


# ---- (2.3) Soft delete ----

def test_delete_soft_deletes_local_row_with_no_handler(session):
    s, user = session
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    ann = s.query(ub.Annotation).one()
    assert ann.hidden is False or ann.hidden is None
    dispatch_annotation_deletes(["kobo-1"], user)
    s.refresh(ann)
    assert ann.hidden is True


def test_delete_soft_deletes_locally_even_when_handler_disabled(session):
    s, user = session
    class DisabledHandler(AnnotationSyncTargetHandler):
        target_name = "hardcover"
        def is_enabled(self, user): return False
        def push(self, *a, **kw): return SyncResult(status="synced")
        def delete(self, *a, **kw): return SyncResult(status="tombstone")
    register_handler(DisabledHandler())
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    dispatch_annotation_deletes(["kobo-1"], user)
    ann = s.query(ub.Annotation).one()
    assert ann.hidden is True


def test_delete_nonexistent_annotation_is_noop(session):
    s, user = session
    dispatch_annotation_deletes(["never-existed"], user)
    assert s.query(ub.Annotation).count() == 0


# ---- (2.4) Recovery — re-create un-hides ----

def test_recreate_unhides_previously_deleted_annotation(session):
    """User deletes a highlight, then re-creates the same annotation_id —
    the local row comes back to life rather than staying hidden."""
    s, user = session
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    dispatch_annotation_deletes(["kobo-1"], user)
    ann = s.query(ub.Annotation).one()
    assert ann.hidden is True
    # PATCH the same annotation_id again with new text.
    new_payload = {
        "id": "kobo-1",
        "highlightedText": "different text",
        "highlightColor": "green",
        "location": {"span": {"chapterProgress": 0.1}},
    }
    dispatch_annotation_sync([new_payload], _book(), user)
    s.refresh(ann)
    assert ann.hidden is False
    assert ann.highlighted_text == "different text"


# ---- (2.5) Synced handler path still works ----

def test_synced_handler_still_creates_sync_target_row(session):
    """Regression: enabling sub-project (2) for the Annotation row shouldn't
    break sub-project (1)'s sync_target writes."""
    s, user = session
    class Synced(AnnotationSyncTargetHandler):
        target_name = "hardcover"
        def is_enabled(self, user): return True
        def push(self, *a, **kw): return SyncResult(status="synced", target_record_id="r99")
        def delete(self, *a, **kw): return SyncResult(status="tombstone")
    register_handler(Synced())
    dispatch_annotation_sync([_full_payload("kobo-1")], _book(), user)
    assert s.query(ub.Annotation).count() == 1
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "synced"
    assert st.target_record_id == "r99"
