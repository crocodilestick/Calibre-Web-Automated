# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo sync timestamp selection"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kobo_sync_utils import get_kobo_created_ts


def _make_book(*, timestamp=None, date_added=None, last_modified=None, book_id=1):
    return SimpleNamespace(
        Books=SimpleNamespace(
            id=book_id,
            timestamp=timestamp,
            last_modified=last_modified,
        ),
        date_added=date_added,
    )


@pytest.mark.unit
class TestKoboCreatedTimestamp:
    """Test _get_kobo_created_ts behavior"""

    def test_all_missing_returns_datetime_min(self):
        book = _make_book()
        assert get_kobo_created_ts(book) == datetime.min

    def test_uses_timestamp_when_available(self):
        ts = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        book = _make_book(timestamp=ts)
        assert get_kobo_created_ts(book) == ts.replace(tzinfo=None)

    def test_uses_date_added_when_timestamp_missing(self):
        date_added = datetime(2026, 2, 1, 8, 30, 0)
        book = _make_book(date_added=date_added)
        assert get_kobo_created_ts(book) == date_added

    def test_prefers_later_of_timestamp_and_date_added(self):
        ts = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        date_added = datetime(2026, 2, 1, 13, 15, 0)
        book = _make_book(timestamp=ts, date_added=date_added)
        assert get_kobo_created_ts(book) == date_added

    def test_falls_back_to_last_modified(self):
        last_modified = datetime(2026, 2, 1, 14, 45, 0, tzinfo=timezone.utc)
        book = _make_book(last_modified=last_modified)
        assert get_kobo_created_ts(book) == last_modified.replace(tzinfo=None)