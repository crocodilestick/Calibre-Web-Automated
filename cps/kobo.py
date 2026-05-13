#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import base64
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
)
from .cw_login import current_user
from werkzeug.datastructures import Headers
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.expression import and_, or_
from sqlalchemy.exc import StatementError
import requests

from . import config, logger, kobo_auth, db, calibre_db, helper, shelf as shelf_lib, ub, csrf, kobo_sync_status, magic_shelf
from . import isoLanguages
from .epub import get_epub_layout
from .constants import COVER_THUMBNAIL_SMALL, COVER_THUMBNAIL_MEDIUM, COVER_THUMBNAIL_LARGE
from .kobo_cover_cache import build_cover_image_id, normalize_cover_uuid
from .helper import get_download_link
from .services import SyncToken as SyncToken, hardcover
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

    # If a Force Full Sync was requested for this user, drop the incoming token's state
    # so that the response replays the entire library, then clear the flag.
    if getattr(current_user, 'kobo_force_full_sync', False):
        log.info("Kobo Sync: full re-sync requested for user %s; ignoring incoming SyncToken", current_user.name)
        sync_token = SyncToken.SyncToken(raw_kobo_store_token=sync_token.raw_kobo_store_token)
        try:
            user_record = ub.session.query(ub.User).filter(ub.User.id == int(current_user.id)).one_or_none()
            if user_record is not None:
                user_record.kobo_force_full_sync = False
                ub.session_commit()
        except Exception as e:
            log.error("Kobo Sync: failed to clear kobo_force_full_sync flag: %s", e)
            ub.session.rollback()
    elif getattr(sync_token, 'migrated_from_v1', False):
        # First sync after upgrading from a v1 token (pre-KoboBookVisibility).
        # In the old v1 protocol, the Kobo device is only aware of visible books, where-as in the new v2 protocol the device is aware of all books regardless of visibility. We need to force a full resync to correct the device state for the v2 protocol expectations.
        log.info("Kobo Sync: v1→v2 token migration for user %s; forcing full re-sync "
                 "to inform device of non-visible Entitlement Ids", current_user.name)
        sync_token = SyncToken.SyncToken(raw_kobo_store_token=sync_token.raw_kobo_store_token)

    only_kobo_shelves = current_user.kobo_only_shelves_sync

    # Initialize pagination state. Reconnect db and refresh Magic-shelf state on the first request
    if sync_token.pagination is not None:
        pagination = sync_token.pagination
    else:
        calibre_db.reconnect_db(config, ub.app_DB_path)
        if only_kobo_shelves and config.config_kobo_sync_magic_shelves:
            magic_shelf.update_kobo_book_visibility_from_magic_shelves(current_user.id)
        pagination = SyncToken.SyncTokenPagination(snapshot_ts=datetime.utcnow())

    sync_results = []

    log.debug("Kobo Sync: books last modified: {}, visibility last modified: {}, pagination: {}".format(
        sync_token.books_last_modified, sync_token.visibility_last_modified, pagination))

    query_window = or_(
        and_(db.Books.last_modified > sync_token.books_last_modified,
             db.Books.last_modified <= pagination.snapshot_ts),
        and_(ub.KoboBookVisibility.last_modified > sync_token.visibility_last_modified,
             ub.KoboBookVisibility.last_modified <= pagination.snapshot_ts),
        and_(ub.ArchivedBook.last_modified > sync_token.visibility_last_modified,
             ub.ArchivedBook.last_modified <= pagination.snapshot_ts),
        and_(
            ub.KoboReadingState.last_modified > sync_token.reading_state_last_modified,
            ub.KoboReadingState.last_modified <= pagination.snapshot_ts,
        ),
    )

    # Iterate over all books in increasing BookId order. If results are too large, the sync process is paginated and the next request will resume starting at the last book_id synced returned in the previous response.
    # selectinload fetches each relationship for all books in one IN-list query rather than
    # one query per book, turning O(n*r) lazy loads into O(r) batch fetches.
    changed_entries = (calibre_db.session.query(
                            db.Books,
                            ub.ArchivedBook.is_archived.label('is_archived'),
                            ub.ArchivedBook.last_modified.label('archived_last_modified'),
                            ub.KoboBookVisibility.is_visible.label('is_visible'),
                            ub.KoboBookVisibility.last_modified.label('visible_last_modified'),
                            ub.KoboReadingState,
                       )
                       .options(
                           selectinload(db.Books.authors),
                           selectinload(db.Books.languages),
                           selectinload(db.Books.series),
                           selectinload(db.Books.publishers),
                           selectinload(db.Books.comments),
                           selectinload(db.Books.data),
                       )
                       .outerjoin(ub.ArchivedBook, and_(db.Books.id == ub.ArchivedBook.book_id,
                                                       ub.ArchivedBook.user_id == current_user.id))
                       .outerjoin(ub.KoboBookVisibility, and_(db.Books.id == ub.KoboBookVisibility.book_id,
                                                              ub.KoboBookVisibility.user_id == current_user.id))
                       .outerjoin(ub.KoboReadingState, and_(
                           db.Books.id == ub.KoboReadingState.book_id,
                           ub.KoboReadingState.user_id == current_user.id,
                        ))
                       .filter(query_window)
                       .filter(db.Books.id > pagination.books_last_id)
                       .filter(calibre_db.common_filters(allow_show_archived=True))
                       .order_by(db.Books.id))

    # Fetch one extra row to detect whether more pages remain without a separate count query.
    book_rows = changed_entries.limit(SYNC_ITEM_LIMIT + 1).all()
    has_more = len(book_rows) > SYNC_ITEM_LIMIT
    book_rows = book_rows[:SYNC_ITEM_LIMIT]
    log.debug("Kobo Sync: selected to sync: %s (more=%s)", len(book_rows), has_more)

    for book in book_rows:
        kobo_reading_state = book.KoboReadingState

        # A book is visible if it's not archived and if it's on a kobo synced shelf
        is_visible = not bool(book.is_archived)
        if only_kobo_shelves:
            is_visible = is_visible and bool(book.is_visible)

        ts_created = get_kobo_created_ts(book)

        book_last_modified = book.Books.last_modified
        book_last_modified = book_last_modified.replace(tzinfo=None) if book_last_modified else None

        visible_last_modified = book.visible_last_modified
        if visible_last_modified and hasattr(visible_last_modified, 'replace'):
            visible_last_modified = visible_last_modified.replace(tzinfo=None)
        archived_lm = book.archived_last_modified
        if archived_lm and hasattr(archived_lm, 'replace'):
            archived_lm = archived_lm.replace(tzinfo=None)

        is_newly_created = ts_created > sync_token.books_last_created
        visibility_changed = any(
            t is not None and t > sync_token.visibility_last_modified
            for t in (visible_last_modified, archived_lm)
        )
        metadata_changed = (book_last_modified is not None
                            and book_last_modified > sync_token.books_last_modified)
  
        if is_newly_created:
            new_entry = {
                "BookEntitlement": create_book_entitlement(book.Books, archived=not is_visible),
                "BookMetadata": get_metadata(book.Books) if is_visible else get_removed_metadata(book.Books.uuid),
            }
            if is_visible and kobo_reading_state is not None:
                new_entry["ReadingState"] = get_kobo_reading_state_response(book.Books, kobo_reading_state)
            sync_results.append({"NewEntitlement": new_entry})
        elif visibility_changed:
            sync_results.append({"ChangedEntitlement": {
                "BookEntitlement": create_book_entitlement(book.Books, archived=not is_visible),
            }})
            if is_visible:
                # Refresh the metadata for a newly visible book, since we previously may have sent a placeholder with empty metadata.
                sync_results.append({"ChangedProductMetadata": {
                    "BookMetadata": get_metadata(book.Books),
                }})
                if kobo_reading_state is not None:
                    sync_results.append({"ChangedReadingState": {
                        "ReadingState": get_kobo_reading_state_response(book.Books, kobo_reading_state),
                    }})
        elif is_visible:
            # Already visible book that's not newly created, must be a modified book or modified reading state:
            if metadata_changed:
                sync_results.append({"ChangedProductMetadata": {
                    "BookMetadata": get_metadata(book.Books),
                }})
            if kobo_reading_state is not None and kobo_reading_state.last_modified > sync_token.reading_state_last_modified:
                sync_results.append({"ChangedReadingState": {
                    "ReadingState": get_kobo_reading_state_response(book.Books, kobo_reading_state),
                }})

        # Advance all per-signal watermarks unconditionally each iteration.
        if book_last_modified and book_last_modified <= pagination.snapshot_ts:
            pagination.books_max_last_modified = max(
                pagination.books_max_last_modified, book_last_modified)
        vis_candidates = [t for t in (visible_last_modified, archived_lm) if t is not None and t <= pagination.snapshot_ts]
        if vis_candidates:
            pagination.visibility_max_last_modified = max(
                pagination.visibility_max_last_modified, max(vis_candidates))
        if kobo_reading_state is not None and kobo_reading_state.last_modified <= pagination.snapshot_ts:
            pagination.reading_state_max_last_modified = max(
                pagination.reading_state_max_last_modified, kobo_reading_state.last_modified)
        pagination.books_max_last_created = max(pagination.books_max_last_created, ts_created)
        pagination.books_last_id = book.Books.id

    cont_sync = has_more
    log.debug("Kobo Sync: more to sync: {}".format(has_more))

    if not cont_sync:
        sync_shelves(sync_token, sync_results, only_kobo_shelves)

    # Add magic shelves as collections
    if not cont_sync and config.config_kobo_sync_magic_shelves:

        for shelf in ub.session.query(ub.MagicShelf)\
            .filter_by(user_id=current_user.id, kobo_sync=False)\
            .all():

            sync_results.append({
                "DeletedTag": {
                    "Tag": {
                        "Id": shelf.uuid,
                        "LastModified": convert_to_kobo_timestamp_string(shelf.last_modified)
                    }
                }
            })

        magic_shelves = ub.session.query(ub.MagicShelf)\
            .filter_by(user_id=current_user.id, kobo_sync=True)\
            .all()

        new_tags_last_modified = sync_token.tags_last_modified
            
        for shelf in magic_shelves:
            books, _ = magic_shelf.get_books_for_magic_shelf(
                shelf.id, page=1, page_size=1000
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

    # If any section has more pages to send, hand the pagination object back
    # on the token so the next request can resume against the same snapshot.
    # When the round is complete, advance each section's watermark to its
    # max-shipped value that was below snapshot_ts. We use the max-shipped value
    # instead of snapshot_ts in case a book was concurrently added to the database
    # outside of calibre-web, in which case it may have a last_created timestamp
    # larger than all the existing last_created, but smaller than snapshot_ts.
    if cont_sync:
        sync_token.pagination = pagination
    else:
        sync_token.books_last_modified = max(
            sync_token.books_last_modified, pagination.books_max_last_modified)
        sync_token.books_last_created = max(
            sync_token.books_last_created, pagination.books_max_last_created)
        sync_token.reading_state_last_modified = max(
            sync_token.reading_state_last_modified, pagination.reading_state_max_last_modified)
        sync_token.visibility_last_modified = max(
            sync_token.visibility_last_modified, pagination.visibility_max_last_modified)
        sync_token.pagination = None

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
    book = calibre_db.get_book_by_uuid(book_uuid)
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


def get_seriesindex(book):
    return book.series_index if isinstance(book.series_index, float) else 1


def get_language(book):
    if not book.languages:
        return 'en'
    return isoLanguages.get(part3=book.languages[0].lang_code).part1


def _normalize_cover_uuid(image_id):
    return normalize_cover_uuid(image_id)


def _get_cover_image_id(book):
    base_id = str(book.uuid)
    try:
        cover_path = None
        if not config.config_use_google_drive:
            cover_path = os.path.join(config.get_book_path(), book.path, "cover.jpg")
        return build_cover_image_id(
            base_id,
            use_google_drive=config.config_use_google_drive,
            last_modified=book.last_modified,
            cover_path=cover_path,
        )
    except Exception as exc:
        log.debug("Kobo Sync: failed to build cover image id for book %s: %s", book.id, exc)
        return base_id


def get_removed_metadata(book_uuid):
    book_uuid = str(book_uuid)
    return {
        "Categories": ["00000000-0000-0000-0000-000000000001"],
        "CoverImageId": book_uuid,
        "CrossRevisionId": book_uuid,
        "CurrentDisplayPrice": {"CurrencyCode": "USD", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": "",
        "DownloadUrls": [],
        "EntitlementId": book_uuid,
        "ExternalIds": [],
        "Genre": "00000000-0000-0000-0000-000000000001",
        "IsEligibleForKoboLove": False,
        "IsInternetArchive": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": "en",
        "PhoneticPronunciations": {},
        "PublicationDate": None,
        "Publisher": {"Imprint": "", "Name": ""},
        "RevisionId": book_uuid,
        "Title": "",
        "WorkId": book_uuid,
        "Series": {},
        "Contributors": None,
    }


def get_metadata(book):
    download_urls = []

    kepub_data = next((d for d in book.data if d.format == 'KEPUB'), None)
    epub_data  = next((d for d in book.data if d.format == 'EPUB'),  None)

    if kepub_data:
        book_data, dl_format, published_format = kepub_data, 'kepub', 'KEPUB'
    elif epub_data and config.config_kepubifypath:
        book_data, dl_format, published_format = epub_data, 'kepub', 'KEPUB'
    elif epub_data:
        book_data, dl_format, published_format = epub_data, 'epub', 'EPUB3'
    else:
        book_data = None

    if book_data:
        try:
            if get_epub_layout(book, book_data) == 'pre-paginated':
                published_format = 'EPUB3FL'
        except (zipfile.BadZipfile, FileNotFoundError) as e:
            log.error(e)
        download_urls.append({
            "Format": published_format,
            "Size": book_data.uncompressed_size,
            "Url": get_download_url_for_book(book.id, dl_format),
            "Platform": "Generic",
            "DrmType": "None",
        })

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
        shelf = ub.Shelf(user_id=current_user.id, name=name, uuid=str(uuid.uuid4()))
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
        log.debug("Received Kobo tag update request on a collection unknown to CalibreWeb")
        if config.config_kobo_proxy:
            return redirect_or_proxy_request()
        else:
            abort(404, description="Collection isn't known to CalibreWeb")

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
    added_book_ids = []
    for item in items:
        try:
            if item["Type"] != "ProductRevisionTagItem":
                items_unknown_to_calibre.append(item)
                continue

            book = calibre_db.get_book_by_uuid(item["RevisionId"])
            if not book:
                items_unknown_to_calibre.append(item)
                continue

            book_id = book.id
            if book_id not in book_ids_already_in_shelf:
                shelf.books.append(ub.BookShelf(book_id=book_id))
                added_book_ids.append(book_id)
        except KeyError:
            items_unknown_to_calibre.append(item)
    if shelf.kobo_sync and added_book_ids:
        kobo_sync_status.set_kobo_visibility(added_book_ids, shelf.user_id, is_visible=True)
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
        log.debug(
            "Received a request to remove an item from a Collection unknown to CalibreWeb.")
        abort(404, description="Collection isn't known to CalibreWeb")

    if not shelf_lib.check_shelf_edit_permissions(shelf):
        abort(401, description="User is unauthaurized to edit shelf.")

    items_unknown_to_calibre = []
    removed_book_ids = []
    for item in items:
        try:
            if item["Type"] != "ProductRevisionTagItem":
                items_unknown_to_calibre.append(item)
                continue

            book = calibre_db.get_book_by_uuid(item["RevisionId"])
            if not book:
                items_unknown_to_calibre.append(item)
                continue

            shelf.books.filter(ub.BookShelf.book_id == book.id).delete()
            removed_book_ids.append(book.id)
        except KeyError:
            items_unknown_to_calibre.append(item)
    ub.session_commit()
    if shelf.kobo_sync and removed_book_ids:
        kobo_sync_status.recompute_kobo_visibility(removed_book_ids, shelf.user_id)

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
            not ub.Shelf.kobo_sync
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
    book = calibre_db.get_book_by_uuid(book_uuid)
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

            request_bookmark = request_reading_state["CurrentBookmark"]
            if request_bookmark:
                current_bookmark = kobo_reading_state.current_bookmark
                current_bookmark.progress_percent = request_bookmark["ProgressPercent"]
                current_bookmark.content_source_progress_percent = request_bookmark["ContentSourceProgressPercent"]
                location = request_bookmark["Location"]
                if location:
                    current_bookmark.location_value = location["Value"]
                    current_bookmark.location_type = location["Type"]
                    current_bookmark.location_source = location["Source"]
                update_results_response["CurrentBookmarkResult"] = {"Result": "Success"}

            request_statistics = request_reading_state["Statistics"]
            if request_statistics:
                statistics = kobo_reading_state.statistics
                statistics.spent_reading_minutes = int(request_statistics["SpentReadingMinutes"])
                statistics.remaining_time_minutes = int(request_statistics["RemainingTimeMinutes"])
                update_results_response["StatisticsResult"] = {"Result": "Success"}

            request_status_info = request_reading_state["StatusInfo"]
            if request_status_info:
                book_read = kobo_reading_state.book_read_link
                new_book_read_status = get_ub_read_status(request_status_info["Status"])
                if new_book_read_status == ub.ReadBook.STATUS_IN_PROGRESS \
                        and new_book_read_status != book_read.read_status:
                    book_read.times_started_reading += 1
                    book_read.last_time_started_reading = datetime.now(timezone.utc)
                book_read.read_status = new_book_read_status
                update_results_response["StatusInfoResult"] = {"Result": "Success"}
        except (KeyError, TypeError, ValueError, StatementError):
            log.debug("Received malformed v1/library/<book_uuid>/state request.")
            ub.session.rollback()
            abort(400, description="Malformed request data is missing 'ReadingStates' key")

        push_reading_state_to_hardcover(book, request_bookmark)

        ub.session.merge(kobo_reading_state)
        ub.session_commit()
        return jsonify({
            "RequestResult": "Success",
            "UpdateResults": [update_results_response],
        })


def push_reading_state_to_hardcover(book: db.Books, request_bookmark: dict):
    """
    Sync reading progress to Hardcover if enabled for the user and book is not blacklisted.

    Most exceptions are caught and logged so that issues with Hardcover do not prevent
    the Kobo from clearing its reading state sync queue.

    :param book: The book for which to sync reading progress.
    :param request_bookmark: The bookmark data from the Kobo request.
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
        hardcoverClient = hardcover.HardcoverClient(current_user.hardcover_token)
    except hardcover.MissingHardcoverToken:
        log.info(f"User {current_user.name} has no Hardcover token, not syncing reading progress to Hardcover")
        return
    except Exception as e:
        log.error(f"Failed to create Hardcover client for user {current_user.name}: {e}")
        return

    try:
        hardcoverClient.update_reading_progress(book.identifiers, request_bookmark["ProgressPercent"])
    except Exception as e:
        log.error(f"Failed to update reading progress for book {book.id} in Hardcover: {e}")


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
    book_read = ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.book_id == book_id,
        ub.ReadBook.user_id == int(current_user.id),
    ).one_or_none()
    if not book_read:
        book_read = ub.ReadBook(user_id=current_user.id, book_id=book_id)
    if not book_read.kobo_reading_state:
        kobo_reading_state = ub.KoboReadingState(user_id=book_read.user_id, book_id=book_id)
        kobo_reading_state.current_bookmark = ub.KoboBookmark()
        kobo_reading_state.statistics = ub.KoboStatistics()
        book_read.kobo_reading_state = kobo_reading_state
    ub.session.add(book_read)
    ub.session_commit()
    return book_read.kobo_reading_state


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
    if statistics.spent_reading_minutes:
        resp["SpentReadingMinutes"] = statistics.spent_reading_minutes
    if statistics.remaining_time_minutes:
        resp["RemainingTimeMinutes"] = statistics.remaining_time_minutes
    return resp


def get_current_bookmark_response(current_bookmark):
    resp = {
        "LastModified": convert_to_kobo_timestamp_string(current_bookmark.last_modified),
    }
    if current_bookmark.progress_percent:
        resp["ProgressPercent"] = current_bookmark.progress_percent
    if current_bookmark.content_source_progress_percent:
        resp["ContentSourceProgressPercent"] = current_bookmark.content_source_progress_percent
    if current_bookmark.location_value:
        resp["Location"] = {
            "Value": current_bookmark.location_value,
            "Type": current_bookmark.location_type,
            "Source": current_bookmark.location_source,
        }
    return resp


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
    book = calibre_db.get_book_by_uuid(book_uuid)
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
        "user_id": content.get("user_id", ""),
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
@kobo.route("/oauth/token", methods=["GET", "POST"])
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
        if config.config_hardcover_annotations_sync and bool(hardcover):
            kobo_resources["reading_services_host"] = calibre_web_url
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
        if config.config_hardcover_annotations_sync and bool(hardcover):
            kobo_resources["reading_services_host"] = url_for("web.index", _external=True).strip("/")

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
