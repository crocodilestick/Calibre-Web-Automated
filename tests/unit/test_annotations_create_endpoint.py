# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Phase 1 — web-reader annotation *create* path.

Pins the pure ``cps.annotations.create_annotation`` helper (explicit
dependencies, no Flask context) the same way the H1 import path pins
``ingest_bookmarks``. HTTP routing / auth / CSRF are covered by the live
container smoke + Playwright (see
notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md §3.4).

A web-created highlight must:
  * land with ``source='webreader'`` and a ``cwn-web-`` annotation_id,
  * store the selection as Kobo-native fields (``span#kobo.x.y`` selector +
    ``-99`` child-index sentinel + offsets) so Phase 2 can later push it to a
    device,
  * compute a portable ``cfi_range`` when the kepub is on disk, and degrade to
    ``cfi_range=None`` (still a valid row) when it isn't.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.kepub_fixture import build_synthetic_kepub


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    from cps import ub, constants
    from cps.services import annotation_backup, kobo_position
    annotation_backup.reset_for_tests()
    monkeypatch.setattr(annotation_backup, "WORKER_AUTOSTART", False)
    kobo_position._get_spine.cache_clear()
    kobo_position._get_chapter_dom.cache_clear()

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


def _make_book(tmp_path, with_epub=True):
    """Fake Book row + a synthetic kepub on disk so cfi computation can run.
    Mirrors tests/unit/test_annotations_data_endpoint.py."""
    book_path = "Author/Title"
    book_dir = tmp_path / "library" / book_path
    book_dir.mkdir(parents=True)
    data_name = "title"
    if with_epub:
        build_synthetic_kepub(book_dir / (data_name + ".kepub"))
    fmt = SimpleNamespace(format="KEPUB", name=data_name)
    return SimpleNamespace(
        id=1, uuid="00000000-0000-0000-0000-deadbeefcafe",
        path=book_path, title="Title",
        data=[fmt] if with_epub else [],
    )


def _payload(**over):
    base = {
        "start_kobospan": "kobo.1.1", "start_offset": 0,
        "end_kobospan": "kobo.1.1", "end_offset": 15,
        "content_id": "00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
        "highlighted_text": "hello world!!!", "highlight_color": "yellow",
        "note_text": None,
    }
    base.update(over)
    return base


@pytest.mark.unit
class TestCreateAnnotation:
    def test_create_returns_webreader_row(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)

        row = ann_mod.create_annotation(
            _payload(), user_id=7, book=book,
            session=memory_db, commit=memory_db.commit,
        )
        assert row.source == "webreader"
        assert row.annotation_id.startswith("cwn-web-")
        assert row.user_id == 7
        assert row.book_id == 1
        assert row.highlighted_text == "hello world!!!"
        assert row.highlight_color == "yellow"
        assert row.hidden in (False, None)

    def test_create_stores_kobospan_path_roundtrip(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        from cps.services.kobo_position import _extract_kobospan_id
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)

        row = ann_mod.create_annotation(
            _payload(start_kobospan="kobo.1.1", end_kobospan="kobo.1.1",
                     start_offset=0, end_offset=15),
            user_id=7, book=book, session=memory_db, commit=memory_db.commit,
        )
        assert row.start_container_path == "span#kobo.1.1"
        assert row.end_container_path == "span#kobo.1.1"
        # The selector must round-trip back to the bare KoboSpan id the reader
        # and the converter consume.
        assert _extract_kobospan_id(row.start_container_path) == "kobo.1.1"
        assert row.start_container_child_index == -99
        assert row.end_container_child_index == -99
        assert row.start_offset == 0
        assert row.end_offset == 15
        assert row.content_id == "00000000-0000-0000-0000-deadbeefcafe!!chapter1.html"

    def test_create_computes_cfi_with_kepub(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)

        row = ann_mod.create_annotation(
            _payload(), user_id=7, book=book,
            session=memory_db, commit=memory_db.commit,
        )
        assert row.cfi_range is not None
        assert row.cfi_range.startswith("epubcfi(")

    def test_create_persists_row(self, memory_db, tmp_path, monkeypatch):
        from cps import ub, annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)

        row = ann_mod.create_annotation(
            _payload(), user_id=7, book=book,
            session=memory_db, commit=memory_db.commit,
        )
        fetched = memory_db.query(ub.Annotation).filter_by(
            annotation_id=row.annotation_id
        ).one()
        assert fetched.source == "webreader"

    def test_create_rejects_missing_anchor(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)

        bad = _payload()
        del bad["start_kobospan"]
        with pytest.raises(ValueError):
            ann_mod.create_annotation(
                bad, user_id=7, book=book,
                session=memory_db, commit=memory_db.commit,
            )

    def test_create_builds_content_id_from_chapter_filename(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=True)
        # The reader knows the chapter href but not the book uuid; the server
        # builds the Kobo-valid "<uuid>!!<chapter>" content_id from book.uuid.
        payload = _payload()
        del payload["content_id"]
        payload["chapter_filename"] = "chapter1.html"
        row = ann_mod.create_annotation(
            payload, user_id=7, book=book,
            session=memory_db, commit=memory_db.commit,
        )
        assert row.content_id == "00000000-0000-0000-0000-deadbeefcafe!!chapter1.html"

    def test_create_tolerates_missing_epub(self, memory_db, tmp_path, monkeypatch):
        from cps import annotations as ann_mod, config
        monkeypatch.setattr(config, "get_book_path", lambda: str(tmp_path / "library"))
        book = _make_book(tmp_path, with_epub=False)  # no kepub on disk

        row = ann_mod.create_annotation(
            _payload(), user_id=7, book=book,
            session=memory_db, commit=memory_db.commit,
        )
        # Row is still created and persisted — the reader rebuilds the CFI
        # client-side from the KoboSpan id, so a missing server CFI is fine.
        assert row.annotation_id.startswith("cwn-web-")
        assert row.cfi_range is None
