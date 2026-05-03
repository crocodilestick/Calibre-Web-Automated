#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
from base64 import b64decode, b64encode
from jsonschema import validate, exceptions
from datetime import datetime

from flask import json
from .. import logger


log = logger.create()


def b64encode_json(json_data):
    return b64encode(json.dumps(json_data).encode()).decode("utf-8")


# Python3 has a timestamp() method we could be calling, however it's not available in python2.
def to_epoch_timestamp(datetime_object):
    return (datetime_object - datetime(1970, 1, 1)).total_seconds()


def get_datetime_from_json(json_object, field_name):
    try:
        return datetime.utcfromtimestamp(json_object[field_name])
    except (KeyError, OSError, OverflowError):
        # OSError is thrown on Windows if timestamp is <1970 or >2038
        return datetime.min


class SyncTokenPagination:
    """In-progress pagination state for a multi-page sync round.

    A ``SyncToken`` carries one of these (or ``None``) to remember where it
    is mid-round. ``snapshot_ts`` is the upper bound of the round's filter
    window — captured once at round start, immutable until the round ends —
    so books or reading states modified mid-round don't disrupt the cursor
    and instead get picked up cleanly in the next round.

    Each paginated section stores its id cursor and a running
    ``max_last_modified`` of everything it has shipped so far in this round.
    When the round completes, the watermarks on the parent ``SyncToken``
    advance to those max-shipped values. Advancing them to the snapshot_ts
    would also be a reasonable design choice, but keeping them at max-shipped
    can allow *some* concurrent changes with backdated timestamps to be picked
    up (e.g. book addition outside of calibre-web).
    """

    def __init__(
        self,
        snapshot_ts=datetime.min,
        books_last_id=0,
        books_max_last_modified=datetime.min,
        books_max_last_created=datetime.min,
        reading_state_last_id=0,
        reading_state_max_last_modified=datetime.min,
        visibility_max_last_modified=datetime.min,
    ):
        self.snapshot_ts = snapshot_ts
        self.books_last_id = books_last_id
        self.books_max_last_modified = books_max_last_modified
        self.books_max_last_created = books_max_last_created
        self.reading_state_last_id = reading_state_last_id
        self.reading_state_max_last_modified = reading_state_max_last_modified
        self.visibility_max_last_modified = visibility_max_last_modified

    def to_dict(self):
        return {
            "snapshot_ts": to_epoch_timestamp(self.snapshot_ts),
            "books_last_id": self.books_last_id,
            "books_max_last_modified": to_epoch_timestamp(self.books_max_last_modified),
            "books_max_last_created": to_epoch_timestamp(self.books_max_last_created),
            "reading_state_last_id": self.reading_state_last_id,
            "reading_state_max_last_modified": to_epoch_timestamp(self.reading_state_max_last_modified),
            "visibility_max_last_modified": to_epoch_timestamp(self.visibility_max_last_modified),
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            snapshot_ts=get_datetime_from_json(data, "snapshot_ts"),
            books_last_id=int(data.get("books_last_id", 0) or 0),
            books_max_last_modified=get_datetime_from_json(data, "books_max_last_modified"),
            books_max_last_created=get_datetime_from_json(data, "books_max_last_created"),
            reading_state_last_id=int(data.get("reading_state_last_id", 0) or 0),
            reading_state_max_last_modified=get_datetime_from_json(data, "reading_state_max_last_modified"),
            visibility_max_last_modified=get_datetime_from_json(data, "visibility_max_last_modified"),
        )

    def __str__(self):
        return ("snap={},books=(id>{},max_lm={},max_lc={}),"
                "rstate=(id>{},max_lm={}),vis_max_lm={}").format(
            self.snapshot_ts,
            self.books_last_id,
            self.books_max_last_modified,
            self.books_max_last_created,
            self.reading_state_last_id,
            self.reading_state_max_last_modified,
            self.visibility_max_last_modified,
        )


class SyncToken:
    """ The SyncToken is used to persist state across requests.
    When serialized over the response headers, the Kobo device will propagate the token onto following
    requests to the service. As an example use-case, the SyncToken is used to detect books that have been added
    to the library since the last time the device synced to the server.

    The token also carries a ``pagination`` slot that is non-None when a
    sync response is split across multiple requests. See
    ``SyncTokenPagination`` for the details of that state.

    Attributes:
        books_last_created: Datetime representing the newest book that the device knows about.
        books_last_modified: Datetime representing the last modified book that the device knows about.
    """

    SYNC_TOKEN_HEADER = "x-kobo-synctoken"  # nosec
    VERSION = "1-2-0"
    LAST_MODIFIED_ADDED_VERSION = "1-1-0"
    PAGINATION_ADDED_VERSION = "1-2-0"
    VISIBILITY_ADDED_VERSION = "1-2-0"
    MIN_VERSION = "1-0-0"

    token_schema = {
        "type": "object",
        "properties": {"version": {"type": "string"}, "data": {"type": "object"}, },
    }
    # This Schema doesn't contain enough information to detect and propagate book deletions from Calibre to the device.
    # A potential solution might be to keep a list of all known book uuids in the token, and look for any missing
    # from the db.
    data_schema_v1 = {
        "type": "object",
        "properties": {
            "raw_kobo_store_token": {"type": "string"},
            "books_last_modified": {"type": "string"},
            "books_last_created": {"type": "string"},
            "archive_last_modified": {"type": "string"},
            "reading_state_last_modified": {"type": "string"},
            "tags_last_modified": {"type": "string"},
        },
    }
    # v2 (>= "1-2-0"): visibility_last_modified replaces archive_last_modified, tracking
    # both KoboBookVisibility.last_modified and ArchivedBook.last_modified under one watermark.
    # A New Pagination object is added to better track paginated responses.
    data_schema_v2 = {
        "type": "object",
        "properties": {
            "raw_kobo_store_token": {"type": "string"},
            "books_last_modified": {"type": "string"},
            "books_last_created": {"type": "string"},
            "visibility_last_modified": {"type": "string"},
            "reading_state_last_modified": {"type": "string"},
            "tags_last_modified": {"type": "string"},
            "pagination": {"type": ["object", "null"]},
        },
    }

    def __init__(
        self,
        raw_kobo_store_token="",
        books_last_created=datetime.min,
        books_last_modified=datetime.min,
        visibility_last_modified=datetime.min,
        reading_state_last_modified=datetime.min,
        tags_last_modified=datetime.min,
        pagination=None,
        migrated_from_v1=False,
    ):  # nosec
        self.raw_kobo_store_token = raw_kobo_store_token
        self.books_last_created = books_last_created
        self.books_last_modified = books_last_modified
        self.visibility_last_modified = visibility_last_modified
        self.reading_state_last_modified = reading_state_last_modified
        self.tags_last_modified = tags_last_modified
        self.pagination = pagination
        self.migrated_from_v1 = migrated_from_v1  # transient; not serialized into build_sync_token()

    @staticmethod
    def from_headers(headers):
        sync_token_header = headers.get(SyncToken.SYNC_TOKEN_HEADER, "")
        if sync_token_header == "":  # nosec
            return SyncToken()

        # On the first sync from a Kobo device, we may receive the SyncToken
        # from the official Kobo store. Without digging too deep into it, that
        # token is of the form [b64encoded blob].[b64encoded blob 2]
        if "." in sync_token_header:
            return SyncToken(raw_kobo_store_token=sync_token_header)

        try:
            sync_token_json = json.loads(
                b64decode(sync_token_header + "=" * (-len(sync_token_header) % 4))
            )
            validate(sync_token_json, SyncToken.token_schema)
            token_version = sync_token_json["version"]
            if token_version < SyncToken.MIN_VERSION:
                raise ValueError

            data_json = sync_token_json["data"]
            # v1 tokens (< 1-2-0) track archive_last_modified; v2 (>= 1-2-0) replaced it with
            # visibility_last_modified, which covers both KoboBookVisibility and ArchivedBook.
            # Pagination and visibility landed in the same release, so the version boundary is the same.
            is_v1 = token_version < SyncToken.VISIBILITY_ADDED_VERSION
            validate(sync_token_json, SyncToken.data_schema_v1 if is_v1 else SyncToken.data_schema_v2)
        except (exceptions.ValidationError, ValueError):
            log.error("Sync token contents do not follow the expected json schema.")
            return SyncToken()

        raw_kobo_store_token = data_json["raw_kobo_store_token"]
        try:
            books_last_modified = get_datetime_from_json(data_json, "books_last_modified")
            books_last_created = get_datetime_from_json(data_json, "books_last_created")
            if is_v1:
                # Migration path: _HandleSyncRequest detects migrated_from_v1=True and resets all
                # watermarks to datetime.min, forcing a full re-sync.  With watermarks at minimum,
                # every book passes through the window: non-visible books emit
                # NewEntitlement(archived=True) via the is_newly_created path (ts_created >
                # datetime.min is always true), correctly signalling their removal to the device.
                visibility_last_modified = get_datetime_from_json(data_json, "archive_last_modified")
            else:
                visibility_last_modified = get_datetime_from_json(data_json, "visibility_last_modified")
            reading_state_last_modified = get_datetime_from_json(data_json, "reading_state_last_modified")
            tags_last_modified = get_datetime_from_json(data_json, "tags_last_modified")
        except TypeError:
            log.error("SyncToken timestamps don't parse to a datetime.")
            return SyncToken(raw_kobo_store_token=raw_kobo_store_token)

        # Pagination is optional: tokens generated before VERSION 1-2-0
        # (or the very first sync request from a device) don't carry it,
        # which means "no round in progress."
        pagination = SyncTokenPagination.from_dict(data_json.get("pagination"))

        return SyncToken(
            raw_kobo_store_token=raw_kobo_store_token,
            books_last_created=books_last_created,
            books_last_modified=books_last_modified,
            visibility_last_modified=visibility_last_modified,
            reading_state_last_modified=reading_state_last_modified,
            tags_last_modified=tags_last_modified,
            pagination=pagination,
            migrated_from_v1=is_v1,
        )

    def set_kobo_store_header(self, store_headers):
        store_headers.set(SyncToken.SYNC_TOKEN_HEADER, self.raw_kobo_store_token)

    def merge_from_store_response(self, store_response):
        self.raw_kobo_store_token = store_response.headers.get(
            SyncToken.SYNC_TOKEN_HEADER, ""
        )

    def to_headers(self, headers):
        headers[SyncToken.SYNC_TOKEN_HEADER] = self.build_sync_token()

    def build_sync_token(self):
        token = {
            "version": SyncToken.VERSION,
            "data": {
                "raw_kobo_store_token": self.raw_kobo_store_token,
                "books_last_modified": to_epoch_timestamp(self.books_last_modified),
                "books_last_created": to_epoch_timestamp(self.books_last_created),
                "visibility_last_modified": to_epoch_timestamp(self.visibility_last_modified),
                "reading_state_last_modified": to_epoch_timestamp(self.reading_state_last_modified),
                "tags_last_modified": to_epoch_timestamp(self.tags_last_modified),
                "pagination": self.pagination.to_dict() if self.pagination is not None else None,
            },
        }
        return b64encode_json(token)

    def __str__(self):
        return "{},{},{},{},{},{},pagination={}".format(
            self.books_last_created,
            self.books_last_modified,
            self.visibility_last_modified,
            self.reading_state_last_modified,
            self.tags_last_modified,
            self.raw_kobo_store_token,
            self.pagination,
        )
