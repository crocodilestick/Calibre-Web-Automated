# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for SyncToken composite-keyset support (fork #347).

The Kobo sync cursor used to track ``books_last_modified`` alone.
When more than SYNC_ITEM_LIMIT books share one ``last_modified``
(typical bulk-import signature — 4458 books all stamped one second
in @andree392's case), the cursor cannot step past the tied block:
it either re-sends the same first 50 forever (the observed loop)
or skips the remainder.

The fix adds an ID tiebreaker to the cursor. SyncToken gains
``books_last_id`` so the wire format can carry it. This file pins:

- The field exists, defaults to ``-1``, round-trips through the
  base64-encoded JSON token format.
- Old tokens (pre-upgrade, no ``books_last_id`` in the payload)
  parse cleanly and default the field to ``-1``. Backward-compat:
  a device on a pre-upgrade token does NOT force a full re-sync
  and does NOT drop books at exactly ``books_last_modified`` —
  ``id > -1`` is True for every valid book id, so all books at the
  cursor's exact timestamp are emitted on the first post-upgrade
  sync.
- A garbage ``books_last_id`` value (string, list, null) defaults
  to -1 rather than crashing.
- The VERSION advanced to "1-2-0"; MIN_VERSION stays "1-0-0"
  so devices on older tokens still parse without forced re-sync.
"""

import base64
import json
from datetime import datetime

import pytest

from cps.services.SyncToken import SyncToken


def _encode(payload):
    return base64.b64encode(json.dumps(payload).encode()).decode("utf-8")


@pytest.mark.unit
class TestSyncTokenBooksLastIdField:
    def test_field_defaults_to_minus_one(self):
        token = SyncToken()
        assert token.books_last_id == -1, (
            "Default must be -1 so the keyset arm 'id > books_last_id' "
            "matches every valid book id at the cursor's timestamp — "
            "old tokens (pre-upgrade) must not drop books."
        )

    def test_field_accepts_explicit_value(self):
        token = SyncToken(books_last_id=42)
        assert token.books_last_id == 42

    def test_field_round_trips_through_build_and_from_headers(self):
        original = SyncToken(books_last_id=1234)
        encoded = original.build_sync_token()
        rehydrated = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert rehydrated.books_last_id == 1234

    def test_default_round_trips(self):
        original = SyncToken()
        encoded = original.build_sync_token()
        rehydrated = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert rehydrated.books_last_id == -1


@pytest.mark.unit
class TestSyncTokenBackwardCompat:
    def test_old_token_missing_books_last_id_defaults_to_minus_one(self):
        """A device that last synced pre-upgrade sends a token with no
        ``books_last_id`` key. Must parse cleanly and default to -1, NOT
        crash and NOT force a full re-sync."""
        encoded = _encode({
            "version": "1-1-0",
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 1735689600.0,
                "books_last_created": 1735689600.0,
                "archive_last_modified": 1735689600.0,
                "reading_state_last_modified": 1735689600.0,
                "tags_last_modified": 1735689600.0,
                # NB: no books_last_id key — pre-upgrade token shape
            },
        })
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert token.books_last_id == -1
        # Other fields must still parse correctly
        assert token.books_last_modified == datetime(2025, 1, 1, 0, 0, 0)

    def test_garbage_books_last_id_string_defaults_to_minus_one(self):
        encoded = _encode({
            "version": SyncToken.VERSION,
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 0,
                "books_last_id": "not-an-int",
            },
        })
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        # jsonschema rejects {"type": "integer"} for a string, so the
        # whole data block fails validation -> default SyncToken returned.
        assert token.books_last_id == -1

    def test_garbage_books_last_id_null_defaults_to_minus_one(self):
        encoded = _encode({
            "version": SyncToken.VERSION,
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 0,
                "books_last_id": None,
            },
        })
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        # jsonschema rejects null for {"type": "integer"} -> default SyncToken.
        assert token.books_last_id == -1


@pytest.mark.unit
class TestSyncTokenVersion:
    def test_version_is_one_dash_three_zero_or_greater(self):
        """VERSION advanced 1-2-0 → 1-3-0 when the schema gained
        magic_shelf_last_id (fork #359 v4.0.153 follow-up).
        Accept >= 1-3-0 so this test doesn't go red on the next bump."""
        v = SyncToken.VERSION
        assert v >= "1-3-0", (
            f"VERSION must be >= 1-3-0 (added magic_shelf_last_id), got {v}"
        )

    def test_min_version_unchanged_at_one_zero_zero(self):
        assert SyncToken.MIN_VERSION == "1-0-0", (
            "MIN_VERSION must NOT change — devices on pre-1-2-0 tokens "
            "must still parse without forced re-sync; the new field is "
            "additive and defaults to -1 (compatible) if absent."
        )

    def test_token_built_carries_advanced_version(self):
        encoded = SyncToken().build_sync_token()
        wrapper = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4)))
        assert wrapper["version"] >= "1-3-0"

    def test_books_last_id_present_in_built_data_payload(self):
        encoded = SyncToken(books_last_id=99).build_sync_token()
        wrapper = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4)))
        assert wrapper["data"]["books_last_id"] == 99


@pytest.mark.unit
class TestSyncTokenMagicShelfLastId:
    def test_field_defaults_to_minus_one(self):
        assert SyncToken().magic_shelf_last_id == -1

    def test_round_trip_through_build_and_from_headers(self):
        original = SyncToken(magic_shelf_last_id=987)
        encoded = original.build_sync_token()
        rehydrated = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert rehydrated.magic_shelf_last_id == 987

    def test_old_token_missing_magic_shelf_last_id_defaults_to_minus_one(self):
        encoded = _encode({
            "version": "1-2-0",
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 0,
                "books_last_id": 42,
                # no magic_shelf_last_id — pre-1-3-0 token shape
            },
        })
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert token.magic_shelf_last_id == -1
        assert token.books_last_id == 42

    def test_garbage_magic_shelf_last_id_defaults_to_minus_one(self):
        encoded = _encode({
            "version": SyncToken.VERSION,
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 0,
                "magic_shelf_last_id": "not-an-int",
            },
        })
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert token.magic_shelf_last_id == -1

    def test_present_in_built_data_payload(self):
        encoded = SyncToken(magic_shelf_last_id=555).build_sync_token()
        wrapper = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4)))
        assert wrapper["data"]["magic_shelf_last_id"] == 555
