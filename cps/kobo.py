#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import base64
import logging
from datetime import datetime, timezone
from cps import cw_babel
from kobo_sync_utils import get_kobo_created_ts
import os
import uuid
import zipfile
from time import gmtime, strftime
import json
from urllib.parse import unquote

from flask import (
    Blueprint,
    request,
    make_response,
    jsonify,
    current_app,
    url_for,
    redirect,
    abort,
    Response,
    send_from_directory,
    g,
)
from .cw_login import current_user
from werkzeug.datastructures import Headers
from sqlalchemy import func
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import select
import requests

from . import config, logger, kobo_auth, db, calibre_db, helper, shelf as shelf_lib, ub, csrf, kobo_sync_status, magic_shelf
from . import isoLanguages
from .epub import get_epub_layout
from .constants import COVER_THUMBNAIL_SMALL, COVER_THUMBNAIL_MEDIUM, COVER_THUMBNAIL_LARGE, CACHE_TYPE_THUMBNAILS
from .kobo_cover_cache import build_cover_image_id, normalize_cover_uuid
from .helper import get_download_link
from .services import SyncToken as SyncToken, hardcover
from .services import cover_preview
from .fs import FileSystem
from .web import download_required
from .kobo_auth import requires_kobo_auth, get_auth_token

KOBO_FORMATS = {"KEPUB": ["KEPUB"], "EPUB": ["EPUB3", "EPUB"]}
KOBO_STOREAPI_URL = "https://storeapi.kobo.com"
KOBO_IMAGEHOST_URL = "https://cdn.kobo.com/book-images"

SYNC_ITEM_LIMIT = 100

kobo = Blueprint("kobo", __name__, url_prefix="/kobo/<auth_token>")
kobo_auth.disable_failed_auth_redirect_for_blueprint(kobo)
kobo_auth.register_url_value_preprocessor(kobo)

log = logger.create()


def get_store_url_for_current_request():
    # Programmatically modify the current url to point to the official Kobo store
    __, __, request_path_with_auth_token = request.full_path.rpartition("/kobo/")
    __, __, request_path = request_path_with_auth_token.rstrip("?").partition(
        "/"
    )
    return KOBO_STOREAPI_URL + "/" + request_path


CONNECTION_SPECIFIC_HEADERS = [
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
]


def get_kobo_activated():
    return config.config_kobo_sync


def make_request_to_kobo_store(sync_token=None):
    outgoing_headers = Headers(request.headers)
    outgoing_headers.remove("Host")
    if sync_token:
        sync_token.set_kobo_store_header(outgoing_headers)

    store_response = requests.request(
        method=request.method,
        url=get_store_url_for_current_request(),
        headers=outgoing_headers,
        data=request.get_data(),
        allow_redirects=False,
        timeout=(2, 10)
    )
    log.debug("Content: " + str(store_response.content))
    log.debug("StatusCode: " + str(store_response.status_code))
    return store_response


def redirect_or_proxy_request():
    if config.config_kobo_proxy:
        if request.method == "GET":
            return redirect(get_store_url_for_current_request(), 307)
        else:
            # The Kobo device turns other request types into GET requests on redirects,
            # so we instead proxy to the Kobo store ourselves.
            store_response = make_request_to_kobo_store()

            return make_proxy_response(store_response)
    else:
        return make_response(jsonify({}))


def make_proxy_response(store_response: requests.Response) -> Response:
    response_headers = store_response.headers
    for header_key in CONNECTION_SPECIFIC_HEADERS:
        response_headers.pop(header_key, default=None)

    return make_response(store_response.content, store_response.status_code, response_headers.items())


def convert_to_kobo_timestamp_string(timestamp):
    try:
        return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    except AttributeError as exc:
        log.debug("Timestamp not valid: {}".format(exc))
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_magic_shelf_book_ids_for_kobo(user_id):
    if not config.config_kobo_sync_magic_shelves:
        # Per-shelf kobo_sync intent with the global flag off is the #359
        # trap — surface it in debug logs so support can spot it instantly.
        # (A one-time boot migration enables the global flag where intent
        # already exists; this log covers shelves marked afterwards, e.g.
        # via API, while the flag is deliberately off.)
        if log.isEnabledFor(logging.DEBUG):
            swallowed = ub.session.query(ub.MagicShelf).filter_by(
                user_id=user_id, kobo_sync=True).count()
            if swallowed:
                log.debug(
                    "Kobo Sync: %s magic shelves are marked kobo_sync but the "
                    "global 'Sync Magic Shelves to Kobo' setting is off — not "
                    "delivering (#359)", swallowed)
        return set()

    magic_shelves = ub.session.query(ub.MagicShelf).filter_by(user_id=user_id, kobo_sync=True).all()
    if not magic_shelves:
        return set()

    book_ids = set()
    for shelf in magic_shelves:
        books, _ = magic_shelf.get_books_for_magic_shelf(
            shelf.id, page=1, page_size=None
        )
        for book in books:
            book_ids.add(book.id)

    if book_ids:
        log.debug("Kobo Sync: magic shelf allowed books: %s", len(book_ids))

    return book_ids


def get_magic_shelf_membership_added_at(user_id):
    """Return the most-recent MagicShelfCache.created_at across the user's
    kobo-sync magic shelves, or ``None`` if no cache rows exist.

    Plays the role ``BookShelf.date_added`` plays for regular shelves —
    a "membership added" timestamp that lets the sync cursor emit
    magic-shelf-only books once when the cache (re)builds, then fall
    out of the cursor on subsequent syncs.

    Returning ``None`` (rather than ``datetime.min``) lets the caller
    distinguish "no kobo-sync magic shelves at all" from "shelves
    exist but never cached" — the former should skip the magic-shelf
    arm entirely; the latter falls through to normal cursor behavior.
    """
    if not config.config_kobo_sync_magic_shelves:
        return None

    max_created_at = (
        ub.session.query(func.max(ub.MagicShelfCache.created_at))
        .join(ub.MagicShelf, ub.MagicShelf.id == ub.MagicShelfCache.shelf_id)
        .filter(ub.MagicShelf.user_id == user_id, ub.MagicShelf.kobo_sync == True)  # noqa: E712
        .scalar()
    )
    if max_created_at is None:
        return None
    if hasattr(max_created_at, "replace") and getattr(max_created_at, "tzinfo", None) is not None:
        max_created_at = max_created_at.replace(tzinfo=None)
    return max_created_at


@kobo.route("/v1/library/sync")
@requires_kobo_auth
# @download_required
def HandleSyncRequest():
    if not current_user.role_download():
        log.info("Users need download permissions for syncing library to Kobo reader")
        return abort(403)

    sync_token = SyncToken.SyncToken.from_headers(request.headers)
    log.info("Kobo library sync request received")
    log.debug("SyncToken: {}".format(sync_token))
    log.debug("Download link format {}".format(get_download_url_for_book('[bookid]', '[bookformat]')))
    if not current_app.wsgi_app.is_proxied:
        log.debug('Kobo: Received unproxied request, changed request port to external server port')

    # if no books synced don't respect sync_token
    if not ub.session.query(ub.KoboSyncedBooks).filter(ub.KoboSyncedBooks.user_id == current_user.id).count():
        sync_token.books_last_modified = datetime.min
        sync_token.books_last_created = datetime.min
        sync_token.reading_state_last_modified = datetime.min
        # Reset books_last_id alongside books_last_modified — with
        # cursor_lm = datetime.min the stale cursor_id is harmless, but
        # keeping the two cursor components consistent makes the keyset
        # behavior easier to reason about for future readers.
        sync_token.books_last_id = -1
        # Reset the magic-shelf sub-cursor too — a fresh-device sync
        # should re-deliver every magic book.
        sync_token.magic_shelf_last_id = -1
        # Reset the magic-shelf membership timestamp so the cache-rebuild
        # detection on the next sync treats the cache as fresh.
        sync_token.magic_shelf_membership_at = datetime.min

    new_books_last_modified = sync_token.books_last_modified  # needed for sync selected shelfs only
    new_books_last_created = sync_token.books_last_created  # needed to distinguish between new and changed entitlement
    new_reading_state_last_modified = sync_token.reading_state_last_modified

    new_archived_last_modified = datetime.min
    sync_results = []

    calibre_db.reconnect_db(config, ub.app_DB_path)


    # Magic-shelf book IDs + membership timestamp are computed for BOTH sync
    # modes (kobo_only_shelves_sync True AND False). Original v4.0.147 fix
    # gated the computation on kobo_only_shelves_sync — which left
    # @recruiterguy stuck: their user is in 'sync-all-library' mode (False),
    # so the cache never refreshed via this code path, the magic-shelf arm
    # never gained a fresh `created_at`, and magic-shelf-only books with
    # old `Books.last_modified` continued to be filtered out by the
    # else-branch cursor. Computing here forces the cache TTL re-evaluation
    # on every sync, regardless of mode.
    magic_shelf_book_ids = get_magic_shelf_book_ids_for_kobo(current_user.id)
    magic_shelf_membership_added_at = get_magic_shelf_membership_added_at(current_user.id)

    # Two-Way-Sync Deletion Logic (kobo_only_shelves_sync=True only — outer
    # membership filter is what drives the deletion detection)
    if current_user.kobo_only_shelves_sync:
        try:
            # Check all books that are on Kobo according to the database
            synced_books_query = ub.session.query(ub.KoboSyncedBooks.book_id).filter(ub.KoboSyncedBooks.user_id == current_user.id)
            synced_book_ids = {item.book_id for item in synced_books_query}

            # Check all books currently on a Kobo Sync shelf
            allowed_books_query = (ub.session.query(ub.BookShelf.book_id)
                                   .join(ub.Shelf, ub.BookShelf.shelf == ub.Shelf.id)
                                   .filter(ub.Shelf.user_id == current_user.id, ub.Shelf.kobo_sync == True))
            allowed_book_ids = {item.book_id for item in allowed_books_query}
            if magic_shelf_book_ids:
                allowed_book_ids |= magic_shelf_book_ids

            # Spot the difference: books that need to be deleted
            books_to_delete_ids = synced_book_ids - allowed_book_ids

            if books_to_delete_ids:
                log.info(f"Kobo Sync: Found {len(books_to_delete_ids)} books to remove from device for user {current_user.name}")

                # Go through the “To be deleted” list
                for book_id in books_to_delete_ids:
                    book = calibre_db.get_book(book_id)
                    if book:
                        # Create a “Remove” command for the Kobo
                        entitlement = {
                            "BookEntitlement": create_book_entitlement(book, archived=True),
                            "BookMetadata": get_metadata(book),
                        }
                        sync_results.append({"ChangedEntitlement": entitlement})

                # Remove all books from the tracking table in one go
                if books_to_delete_ids:
                    ub.session.query(ub.KoboSyncedBooks).filter(
                        ub.KoboSyncedBooks.user_id == current_user.id,
                        ub.KoboSyncedBooks.book_id.in_(books_to_delete_ids)
                    ).delete(synchronize_session=False)
                    ub.session_commit()

        except Exception as e:
            log.error(f"Kobo Sync: Error during deletion logic: {e}")
            ub.session.rollback()

    only_kobo_shelves = current_user.kobo_only_shelves_sync

    log.debug("Kobo Sync: books last modified: {}".format(sync_token.books_last_modified))

    rstate_join = and_(
        db.Books.id == ub.KoboReadingState.book_id,
        ub.KoboReadingState.user_id == current_user.id,
    )
    # Composite-keyset cursor: filter rows after (books_last_modified, books_last_id)
    # in lexicographic order. This walks paginated batches through blocks of books
    # that share one last_modified (fork #347 — 4458 books all stamped one second
    # in a bulk import; the timestamp-only cursor either re-sent the same first
    # SYNC_ITEM_LIMIT forever or skipped the remainder). For pre-upgrade tokens
    # books_last_id defaults to -1, so the keyset arm 'id > -1' is True for every
    # valid book id and no books at exactly books_last_modified are dropped on
    # the first post-upgrade sync.
    cursor_lm = sync_token.books_last_modified
    cursor_id = sync_token.books_last_id
    composite_keyset_books_only = or_(
        db.Books.last_modified > cursor_lm,
        and_(db.Books.last_modified == cursor_lm, db.Books.id > cursor_id),
    )

    # Magic-shelf membership arm (fork #359): magic-shelf-only books are not in
    # book_shelf_link, so BookShelf.date_added is NULL and Books.last_modified is
    # usually in the past — the standard cursor arms filter them out before the
    # outer (kobo_sync shelf OR magic-shelf) membership filter is evaluated, and
    # they never reach the device. The cache row's created_at is the membership
    # timestamp: when the cache (re)builds, emit all magic-shelf books once;
    # cursor then advances past created_at and the arm goes False so the device
    # doesn't re-emit (the #213 termination guard, preserved structurally).
    #
    # The arm fires for BOTH kobo_only_shelves_sync modes — in 'sync-all'
    # mode the outer membership filter doesn't apply, but the inner cursor
    # would still filter magic-shelf-only books out because their
    # Books.last_modified is in the past relative to the device cursor.
    # @recruiterguy's v4.0.147 verification showed this gap concretely.
    magic_shelf_arm_active = bool(
        magic_shelf_book_ids
        and magic_shelf_membership_added_at is not None
        and magic_shelf_membership_added_at > cursor_lm
    )

    # Magic-shelf SUB-CURSOR: the bare `id IN magic_shelf_book_ids` arm is
    # cursor-unaware — for magic shelves with >= SYNC_ITEM_LIMIT books, it
    # emits the same first SYNC_ITEM_LIMIT ids every round (Greptile P1 on
    # PR #366). Filtering `id > magic_shelf_last_id` walks the arm via a
    # second-tier keyset across batches.
    #
    # CRITICAL: when the cache is rebuilt (membership_added_at advances
    # past the last-recorded membership_at on the token), reset the
    # sub-cursor to -1 so the next walk starts from id=0. Without this
    # reset, a user who adds a low-id book to the shelf after a sync
    # ended at a high magic_shelf_last_id would see the new book
    # filtered out by `id > magic_shelf_last_id`; the fold then fires
    # on an empty batch, advances cursor past the new T_magic, and the
    # book stays undelivered until ANOTHER cache rebuild happens
    # (Greptile P on PR #367 v4.0.153).
    if (
        magic_shelf_membership_added_at is not None
        and magic_shelf_membership_added_at > sync_token.magic_shelf_membership_at
    ):
        magic_shelf_last_id = -1
    else:
        magic_shelf_last_id = sync_token.magic_shelf_last_id

    magic_shelf_arm = and_(
        db.Books.id.in_(magic_shelf_book_ids),
        db.Books.id > magic_shelf_last_id,
    )

    # only_kobo_shelves branch joins BookShelf, so its inner filter includes
    # the BookShelf.date_added arm (fork #220) alongside the composite keyset
    # and (when active) the magic-shelf membership arm.
    if magic_shelf_arm_active:
        inner_cursor_filter_with_bookshelf = or_(
            ub.BookShelf.date_added > cursor_lm,
            composite_keyset_books_only,
            magic_shelf_arm,
        )
    else:
        inner_cursor_filter_with_bookshelf = or_(
            ub.BookShelf.date_added > cursor_lm,
            composite_keyset_books_only,
        )

    # else branch does not join BookShelf — drop the date_added arm but keep
    # the composite keyset + magic-shelf arm (when active). This is what
    # closes the @recruiterguy gap: in sync-all mode, magic-shelf-only books
    # with old Books.last_modified still get through the inner cursor via
    # the third arm.
    if magic_shelf_arm_active:
        inner_cursor_filter_sync_all = or_(
            composite_keyset_books_only,
            magic_shelf_arm,
        )
    else:
        inner_cursor_filter_sync_all = composite_keyset_books_only

    if only_kobo_shelves:
        changed_entries = calibre_db.session.query(db.Books,
                                                   ub.ArchivedBook.last_modified,
                                                   ub.BookShelf.date_added,
                                                   ub.ArchivedBook.is_archived,
                                                   ub.KoboReadingState)
        # Per-device sync state lives in the `x-kobo-synctoken` cursor
        # (the last_modified comparisons below). Don't filter by
        # KoboSyncedBooks here — that table is user-keyed, so it would
        # lock additional devices on the same user out of receiving
        # books another device already synced.
        #
        # Magic-shelf membership is enforced by the OUTER filter
        # (kobo_sync shelf OR magic-shelf) further down. The INNER
        # cursor includes a magic-shelf arm ONLY when the cache was
        # (re)built after the device's cursor, then advances cursor
        # past the cache's created_at — same termination guarantee as
        # #213 (cont_sync goes False once the cache stops moving) but
        # without the original "infinite loop" failure mode.
        changed_entries = (changed_entries
                           .join(db.Data).outerjoin(ub.ArchivedBook, and_(db.Books.id == ub.ArchivedBook.book_id,
                                                                          ub.ArchivedBook.user_id == current_user.id))
                           .outerjoin(ub.KoboReadingState, rstate_join)
                           .filter(inner_cursor_filter_with_bookshelf)
                           .filter(db.Data.format.in_(KOBO_FORMATS))
                           .filter(calibre_db.common_filters(allow_show_archived=True))
                           .order_by(db.Books.last_modified)
                           .order_by(db.Books.id)
                           .outerjoin(ub.BookShelf, db.Books.id == ub.BookShelf.book_id)
                           .outerjoin(ub.Shelf, ub.Shelf.id == ub.BookShelf.shelf)
                           .filter(or_(
                               and_(ub.Shelf.user_id == current_user.id, ub.Shelf.kobo_sync == True),
                               db.Books.id.in_(magic_shelf_book_ids) if magic_shelf_book_ids else False
                           ))
                           .options(joinedload(db.Books.authors),
                                    joinedload(db.Books.publishers),
                                    joinedload(db.Books.series),
                                    joinedload(db.Books.languages),
                                    joinedload(db.Books.comments),
                                    joinedload(db.Books.data))
                           .distinct())
    else:
        changed_entries = calibre_db.session.query(db.Books,
                                                   ub.ArchivedBook.last_modified,
                                                   ub.ArchivedBook.is_archived,
                                                   ub.KoboReadingState)
        # Same per-device cursor invariant as the shelf branch above:
        # don't filter by KoboSyncedBooks (user-keyed, breaks multi-device).
        # The composite keyset (Books.last_modified, Books.id) is the per-device
        # throttle — without it, this branch returns every book on every sync
        # and keeps cont_sync True forever. The 'else' branch's SELECT does
        # not join BookShelf, so the date_added arm is dropped here. The
        # magic-shelf arm DOES participate (when active), letting magic-shelf
        # books with old Books.last_modified deliver in 'sync-all' mode too —
        # fixing the @recruiterguy regression in v4.0.147.
        changed_entries = (changed_entries
                           .join(db.Data).outerjoin(ub.ArchivedBook, and_(db.Books.id == ub.ArchivedBook.book_id,
                                                                          ub.ArchivedBook.user_id == current_user.id))
                           .outerjoin(ub.KoboReadingState, rstate_join)
                           .filter(inner_cursor_filter_sync_all)
                           .filter(calibre_db.common_filters(allow_show_archived=True))
                           .filter(db.Data.format.in_(KOBO_FORMATS))
                           .order_by(db.Books.last_modified)
                           .order_by(db.Books.id)
                           .options(joinedload(db.Books.authors),
                                    joinedload(db.Books.publishers),
                                    joinedload(db.Books.series),
                                    joinedload(db.Books.languages),
                                    joinedload(db.Books.comments),
                                    joinedload(db.Books.data)))
    log.debug("Kobo Sync: changed entries: {}".format(changed_entries.count()))

    reading_states_in_new_entitlements = []
    # Materialize the limited result set ONCE — the prior shape called .all()
    # twice (once for the debug log, once for the for-loop) which round-tripped
    # the joined-load query twice per sync request.
    books_list = changed_entries.limit(SYNC_ITEM_LIMIT).all()
    log.debug("Kobo Sync: selected to sync: {}".format(len(books_list)))
    for book in books_list:
        kobo_reading_state = book.KoboReadingState  # None when no record exists yet
        entitlement = {
            "BookEntitlement": create_book_entitlement(book.Books, archived=(book.is_archived==True)),
            "BookMetadata": get_metadata(book.Books),
        }

        if (kobo_reading_state is not None
                and kobo_reading_state.last_modified > sync_token.reading_state_last_modified):
            entitlement["ReadingState"] = get_kobo_reading_state_response(book.Books, kobo_reading_state)
            new_reading_state_last_modified = max(new_reading_state_last_modified, kobo_reading_state.last_modified)
            reading_states_in_new_entitlements.append(book.Books.id)

        ts_created = get_kobo_created_ts(book)

        if ts_created > sync_token.books_last_created:
            sync_results.append({"NewEntitlement": entitlement})
        else:
            sync_results.append({"ChangedEntitlement": entitlement})

        new_books_last_modified = max(
            book.Books.last_modified.replace(tzinfo=None), new_books_last_modified
        )

        # Also advance the cursor by BookShelf.date_added when the row
        # carries one (only_kobo_shelves branch selects it on line ~242).
        # The filter at line ~258-261 matches a book when EITHER
        # Books.last_modified OR BookShelf.date_added is past the
        # cursor. Without this max() the cursor only tracks
        # last_modified, so a book added to a kobo_sync shelf after its
        # own last_modified re-matches every sync and traps the device
        # in an infinite cont_sync loop (fork #220 — wire-confirmed
        # 112 syncs in 60s during the 2026-05-17 MITM capture). Guard
        # with getattr because the else branch's SELECT does not
        # include date_added.
        date_added = getattr(book, "date_added", None)
        if date_added is not None:
            if hasattr(date_added, "replace") and getattr(date_added, "tzinfo", None) is not None:
                date_added = date_added.replace(tzinfo=None)
            new_books_last_modified = max(date_added, new_books_last_modified)

        new_books_last_created = max(ts_created, new_books_last_created)
        kobo_sync_status.add_synced_books(book.Books.id)

    # Magic-shelf sub-cursor: advance to the highest magic-shelf book id
    # emitted this round. magic_shelf_book_ids may be empty when the arm
    # wasn't active, in which case the comprehension is empty and we keep
    # the existing sub-cursor unchanged.
    #
    # CRITICAL: source from the LOCAL magic_shelf_last_id (which may have
    # been reset to -1 by the cache-rebuild detection above), NOT from
    # sync_token.magic_shelf_last_id. Otherwise: when the first batch after
    # a cache rebuild contains no magic books (e.g. it's full of regular
    # books that sort before the magic ones), the rebuild reset is
    # silently overwritten by the old token value, the membership_at is
    # advanced to match, and subsequent syncs never re-trigger the rebuild
    # detection — leaving low-id magic books undelivered (Greptile P on
    # PR #368).
    magic_book_ids_emitted = [
        b.Books.id for b in books_list
        if magic_shelf_book_ids and b.Books.id in magic_shelf_book_ids
    ]
    if magic_book_ids_emitted:
        new_magic_shelf_last_id = max(magic_shelf_last_id,
                                       max(magic_book_ids_emitted))
    else:
        new_magic_shelf_last_id = magic_shelf_last_id

    # Composite-keyset cursor: keep books_last_id aligned with new_books_last_modified.
    # The query ORDER BY (last_modified, id) means books_list iteration is sorted, so
    # the last emitted row is the highest (last_modified, id) tuple in the batch.
    #   - If new_books_last_modified == that row's last_modified, store the row's id so
    #     the next sync's keyset arm `id > books_last_id` walks past it.
    #   - If new_books_last_modified got pushed past the batch's max ts (via the
    #     date_added fold from fork #220 or via the magic-shelf cache fold below),
    #     reset id to -1 — there are no books at the new ts in this batch, so any
    #     valid id passes the next sync's keyset arm.
    #   - If the batch was empty, keep the existing cursor id (no emission).
    if books_list:
        last_book = books_list[-1]
        last_book_lm = last_book.Books.last_modified
        if hasattr(last_book_lm, "replace") and getattr(last_book_lm, "tzinfo", None) is not None:
            last_book_lm = last_book_lm.replace(tzinfo=None)
        if new_books_last_modified == last_book_lm:
            new_books_last_id = last_book.Books.id
        else:
            new_books_last_id = -1
    else:
        new_books_last_id = sync_token.books_last_id

    # If the magic-shelf membership arm was active this round, advance the cursor
    # past the cache's created_at so the arm goes False next sync — same termination
    # guarantee as fork #213 (cont_sync goes False once cache.created_at stops
    # advancing), but without the original "infinite loop" failure mode. If the
    # cache.created_at advances cursor past the batch's max book ts, reset id to -1
    # (no books at the new ts in this batch).
    #
    # CRITICAL: only fire the fold when the batch is PARTIAL (len(books_list) <
    # SYNC_ITEM_LIMIT). Greptile-surfaced bug: when the batch is full, there may
    # be pending regular books whose Books.last_modified falls between the batch's
    # max_lm and magic_shelf_membership_added_at. Advancing the cursor to T_magic
    # silently drops them on every subsequent sync (their lm < cursor.lm, the
    # composite keyset fails, the magic-shelf arm gate goes False because cache
    # no longer > cursor). Deferring the fold until the batch is partial means
    # the next round walks the remaining ties via the composite keyset; the
    # magic-shelf arm continues to fire so already-emitted magic books re-emit
    # (idempotent on device — bandwidth waste only, no data loss). Once all
    # pending books are drained (batch < limit), the fold fires, cursor jumps
    # past T_magic, arm goes False, termination achieved.
    batch_drained = len(books_list) < SYNC_ITEM_LIMIT
    if magic_shelf_arm_active and batch_drained:
        if magic_shelf_membership_added_at > new_books_last_modified:
            new_books_last_modified = magic_shelf_membership_added_at
            new_books_last_id = -1
            # Cache-rebuild epoch closed — reset the sub-cursor so the next
            # rebuild (which advances cache.created_at > cursor.lm again)
            # starts walking the magic books from id=0.
            new_magic_shelf_last_id = -1
        elif magic_shelf_membership_added_at == new_books_last_modified and not books_list:
            # Cache rebuilt but no books actually changed past the old cursor — still
            # advance to prevent the arm from firing again (idempotent re-trigger).
            new_books_last_id = -1
            new_magic_shelf_last_id = -1

    max_change = changed_entries.filter(ub.ArchivedBook.is_archived)\
        .filter(ub.ArchivedBook.user_id == current_user.id) \
        .order_by(func.datetime(ub.ArchivedBook.last_modified).desc()).first()

    max_change = max_change.last_modified if max_change else new_archived_last_modified

    new_archived_last_modified = max(new_archived_last_modified, max_change)

    # no. of books returned
    book_count = changed_entries.count()
    # Mirror the reading-states branch below: only signal `continue` when
    # the result set exceeds the batch cap, so an exhaustive batch ends
    # the session and the device persists the advanced synctoken.
    cont_sync = bool(book_count > SYNC_ITEM_LIMIT)
    log.debug("Kobo Sync: remaining books to sync: {}".format(book_count))
    # generate reading state data
    changed_reading_states = ub.session.query(ub.KoboReadingState)

    log.debug("Kobo Sync: rstate last modified: {}".format(sync_token.reading_state_last_modified))
    if only_kobo_shelves:
        changed_reading_states = changed_reading_states.outerjoin(ub.BookShelf,
                                                                  ub.KoboReadingState.book_id == ub.BookShelf.book_id)\
            .outerjoin(ub.Shelf, ub.Shelf.id == ub.BookShelf.shelf)\
            .filter(ub.KoboReadingState.last_modified > sync_token.reading_state_last_modified)\
            .filter(or_(
                and_(current_user.id == ub.Shelf.user_id, ub.Shelf.kobo_sync == True),
                ub.KoboReadingState.book_id.in_(magic_shelf_book_ids) if magic_shelf_book_ids else False
            ))\
            .distinct()
    else:
        changed_reading_states = changed_reading_states.filter(
            ub.KoboReadingState.last_modified > sync_token.reading_state_last_modified)

    changed_reading_states = changed_reading_states.filter(
        and_(ub.KoboReadingState.user_id == current_user.id,
             ub.KoboReadingState.book_id.notin_(reading_states_in_new_entitlements)))\
        .order_by(ub.KoboReadingState.last_modified)
    log.debug("Kobo Sync: changed states: {}".format(changed_reading_states.count()))
    cont_sync |= bool(changed_reading_states.count() > SYNC_ITEM_LIMIT)
    for kobo_reading_state in changed_reading_states.limit(SYNC_ITEM_LIMIT).all():
        book = calibre_db.session.query(db.Books).filter(db.Books.id == kobo_reading_state.book_id).one_or_none()
        if book:
            sync_results.append({
                "ChangedReadingState": {
                    "ReadingState": get_kobo_reading_state_response(book, kobo_reading_state)
                }
            })
            new_reading_state_last_modified = max(new_reading_state_last_modified, kobo_reading_state.last_modified)

    sync_shelves(sync_token, sync_results, only_kobo_shelves)

    # Always emit DeletedTags for magic shelves that should NOT be on
    # the device — covers two distinct cases:
    #   (a) per-shelf kobo_sync flag was just flipped to False (user
    #       toggled a specific magic shelf off in the UI), or
    #   (b) global config_kobo_sync_magic_shelves flag was flipped off
    #       (admin disabled the whole feature). In case (b) every
    #       magic shelf the user owns needs a tombstone, even ones
    #       still marked kobo_sync=True, because the device may have
    #       synced them while the global flag was on.
    # Without this, toggling either flag off leaves orphan magic-shelf
    # entries on previously-synced devices that retry DELETE forever
    # (B1 retry loop). Wire-confirmed against the live
    # "Test_E2E_Discovered" magic-shelf during the 2026-05-17 capture.
    deletable_magic_shelves = ub.session.query(ub.MagicShelf).filter_by(
        user_id=current_user.id,
    )
    if config.config_kobo_sync_magic_shelves:
        deletable_magic_shelves = deletable_magic_shelves.filter_by(kobo_sync=False)
    # else: global flag off, emit DeletedTag for all magic shelves
    for shelf in deletable_magic_shelves.all():
        sync_results.append({
            "DeletedTag": {
                "Tag": {
                    "Id": shelf.uuid,
                    "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified)
                }
            }
        })

    # Add magic shelves as collections (only when feature is enabled)
    if config.config_kobo_sync_magic_shelves:
        magic_shelves = ub.session.query(ub.MagicShelf)\
            .filter_by(user_id=current_user.id, kobo_sync=True)\
            .all()

        new_tags_last_modified = sync_token.tags_last_modified

        for shelf in magic_shelves:
            books, _ = magic_shelf.get_books_for_magic_shelf(
                shelf.id, page=1, page_size=None
            )

            new_tags_last_modified = max(shelf.last_modified, new_tags_last_modified)

            tag = create_kobo_tag_magic(shelf, books)
            if not tag:
                continue

            if shelf.created > sync_token.tags_last_modified:
                log.debug("Syncing new magic shelf %s to Kobo device", shelf.name)
                sync_results.append({
                    "NewTag": tag
                })
            else:
                log.debug("Syncing changed magic shelf %s to Kobo device", shelf.name)
                sync_results.append({
                    "ChangedTag": tag
                })

        sync_token.tags_last_modified = new_tags_last_modified

    # Emit DeletedEntitlement tombstones for books hard-deleted from CW
    # (B3 fix — closes the orphan-book-on-device gap from the 2026-05-17
    # MITM capture). editbooks.delete_whole_book captures (user_id,
    # book_uuid, deleted_at) into kobo_deleted_book before tearing down
    # the metadata.db row; here we play those tombstones back to each
    # affected device as DeletedEntitlement and advance
    # archive_last_modified past the tombstone so the device sees each
    # one exactly once. Page-cap with SYNC_ITEM_LIMIT so a mass-delete
    # doesn't blow past the device's sync-response size limit.
    # Compare against the device's cursor (sync_token.archive_last_modified),
    # NOT against the local new_archived_last_modified — the latter has
    # already been rolled forward by any ArchivedBook.last_modified row,
    # which would mask legitimate tombstones whose deleted_at lies
    # between sync_token.archive_last_modified and new_archived_last_modified.
    cursor_archive_lm = sync_token.archive_last_modified
    pending_deletions = (
        ub.session.query(ub.KoboDeletedBook)
        .filter(ub.KoboDeletedBook.user_id == current_user.id)
        .filter(ub.KoboDeletedBook.deleted_at > cursor_archive_lm)
        .order_by(ub.KoboDeletedBook.deleted_at)
        .limit(SYNC_ITEM_LIMIT)
        .all()
    )
    for tombstone in pending_deletions:
        sync_results.append({
            "DeletedEntitlement": {
                "BookEntitlement": {
                    "Id": tombstone.book_uuid,
                    "RevisionId": tombstone.book_uuid,
                    "CrossRevisionId": tombstone.book_uuid,
                }
            }
        })
        ta = tombstone.deleted_at
        if hasattr(ta, "replace") and getattr(ta, "tzinfo", None) is not None:
            ta = ta.replace(tzinfo=None)
        new_archived_last_modified = max(ta, new_archived_last_modified)

    # If there are MORE pending deletions than SYNC_ITEM_LIMIT, mark
    # cont_sync so the device comes back for the next page rather than
    # losing tombstones to the page cap.
    if len(pending_deletions) >= SYNC_ITEM_LIMIT:
        remaining = (
            ub.session.query(ub.KoboDeletedBook)
            .filter(ub.KoboDeletedBook.user_id == current_user.id)
            .filter(ub.KoboDeletedBook.deleted_at > new_archived_last_modified)
            .count()
        )
        if remaining > 0:
            cont_sync = True

    # update last created timestamp to distinguish between new and changed entitlements
    if not cont_sync:
        sync_token.books_last_created = new_books_last_created
    sync_token.books_last_modified = new_books_last_modified
    sync_token.books_last_id = new_books_last_id
    sync_token.magic_shelf_last_id = new_magic_shelf_last_id
    # Persist the cache-rebuild timestamp so the next sync can detect a
    # newer rebuild and reset the sub-cursor (Greptile P on PR #367).
    if magic_shelf_membership_added_at is not None:
        sync_token.magic_shelf_membership_at = max(
            sync_token.magic_shelf_membership_at,
            magic_shelf_membership_added_at,
        )
    sync_token.archive_last_modified = new_archived_last_modified
    sync_token.reading_state_last_modified = new_reading_state_last_modified

    return generate_sync_response(sync_token, sync_results, cont_sync)


def generate_sync_response(sync_token, sync_results, set_cont=False):
    extra_headers = {}
    if config.config_kobo_proxy and not set_cont:
        # Merge in sync results from the official Kobo store.
        try:
            store_response = make_request_to_kobo_store(sync_token)

            store_sync_results = store_response.json()
            sync_results += store_sync_results
            sync_token.merge_from_store_response(store_response)
            extra_headers["x-kobo-sync"] = store_response.headers.get("x-kobo-sync")
            extra_headers["x-kobo-sync-mode"] = store_response.headers.get("x-kobo-sync-mode")
            extra_headers["x-kobo-recent-reads"] = store_response.headers.get("x-kobo-recent-reads")

        except Exception as ex:
            log.error_or_exception("Failed to receive or parse response from Kobo's sync endpoint: {}".format(ex))
    if set_cont:
        extra_headers["x-kobo-sync"] = "continue"
    sync_token.to_headers(extra_headers)

    # Track Kobo sync activity
    try:
        from scripts.cwa_db import CWA_DB
        import json as json_lib
        cwa_db = CWA_DB()
        cwa_db.log_activity(
            user_id=int(current_user.id),
            user_name=current_user.name,
            event_type='KOBO_SYNC',
            extra_data=json_lib.dumps({
                'books_synced': len(sync_results),
                'endpoint': '/v1/library/sync'
            })
        )
    except Exception as e:
        log.debug(f"Failed to log Kobo sync activity: {e}")

    # log.debug("Kobo Sync Content: {}".format(sync_results))
    # jsonify decodes the unicode string different to what kobo expects
    response = make_response(json.dumps(sync_results), extra_headers)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response


@kobo.route("/v1/library/<book_uuid>/metadata")
@requires_kobo_auth
@download_required
def HandleMetadataRequest(book_uuid):
    if not current_app.wsgi_app.is_proxied:
        log.debug('Kobo: Received unproxied request, changed request port to external server port')
    log.info("Kobo library metadata request received for book %s" % book_uuid)
    # Policy boundary: metadata GET. Symmetric with web/OPDS — books the
    # user can't see in the web UI shouldn't expose metadata via Kobo.
    book = calibre_db.get_book_by_uuid_for_kobo(book_uuid, enforce_policy=True)
    if not book or not book.data:
        log.info("Book %s not found in database", book_uuid)
        return redirect_or_proxy_request()

    metadata = get_metadata(book)
    response = make_response(json.dumps([metadata], ensure_ascii=False))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response


def get_download_url_for_book(book_id, book_format):
    endpoint_name = "kobo.download_book"
    endpoint_path = "download"
    if request.headers.get("x-kobo-deviceos") == "Android":
        endpoint_name = "kobo.redirect_download_book"
        endpoint_path = "redirect_download"

    if not current_app.wsgi_app.is_proxied:
        if ':' in request.host and not request.host.endswith(']'):
            host = "".join(request.host.split(':')[:-1])
        else:
            host = request.host

        return "{url_scheme}://{url_base}:{url_port}/kobo/{auth_token}/{endpoint_path}/{book_id}/{book_format}".format(
            url_scheme=request.scheme,
            url_base=host,
            url_port=config.config_external_port,
            auth_token=get_auth_token(),
            endpoint_path=endpoint_path,
            book_id=book_id,
            book_format=book_format.lower()
        )
    return url_for(
        endpoint_name,
        auth_token=kobo_auth.get_auth_token(),
        book_id=book_id,
        book_format=book_format.lower(),
        _external=True,
    )


def create_book_entitlement(book, archived):
    book_uuid = str(book.uuid)
    return {
        "Accessibility": "Full",
        "ActivePeriod": {"From": convert_to_kobo_timestamp_string(datetime.now(timezone.utc))},
        "Created": convert_to_kobo_timestamp_string(book.timestamp),
        "CrossRevisionId": book_uuid,
        "Id": book_uuid,
        "IsRemoved": archived,
        "IsHiddenFromArchive": False,
        "IsLocked": False,
        "LastModified": convert_to_kobo_timestamp_string(book.last_modified),
        "OriginCategory": "Imported",
        "RevisionId": book_uuid,
        "Status": "Active",
    }


def current_time():
    return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())


def get_description(book):
    if not book.comments:
        return None
    return book.comments[0].text


def get_author(book):
    if not book.authors:
        return {"Contributors": None}
    author_list = []
    autor_roles = []
    for author in book.authors:
        autor_roles.append({"Name": author.name})
        author_list.append(author.name)
    return {"ContributorRoles": autor_roles, "Contributors": author_list}


def get_publisher(book):
    if not book.publishers:
        return None
    return book.publishers[0].name


def get_series(book):
    if not book.series:
        return None
    return book.series[0].name


def get_subtitle(book):
    # Backport of janeczku PR #3358 (@dotknott): surface a per-book
    # Subtitle in Kobo sync metadata when the Calibre library has a
    # custom column labeled "subtitle". The upstream patch had three
    # null-handling bugs (.all()[0] IndexError when no column exists,
    # unreachable else branch, TypeError on None custom_column attr);
    # rewritten here for correct empty-result handling end-to-end.
    col = (calibre_db.session.query(db.CustomColumns)
                       .filter(db.CustomColumns.mark_for_delete == 0)
                       .filter(db.CustomColumns.datatype.notin_(db.cc_exceptions))
                       .filter(db.CustomColumns.label == 'subtitle')
                       .first())
    if col is None:
        return ""
    column_attr = getattr(book, 'custom_column_' + str(col.id), None)
    if not column_attr:
        return ""
    value = getattr(column_attr[0], 'value', None)
    return value or ""


def get_seriesindex(book):
    return book.series_index if isinstance(book.series_index, float) else 1


def get_language(book):
    if not book.languages:
        return 'en'
    return isoLanguages.get(part3=book.languages[0].lang_code).part1


def _normalize_cover_uuid(image_id):
    return normalize_cover_uuid(image_id)


def _current_padding_settings():
    """Snapshot of the admin's Kobo-padding config. Centralized so the
    sync-metadata path and the cover-serving path agree on the same hash."""
    return cover_preview.CoverPreviewSettings(
        enabled=bool(getattr(config, "config_kobo_cover_padding_enabled", False)),
        target_aspect=getattr(config, "config_kobo_cover_padding_aspect", "kobo_libra_color") or "kobo_libra_color",
        fill_mode=getattr(config, "config_kobo_cover_padding_fill_mode", "edge_mirror") or "edge_mirror",
        manual_color=getattr(config, "config_kobo_cover_padding_color", "") or "",
    )


def _get_cover_image_id(book):
    base_id = str(book.uuid)
    try:
        cover_path = None
        if not config.config_use_google_drive:
            cover_path = os.path.join(config.get_book_path(), book.path, "cover.jpg")
        image_id = build_cover_image_id(
            base_id,
            use_google_drive=config.config_use_google_drive,
            last_modified=book.last_modified,
            cover_path=cover_path,
        )
        # When server-side padding is on, append its settings hash so a
        # device whose cached cover was rendered with old settings
        # re-fetches after the admin changes the aspect or fill style.
        padding = _current_padding_settings()
        if padding.enabled:
            image_id = f"{image_id}-p{padding.settings_hash()}"
        return image_id
    except Exception as exc:
        log.debug("Kobo Sync: failed to build cover image id for book %s: %s", book.id, exc)
        return base_id

def build_download_url(book, book_data, download_format, declared_format):
    return {
            "Format": declared_format,
            "Size": book_data.uncompressed_size,
            "Url": get_download_url_for_book(book.id, download_format),
            "Platform": "Generic",
            "DrmType": "None",
        }

def get_metadata(book):
    download_urls = []

    kepub_data = next((d for d in book.data if d.format == 'KEPUB'), None)
    epub_data  = next((d for d in book.data if d.format == 'EPUB'),  None)

    # Send kepub if kepub format is available or if deferred kepub conversion
    # is supported
    if kepub_data:
        book_data, dl_format = kepub_data, 'kepub'
    elif epub_data and config.config_kepubifypath:
        book_data, dl_format = epub_data, 'kepub'
    elif epub_data:
        book_data, dl_format = epub_data, 'epub'
    else:
        book_data = None

    if book_data:
        is_fixed_layout = False
        try:
            if get_epub_layout(book, book_data) == 'pre-paginated':
                is_fixed_layout = True
        except (zipfile.BadZipfile, FileNotFoundError) as e:
            log.error(e)
        if is_fixed_layout:
            # Only send EPUB3FL if the book is a fixed layout. This forces the device
            # to pick this download, regardless of the priority order in the firmware
            download_urls.append(build_download_url(book, book_data, dl_format, 'EPUB3FL'))
        else:
            if dl_format == 'kepub':
                download_urls.append(build_download_url(book, book_data, dl_format, 'KEPUB'))
            else:
                # Send both EPUB and EPUB3 for epub files, in case legacy devices only support
                # EPUB download urls
                download_urls.append(build_download_url(book, book_data, dl_format, 'EPUB3'))
                download_urls.append(build_download_url(book, book_data, dl_format, 'EPUB'))

    book_uuid = book.uuid
    cover_image_id = _get_cover_image_id(book)
    if cover_image_id != str(book_uuid):
        log.debug("Kobo Sync: cache-busting cover id for book %s: %s", book.id, cover_image_id)
    metadata = {
        "Categories": ["00000000-0000-0000-0000-000000000001", ],
        # "Contributors": get_author(book),
        "CoverImageId": cover_image_id,
        "CrossRevisionId": book_uuid,
        "CurrentDisplayPrice": {"CurrencyCode": "USD", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": get_description(book),
        "DownloadUrls": download_urls,
        "EntitlementId": book_uuid,
        "ExternalIds": [],
        "Genre": "00000000-0000-0000-0000-000000000001",
        "IsEligibleForKoboLove": False,
        "IsInternetArchive": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": get_language(book),
        "PhoneticPronunciations": {},
        "PublicationDate": convert_to_kobo_timestamp_string(book.pubdate),
        "Publisher": {"Imprint": "", "Name": get_publisher(book), },
        "RevisionId": book_uuid,
        "Title": book.title,
        "Subtitle": get_subtitle(book),
        "WorkId": book_uuid,
        "Series": {},
    }
    metadata.update(get_author(book))

    series_name = get_series(book)
    if series_name:
        name = series_name
        try:
            metadata["Series"] = {
                "Name": series_name,
                "Number": get_seriesindex(book),        # ToDo Check int() ?
                "NumberFloat": float(get_seriesindex(book)),
                # Get a deterministic id based on the series name.
                "Id": str(uuid.uuid3(uuid.NAMESPACE_DNS, name)),
            }
        except Exception as e:
            print(e)
    return metadata


@csrf.exempt
@kobo.route("/v1/library/tags", methods=["POST", "DELETE"])
@requires_kobo_auth
# Creates a Shelf with the given items, and returns the shelf's uuid.
def HandleTagCreate():
    # catch delete requests, otherwise they are handled in the book delete handler
    if request.method == "DELETE":
        abort(405)
    name, items = None, None
    try:
        shelf_request = request.json
        name = shelf_request["Name"]
        items = shelf_request["Items"]
        if not name:
            raise TypeError
    except (KeyError, TypeError):
        log.debug("Received malformed v1/library/tags request.")
        abort(400, description="Malformed tags POST request. Data has empty 'Name', missing 'Name' or 'Items' field")

    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.name == name, ub.Shelf.user_id ==
                                              current_user.id).one_or_none()
    if shelf and not shelf_lib.check_shelf_edit_permissions(shelf):
        abort(401, description="User is unauthaurized to create shelf.")

    if not shelf:
        # Device-created shelves are Kobo-managed by definition; default
        # kobo_sync=True so subsequent syncs continue to emit NewTag and
        # the shelf round-trips across multi-device setups + survives a
        # factory reset. Users can untoggle via the shelf-edit UI later.
        shelf = ub.Shelf(user_id=current_user.id, name=name, uuid=str(uuid.uuid4()), kobo_sync=True)
        ub.session.add(shelf)

    items_unknown_to_calibre = add_items_to_shelf(items, shelf)
    if items_unknown_to_calibre:
        log.debug("Received request to add unknown books to a collection. Silently ignoring items.")
    ub.session_commit()
    return make_response(jsonify(str(shelf.uuid)), 201)


@csrf.exempt
@kobo.route("/v1/library/tags/<tag_id>", methods=["DELETE", "PUT"])
@requires_kobo_auth
def HandleTagUpdate(tag_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.uuid == tag_id,
                                              ub.Shelf.user_id == current_user.id).one_or_none()
    if not shelf:
        # Device-trailing: the shelf is unknown to CalibreWeb because it
        # was deleted server-side (or was a magic-shelf that no longer
        # syncs). The device only sees the absence; without a tombstone
        # in the sync response it pushes DELETE here every sync. Answering
        # 404 makes the device interpret the failure as transient and
        # retry forever, burning bandwidth indefinitely. Match the
        # HandleStateRequest pattern (line ~989) and
        # redirect_or_proxy_request() unconditionally so the loop ends,
        # regardless of config_kobo_proxy.
        log.debug("Received Kobo tag update for unknown collection %s — "
                  "answering via redirect_or_proxy_request to terminate "
                  "the device's retry loop", tag_id)
        return redirect_or_proxy_request()

    if request.method == "DELETE":
        if not shelf_lib.delete_shelf_helper(shelf):
            abort(401, description="Error deleting Shelf")
    else:
        name = None
        try:
            shelf_request = request.json
            name = shelf_request["Name"]
        except (KeyError, TypeError):
            log.debug("Received malformed v1/library/tags rename request.")
            abort(400, description="Malformed tags POST request. Data is missing 'Name' field")

        shelf.name = name
        ub.session.merge(shelf)
        ub.session_commit()
    return make_response(' ', 200)


# Adds items to the given shelf.
def add_items_to_shelf(items, shelf):
    book_ids_already_in_shelf = set([book_shelf.book_id for book_shelf in shelf.books])
    items_unknown_to_calibre = []
    for item in items:
        try:
            if item["Type"] != "ProductRevisionTagItem":
                items_unknown_to_calibre.append(item)
                continue

            # Policy boundary: shelf-add. Adding a denied/hidden book to a
            # Kobo-synced shelf would leak it to every other Kobo on the
            # same account. Treat as unknown-to-calibre so the device
            # silently drops it (existing items_unknown_to_calibre path).
            book = calibre_db.get_book_by_uuid_for_kobo(
                item["RevisionId"], enforce_policy=True,
            )
            if not book:
                items_unknown_to_calibre.append(item)
                continue

            book_id = book.id
            if book_id not in book_ids_already_in_shelf:
                shelf.books.append(ub.BookShelf(book_id=book_id))
        except KeyError:
            items_unknown_to_calibre.append(item)
    return items_unknown_to_calibre


@csrf.exempt
@kobo.route("/v1/library/tags/<tag_id>/items", methods=["POST"])
@requires_kobo_auth
def HandleTagAddItem(tag_id):
    items = None
    try:
        tag_request = request.json
        items = tag_request["Items"]
    except (KeyError, TypeError):
        log.debug("Received malformed v1/library/tags/<tag_id>/items/delete request.")
        abort(400, description="Malformed tags POST request. Data is missing 'Items' field")

    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.uuid == tag_id,
                                              ub.Shelf.user_id == current_user.id).one_or_none()
    if not shelf:
        log.debug("Received Kobo request on a collection unknown to CalibreWeb")
        abort(404, description="Collection isn't known to CalibreWeb")

    if not shelf_lib.check_shelf_edit_permissions(shelf):
        abort(401, description="User is unauthaurized to edit shelf.")

    items_unknown_to_calibre = add_items_to_shelf(items, shelf)
    if items_unknown_to_calibre:
        log.debug("Received request to add an unknown book to a collection. Silently ignoring item.")

    ub.session.merge(shelf)
    ub.session_commit()
    return make_response('', 201)


@csrf.exempt
@kobo.route("/v1/library/tags/<tag_id>/items/delete", methods=["POST"])
@requires_kobo_auth
def HandleTagRemoveItem(tag_id):
    items = None
    try:
        tag_request = request.json
        items = tag_request["Items"]
    except (KeyError, TypeError):
        log.debug("Received malformed v1/library/tags/<tag_id>/items/delete request.")
        abort(400, description="Malformed tags POST request. Data is missing 'Items' field")

    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.uuid == tag_id,
                                              ub.Shelf.user_id == current_user.id).one_or_none()
    if not shelf:
        # Same device-trailing pattern as HandleTagUpdate: the shelf
        # vanished server-side between syncs but the device still
        # thinks it exists and is now trying to remove an item from it.
        # Answering 404 traps the device in a retry loop. Mirror the
        # HandleStateRequest pattern and redirect_or_proxy_request().
        log.debug(
            "Received Kobo tag-remove-item for unknown collection %s — "
            "answering via redirect_or_proxy_request to terminate "
            "the device's retry loop", tag_id)
        return redirect_or_proxy_request()

    if not shelf_lib.check_shelf_edit_permissions(shelf):
        abort(401, description="User is unauthaurized to edit shelf.")

    items_unknown_to_calibre = []
    for item in items:
        try:
            if item["Type"] != "ProductRevisionTagItem":
                items_unknown_to_calibre.append(item)
                continue

            # Destructive, user-initiated: shelf-remove. Never block on
            # policy filters — the user must be able to clean up shelves
            # even when the underlying book is now hidden / denied / etc.
            book = calibre_db.get_book_by_uuid_for_kobo(
                item["RevisionId"], enforce_policy=False,
            )
            if not book:
                items_unknown_to_calibre.append(item)
                continue

            shelf.books.filter(ub.BookShelf.book_id == book.id).delete()
        except KeyError:
            items_unknown_to_calibre.append(item)
    ub.session_commit()

    if items_unknown_to_calibre:
        log.debug("Received request to remove an unknown book to a collecition. Silently ignoring item.")

    return make_response('', 200)


# Add new, changed, or deleted shelves to the sync_results.
# Note: Public shelves that aren't owned by the user aren't supported.
def sync_shelves(sync_token, sync_results, only_kobo_shelves=False):
    new_tags_last_modified = sync_token.tags_last_modified
    # transmit all archived shelfs independent of last sync (why should this matter?)
    for shelf in ub.session.query(ub.ShelfArchive).filter(ub.ShelfArchive.user_id == current_user.id):
        new_tags_last_modified = max(shelf.last_modified, new_tags_last_modified)
        sync_results.append({
            "DeletedTag": {
                "Tag": {
                    "Id": shelf.uuid,
                    "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified)
                }
            }
        })
        ub.session.delete(shelf)
        ub.session_commit()

    extra_filters = []
    if only_kobo_shelves:
        for shelf in ub.session.query(ub.Shelf).filter(
            func.datetime(ub.Shelf.last_modified) > sync_token.tags_last_modified,
            ub.Shelf.user_id == current_user.id,
            ub.Shelf.kobo_sync == False  # noqa: E712 -- SQLAlchemy column comparison
        ):
            sync_results.append({
                "DeletedTag": {
                    "Tag": {
                        "Id": shelf.uuid,
                        "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified)
                    }
                }
            })
        extra_filters.append(ub.Shelf.kobo_sync)

    shelflist = ub.session.query(ub.Shelf).outerjoin(ub.BookShelf).filter(
        or_(func.datetime(ub.Shelf.last_modified) > sync_token.tags_last_modified,
            func.datetime(ub.BookShelf.date_added) > sync_token.tags_last_modified),
        ub.Shelf.user_id == current_user.id,
        *extra_filters
    ).distinct().order_by(func.datetime(ub.Shelf.last_modified).asc())

    for shelf in shelflist:
        if not shelf_lib.check_shelf_view_permissions(shelf):
            continue

        new_tags_last_modified = max(shelf.last_modified, new_tags_last_modified)

        tag = create_kobo_tag(shelf)
        if not tag:
            continue

        if shelf.created > sync_token.tags_last_modified:
            sync_results.append({
                "NewTag": tag
            })
        else:
            sync_results.append({
                "ChangedTag": tag
            })
    sync_token.tags_last_modified = new_tags_last_modified
    ub.session_commit()


# Creates a Kobo "Tag" object from a ub.Shelf object
def create_kobo_tag(shelf):
    tag = {
        "Created": convert_to_kobo_timestamp_string(shelf.created),
        "Id": shelf.uuid,
        "Items": [],
        "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified),
        "Name": shelf.name,
        "Type": "UserTag"
    }
    for book_shelf in shelf.books:
        book = calibre_db.get_book(book_shelf.book_id)
        if not book:
            log.info("Book (id: %s) in BookShelf (id: %s) not found in book database",  book_shelf.book_id, shelf.id)
            continue
        tag["Items"].append(
            {
                "RevisionId": book.uuid,
                "Type": "ProductRevisionTagItem"
            }
        )
    return {"Tag": tag}

# Creates a Kobo "Tag" object from a ub.MagicShelf object
def create_kobo_tag_magic(shelf, books):
    tag = {
        "Created": convert_to_kobo_timestamp_string(shelf.created),
        "Id": shelf.uuid,
        "Items": [],
        "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified),
        "Name": shelf.name,
        "Type": "UserTag"
    }
    for book in books:
        tag["Items"].append(
            {
                "RevisionId": book.uuid,
                "Type": "ProductRevisionTagItem"
            }
        )
    return {"Tag": tag}


@csrf.exempt
@kobo.route("/v1/library/<book_uuid>/state", methods=["GET", "PUT"])
@requires_kobo_auth
def HandleStateRequest(book_uuid):
    # Device-trailing: state GET/PUT. The book is already on the Kobo;
    # reading progress must keep syncing even if the book later becomes
    # hidden/denied (otherwise the device retries forever and the user
    # sees sync failures). Sync push handler is the policy boundary.
    book = calibre_db.get_book_by_uuid_for_kobo(book_uuid, enforce_policy=False)
    if not book or not book.data:
        log.info("Book %s not found in database", book_uuid)
        return redirect_or_proxy_request()

    kobo_reading_state = get_or_create_reading_state(book.id)

    if request.method == "GET":
        return jsonify([get_kobo_reading_state_response(book, kobo_reading_state)])
    else:
        update_results_response = {"EntitlementId": book_uuid}

        try:
            request_data = request.json
            request_reading_state = request_data["ReadingStates"][0]

            # Use the device's own timestamp so the GET response mirrors it back,
            # preventing the "newer PT" conflict popup. Official Kobo cloud does the same.
            lm_str = request_reading_state.get("LastModified")
            request_lm = (datetime.strptime(lm_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                          if lm_str else datetime.now(timezone.utc))
            g.kobo_reading_state_lm = request_lm

            request_bookmark = request_reading_state["CurrentBookmark"]
            if request_bookmark:
                current_bookmark = kobo_reading_state.current_bookmark
                current_bookmark.progress_percent = request_bookmark["ProgressPercent"]
                current_bookmark.content_source_progress_percent = request_bookmark["ContentSourceProgressPercent"]
                location = request_bookmark.get("Location")
                if location:
                    current_bookmark.location_value = location["Value"]
                    current_bookmark.location_type = location["Type"]
                    current_bookmark.location_source = location["Source"]
                current_bookmark.last_modified = request_lm
                update_results_response["CurrentBookmarkResult"] = {"Result": "Success"}

            request_statistics = request_reading_state["Statistics"]
            if request_statistics:
                statistics = kobo_reading_state.statistics
                spent = request_statistics.get("SpentReadingMinutes")
                if spent is not None:
                    statistics.spent_reading_minutes = int(spent)
                remaining = request_statistics.get("RemainingTimeMinutes")
                if remaining is not None:
                    statistics.remaining_time_minutes = int(remaining)
                statistics.last_modified = request_lm
                update_results_response["StatisticsResult"] = {"Result": "Success"}

            request_status_info = request_reading_state["StatusInfo"]
            if request_status_info:
                book_read = kobo_reading_state.book_read_link
                new_book_read_status = get_ub_read_status(request_status_info["Status"])
                if new_book_read_status != book_read.read_status:
                    if new_book_read_status == ub.ReadBook.STATUS_IN_PROGRESS:
                        book_read.times_started_reading += 1
                        book_read.last_time_started_reading = datetime.now(timezone.utc)
                    book_read.read_status = new_book_read_status
                    book_read.last_modified = request_lm
                update_results_response["StatusInfoResult"] = {"Result": "Success"}
        except (KeyError, TypeError, ValueError, StatementError):
            log.debug("Received malformed v1/library/<book_uuid>/state request.")
            ub.session.rollback()
            abort(400, description="Malformed request data is missing 'ReadingStates' key")

        if request_bookmark and request_bookmark.get("ProgressPercent") is not None:
            push_reading_state_to_hardcover(current_user, book, request_bookmark["ProgressPercent"])

        ub.session.merge(kobo_reading_state)
        ub.session_commit()
        return jsonify({
            "RequestResult": "Success",
            "UpdateResults": [update_results_response],
        })


def push_reading_state_to_hardcover(user, book: db.Books, progress_percentage: int):
    """
    Sync reading progress to Hardcover if enabled for the user and book is not blacklisted.

    Most exceptions are caught and logged so that issues with Hardcover do not prevent
    the Kobo from clearing its reading state sync queue.

    :param book: The book for which to sync reading progress.
    :param progress_percentage: Reading progress percentage.
    :return: None
    """

    if not config.config_hardcover_sync or not bool(hardcover):
        return

    # Check if book is blacklisted from reading progress syncing
    book_blacklist = ub.session.query(ub.HardcoverBookBlacklist).filter(
        ub.HardcoverBookBlacklist.book_id == book.id).first()

    if book_blacklist and book_blacklist.blacklist_reading_progress:
        log.debug(f"Skipping reading progress sync for book {book.id} - blacklisted for reading progress")
        return

    try:
        hardcoverClient = hardcover.HardcoverClient(user.hardcover_token)
    except hardcover.MissingHardcoverToken:
        log.info(f"User {user.name} has no Hardcover token, not syncing reading progress to Hardcover")
        return
    except Exception as e:
        log.error(f"Failed to create Hardcover client for user {user.name}: {e}")
        return

    try:
        hardcoverClient.update_reading_progress(book.identifiers, progress_percentage)
    except Exception as e:
        log.error(f"Failed to update reading progress for book {book.id} in Hardcover: {e}",
                  exc_info=True)


def get_read_status_for_kobo(ub_book_read):
    enum_to_string_map = {
        None: "ReadyToRead",
        ub.ReadBook.STATUS_UNREAD: "ReadyToRead",
        ub.ReadBook.STATUS_FINISHED: "Finished",
        ub.ReadBook.STATUS_IN_PROGRESS: "Reading",
    }
    return enum_to_string_map[ub_book_read.read_status]


def get_ub_read_status(kobo_read_status):
    string_to_enum_map = {
        None: None,
        "ReadyToRead": ub.ReadBook.STATUS_UNREAD,
        "Finished": ub.ReadBook.STATUS_FINISHED,
        "Reading": ub.ReadBook.STATUS_IN_PROGRESS,
    }
    return string_to_enum_map[kobo_read_status]


def get_or_create_reading_state(book_id):
    """Return the canonical KoboReadingState row for (current_user, book_id),
    creating ReadBook + KoboReadingState (+ child rows) if missing.

    Concurrency-safe: two simultaneous PUTs to /v1/library/<uuid>/state from
    the same device — which legitimately happen on wake-from-sleep — would
    otherwise race past the read-then-write check and both insert. The
    audit-2026-05-11 fix:

    1. Bottom-row creation uses INSERT ... ON CONFLICT(user_id, book_id) DO
       NOTHING via the sqlite dialect insert, so duplicate inserts no-op
       at the SQL layer.
    2. The (user_id, book_id) UNIQUE index added in
       ``migrate_kobo_unique_constraints`` backs the ON CONFLICT clause
       and guarantees post-insert SELECT returns exactly one row.
    3. We commit each create separately so a concurrent winner's insert
       is visible to our subsequent SELECT — the ON CONFLICT path makes
       this safe (no spurious IntegrityError to recover from).
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    user_id = int(current_user.id)

    # 1. ReadBook (book_read_link). Atomic insert-if-missing.
    rb_stmt = (
        sqlite_insert(ub.ReadBook)
        .values(user_id=user_id, book_id=book_id,
                read_status=ub.ReadBook.STATUS_UNREAD,
                times_started_reading=0)
        .on_conflict_do_nothing(index_elements=["user_id", "book_id"])
    )
    ub.session.execute(rb_stmt)
    ub.session.commit()
    book_read = (
        ub.session.query(ub.ReadBook)
        .filter(ub.ReadBook.user_id == user_id,
                ub.ReadBook.book_id == book_id)
        .one()
    )

    # 2. KoboReadingState. Same pattern — but we also need the matching
    #    KoboBookmark + KoboStatistics child rows. We create the parent
    #    first, then attach children via the ORM if they're missing.
    if not book_read.kobo_reading_state:
        krs_stmt = (
            sqlite_insert(ub.KoboReadingState)
            .values(user_id=user_id, book_id=book_id)
            .on_conflict_do_nothing(index_elements=["user_id", "book_id"])
        )
        ub.session.execute(krs_stmt)
        ub.session.commit()
        # Re-fetch via the relationship so SQLAlchemy's identity map picks
        # up the row just inserted (possibly by us, possibly by a racing
        # request). ``book_read.kobo_reading_state`` is a primaryjoin on
        # (user_id, book_id), so the row will resolve automatically.
        ub.session.refresh(book_read)

    kobo_reading_state = book_read.kobo_reading_state

    # 3. Child rows. These have an FK to KoboReadingState.id, so they
    #    can be created via ORM safely (the parent row is now stable).
    if kobo_reading_state.current_bookmark is None:
        kobo_reading_state.current_bookmark = ub.KoboBookmark()
    if kobo_reading_state.statistics is None:
        kobo_reading_state.statistics = ub.KoboStatistics()
    ub.session.commit()

    return kobo_reading_state


def get_kobo_reading_state_response(book, kobo_reading_state):
    return {
        "EntitlementId": book.uuid,
        "Created": convert_to_kobo_timestamp_string(book.timestamp),
        "LastModified": convert_to_kobo_timestamp_string(kobo_reading_state.last_modified),
        # AFAICT PriorityTimestamp is always equal to LastModified.
        "PriorityTimestamp": convert_to_kobo_timestamp_string(kobo_reading_state.priority_timestamp),
        "StatusInfo": get_status_info_response(kobo_reading_state.book_read_link),
        "Statistics": get_statistics_response(kobo_reading_state.statistics),
        "CurrentBookmark": get_current_bookmark_response(kobo_reading_state.current_bookmark),
    }


def get_status_info_response(book_read):
    resp = {
        "LastModified": convert_to_kobo_timestamp_string(book_read.last_modified),
        "Status": get_read_status_for_kobo(book_read),
        "TimesStartedReading": book_read.times_started_reading,
    }
    if book_read.last_time_started_reading:
        resp["LastTimeStartedReading"] = convert_to_kobo_timestamp_string(book_read.last_time_started_reading)
    return resp


def get_statistics_response(statistics):
    resp = {
        "LastModified": convert_to_kobo_timestamp_string(statistics.last_modified),
    }
    if statistics.spent_reading_minutes is not None:
        resp["SpentReadingMinutes"] = statistics.spent_reading_minutes
    if statistics.remaining_time_minutes is not None:
        resp["RemainingTimeMinutes"] = statistics.remaining_time_minutes
    return resp


def _clean_progress(value):
    """Return progress as int if it's a whole number, preserving Kobo device expectations."""
    if value is not None and value == int(value):
        return int(value)
    return value


def get_current_bookmark_response(current_bookmark):
    resp = {
        "LastModified": convert_to_kobo_timestamp_string(current_bookmark.last_modified),
    }
    if current_bookmark.progress_percent is not None:
        resp["ProgressPercent"] = _clean_progress(current_bookmark.progress_percent)
    if current_bookmark.content_source_progress_percent is not None:
        resp["ContentSourceProgressPercent"] = _clean_progress(current_bookmark.content_source_progress_percent)
    if current_bookmark.location_value:
        resp["Location"] = {
            "Value": current_bookmark.location_value,
            "Type": current_bookmark.location_type,
            "Source": current_bookmark.location_source,
        }
    return resp


def _serve_padded_cover_if_enabled(book_uuid, resolution):
    """Return a Response with the aspect-ratio-padded cover, or None when
    padding is disabled / not applicable / produced an error. Callers fall
    back to the normal helper.get_book_cover_with_uuid path on None.

    Padded variants live under the same thumbnails cache dir but with a
    `kobopad-...` filename prefix that encodes book uuid + resolution +
    source mtime + settings hash.
    """
    settings = _current_padding_settings()
    if not settings.enabled or not cover_preview.use_IM:
        return None

    source = helper.get_kobo_cover_source_path(book_uuid, resolution)
    if not source:
        return None
    src_dir, src_filename, src_full = source

    try:
        src_mtime = int(os.path.getmtime(src_full))
    except OSError:
        return None

    cache = FileSystem()
    cache_dir = cache.get_cache_dir(CACHE_TYPE_THUMBNAILS)
    cache_filename = cover_preview.cache_filename_for(
        book_uuid, resolution, src_mtime, settings,
    )

    target = cover_preview.pad_path_to_cache(
        src_full, cache_dir, cache_filename, settings,
    )
    if not target:
        log.debug("Kobo Sync: padding pipeline produced no file for %s; "
                  "falling back to unpadded cover", book_uuid)
        return None

    log.debug("Kobo Sync: serving padded cover %s", cache_filename)
    return send_from_directory(cache_dir, cache_filename)


@kobo.route("/<book_uuid>/<width>/<height>/<isGreyscale>/image.jpg", defaults={'Quality': ""})
@kobo.route("/<book_uuid>/<width>/<height>/<Quality>/<isGreyscale>/image.jpg")
@requires_kobo_auth
def HandleCoverImageRequest(book_uuid, width, height, Quality, isGreyscale):
    book_uuid = _normalize_cover_uuid(book_uuid)
    try:
        if int(height) > 1000:
            resolution = COVER_THUMBNAIL_LARGE
        elif int(height) > 500:
            resolution = COVER_THUMBNAIL_MEDIUM
        else:
            resolution = COVER_THUMBNAIL_SMALL
    except ValueError:
        log.error("Requested height %s of book %s is invalid" % (height, book_uuid))
        resolution = COVER_THUMBNAIL_SMALL

    padded_response = _serve_padded_cover_if_enabled(book_uuid, resolution)
    if padded_response is not None:
        return padded_response

    book_cover = helper.get_book_cover_with_uuid(book_uuid, resolution=resolution)
    if book_cover:
        log.debug("Serving local cover image of book %s" % book_uuid)
        return book_cover

    if not config.config_kobo_proxy:
        log.debug("Returning 404 for cover image of unknown book %s" % book_uuid)
        # additional proxy request make no sense, -> direct return
        return abort(404)

    log.debug("Redirecting request for cover image of unknown book %s to Kobo" % book_uuid)
    return redirect(KOBO_IMAGEHOST_URL +
                    "/{book_uuid}/{width}/{height}/false/image.jpg".format(book_uuid=book_uuid,
                                                                           width=width,
                                                                           height=height), 307)


@kobo.route("")
def TopLevelEndpoint():
    return make_response(jsonify({}))


@csrf.exempt
@kobo.route("/v1/library/<book_uuid>", methods=["DELETE"])
@requires_kobo_auth
def HandleBookDeletionRequest(book_uuid):
    log.info("Kobo book delete request received for book %s", book_uuid)
    # Destructive, user-initiated: book DELETE. Never block on policy
    # filters — user must be able to remove a book from their Kobo
    # regardless of current hidden / denied / language state.
    book = calibre_db.get_book_by_uuid_for_kobo(book_uuid, enforce_policy=False)
    if not book:
        log.info("Book %s not found in database", book_uuid)
        return redirect_or_proxy_request()

    book_id = book.id
    # If the user has shelf sync enabled, do nothing.
    # The book will be removed from the device on the next sync.
    if current_user.kobo_only_shelves_sync:
        pass
    # Otherwise, archive the book if the user has permission to see archived books.
    elif current_user.check_visibility(32768):
        kobo_sync_status.change_archived_books(book_id, True)

    kobo_sync_status.remove_synced_book(book_id)
    return "", 204


# TODO: Implement the following routes
@csrf.exempt
@kobo.route("/v1/library/<dummy>", methods=["DELETE", "GET", "POST"])
@kobo.route("/v1/library/<dummy>/preview", methods=["POST"])
def HandleUnimplementedRequest(dummy=None):
    log.debug(f"Unimplemented Library Request received: %s (%s)",
              request.base_url,
              'forwarded to Kobo Store' if config.config_kobo_proxy else 'returning empty response')
    return redirect_or_proxy_request()


# TODO: Implement the following routes
@csrf.exempt
@kobo.route("/v1/user/loyalty/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/user/profile", methods=["GET", "POST"])
@kobo.route("/v1/user/wishlist", methods=["GET", "POST"])
@kobo.route("/v1/user/recommendations", methods=["GET", "POST"])
@kobo.route("/v1/analytics/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/assets", methods=["GET"])
def HandleUserRequest(dummy=None):
    log.debug("Unimplemented User Request received: %s (%s)",
              request.base_url,
              'forwarded to Kobo Store' if config.config_kobo_proxy else 'returning empty response')
    return redirect_or_proxy_request()


@csrf.exempt
@kobo.route("/v1/user/loyalty/benefits", methods=["GET"])
def handle_benefits():
    if config.config_kobo_proxy:
        return redirect_or_proxy_request()
    else:
        return make_response(jsonify({"Benefits": {}}))


@csrf.exempt
@kobo.route("/v1/analytics/gettests", methods=["GET", "POST"])
def handle_getests():
    if config.config_kobo_proxy:
        return redirect_or_proxy_request()
    else:
        testkey = request.headers.get("X-Kobo-userkey", "")
        return make_response(jsonify({"Result": "Success", "TestKey": testkey, "Tests": {}}))


@csrf.exempt
@kobo.route("/v1/products/<dummy>/prices", methods=["GET", "POST"])
@kobo.route("/v1/products/<dummy>/recommendations", methods=["GET", "POST"])
@kobo.route("/v1/products/<dummy>/nextread", methods=["GET", "POST"])
@kobo.route("/v1/products/<dummy>/reviews", methods=["GET", "POST"])
@kobo.route("/v1/products/featured/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/products/featured/", methods=["GET", "POST"])
@kobo.route("/v1/products/books/external/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/products/books/series/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/products/books/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/products/books/<dummy>/", methods=["GET", "POST"])
@kobo.route("/v1/products/dailydeal", methods=["GET", "POST"])
@kobo.route("/v1/products/deals", methods=["GET", "POST"])
@kobo.route("/v1/products/featuredforkoboplus/")
@kobo.route("/v1/products", methods=["GET", "POST"])
@kobo.route("/v1/affiliate", methods=["GET", "POST"])
@kobo.route("/v1/deals", methods=["GET", "POST"])
@kobo.route("/v1/categories/<dummy>", methods=["GET", "POST"])
@kobo.route("/v1/categories/<dummy>/featured", methods=["GET", "POST"])
@kobo.route("/v1/categories/<dummy>/products")
def HandleProductsRequest(dummy=None):
    log.debug(f"Unimplemented Products Request received: %s (%s)",
              request.base_url,
              'forwarded to Kobo Store' if config.config_kobo_proxy else 'returning empty response')
    return redirect_or_proxy_request()


def make_calibre_web_auth_response():
    # As described in kobo_auth.py, CalibreWeb doesn't make use practical use of this auth/device API call for
    # authentation (nor for authorization). We return a dummy response just to keep the device happy.
    content = request.get_json()
    AccessToken = base64.b64encode(os.urandom(24)).decode('utf-8')
    RefreshToken = base64.b64encode(os.urandom(24)).decode('utf-8')
    return make_response(
        jsonify(
            {
                "AccessToken": AccessToken,
                "RefreshToken": RefreshToken,
                "TokenType": "Bearer",
                "TrackingId": str(uuid.uuid4()),
                "UserKey": content.get('UserKey', ""),
            }
        )
    )


def make_calibre_web_oauth_response():
    # Provide a dummy OAuth token response for unregistered devices or
    # when Kobo Store proxying is disabled.
    content = request.get_json(silent=True) or {}
    access_token = base64.b64encode(os.urandom(24)).decode('utf-8')
    refresh_token = base64.b64encode(os.urandom(24)).decode('utf-8')
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": content.get("scope", ""),
        "user_id": str(current_user.id) if current_user and not current_user.is_anonymous else content.get("user_id", ""),
        # Include legacy field names used by some Kobo requests
        "AccessToken": access_token,
        "RefreshToken": refresh_token,
        "TokenType": "Bearer",
    }
    return make_response(jsonify(payload))


@csrf.exempt
@kobo.route("/v1/auth/device", methods=["POST"])
@requires_kobo_auth
def HandleAuthRequest():
    log.debug('Kobo Auth request')
    if config.config_kobo_proxy:
        try:
            return redirect_or_proxy_request()
        except Exception:
            log.error("Failed to receive or parse response from Kobo's auth endpoint. Falling back to un-proxied mode.")
    return make_calibre_web_auth_response()



@csrf.exempt
@kobo.route('/oauth/.well-known/openid-configuration', methods=['GET', 'POST'])
@requires_kobo_auth
def HandleOidcDiscovery():
    base_url = url_for("kobo.HandleOauthRequest",
                       auth_token=get_auth_token(),
                       _external=True).rsplit("/oauth", 1)[0]
    payload = {
        'issuer': base_url,
        'authorization_endpoint': base_url + '/oauth/authorize',
        'token_endpoint': base_url + '/oauth/token',
        'userinfo_endpoint': base_url + '/oauth/userinfo',
        'response_types_supported': ['code'],
        'subject_types_supported': ['public'],
        'id_token_signing_alg_values_supported': ['RS256'],
    }
    return make_response(jsonify(payload))

@csrf.exempt
@kobo.route("/oauth/token", methods=["GET", "POST"])
@kobo.route("/oauth/authorize", methods=["GET", "POST"])
@kobo.route("/oauth/refresh", methods=["GET", "POST"])
@kobo.route("/oauth/<path:subpath>", methods=["GET", "POST"])
@requires_kobo_auth
def HandleOauthRequest(subpath=None):
    log.debug("Kobo OAuth request: %s", request.path)
    return make_calibre_web_oauth_response()


@kobo.route("/v1/initialization")
@requires_kobo_auth
def HandleInitRequest():
    log.info('Init')

    kobo_resources = None
    if config.config_kobo_proxy:
        try:
            store_response = make_request_to_kobo_store()
            store_response_json = store_response.json()

            # It is relatively important to handle ExpiredToken errors here to trigger re-authentication.
            # Kobo uses this endpoint to assure that the auth token is valid and recover from errors elsewhere.
            # If this does not work properly users may get stuck with an expired token and no way to re-authenticate.
            # The handling here has been kept minimal because some users may not wish to auth with Onestore,
            # but Kobo requires auth for more endpoints than used to be the case, and it perhaps does not make sense
            # for users to enable proxy requests to the Kobo Store without a working Kobo account.

            if rs := store_response_json.get("ResponseStatus", {}):
                if ec := rs.get("ErrorCode", ""):
                    msg = rs.get("Message", "(No message provided)")
                    if ec == "ExpiredToken":
                        log.info(f"Kobo Store session expired: {msg}. Triggering re-authentication.")
                        return make_proxy_response(store_response)
                    log.warning(f"Kobo: Kobo Store initialization returned error code {ec}: {msg}")
            if "Resources" in store_response_json:
                kobo_resources = store_response_json["Resources"]
            else:
                log.error("Kobo: Kobo Store initialization response missing 'Resources' field.")
        except Exception as e:
            log.error_or_exception(f"Failed to receive or parse response from Kobo's init endpoint: {e}")
    if not kobo_resources:
        log.debug("Using fallback Kobo resource definitions")
        kobo_resources = NATIVE_KOBO_RESOURCES()

    if not current_app.wsgi_app.is_proxied:
        log.debug('Kobo: Received unproxied request, changed request port to external server port')
        if ':' in request.host and not request.host.endswith(']'):
            host = "".join(request.host.split(':')[:-1])
        else:
            host = request.host
        calibre_web_url = "{url_scheme}://{url_base}:{url_port}".format(
            url_scheme=request.scheme,
            url_base=host,
            url_port=config.config_external_port
        )
        log.debug('Kobo: Received unproxied request, changed request url to %s', calibre_web_url)
        kobo_resources["image_host"] = calibre_web_url
        kobo_resources["image_url_quality_template"] = unquote(calibre_web_url +
                                                               url_for("kobo.HandleCoverImageRequest",
                                                                       auth_token=kobo_auth.get_auth_token(),
                                                                       book_uuid="{ImageId}",
                                                                       width="{Width}",
                                                                       height="{Height}",
                                                                       Quality='{Quality}',
                                                                       isGreyscale='isGreyscale'))
        kobo_resources["image_url_template"] = unquote(calibre_web_url +
                                                       url_for("kobo.HandleCoverImageRequest",
                                                               auth_token=kobo_auth.get_auth_token(),
                                                               book_uuid="{ImageId}",
                                                               width="{Width}",
                                                               height="{Height}",
                                                               isGreyscale='false'))
        # Route reading-services (annotations + reading state) through CWNG
        # whenever Kobo sync is on — not just when Hardcover is enabled.
        # The annotation handler captures a local copy then ALWAYS proxies
        # the request on to Kobo's real reading services, so device-side
        # data is never withheld. Previously this was gated on Hardcover,
        # so with Hardcover off the device sent annotations straight to
        # Kobo and CWNG never saw them — the live-Kobo capture from #305
        # sub-project (2) was a no-op on the wire. (Found via real-device
        # test 2026-05-24.)
        if config.config_kobo_sync or (config.config_hardcover_annotations_sync and bool(hardcover)):
            kobo_resources["reading_services_host"] = calibre_web_url
        kobo_resources["library_sync"] = calibre_web_url + url_for("kobo.HandleSyncRequest",
                                                                    auth_token=kobo_auth.get_auth_token())
    else:
        kobo_resources["image_host"] = url_for("web.index", _external=True).strip("/")
        kobo_resources["image_url_quality_template"] = unquote(url_for("kobo.HandleCoverImageRequest",
                                                                       auth_token=kobo_auth.get_auth_token(),
                                                                       book_uuid="{ImageId}",
                                                                       width="{Width}",
                                                                       height="{Height}",
                                                                       Quality='{Quality}',
                                                                       isGreyscale='isGreyscale',
                                                                       _external=True))
        kobo_resources["image_url_template"] = unquote(url_for("kobo.HandleCoverImageRequest",
                                                               auth_token=kobo_auth.get_auth_token(),
                                                               book_uuid="{ImageId}",
                                                               width="{Width}",
                                                               height="{Height}",
                                                               isGreyscale='false',
                                                               _external=True))
        # See note above — redirect reading-services to CWNG whenever Kobo
        # sync is on so live annotation capture works without Hardcover.
        if config.config_kobo_sync or (config.config_hardcover_annotations_sync and bool(hardcover)):
            kobo_resources["reading_services_host"] = url_for("web.index", _external=True).strip("/")
        kobo_resources["library_sync"] = url_for("kobo.HandleSyncRequest",
                                                  auth_token=kobo_auth.get_auth_token(),
                                                  _external=True)

    # When not proxying Kobo Store requests, point oauth_host to CWA and
    # serve dummy OAuth responses for unregistered devices.
    if not config.config_kobo_proxy:
        oauth_token_url = url_for("kobo.HandleOauthRequest",
                                  auth_token=kobo_auth.get_auth_token(),
                                  _external=True)
        kobo_resources["oauth_host"] = oauth_token_url.rsplit("/oauth", 1)[0] + "/oauth"

    response = make_response(jsonify({"Resources": kobo_resources}))
    response.headers["x-kobo-apitoken"] = "e30="

    return response


@kobo.route("/download/<book_id>/<book_format>")
@requires_kobo_auth
@download_required
def download_book(book_id, book_format):
    return get_download_link(book_id, book_format, "kobo")


@kobo.route("/redirect_download/<book_id>/<book_format>")
@requires_kobo_auth
@download_required
def redirect_download_book(book_id, book_format):
    return redirect(url_for(
        "kobo.download_book",
        auth_token=kobo_auth.get_auth_token(),
        book_id=book_id,
        book_format=book_format.lower(),
        _external=True,
    ))


def NATIVE_KOBO_RESOURCES():
    return {
        "account_page": "https://www.kobo.com/account/settings",
        "account_page_rakuten": "https://my.rakuten.co.jp/",
        "add_device": "https://storeapi.kobo.com/v1/user/add-device",
        "add_entitlement": "https://storeapi.kobo.com/v1/library/{RevisionIds}",
        "affiliaterequest": "https://storeapi.kobo.com/v1/affiliate",
        "assets": "https://storeapi.kobo.com/v1/assets",
        "audiobook": "https://storeapi.kobo.com/v1/products/audiobooks/{ProductId}",
        "audiobook_detail_page": "https://www.kobo.com/{region}/{language}/audiobook/{slug}",
        "audiobook_get_credits": "https://www.kobo.com/{region}/{language}/audiobooks/plans",
        "audiobook_landing_page": "https://www.kobo.com/{region}/{language}/audiobooks",
        "audiobook_preview": "https://storeapi.kobo.com/v1/products/audiobooks/{Id}/preview",
        "audiobook_purchase_withcredit": "https://storeapi.kobo.com/v1/store/audiobook/{Id}",
        "audiobook_subscription_management": "https://www.kobo.com/{region}/{language}/account/subscriptions",
        "audiobook_subscription_orange_deal_inclusion_url": "https://authorize.kobo.com/inclusion",
        "audiobook_subscription_purchase": "https://www.kobo.com/{region}/{language}/checkoutoption/21C6D938-934B-4A91-B979-E14D70B2F280",
        "audiobook_subscription_tiers": "https://www.kobo.com/{region}/{language}/checkoutoption/21C6D938-934B-4A91-B979-E14D70B2F280",
        "authorproduct_recommendations": "https://storeapi.kobo.com/v1/products/books/authors/recommendations",
        "autocomplete": "https://storeapi.kobo.com/v1/products/autocomplete",
        "blackstone_header": {
            "key": "x-amz-request-payer",
            "value": "requester"
        },
        "book": "https://storeapi.kobo.com/v1/products/books/{ProductId}",
        "book_detail_page": "https://www.kobo.com/{region}/{language}/ebook/{slug}",
        "book_detail_page_rakuten": "https://books.rakuten.co.jp/rk/{crossrevisionid}",
        "book_landing_page": "https://www.kobo.com/ebooks",
        "book_subscription": "https://storeapi.kobo.com/v1/products/books/subscriptions",
        "browse_history": "https://storeapi.kobo.com/v1/user/browsehistory",
        "categories": "https://storeapi.kobo.com/v1/categories",
        "categories_page": "https://www.kobo.com/ebooks/categories",
        "category": "https://storeapi.kobo.com/v1/categories/{CategoryId}",
        "category_featured_lists": "https://storeapi.kobo.com/v1/categories/{CategoryId}/featured",
        "category_products": "https://storeapi.kobo.com/v1/categories/{CategoryId}/products",
        "checkout_borrowed_book": "https://storeapi.kobo.com/v1/library/borrow",
        "client_authd_referral": "https://authorize.kobo.com/api/AuthenticatedReferral/client/v1/getLink",
        "configuration_data": "https://storeapi.kobo.com/v1/configuration",
        "content_access_book": "https://storeapi.kobo.com/v1/products/books/{ProductId}/access",
        "customer_care_live_chat": "https://v2.zopim.com/widget/livechat.html?key=Y6gwUmnu4OATxN3Tli4Av9bYN319BTdO",
        "daily_deal": "https://storeapi.kobo.com/v1/products/dailydeal",
        "deals": "https://storeapi.kobo.com/v1/deals",
        "delete_entitlement": "https://storeapi.kobo.com/v1/library/{Ids}",
        "delete_tag": "https://storeapi.kobo.com/v1/library/tags/{TagId}",
        "delete_tag_items": "https://storeapi.kobo.com/v1/library/tags/{TagId}/items/delete",
        "device_auth": "https://storeapi.kobo.com/v1/auth/device",
        "device_refresh": "https://storeapi.kobo.com/v1/auth/refresh",
        "dictionary_host": "https://ereaderfiles.kobo.com",
        "discovery_host": "https://discovery.kobobooks.com",
        "ereaderdevices": "https://storeapi.kobo.com/v2/products/EReaderDeviceFeeds",
        "dropbox_link_account_poll": "https://authorize.kobo.com/{region}/{language}/LinkDropbox",
        "dropbox_link_account_start": "https://authorize.kobo.com/LinkDropbox/start",
        "eula_page": "https://www.kobo.com/termsofuse?style=onestore",
        "exchange_auth": "https://storeapi.kobo.com/v1/auth/exchange",
        "external_book": "https://storeapi.kobo.com/v1/products/books/external/{Ids}",
        "facebook_sso_page": "https://authorize.kobo.com/signin/provider/Facebook/login?returnUrl=http://kobo.com/",
        "featured_list": "https://storeapi.kobo.com/v1/products/featured/{FeaturedListId}",
        "featured_lists": "https://storeapi.kobo.com/v1/products/featured",
        "free_books_page": {
            "EN": "https://www.kobo.com/{region}/{language}/p/free-ebooks",
            "FR": "https://www.kobo.com/{region}/{language}/p/livres-gratuits",
            "IT": "https://www.kobo.com/{region}/{language}/p/libri-gratuiti",
            "NL": "https://www.kobo.com/{region}/{language}/List/bekijk-het-overzicht-van-gratis-ebooks/QpkkVWnUw8sxmgjSlCbJRg",
            "PT": "https://www.kobo.com/{region}/{language}/p/livros-gratis"
        },
        "fte_feedback": "https://storeapi.kobo.com/v1/products/ftefeedback",
        "funnel_metrics": "https://storeapi.kobo.com/v1/funnelmetrics",
        "get_download_keys": "https://storeapi.kobo.com/v1/library/downloadkeys",
        "get_download_link": "https://storeapi.kobo.com/v1/library/downloadlink",
        "get_tests_request": "https://storeapi.kobo.com/v1/analytics/gettests",
        "giftcard_epd_redeem_url": "https://www.kobo.com/{storefront}/{language}/redeem-ereader",
        "giftcard_redeem_url": "https://www.kobo.com/{storefront}/{language}/redeem",
        "googledrive_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkcloudstorage/provider/google_drive",
        "gpb_flow_enabled": "False",
        "help_page": "https://www.kobo.com/help",
        "image_host": "https://cdn.kobo.com/book-images/",
        "image_url_quality_template": "https://cdn.kobo.com/book-images/{ImageId}/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg",
        "image_url_template": "https://cdn.kobo.com/book-images/{ImageId}/{Width}/{Height}/false/image.jpg",
        "instapaper_enabled": "True",
        "instapaper_env_url": "https://www.instapaper.com/api/kobo",
        "instapaper_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkinstapaper",
        "kobo_audiobooks_credit_redemption": "True",
        "kobo_audiobooks_enabled": "True",
        "kobo_audiobooks_orange_deal_enabled": "True",
        "kobo_audiobooks_subscriptions_enabled": "True",
        "kobo_display_price": "True",
        "kobo_dropbox_link_account_enabled": "True",
        "kobo_google_tax": "False",
        "kobo_googledrive_link_account_enabled": "True",
        "kobo_nativeborrow_enabled": "True",
        "kobo_onedrive_link_account_enabled": "False",
        "kobo_onestorelibrary_enabled": "False",
        "kobo_privacyCentre_url": "https://www.kobo.com/privacy",
        "kobo_redeem_enabled": "True",
        "kobo_shelfie_enabled": "False",
        "kobo_subscriptions_enabled": "True",
        "kobo_superpoints_enabled": "True",
        "kobo_wishlist_enabled": "True",
        "library_book": "https://storeapi.kobo.com/v1/user/library/books/{LibraryItemId}",
        "library_items": "https://storeapi.kobo.com/v1/user/library",
        "library_metadata": "https://storeapi.kobo.com/v1/library/{Ids}/metadata",
        "library_prices": "https://storeapi.kobo.com/v1/user/library/previews/prices",
        "library_search": "https://storeapi.kobo.com/v1/library/search",
        "library_sync": "https://storeapi.kobo.com/v1/library/sync",
        "love_dashboard_page": "https://www.kobo.com/{region}/{language}/kobosuperpoints",
        "love_points_redemption_page": "https://www.kobo.com/{region}/{language}/KoboSuperPointsRedemption?productId={ProductId}",
        "magazine_landing_page": "https://www.kobo.com/emagazines",
        "more_sign_in_options": "https://authorize.kobo.com/signin?returnUrl=http://kobo.com/#allProviders",
        "notebooks": "https://storeapi.kobo.com/api/internal/notebooks",
        "notifications_registration_issue": "https://storeapi.kobo.com/v1/notifications/registration",
        "oauth_host": "https://oauth.kobo.com",
        "password_retrieval_page": "https://www.kobo.com/passwordretrieval.html",
        "personalizedrecommendations": "https://storeapi.kobo.com/v2/users/personalizedrecommendations",
        "pocket_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkpocket",
        "post_analytics_event": "https://storeapi.kobo.com/v1/analytics/event",
        "ppx_purchasing_url": "https://purchasing.kobo.com",
        "privacy_page": "https://www.kobo.com/privacypolicy?style=onestore",
        "product_nextread": "https://storeapi.kobo.com/v1/products/{ProductIds}/nextread",
        "product_prices": "https://storeapi.kobo.com/v1/products/{ProductIds}/prices",
        "product_recommendations": "https://storeapi.kobo.com/v1/products/{ProductId}/recommendations",
        "product_reviews": "https://storeapi.kobo.com/v1/products/{ProductIds}/reviews",
        "products": "https://storeapi.kobo.com/v1/products",
        "productsv2": "https://storeapi.kobo.com/v2/products",
        "provider_external_sign_in_page": "https://authorize.kobo.com/ExternalSignIn/{providerName}?returnUrl=http://kobo.com/",
        "purchase_buy": "https://www.kobo.com/checkoutoption/",
        "purchase_buy_templated": "https://www.kobo.com/{region}/{language}/checkoutoption/{ProductId}",
        "quickbuy_checkout": "https://storeapi.kobo.com/v1/store/quickbuy/{PurchaseId}/checkout",
        "quickbuy_create": "https://storeapi.kobo.com/v1/store/quickbuy/purchase",
        "rakuten_token_exchange": "https://storeapi.kobo.com/v1/auth/rakuten_token_exchange",
        "rating": "https://storeapi.kobo.com/v1/products/{ProductId}/rating/{Rating}",
        "reading_services_host": "https://readingservices.kobo.com",
        "reading_state": "https://storeapi.kobo.com/v1/library/{Ids}/state",
        "redeem_interstitial_page": "https://www.kobo.com",
        "registration_page": "https://authorize.kobo.com/signup?returnUrl=http://kobo.com/",
        "related_items": "https://storeapi.kobo.com/v1/products/{Id}/related",
        "remaining_book_series": "https://storeapi.kobo.com/v1/products/books/series/{SeriesId}",
        "rename_tag": "https://storeapi.kobo.com/v1/library/tags/{TagId}",
        "review": "https://storeapi.kobo.com/v1/products/reviews/{ReviewId}",
        "review_sentiment": "https://storeapi.kobo.com/v1/products/reviews/{ReviewId}/sentiment/{Sentiment}",
        "shelfie_recommendations": "https://storeapi.kobo.com/v1/user/recommendations/shelfie",
        "sign_in_page": "https://auth.kobobooks.com/ActivateOnWeb",
        "social_authorization_host": "https://social.kobobooks.com:8443",
        "social_host": "https://social.kobobooks.com",
        "store_home": "www.kobo.com/{region}/{language}",
        "store_host": "www.kobo.com",
        "store_newreleases": "https://www.kobo.com/{region}/{language}/List/new-releases/961XUjtsU0qxkFItWOutGA",
        "store_search": "https://www.kobo.com/{region}/{language}/Search?Query={query}",
        "store_top50": "https://www.kobo.com/{region}/{language}/ebooks/Top",
        "subs_landing_page": "https://www.kobo.com/{region}/{language}/plus",
        "subs_management_page": "https://www.kobo.com/{region}/{language}/account/subscriptions",
        "subs_plans_page": "https://www.kobo.com/{region}/{language}/plus/plans",
        "subs_purchase_buy_templated": "https://www.kobo.com/{region}/{language}/Checkoutoption/{ProductId}/{TierId}",
        "subscription_publisher_price_page": "https://www.kobo.com/{region}/{language}/subscriptionpublisherprice",
        "tag_items": "https://storeapi.kobo.com/v1/library/tags/{TagId}/Items",
        "tags": "https://storeapi.kobo.com/v1/library/tags",
        "taste_profile": "https://storeapi.kobo.com/v1/products/tasteprofile",
        "terms_of_sale_page": "https://authorize.kobo.com/{region}/{language}/terms/termsofsale",
        "update_accessibility_to_preview": "https://storeapi.kobo.com/v1/library/{EntitlementIds}/preview",
        "use_one_store": "True",
        "user_loyalty_benefits": "https://storeapi.kobo.com/v1/user/loyalty/benefits",
        "user_platform": "https://storeapi.kobo.com/v1/user/platform",
        "user_profile": "https://storeapi.kobo.com/v1/user/profile",
        "user_ratings": "https://storeapi.kobo.com/v1/user/ratings",
        "user_recommendations": "https://storeapi.kobo.com/v1/user/recommendations",
        "user_reviews": "https://storeapi.kobo.com/v1/user/reviews",
        "user_wishlist": "https://storeapi.kobo.com/v1/user/wishlist",
        "userguide_host": "https://ereaderfiles.kobo.com",
        "wishlist_page": "https://www.kobo.com/{region}/{language}/account/wishlist"
    }
