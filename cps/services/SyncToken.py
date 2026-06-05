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


class SyncToken:
    """ The SyncToken is used to persist state across requests.
    When serialized over the response headers, the Kobo device will propagate the token onto following
    requests to the service. As an example use-case, the SyncToken is used to detect books that have been added
    to the library since the last time the device synced to the server.

    Attributes:
        books_last_created: Datetime representing the newest book that the device knows about.
        books_last_modified: Datetime representing the last modified book that the device knows about.
        books_last_id: Composite-keyset tiebreaker — the last Books.id emitted at exactly
            books_last_modified. Walks paginated batches through blocks of books that share one
            last_modified (e.g. a bulk import). Default -1 means "no tiebreaker"; any valid book
            id is > -1, so old tokens still see every book at exactly books_last_modified on the
            first post-upgrade sync.
    """

    SYNC_TOKEN_HEADER = "x-kobo-synctoken"  # nosec
    VERSION = "1-2-0"
    LAST_MODIFIED_ADDED_VERSION = "1-1-0"
    MIN_VERSION = "1-0-0"

    token_schema = {
        "type": "object",
        "properties": {"version": {"type": "string"}, "data": {"type": "object"}, },
        "required": ["version", "data"],
    }
    # This Schema doesn't contain enough information to detect and propagate book deletions from Calibre to the device.
    # A potential solution might be to keep a list of all known book uuids in the token, and look for any missing
    # from the db.
    data_schema_v1 = {
        "type": "object",
        "properties": {
            "raw_kobo_store_token": {"type": "string"},
            "books_last_modified": {"type": "number"},
            "books_last_created": {"type": "number"},
            "archive_last_modified": {"type": "number"},
            "reading_state_last_modified": {"type": "number"},
            "tags_last_modified": {"type": "number"},
            "books_last_id": {"type": "integer"},
        },
    }

    def __init__(
        self,
        raw_kobo_store_token="",
        books_last_created=datetime.min,
        books_last_modified=datetime.min,
        archive_last_modified=datetime.min,
        reading_state_last_modified=datetime.min,
        tags_last_modified=datetime.min,
        books_last_id=-1,
    ):  # nosec
        self.raw_kobo_store_token = raw_kobo_store_token
        self.books_last_created = books_last_created
        self.books_last_modified = books_last_modified
        self.archive_last_modified = archive_last_modified
        self.reading_state_last_modified = reading_state_last_modified
        self.tags_last_modified = tags_last_modified
        self.books_last_id = books_last_id

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
            if sync_token_json["version"] < SyncToken.MIN_VERSION:
                raise ValueError

            data_json = sync_token_json["data"]
            validate(data_json, SyncToken.data_schema_v1)
            raw_kobo_store_token = data_json.get("raw_kobo_store_token", "")
        except (exceptions.ValidationError, ValueError, TypeError, KeyError):
            log.error("Sync token contents do not follow the expected json schema.")
            return SyncToken()
        try:
            books_last_modified = get_datetime_from_json(data_json, "books_last_modified")
            books_last_created = get_datetime_from_json(data_json, "books_last_created")
            archive_last_modified = get_datetime_from_json(data_json, "archive_last_modified")
            reading_state_last_modified = get_datetime_from_json(data_json, "reading_state_last_modified")
            tags_last_modified = get_datetime_from_json(data_json, "tags_last_modified")
        except TypeError:
            log.error("SyncToken timestamps don't parse to a datetime.")
            return SyncToken(raw_kobo_store_token=raw_kobo_store_token)

        books_last_id = data_json.get("books_last_id", -1)
        if not isinstance(books_last_id, int):
            books_last_id = -1

        return SyncToken(
            raw_kobo_store_token=raw_kobo_store_token,
            books_last_created=books_last_created,
            books_last_modified=books_last_modified,
            archive_last_modified=archive_last_modified,
            reading_state_last_modified=reading_state_last_modified,
            tags_last_modified=tags_last_modified,
            books_last_id=books_last_id,
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
                "archive_last_modified": to_epoch_timestamp(self.archive_last_modified),
                "reading_state_last_modified": to_epoch_timestamp(self.reading_state_last_modified),
                "tags_last_modified": to_epoch_timestamp(self.tags_last_modified),
                "books_last_id": self.books_last_id,
            },
        }
        return b64encode_json(token)

    def __str__(self):
        return "{},{},{},{},{},{},{}".format(self.books_last_created,
                                             self.books_last_modified,
                                             self.archive_last_modified,
                                             self.reading_state_last_modified,
                                             self.tags_last_modified,
                                             self.books_last_id,
                                             self.raw_kobo_store_token)
