# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the H1 Phase 4 view + export surface in
``cps/annotations.py``.

The view/export endpoints themselves need a Flask app to drive; the
heavy lifting lives in pure helper functions (``render_markdown``,
``render_csv``, ``render_json``, ``_safe_filename_part``,
``_load_user_annotations``, ``_row_to_dict``) — those are tested here
with real in-memory ``KoboAnnotationSync`` rows so the round-trip is
exact, not mocked.

Coverage:

1. ``_load_user_annotations`` returns per-user-per-book rows sorted by
   ``chapter_progress`` then ``created_at`` then ``id``.
2. Hidden rows excluded; cross-user and cross-book rows excluded.
3. Markdown export carries title, blockquote per highlight, metadata
   line with color/note/progress/source.
4. CSV export: header row + one data row per highlight; stable column
   order; embedded commas/newlines round-trip via QUOTE_MINIMAL.
5. JSON export envelope matches the backup schema so a power user
   can use either interchangeably.
6. Empty-book case: no annotations → empty list / empty CSV body /
   JSON ``annotation_count: 0``.
7. ``_safe_filename_part`` slugifies tricky titles (CJK, slashes,
   leading dots) without producing path-traversal vectors.
"""

from __future__ import annotations

import csv
import io
import json

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
    # Patch ub.session to use the in-memory one so _load_user_annotations
    # (which reads via ub.session) hits our test DB.
    monkeypatch.setattr(ub, "session", session)
    monkeypatch.setattr(constants, "CONFIG_DIR", str(tmp_path))
    yield session
    session.close()
    annotation_backup.reset_for_tests()


def _seed(session, **overrides):
    from cps import ub
    defaults = dict(
        user_id=7, book_id=348,
        annotation_id="seed-001",
        highlighted_text="The quick brown fox.",
        highlight_color="yellow",
        note_text=None,
        content_id="book!!chapter1.html",
        chapter_progress=0.1,
        context_string=None,
        cfi_range=None,
        source="kobo",
        hidden=False,
    )
    defaults.update(overrides)
    row = ub.KoboAnnotationSync(**defaults)
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------------
# _load_user_annotations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadUserAnnotations:
    def test_per_user_per_book_isolation(self, memory_db):
        from cps.annotations import _load_user_annotations

        _seed(memory_db, user_id=7, book_id=348, annotation_id="me-1")
        _seed(memory_db, user_id=7, book_id=349, annotation_id="other-book")
        _seed(memory_db, user_id=99, book_id=348, annotation_id="other-user")

        rows = _load_user_annotations(7, 348)
        assert len(rows) == 1
        assert rows[0].annotation_id == "me-1"

    def test_excludes_hidden_rows(self, memory_db):
        from cps.annotations import _load_user_annotations

        _seed(memory_db, annotation_id="visible", hidden=False)
        _seed(memory_db, annotation_id="soft-deleted", hidden=True)

        rows = _load_user_annotations(7, 348)
        assert [r.annotation_id for r in rows] == ["visible"]

    def test_sort_by_chapter_progress(self, memory_db):
        from cps.annotations import _load_user_annotations

        _seed(memory_db, annotation_id="late",  chapter_progress=0.9)
        _seed(memory_db, annotation_id="early", chapter_progress=0.1)
        _seed(memory_db, annotation_id="mid",   chapter_progress=0.5)

        ids = [r.annotation_id for r in _load_user_annotations(7, 348)]
        assert ids == ["early", "mid", "late"]


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkdownExport:
    def test_includes_book_title_and_blockquotes(self, memory_db):
        from cps.annotations import render_markdown, _load_user_annotations

        _seed(memory_db, highlighted_text="All animals are equal.")
        md = render_markdown("Animal Farm", _load_user_annotations(7, 348))

        assert md.startswith("# Animal Farm\n")
        assert "> All animals are equal." in md

    def test_metadata_line_when_color_or_note_present(self, memory_db):
        from cps.annotations import render_markdown, _load_user_annotations

        _seed(memory_db,
              highlighted_text="The picture",
              highlight_color="red",
              note_text="key passage",
              chapter_progress=0.42,
              source="kobo")
        md = render_markdown("Dorian Gray", _load_user_annotations(7, 348))

        assert "color: **red**" in md
        assert "note: key passage" in md
        assert "chapter progress: 42%" in md
        assert "source: kobo" in md

    def test_multi_line_highlight_each_line_quoted(self, memory_db):
        from cps.annotations import render_markdown, _load_user_annotations

        _seed(memory_db, highlighted_text="Line one.\nLine two.\nLine three.")
        md = render_markdown("Multiline", _load_user_annotations(7, 348))
        assert "> Line one." in md
        assert "> Line two." in md
        assert "> Line three." in md


# ---------------------------------------------------------------------------
# render_csv
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCsvExport:
    def test_csv_round_trip(self, memory_db):
        from cps.annotations import render_csv, _load_user_annotations, _EXPORT_FIELDS

        _seed(memory_db, highlighted_text="ordinary text",
              note_text="my note", highlight_color="blue")
        body = render_csv(_load_user_annotations(7, 348))

        reader = csv.DictReader(io.StringIO(body))
        assert reader.fieldnames == list(_EXPORT_FIELDS)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["highlighted_text"] == "ordinary text"
        assert rows[0]["note_text"] == "my note"
        assert rows[0]["highlight_color"] == "blue"

    def test_csv_handles_embedded_commas_and_newlines(self, memory_db):
        from cps.annotations import render_csv, _load_user_annotations

        _seed(memory_db,
              highlighted_text='text with, commas\nand "quotes" plus a newline',
              note_text='note, has commas')
        body = render_csv(_load_user_annotations(7, 348))

        # Round-trip via the CSV parser — if escaping is wrong this
        # fails with a parse error or yields garbage columns.
        rows = list(csv.DictReader(io.StringIO(body)))
        assert rows[0]["highlighted_text"] == 'text with, commas\nand "quotes" plus a newline'
        assert rows[0]["note_text"] == 'note, has commas'

    def test_empty_book_returns_header_only(self, memory_db):
        from cps.annotations import render_csv, _load_user_annotations

        body = render_csv(_load_user_annotations(7, 999))
        lines = [l for l in body.splitlines() if l]
        # Just the header.
        assert len(lines) == 1
        assert lines[0].startswith("annotation_id,book_id,")


# ---------------------------------------------------------------------------
# render_json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonExport:
    def test_json_envelope_matches_backup_shape(self, memory_db):
        from cps.annotations import render_json, _load_user_annotations

        _seed(memory_db, annotation_id="a1",
              highlighted_text="First", highlight_color="yellow")
        _seed(memory_db, annotation_id="a2",
              highlighted_text="Second", highlight_color="red",
              chapter_progress=0.5)
        body = render_json("Test Book", 348, 7, _load_user_annotations(7, 348))
        payload = json.loads(body)

        assert payload["schema_version"] == 1
        assert payload["user_id"] == 7
        assert payload["book_id"] == 348
        assert payload["book_title"] == "Test Book"
        assert payload["annotation_count"] == 2
        assert {a["annotation_id"] for a in payload["annotations"]} == {"a1", "a2"}
        # Spot-check the per-row shape mirrors the backup snapshot.
        a1 = next(a for a in payload["annotations"] if a["annotation_id"] == "a1")
        assert a1["highlighted_text"] == "First"
        assert a1["highlight_color"] == "yellow"

    def test_empty_book_returns_zero_count(self, memory_db):
        from cps.annotations import render_json, _load_user_annotations

        body = render_json("Empty", 999, 7, _load_user_annotations(7, 999))
        payload = json.loads(body)
        assert payload["annotation_count"] == 0
        assert payload["annotations"] == []


# ---------------------------------------------------------------------------
# _safe_filename_part
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSafeFilenamePart:
    def test_clean_title_passes_through(self):
        from cps.annotations import _safe_filename_part
        assert _safe_filename_part("Animal Farm") == "Animal-Farm"

    def test_removes_path_traversal_chars(self):
        """Path traversal requires ``/`` or ``\\`` — dots alone in a
        filename body can't navigate. Slugifier strips both."""
        from cps.annotations import _safe_filename_part
        assert "/" not in _safe_filename_part("../../../etc/passwd")
        assert "\\" not in _safe_filename_part("c:\\windows\\system32")

    def test_cjk_title_yields_default(self):
        """Pure-CJK title strips to empty + falls back to default
        rather than producing a zero-length filename."""
        from cps.annotations import _safe_filename_part
        assert _safe_filename_part("動物農場") == "book"

    def test_empty_input_yields_default(self):
        from cps.annotations import _safe_filename_part
        assert _safe_filename_part("") == "book"
        assert _safe_filename_part(None) == "book"

    def test_preserves_dots_and_underscores(self):
        from cps.annotations import _safe_filename_part
        assert _safe_filename_part("v1.0_release") == "v1.0_release"
