# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the H1 Phase 5 data endpoint helpers in
``cps/annotations.py``.

The Flask-level routing + auth is covered by the live container smoke;
this file pins the pure helpers:

1. ``_resolve_epub_path`` returns the on-disk EPUB path for a book
   whose ``data`` carries an ``EPUB``/``KEPUB`` format; None when
   neither format exists or the file is missing on disk.
2. ``_ensure_cfi_range`` short-circuits when the row already has a
   ``cfi_range``; otherwise calls P2's converter; persists the
   result back when the conversion succeeds; tolerates malformed
   ``content_id``.
"""

from __future__ import annotations

from pathlib import Path
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
    """Build a fake Book row stand-in + write a synthetic kepub to
    ``<tmp_path>/<book.path>/<data.name>.kepub`` so
    ``_resolve_epub_path`` can find it."""
    book_path = "Author/Title"
    book_dir = tmp_path / "library" / book_path
    book_dir.mkdir(parents=True)
    data_name = "title"
    if with_epub:
        build_synthetic_kepub(book_dir / (data_name + ".kepub"))
    fmt = SimpleNamespace(format="KEPUB", name=data_name)
    book = SimpleNamespace(
        id=1, path=book_path, title="Title",
        data=[fmt] if with_epub else [],
    )
    return book


# ---------------------------------------------------------------------------
# _resolve_epub_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveEpubPath:
    def test_finds_kepub_on_disk(self, tmp_path, monkeypatch):
        from cps import annotations as ann_mod
        from cps import config

        book = _make_book(tmp_path, with_epub=True)
        monkeypatch.setattr(
            config, "get_book_path",
            lambda: str(tmp_path / "library"),
        )

        path = ann_mod._resolve_epub_path(book)
        assert path is not None
        assert Path(path).is_file()
        assert path.endswith(".kepub")

    def test_returns_none_when_no_epub_format(self, tmp_path, monkeypatch):
        from cps import annotations as ann_mod
        from cps import config

        book = _make_book(tmp_path, with_epub=False)
        monkeypatch.setattr(
            config, "get_book_path",
            lambda: str(tmp_path / "library"),
        )

        assert ann_mod._resolve_epub_path(book) is None

    def test_returns_none_when_file_missing_on_disk(self, tmp_path, monkeypatch):
        from cps import annotations as ann_mod
        from cps import config

        # Book has an EPUB format declared but the file isn't there.
        book = SimpleNamespace(
            id=1, path="Author/Missing", title="Missing",
            data=[SimpleNamespace(format="EPUB", name="missing")],
        )
        monkeypatch.setattr(
            config, "get_book_path",
            lambda: str(tmp_path / "library"),
        )
        assert ann_mod._resolve_epub_path(book) is None


# ---------------------------------------------------------------------------
# _ensure_cfi_range
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnsureCfiRange:
    def test_short_circuits_when_cfi_already_present(self, memory_db, tmp_path):
        from cps import ub, annotations as ann_mod

        row = ub.KoboAnnotationSync(
            user_id=7, book_id=1, annotation_id="cached-cfi",
            highlighted_text="x", cfi_range="epubcfi(/already/present)",
            source="kobo",
        )
        memory_db.add(row); memory_db.commit()

        book = _make_book(tmp_path, with_epub=False)
        # No epub on disk + no content_id — but cfi already set, so we
        # never reach the compute path.
        result = ann_mod._ensure_cfi_range(row, book)
        assert result == "epubcfi(/already/present)"

    def test_computes_cfi_when_missing(self, memory_db, tmp_path, monkeypatch):
        from cps import ub, annotations as ann_mod, config

        row = ub.KoboAnnotationSync(
            user_id=7, book_id=1, annotation_id="needs-cfi",
            highlighted_text="hello",
            cfi_range=None,
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99, start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99, end_offset=15,
            source="kobo",
        )
        memory_db.add(row); memory_db.commit()

        book = _make_book(tmp_path, with_epub=True)
        monkeypatch.setattr(
            config, "get_book_path",
            lambda: str(tmp_path / "library"),
        )

        result = ann_mod._ensure_cfi_range(row, book)
        assert result is not None
        assert result.startswith("epubcfi(")
        # The compute path persists back to the row.
        assert row.cfi_range == result

    def test_returns_none_on_malformed_content_id(self, memory_db, tmp_path):
        from cps import ub, annotations as ann_mod

        row = ub.KoboAnnotationSync(
            user_id=7, book_id=1, annotation_id="bad-content",
            highlighted_text="x", content_id="no-double-bang",
            source="kobo",
        )
        memory_db.add(row); memory_db.commit()

        book = _make_book(tmp_path, with_epub=True)
        assert ann_mod._ensure_cfi_range(row, book) is None

    def test_returns_none_when_no_epub_on_disk(self, memory_db, tmp_path, monkeypatch):
        from cps import ub, annotations as ann_mod, config

        row = ub.KoboAnnotationSync(
            user_id=7, book_id=1, annotation_id="no-epub",
            highlighted_text="x",
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99, start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99, end_offset=10,
            source="kobo",
        )
        memory_db.add(row); memory_db.commit()

        book = _make_book(tmp_path, with_epub=False)
        monkeypatch.setattr(
            config, "get_book_path",
            lambda: str(tmp_path / "library"),
        )
        assert ann_mod._ensure_cfi_range(row, book) is None
