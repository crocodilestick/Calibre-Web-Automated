# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Integration tests for the H1 Phase 3 import path.

Exercises ``cps.annotations.ingest_bookmarks`` end-to-end against an
in-memory SQLAlchemy session — covers the full INSERT loop including
UUID resolution, orphan-skipping, hidden-row filtering, dedup against
``(user_id, annotation_id)``, and the JSON summary shape the endpoint
returns.

Coverage:

1. End-to-end ingest of the canonical synthetic fixture produces the
   expected counts: imported=3, skipped_orphan=2, skipped_hidden=1.
2. All H1 columns on each inserted row are populated.
3. Re-running the same import is idempotent — second pass counts as
   ``skipped_existing``.
4. Mixed UUID + sideloaded ``file://`` URIs split correctly into
   imported vs skipped_orphan.
5. Multi-user isolation — user A's import never resolves user B's
   existing rows.
6. Commit failure rolls back cleanly + reports imported=0.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.kobo_reader_sqlite import build_synthetic_kobo_db


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    """Same shape as the backup-feature fixture — full ub.Base schema
    in-memory + worker autostart disabled so the after_flush hook
    doesn't try to dispatch to a production-DB-bound thread."""
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


def _make_book_lookup(uuid_to_book_id: dict[str, int]):
    """Build a callable that maps Bookmark.VolumeID → fake Book
    object whose ``.id`` is what the production lookup would return.
    Unknown UUIDs return ``None`` to simulate "book not in library"."""
    def lookup(uuid):
        if not uuid or uuid not in uuid_to_book_id:
            return None
        return SimpleNamespace(id=uuid_to_book_id[uuid])
    return lookup


@pytest.fixture
def synthetic_db(tmp_path):
    return build_synthetic_kobo_db(tmp_path / "kr.sqlite")


# ---------------------------------------------------------------------------
# 1 + 4. End-to-end ingest produces the expected counts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIngestCounts:
    def test_canonical_fixture_counts(self, memory_db, synthetic_db):
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        # Only the primary UUID maps to a CW book; the extra UUID +
        # the file:// URI are both orphans.
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })

        result = ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=book_lookup, commit=session.commit,
        )
        assert result["imported"] == 3, result
        assert result["skipped_hidden"] == 1, result
        assert result["skipped_orphan"] == 2, result    # bm-004 sideloaded + bm-006 unknown UUID
        assert result["skipped_existing"] == 0, result
        # total_seen excludes empty BookmarkID + empty Text rows
        # (filtered at the parser SQL level).
        assert result["total_seen"] == 6, result

    def test_inserted_rows_carry_full_h1_payload(self, memory_db, synthetic_db):
        from cps import ub
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })
        ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=book_lookup, commit=session.commit,
        )

        # bm-002 has all the bells: multi-span, typed note, red color.
        row = session.query(ub.Annotation).filter_by(
            annotation_id="bm-002"
        ).one()
        assert row.user_id == 7
        assert row.book_id == 348
        assert row.highlighted_text == "Four legs good, two legs bad."
        assert row.highlight_color == "red"
        assert row.note_text == "my favorite line"
        assert row.start_container_path == "span#kobo\\.1\\.2"
        assert row.end_container_path == "span#kobo\\.1\\.3"
        assert row.start_offset == 0
        assert row.end_offset == 21
        assert row.source == "kobo"
        assert row.chapter_progress == 0.024

    def test_color_round_trips(self, memory_db, synthetic_db):
        from cps import ub
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })
        ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=book_lookup, commit=session.commit,
        )
        rows = {r.annotation_id: r for r in
                session.query(ub.Annotation).filter_by(user_id=7).all()}
        assert rows["bm-001"].highlight_color == "yellow"
        assert rows["bm-002"].highlight_color == "red"
        assert rows["bm-003"].highlight_color == "green"


# ---------------------------------------------------------------------------
# 2. Re-import is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIdempotency:
    def test_second_import_skips_existing(self, memory_db, synthetic_db):
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })

        first = ingest_bookmarks(synthetic_db, user_id=7, session=session,
                                  book_lookup=book_lookup, commit=session.commit)
        assert first["imported"] == 3

        second = ingest_bookmarks(synthetic_db, user_id=7, session=session,
                                   book_lookup=book_lookup, commit=session.commit)
        assert second["imported"] == 0
        assert second["skipped_existing"] == 3, second
        # Orphans are still orphans on re-import; that count stays.
        assert second["skipped_orphan"] == 2

    def test_no_duplicate_rows_after_double_import(self, memory_db, synthetic_db):
        from cps import ub
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })

        for _i in range(3):
            ingest_bookmarks(synthetic_db, user_id=7, session=session,
                              book_lookup=book_lookup, commit=session.commit)

        total = session.query(ub.Annotation).filter_by(user_id=7).count()
        assert total == 3, "Re-import must never duplicate rows"


# ---------------------------------------------------------------------------
# 3. Multi-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultiUserIsolation:
    def test_user_a_import_does_not_collide_with_user_b(self, memory_db, synthetic_db):
        from cps import ub
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        # User B has already imported the same annotations earlier.
        ingest_bookmarks(
            synthetic_db, user_id=99, session=session,
            book_lookup=_make_book_lookup({"b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348}),
            commit=session.commit,
        )
        # User A imports for the first time — must NOT see user B's
        # rows as "existing" — annotation_id is scoped per-user.
        result = ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=_make_book_lookup({"b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348}),
            commit=session.commit,
        )
        assert result["imported"] == 3
        assert result["skipped_existing"] == 0

        a_rows = session.query(ub.Annotation).filter_by(user_id=7).count()
        b_rows = session.query(ub.Annotation).filter_by(user_id=99).count()
        assert a_rows == 3
        assert b_rows == 3


# ---------------------------------------------------------------------------
# 4. Sideloaded URI handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSideloadedBookHandling:
    def test_file_uri_volume_id_counted_as_orphan(self, memory_db, synthetic_db):
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        # Only the UUID-format VolumeID maps; file://... doesn't.
        result = ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=_make_book_lookup({"b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348}),
            commit=session.commit,
        )
        # bm-004 (file:// URI) counts as orphan + bm-006 (unknown UUID)
        # also orphan = 2.
        assert result["skipped_orphan"] == 2


# ---------------------------------------------------------------------------
# 5. Commit failure rolls back
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommitFailure:
    def test_commit_failure_reports_imported_zero(self, memory_db, synthetic_db):
        from cps.annotations import ingest_bookmarks

        session, _, _ = memory_db
        book_lookup = _make_book_lookup({
            "b3d1b38b-74fd-43b7-a796-996e5a6a8b04": 348,
        })

        def boom():
            raise RuntimeError("synthetic commit failure")

        result = ingest_bookmarks(
            synthetic_db, user_id=7, session=session,
            book_lookup=book_lookup, commit=boom,
        )
        assert result["imported"] == 0
        # Other counts are still reported honestly so the user sees
        # what would have been imported if the commit had succeeded.
        assert result["skipped_orphan"] == 2
        assert result["skipped_hidden"] == 1
