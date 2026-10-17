# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from format_tiers import (
    DEFAULT_FORMAT_PRIORITY,
    best_format_rank,
    format_priority_from_settings,
    format_rank,
)

from .test_duplicates_timezone import _load_duplicates_module


pytestmark = pytest.mark.unit


def test_priority_from_settings_uppercases_formats():
    settings = {"duplicate_format_priority": '{"epub": 10, "Mobi": 20}'}
    assert format_priority_from_settings(settings) == {"EPUB": 10, "MOBI": 20}


@pytest.mark.parametrize("value", ["", "not json", "[1, 2]", "{}", None])
def test_priority_from_settings_falls_back_to_defaults(value):
    assert format_priority_from_settings({"duplicate_format_priority": value}) == DEFAULT_FORMAT_PRIORITY


def test_converted_format_ranks_as_its_source():
    assert format_rank("epub", DEFAULT_FORMAT_PRIORITY) == 100
    assert format_rank("epub", DEFAULT_FORMAT_PRIORITY, "mobi") == 80
    assert format_rank("lit", DEFAULT_FORMAT_PRIORITY) == 0


def test_best_rank_uses_origins():
    priority = DEFAULT_FORMAT_PRIORITY
    assert best_format_rank(["EPUB", "PDF"], priority) == 100
    assert best_format_rank(["EPUB", "PDF"], priority, {"EPUB": "PDF"}) == 60
    assert best_format_rank(["EPUB", "MOBI"], priority, {"EPUB": "MOBI"}) == 80
    assert best_format_rank([], priority) == 0


def _keep_native_or_converted(monkeypatch, rank_converted_as_source):
    duplicates = _load_duplicates_module()

    class FakeDb:
        cwa_settings = {"duplicate_rank_converted_as_source": rank_converted_as_source}

        def format_origins_for_books(self, book_ids):
            return {2: {"EPUB": "MOBI"}}

    monkeypatch.setattr(duplicates, "CWA_DB", FakeDb, raising=False)

    def book(book_id, day):
        return SimpleNamespace(id=book_id, timestamp=datetime(2024, 1, day, tzinfo=timezone.utc),
                               data=[SimpleNamespace(format="EPUB")])

    native = book(1, 1)
    converted = book(2, 2)  # newer, so it wins the tie when origins are ignored
    kept = duplicates.select_book_to_keep([native, converted], "highest_quality_format")
    return "native" if kept is native else "converted"


def test_highest_quality_format_prefers_native_when_enabled(monkeypatch):
    assert _keep_native_or_converted(monkeypatch, 1) == "native"


def test_highest_quality_format_ignores_origins_by_default(monkeypatch):
    assert _keep_native_or_converted(monkeypatch, 0) == "converted"
