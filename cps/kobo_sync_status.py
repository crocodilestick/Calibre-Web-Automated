# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from datetime import datetime, timezone

from sqlalchemy.sql.expression import and_

from .cw_login import current_user
from . import ub, calibre_db, db
from . import logger


log = logger.create()


def _is_book_on_any_kobo_shelf(book_id, user_id, session):
    """Return True if book_id is on at least one kobo_sync=True shelf for user_id."""
    return session.query(ub.BookShelf).join(
        ub.Shelf, ub.Shelf.id == ub.BookShelf.shelf
    ).filter(
        ub.BookShelf.book_id == book_id,
        ub.Shelf.user_id == int(user_id),
        ub.Shelf.kobo_sync == True,
    ).first() is not None


def set_kobo_visibility(book_ids, user_id, is_visible, session=None):
    """Bulk-set is_visible for a list of books without rechecking shelf membership.

    Use when the visibility value is already known (e.g., book just added to a
    kobo shelf → True; confirmed not on any shelf after removal → False).
    Only rows where is_visible actually changes get a new last_modified so the
    sync cursor only fires for genuine state transitions.
    """
    if not book_ids:
        return
    s = session or ub.session
    now = datetime.now(timezone.utc)
    book_ids = list(book_ids)

    existing = {r.book_id: r for r in s.query(ub.KoboBookVisibility).filter(
        ub.KoboBookVisibility.user_id == int(user_id),
        ub.KoboBookVisibility.book_id.in_(book_ids),
    ).all()}

    for bid in book_ids:
        if bid in existing:
            row = existing[bid]
            if row.is_visible == is_visible:
                continue
            row.is_visible = is_visible
            row.last_modified = now
        else:
            s.add(ub.KoboBookVisibility(
                user_id=int(user_id), book_id=bid,
                is_visible=is_visible, last_modified=now,
            ))

    if session is None:
        ub.session_commit()
    else:
        ub.session_commit(_session=session)


def recompute_kobo_visibility(book_ids, user_id, session=None, force_visible=None):
    """Recompute is_visible for each book by querying current kobo shelf membership.

    Use when a book was removed from a shelf: it might still be on another
    kobo-sync shelf, so we can't assume is_visible=False.  Issues two bulk
    queries regardless of how many books are in the list.
    """
    if not book_ids:
        return
    s = session or ub.session
    now = datetime.now(timezone.utc)
    book_ids = list(book_ids)

    # Single query: which of these books are still on any kobo-sync shelf?
    still_visible = {r.book_id for r in s.query(ub.BookShelf.book_id).join(
        ub.Shelf, ub.Shelf.id == ub.BookShelf.shelf
    ).filter(
        ub.BookShelf.book_id.in_(book_ids),
        ub.Shelf.user_id == int(user_id),
        ub.Shelf.kobo_sync == True,
    ).all()}

    existing = {r.book_id: r for r in s.query(ub.KoboBookVisibility).filter(
        ub.KoboBookVisibility.user_id == int(user_id),
        ub.KoboBookVisibility.book_id.in_(book_ids),
    ).all()}

    for bid in book_ids:
        vis = bid in still_visible or (force_visible is not None and bid in force_visible)
        if bid in existing:
            row = existing[bid]
            if row.is_visible == vis:
                continue
            row.is_visible = vis
            row.last_modified = now
        else:
            s.add(ub.KoboBookVisibility(
                user_id=int(user_id), book_id=bid,
                is_visible=vis, last_modified=now,
            ))

    if session is None:
        ub.session_commit()
    else:
        ub.session_commit(_session=session)


def change_archived_books(book_id, state=None, message=None):
    archived_book = ub.session.query(ub.ArchivedBook).filter(and_(
        ub.ArchivedBook.user_id == int(current_user.id),
        ub.ArchivedBook.book_id == book_id,
    )).first()
    if not archived_book:
        archived_book = ub.ArchivedBook(user_id=current_user.id, book_id=book_id)

    archived_book.is_archived = state if state else not archived_book.is_archived
    archived_book.last_modified = datetime.now(timezone.utc)

    ub.session.merge(archived_book)
    ub.session_commit(message)
    return archived_book.is_archived


def on_sync_shelves_disabled(user_id):
    """Called when kobo_only_shelves_sync is turned OFF (ON→OFF).

    All non-archived books become visible regardless of shelf membership.
    Writes KBV rows surgically so only books whose visibility actually changes
    get a new last_modified, keeping the sync window tight.
    """
    all_book_ids = [r for r, in calibre_db.session.query(db.Books.id).all()]
    set_kobo_visibility(all_book_ids, user_id, is_visible=True)


def update_on_sync_shelfs(user_id):
    """Called when kobo_only_shelves_sync is turned ON (OFF→ON).

    Recomputes KBV visibility for every book based on current kobo-sync shelf
    membership.  Books no longer on any kobo shelf get is_visible=False with a
    fresh last_modified so the device sees them disappear on the next sync.
    Non-kobo shelves are also archived from the device's collection list.
    """
    all_book_ids = [r for r, in calibre_db.session.query(db.Books.id).all()]
    recompute_kobo_visibility(all_book_ids, user_id)

    shelves_to_archive = ub.session.query(ub.Shelf).filter(
        ub.Shelf.user_id == int(user_id),
        ub.Shelf.kobo_sync == 0,
    ).all()
    for shelf in shelves_to_archive:
        ub.session.add(ub.ShelfArchive(uuid=shelf.uuid, user_id=user_id))
        ub.session_commit()
