# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Single source of truth for per-user-book rows in app.db.

Several places need to enumerate "every app.db row that ties a user to a
book": deleting a book, merging a duplicate into the kept copy, switching
the Calibre database, deleting a user. Historically each site kept its own
hand-written list and the lists disagreed — the duplicate merge moved only
file formats (orphaning the user's annotations, reading progress and shelf
membership), the database-change wipe missed annotations entirely, and the
per-user delete left the user's annotation rows and on-disk backup files
behind.

These two functions are the ONLY place that set is enumerated:

* :func:`migrate_user_book_data` — re-point/merge everything from a book
  that is about to be deleted (a duplicate-merge loser) onto the kept book.
* :func:`purge_user_book_data` — delete everything for a book and/or user.

Neither commits; the caller owns the transaction. When adding a new
per-user-book model to ``cps/ub.py``, add it here (the test suite pins the
enumeration against the model registry).
"""

import os

from . import logger, ub

log = logger.create()


def _newer(a, b):
    """True if datetime ``a`` is strictly newer than ``b``. Tolerates None and
    the naive/aware mix SQLite round-trips produce (columns are stored
    naive; fresh ORM defaults are timezone-aware)."""
    if a is None:
        return False
    if b is None:
        return True
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    return a > b

# Models keyed (user_id, book_id) handled by this module, with merge
# semantics for migrate. BookShelf has no user_id (shelf-scoped) and
# KoboBookmark/KoboStatistics/AnnotationSyncTarget are children reached
# through their parents; all are still handled below.
PER_USER_BOOK_MODELS = (
    "Annotation",            # + AnnotationSyncTarget children
    "Bookmark",
    "ReadBook",
    "KoboReadingState",      # + KoboBookmark/KoboStatistics children
    "KoboAnnotationBackup",  # + on-disk .json.gz snapshots
    "Downloads",
    "ArchivedBook",
    "BookShelf",             # shelf-scoped, no user_id column
    "KoboSyncedBooks",
    "UserHiddenBook",
    "BookCoverPreview",
)


def migrate_user_book_data(from_book_id, to_book_id, session=None):
    """Move all per-user-book rows from ``from_book_id`` to ``to_book_id``.

    Used by the duplicate merge before the losing book is deleted, so the
    user's annotations, reading progress, shelf membership etc. survive on
    the kept copy. Where the kept book already has a row for the same user
    (UNIQUE constraints on most of these tables), the two are merged rather
    than blindly re-pointed. Does not commit.
    """
    session = session if session is not None else ub.session
    if from_book_id == to_book_id:
        return

    # Annotations: re-point, but a user may already have the same
    # annotation_id on the kept book (e.g. the device synced both copies) —
    # there only the loser row is dropped (ORM delete so sync-target
    # children go with it).
    for ann in session.query(ub.Annotation).filter(
            ub.Annotation.book_id == from_book_id).all():
        clash = session.query(ub.Annotation).filter(
            ub.Annotation.user_id == ann.user_id,
            ub.Annotation.annotation_id == ann.annotation_id,
            ub.Annotation.book_id == to_book_id).first()
        if clash is not None:
            # sync_targets declares passive_deletes=True (expects DB-level
            # ON DELETE CASCADE), but SQLite FK enforcement is off — delete
            # the children explicitly.
            session.query(ub.AnnotationSyncTarget).filter(
                ub.AnnotationSyncTarget.annotation_id == ann.id).delete(
                synchronize_session=False)
            session.delete(ann)
        else:
            ann.book_id = to_book_id
    session.flush()

    # Kobo reading state: UNIQUE(user_id, book_id). If both books have a
    # state for the same user, the most recently modified one wins; ORM
    # deletes so the bookmark/statistics children follow.
    for state in session.query(ub.KoboReadingState).filter(
            ub.KoboReadingState.book_id == from_book_id).all():
        existing = session.query(ub.KoboReadingState).filter(
            ub.KoboReadingState.user_id == state.user_id,
            ub.KoboReadingState.book_id == to_book_id).first()
        if existing is None:
            state.book_id = to_book_id
        elif _newer(state.last_modified, existing.last_modified):
            session.delete(existing)
            session.flush()  # clear the UNIQUE slot before re-pointing
            state.book_id = to_book_id
        else:
            session.delete(state)
    session.flush()

    # ReadBook: UNIQUE(user_id, book_id); merge keeps the further-along
    # read status. Bulk delete (no ORM cascade) — the loser's
    # KoboReadingState was already merged above.
    _READ_RANK = {ub.ReadBook.STATUS_UNREAD: 0,
                  ub.ReadBook.STATUS_IN_PROGRESS: 1,
                  ub.ReadBook.STATUS_FINISHED: 2}
    for rb in session.query(ub.ReadBook).filter(
            ub.ReadBook.book_id == from_book_id).all():
        existing = session.query(ub.ReadBook).filter(
            ub.ReadBook.user_id == rb.user_id,
            ub.ReadBook.book_id == to_book_id).first()
        if existing is None:
            session.query(ub.ReadBook).filter(ub.ReadBook.id == rb.id).update(
                {ub.ReadBook.book_id: to_book_id}, synchronize_session=False)
        else:
            if _READ_RANK.get(rb.read_status, 0) > _READ_RANK.get(existing.read_status, 0):
                existing.read_status = rb.read_status
            existing.times_started_reading = \
                (existing.times_started_reading or 0) + (rb.times_started_reading or 0)
            if _newer(rb.last_time_started_reading, existing.last_time_started_reading):
                existing.last_time_started_reading = rb.last_time_started_reading
            session.query(ub.ReadBook).filter(ub.ReadBook.id == rb.id).delete(
                synchronize_session=False)
    session.flush()

    # Bookmark (reader position, per user+format): keep the kept book's own
    # position where one exists.
    for bm in session.query(ub.Bookmark).filter(
            ub.Bookmark.book_id == from_book_id).all():
        clash = session.query(ub.Bookmark).filter(
            ub.Bookmark.user_id == bm.user_id,
            ub.Bookmark.book_id == to_book_id,
            ub.Bookmark.format == bm.format).first()
        if clash is not None:
            session.delete(bm)
        else:
            bm.book_id = to_book_id

    # Shelf membership: re-point unless the kept book is already on that
    # shelf (keeps the existing position there).
    for link in session.query(ub.BookShelf).filter(
            ub.BookShelf.book_id == from_book_id).all():
        clash = session.query(ub.BookShelf).filter(
            ub.BookShelf.book_id == to_book_id,
            ub.BookShelf.shelf == link.shelf).first()
        if clash is not None:
            session.delete(link)
        else:
            link.book_id = to_book_id

    # Simple UNIQUE(user, book) flags: keep the kept book's row on clash.
    for model in (ub.ArchivedBook, ub.Downloads, ub.UserHiddenBook,
                  ub.BookCoverPreview):
        for row in session.query(model).filter(model.book_id == from_book_id).all():
            clash = session.query(model).filter(
                model.user_id == row.user_id,
                model.book_id == to_book_id).first()
            if clash is not None:
                session.delete(row)
            else:
                row.book_id = to_book_id
    session.flush()

    # Annotation backup snapshots index: re-point so retention keeps
    # managing them; the gzip files referenced by file_path stay valid.
    session.query(ub.KoboAnnotationBackup).filter(
        ub.KoboAnnotationBackup.book_id == from_book_id).update(
        {ub.KoboAnnotationBackup.book_id: to_book_id}, synchronize_session=False)

    # KoboSyncedBooks marks "this book's file already delivered to this
    # device". The kept book's file is a different file, so the marker must
    # NOT migrate — drop it and let the next sync deliver the kept copy.
    session.query(ub.KoboSyncedBooks).filter(
        ub.KoboSyncedBooks.book_id == from_book_id).delete(synchronize_session=False)

    session.flush()
    log.info("[user-book-data] migrated per-user data from book %s to book %s",
             from_book_id, to_book_id)


def purge_user_book_data(book_id=None, user_id=None, session=None,
                         remove_backup_files=True):
    """Delete every per-user-book row matching ``book_id`` and/or ``user_id``.

    With only ``book_id``: a book is being deleted (every user's rows go).
    With only ``user_id``: a user is being deleted (their rows for every
    book go, including on-disk annotation-backup files — PII).
    With neither: the Calibre database was swapped out; everything goes.

    ``remove_backup_files=False`` leaves the annotation-backup index rows
    and their gzip snapshots in place (the recovery path for an accidental
    book delete — retention keeps managing them). Does not commit.
    """
    session = session if session is not None else ub.session

    def _scoped(query, model):
        if book_id is not None:
            query = query.filter(model.book_id == book_id)
        if user_id is not None:
            query = query.filter(model.user_id == user_id)
        return query

    # Annotations: delete sync-target children first (bulk deletes bypass
    # ORM cascade, and SQLite FK enforcement can't be relied on).
    ann_ids = _scoped(session.query(ub.Annotation.id), ub.Annotation)
    session.query(ub.AnnotationSyncTarget).filter(
        ub.AnnotationSyncTarget.annotation_id.in_(
            ann_ids.scalar_subquery())).delete(synchronize_session=False)
    _scoped(session.query(ub.Annotation), ub.Annotation).delete(
        synchronize_session=False)

    # Kobo reading state + children.
    krs_ids = _scoped(session.query(ub.KoboReadingState.id), ub.KoboReadingState)
    for child in (ub.KoboBookmark, ub.KoboStatistics):
        session.query(child).filter(
            child.kobo_reading_state_id.in_(
                krs_ids.scalar_subquery())).delete(synchronize_session=False)
    _scoped(session.query(ub.KoboReadingState), ub.KoboReadingState).delete(
        synchronize_session=False)

    for model in (ub.Bookmark, ub.ReadBook, ub.ArchivedBook, ub.Downloads,
                  ub.KoboSyncedBooks, ub.UserHiddenBook, ub.BookCoverPreview):
        _scoped(session.query(model), model).delete(synchronize_session=False)

    # BookShelf has no user_id — shelf membership is shelf-scoped, and the
    # user-delete path removes the user's shelves (with their links)
    # separately. Only book-scoped (and full) purges touch it.
    if user_id is None:
        query = session.query(ub.BookShelf)
        if book_id is not None:
            query = query.filter(ub.BookShelf.book_id == book_id)
        query.delete(synchronize_session=False)

    if remove_backup_files:
        backups = _scoped(session.query(ub.KoboAnnotationBackup),
                          ub.KoboAnnotationBackup).all()
        for row in backups:
            try:
                if row.file_path and os.path.isfile(row.file_path):
                    os.remove(row.file_path)
            except OSError as e:
                log.warning("[user-book-data] could not remove annotation "
                            "backup %s: %s", row.file_path, e)
            session.delete(row)

    session.flush()
    log.info("[user-book-data] purged per-user data (book_id=%s, user_id=%s)",
             book_id, user_id)
