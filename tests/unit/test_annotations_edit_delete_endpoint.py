# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase 1 — web-reader annotation *edit* + *delete* helpers.

Pins the pure ``edit_annotation`` / ``delete_annotation`` helpers in
``cps.annotations``. HTTP routing / auth / CSRF: container smoke + Playwright.

Rules under test:
  * edit mutates only color + note; position fields are immutable,
  * an invalid color is rejected (ValueError → route 400),
  * delete is a soft-delete (``hidden=True``) and idempotent,
  * a row that belongs to another user (or doesn't exist) is invisible — the
    helper returns ``None`` so the route 404s (IDOR guard).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
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
    monkeypatch.setattr(ub, "session", session)
    monkeypatch.setattr(constants, "CONFIG_DIR", str(tmp_path))
    yield session
    session.close()
    annotation_backup.reset_for_tests()


def _seed(session, *, user_id=7, book_id=1, annotation_id="cwn-web-abc",
          color="yellow", note=None):
    from cps import ub
    row = ub.Annotation(
        user_id=user_id, book_id=book_id, annotation_id=annotation_id,
        source="webreader", highlighted_text="some text", highlight_color=color,
        note_text=note,
        content_id="uuid!!chapter1.html",
        start_container_path="span#kobo.1.1", start_container_child_index=-99,
        start_offset=0, end_container_path="span#kobo.1.1",
        end_container_child_index=-99, end_offset=9, hidden=False,
    )
    session.add(row)
    session.commit()
    return row


@pytest.mark.unit
class TestEditAnnotation:
    def test_edit_updates_color_and_note(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        row = ann_mod.edit_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit, color="green", note="my note",
        )
        assert row is not None
        assert row.highlight_color == "green"
        assert row.note_text == "my note"

    def test_edit_does_not_touch_position(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        row = ann_mod.edit_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit, color="red",
        )
        # Position fields are immutable on edit.
        assert row.start_container_path == "span#kobo.1.1"
        assert row.start_offset == 0
        assert row.end_offset == 9

    def test_edit_only_note_leaves_color(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db, color="blue")
        row = ann_mod.edit_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit, note="just a note",
        )
        assert row.highlight_color == "blue"   # unchanged
        assert row.note_text == "just a note"

    def test_edit_invalid_color_rejected(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        with pytest.raises(ValueError):
            ann_mod.edit_annotation(
                "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
                commit=memory_db.commit, color="chartreuse",
            )

    def test_edit_foreign_user_returns_none(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db, user_id=7)
        # User 99 must not be able to edit user 7's annotation.
        result = ann_mod.edit_annotation(
            "cwn-web-abc", user_id=99, book_id=1, session=memory_db,
            commit=memory_db.commit, color="green",
        )
        assert result is None

    def test_edit_unknown_returns_none(self, memory_db):
        from cps import annotations as ann_mod
        result = ann_mod.edit_annotation(
            "does-not-exist", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit, color="green",
        )
        assert result is None


@pytest.mark.unit
class TestDeleteAnnotation:
    def test_delete_soft_deletes(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        row = ann_mod.delete_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        assert row is not None
        assert row.hidden is True

    def test_deleted_row_drops_from_load(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        ann_mod.delete_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        visible = ann_mod._load_user_annotations(7, 1)
        assert all(r.annotation_id != "cwn-web-abc" for r in visible)

    def test_delete_idempotent(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db)
        ann_mod.delete_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        # Second delete is a no-op that still resolves the (hidden) row → 200.
        again = ann_mod.delete_annotation(
            "cwn-web-abc", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        assert again is not None
        assert again.hidden is True

    def test_delete_unknown_returns_none(self, memory_db):
        from cps import annotations as ann_mod
        result = ann_mod.delete_annotation(
            "nope", user_id=7, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        assert result is None

    def test_delete_foreign_user_returns_none(self, memory_db):
        from cps import annotations as ann_mod
        _seed(memory_db, user_id=7)
        result = ann_mod.delete_annotation(
            "cwn-web-abc", user_id=99, book_id=1, session=memory_db,
            commit=memory_db.commit,
        )
        assert result is None
        # The real owner's row is untouched.
        from cps import ub
        owner_row = memory_db.query(ub.Annotation).filter_by(
            user_id=7, annotation_id="cwn-web-abc"
        ).one()
        assert owner_row.hidden is False
