# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""D4: per-user-book data has ONE enumerator (cps/user_book_data.py).

Merging a duplicate used to copy only file formats — the losing book was
then deleted and the user's annotations, reading progress, Kobo state and
shelf membership on it were orphaned (annotations: silent data loss). The
admin database-change wipe and the per-user delete each kept their own
disagreeing hand-list, both missing annotations (per-user delete also left
on-disk annotation-backup gzips behind — PII surviving account deletion).

migrate_user_book_data / purge_user_book_data are now the only places that
enumerate the per-user-book model set; behavioural tests run against a real
in-memory app.db; source-pins lock the four call sites onto the helpers.
"""

import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO = pathlib.Path(__file__).resolve().parents[2]

WINNER = 101
LOSER = 202
USER = 7


@pytest.fixture
def session(monkeypatch):
    import sys
    # some suites stub cps.*, flask, sqlalchemy… into sys.modules and don't
    # restore — evict the whole affected families so we import the real ones.
    if "cps.ub" in sys.modules and not hasattr(sys.modules["cps.ub"], "Base"):
        stubbed = {"cps", "cwa_db", "flask", "flask_babel", "flask_dance",
                   "sqlalchemy", "werkzeug"}
        for name in [m for m in list(sys.modules) if m.split(".")[0] in stubbed]:
            sys.modules.pop(name, None)
    from cps import ub
    from cps.services import annotation_backup
    annotation_backup.reset_for_tests()
    monkeypatch.setattr(annotation_backup, "WORKER_AUTOSTART", False)
    engine = create_engine("sqlite:///:memory:", future=True)
    ub.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # the BookShelf before_flush listener walks link.ub_shelf — give the
    # shelves used in these tests real rows.
    s.add_all([ub.Shelf(id=1, name="one", user_id=USER),
               ub.Shelf(id=2, name="two", user_id=USER)])
    s.commit()
    yield s
    s.close()


def _set_state_timestamps(session, ub, book_to_ts):
    # the ub before_flush listener stamps KoboReadingState.last_modified to
    # now() whenever its bookmark child flushes, clobbering explicit values —
    # set them afterwards with a bulk UPDATE (which the listener ignores).
    for book_id, ts in book_to_ts.items():
        session.query(ub.KoboReadingState).filter(
            ub.KoboReadingState.book_id == book_id).update(
            {ub.KoboReadingState.last_modified: ts}, synchronize_session=False)
    session.commit()
    session.expire_all()


def _shelf_link(session, ub, book_id, shelf_id, order):
    # production creates links through the Shelf.books relationship, which
    # populates the ub_shelf backref the before_flush listener relies on.
    shelf = session.get(ub.Shelf, shelf_id)
    link = ub.BookShelf(book_id=book_id, order=order, ub_shelf=shelf)
    session.add(link)
    return link


def _annotation(ub, book_id, annotation_id="ann-1", user_id=USER, **kw):
    return ub.Annotation(user_id=user_id, annotation_id=annotation_id,
                         book_id=book_id, highlighted_text=kw.pop("text", "hl"),
                         source="webreader", **kw)


@pytest.mark.unit
class TestMigrate:
    def test_annotation_moves_to_winner_with_sync_targets(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        ann = _annotation(ub, LOSER)
        ann.sync_targets.append(ub.AnnotationSyncTarget(target="hardcover", status="synced"))
        session.add(ann)
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        moved = session.query(ub.Annotation).one()
        assert moved.book_id == WINNER
        assert moved.highlighted_text == "hl"
        assert session.query(ub.AnnotationSyncTarget).count() == 1

    def test_annotation_clash_keeps_winner_row(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        keep = _annotation(ub, WINNER, text="winner-copy")
        lose = _annotation(ub, LOSER, text="loser-copy")
        lose.sync_targets.append(ub.AnnotationSyncTarget(target="hardcover", status="pending"))
        session.add_all([keep, lose])
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        rows = session.query(ub.Annotation).all()
        assert len(rows) == 1 and rows[0].highlighted_text == "winner-copy"
        # the dropped loser row's sync-target child went with it
        assert session.query(ub.AnnotationSyncTarget).count() == 0

    def test_kobo_reading_state_newer_loser_wins(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        now = datetime.now(timezone.utc)
        old = ub.KoboReadingState(user_id=USER, book_id=WINNER)
        new = ub.KoboReadingState(user_id=USER, book_id=LOSER)
        new.current_bookmark = ub.KoboBookmark(progress_percent=42.0)
        session.add_all([old, new])
        session.commit()
        _set_state_timestamps(session, ub, {WINNER: now - timedelta(days=2), LOSER: now})

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        state = session.query(ub.KoboReadingState).one()
        assert state.book_id == WINNER
        assert state.current_bookmark.progress_percent == 42.0

    def test_kobo_reading_state_older_loser_dropped(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        now = datetime.now(timezone.utc)
        keep = ub.KoboReadingState(user_id=USER, book_id=WINNER)
        keep.current_bookmark = ub.KoboBookmark(progress_percent=80.0)
        stale = ub.KoboReadingState(user_id=USER, book_id=LOSER)
        stale.current_bookmark = ub.KoboBookmark(progress_percent=10.0)
        session.add_all([keep, stale])
        session.commit()
        _set_state_timestamps(session, ub, {WINNER: now, LOSER: now - timedelta(days=2)})

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        state = session.query(ub.KoboReadingState).one()
        assert state.book_id == WINNER
        assert state.current_bookmark.progress_percent == 80.0
        assert session.query(ub.KoboBookmark).count() == 1

    def test_read_book_merge_keeps_furthest_status(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        session.add_all([
            ub.ReadBook(user_id=USER, book_id=WINNER,
                        read_status=ub.ReadBook.STATUS_IN_PROGRESS, times_started_reading=1),
            ub.ReadBook(user_id=USER, book_id=LOSER,
                        read_status=ub.ReadBook.STATUS_FINISHED, times_started_reading=3),
        ])
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        rb = session.query(ub.ReadBook).one()
        assert rb.book_id == WINNER
        assert rb.read_status == ub.ReadBook.STATUS_FINISHED
        assert rb.times_started_reading == 4

    def test_shelf_membership_repointed_unless_already_on_shelf(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        _shelf_link(session, ub, LOSER, 1, 5)      # winner not on shelf 1
        _shelf_link(session, ub, LOSER, 2, 1)      # clash on shelf 2
        _shelf_link(session, ub, WINNER, 2, 9)
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        links = session.query(ub.BookShelf).order_by(ub.BookShelf.shelf).all()
        assert [(l.shelf, l.book_id, l.order) for l in links] == [(1, WINNER, 5), (2, WINNER, 9)]

    def test_kobo_synced_marker_dropped_not_migrated(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        session.add(ub.KoboSyncedBooks(user_id=USER, book_id=LOSER))
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        # the marker means "this file was delivered" — the kept book is a
        # different file, so it must sync fresh, not inherit the marker.
        assert session.query(ub.KoboSyncedBooks).count() == 0

    def test_simple_flags_migrate_and_dedupe(self, session):
        from cps import ub
        from cps.user_book_data import migrate_user_book_data
        session.add_all([
            ub.ArchivedBook(user_id=USER, book_id=LOSER, is_archived=True),
            ub.Downloads(user_id=USER, book_id=LOSER),
            ub.Downloads(user_id=USER, book_id=WINNER),  # clash → loser row dropped
        ])
        session.commit()

        migrate_user_book_data(LOSER, WINNER, session=session)
        session.commit()

        assert session.query(ub.ArchivedBook).one().book_id == WINNER
        downloads = session.query(ub.Downloads).all()
        assert len(downloads) == 1 and downloads[0].book_id == WINNER


@pytest.mark.unit
class TestPurge:
    def _populate(self, session, ub):
        ann = _annotation(ub, LOSER)
        ann.sync_targets.append(ub.AnnotationSyncTarget(target="hardcover", status="synced"))
        state = ub.KoboReadingState(user_id=USER, book_id=LOSER)
        state.current_bookmark = ub.KoboBookmark(progress_percent=10.0)
        state.statistics = ub.KoboStatistics(spent_reading_minutes=5)
        session.add_all([
            ann, state,
            ub.ReadBook(user_id=USER, book_id=LOSER, read_status=1),
            ub.Bookmark(user_id=USER, book_id=LOSER, format="EPUB", bookmark_key="k"),
            ub.ArchivedBook(user_id=USER, book_id=LOSER, is_archived=False),
            ub.Downloads(user_id=USER, book_id=LOSER),
            ub.KoboSyncedBooks(user_id=USER, book_id=LOSER),
        ])
        _shelf_link(session, ub, LOSER, 1, 1)
        session.commit()

    def test_purge_by_book_removes_everything_for_all_users(self, session):
        from cps import ub
        from cps.user_book_data import purge_user_book_data
        self._populate(session, ub)

        purge_user_book_data(book_id=LOSER, session=session, remove_backup_files=False)
        session.commit()

        for model in (ub.Annotation, ub.AnnotationSyncTarget, ub.KoboReadingState,
                      ub.KoboBookmark, ub.KoboStatistics, ub.ReadBook, ub.Bookmark,
                      ub.ArchivedBook, ub.Downloads, ub.BookShelf, ub.KoboSyncedBooks):
            assert session.query(model).count() == 0, model.__name__

    def test_purge_by_book_leaves_other_books_alone(self, session):
        from cps import ub
        from cps.user_book_data import purge_user_book_data
        self._populate(session, ub)
        session.add(_annotation(ub, WINNER, annotation_id="ann-other"))
        session.commit()

        purge_user_book_data(book_id=LOSER, session=session, remove_backup_files=False)
        session.commit()

        assert session.query(ub.Annotation).one().book_id == WINNER

    def test_purge_by_user_removes_backup_files_on_disk(self, session, tmp_path):
        from cps import ub
        from cps.user_book_data import purge_user_book_data
        gz = tmp_path / "snapshot.json.gz"
        gz.write_bytes(b"x")
        session.add_all([
            _annotation(ub, LOSER),
            ub.KoboAnnotationBackup(user_id=USER, book_id=LOSER, content_hash="h",
                                    file_path=str(gz), size_bytes=1, annotation_count=1),
            _annotation(ub, LOSER, annotation_id="ann-keep", user_id=USER + 1),
        ])
        session.commit()

        purge_user_book_data(user_id=USER, session=session)
        session.commit()

        assert not gz.exists(), "backup gzip (PII) must be removed with the user"
        assert session.query(ub.KoboAnnotationBackup).count() == 0
        remaining = session.query(ub.Annotation).one()
        assert remaining.user_id == USER + 1, "other users' annotations untouched"

    def test_purge_by_user_does_not_touch_shelf_links(self, session):
        from cps import ub
        from cps.user_book_data import purge_user_book_data
        # BookShelf has no user column — shelf membership belongs to the
        # shelf (handled by the user-delete path via the user's shelves).
        _shelf_link(session, ub, LOSER, 1, 1)
        session.commit()

        purge_user_book_data(user_id=USER, session=session)
        session.commit()

        assert session.query(ub.BookShelf).count() == 1

    def test_book_purge_can_retain_backup_snapshots(self, session, tmp_path):
        from cps import ub
        from cps.user_book_data import purge_user_book_data
        gz = tmp_path / "snapshot.json.gz"
        gz.write_bytes(b"x")
        session.add(ub.KoboAnnotationBackup(user_id=USER, book_id=LOSER, content_hash="h",
                                            file_path=str(gz), size_bytes=1, annotation_count=1))
        session.commit()

        purge_user_book_data(book_id=LOSER, session=session, remove_backup_files=False)
        session.commit()

        assert gz.exists()
        assert session.query(ub.KoboAnnotationBackup).count() == 1, (
            "remove_backup_files=False keeps the recovery snapshots indexed"
        )


@pytest.mark.unit
class TestCallSitesPinned:
    """The four enumeration sites must go through the helpers — RED on main."""

    def test_resolution_loop_migrates_user_data_before_delete(self):
        src = (REPO / "cps" / "duplicates.py").read_text(encoding="utf-8")
        body = src.split("def auto_resolve_duplicates", 1)[1].split("\ndef ", 1)[0]
        migrate = body.find("migrate_user_book_data(deleted_book_id, book_to_keep_id)")
        delete = body.find("delete_whole_book(deleted_book_id, book)")
        assert migrate != -1, (
            "resolving a duplicate must migrate per-user data (annotations, "
            "progress, shelves) to the kept book for EVERY strategy — D4 data loss"
        )
        assert delete != -1 and migrate < delete, (
            "migration must happen BEFORE the loser is deleted"
        )

    def test_delete_whole_book_purges_via_helper(self):
        src = (REPO / "cps" / "editbooks.py").read_text(encoding="utf-8")
        body = src.split("def delete_whole_book", 1)[1].split("\ndef ", 1)[0]
        assert "purge_user_book_data(book_id=book_id" in body
        for stale in ("ub.session.query(ub.BookShelf)", "ub.session.query(ub.ReadBook)",
                      "ub.session.query(ub.ArchivedBook)", "ub.delete_download("):
            assert stale not in body, f"hand-list remnant in delete_whole_book: {stale}"

    def test_admin_db_change_wipe_purges_via_helper(self):
        src = (REPO / "cps" / "admin.py").read_text(encoding="utf-8")
        idx = src.find("Calibre Database changed")
        block = src[idx:idx + 800]
        assert "purge_user_book_data()" in block
        assert "ub.session.query(ub.Downloads).delete()" not in block

    def test_admin_user_delete_purges_via_helper(self):
        src = (REPO / "cps" / "admin.py").read_text(encoding="utf-8")
        body = src.split("def _delete_user", 1)[1].split("\ndef ", 1)[0]
        assert "purge_user_book_data(user_id=content.id)" in body
        for stale in ("ub.ReadBook.user_id", "ub.Bookmark.user_id",
                      "ub.KoboSyncedBooks.user_id", "ub.KoboReadingState.user_id"):
            assert stale not in body, f"hand-list remnant in _delete_user: {stale}"
