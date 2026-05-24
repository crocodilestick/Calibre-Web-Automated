# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for HardcoverHandler — stateless push/delete + idempotency."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from cps.services.annotation_sync.hardcover import HardcoverHandler
from tests.fixtures.mock_hardcover_client import MockHardcoverClient


class FakeUser:
    def __init__(self, hardcover_token="tok", id=1):
        self.hardcover_token = hardcover_token
        self.id = id


def _book_with_isbn(book_id=1):
    return SimpleNamespace(
        id=book_id,
        title=f"Book {book_id}",
        identifiers=[SimpleNamespace(type="isbn", val="9780000000000")],
    )


class FakeAnnotation:
    """Mimics cps.ub.Annotation fields used by the handler."""

    def __init__(self, **kw):
        defaults = {
            "id": 1, "annotation_id": "kobo-uuid-001",
            "highlighted_text": "hello", "note_text": "note",
            "highlight_color": "yellow", "chapter_progress": 0.5,
            "source": "kobo",
        }
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)
        self._sync_target_row = kw.get("_sync_target_row")

    def sync_target(self, name):
        if self._sync_target_row and self._sync_target_row.target == name:
            return self._sync_target_row
        return None


def _make_handler(client, config_on=True, blacklisted=False, not_found_exc=None):
    return HardcoverHandler(
        client_factory=lambda token: client,
        config_getter=lambda: config_on,
        book_identifiers_getter=lambda b: {"isbn": "9780000000000"},
        blacklist_check=lambda book_id: blacklisted,
        not_found_exception=not_found_exc,
    )


def test_push_first_time_uses_add_journal_entry():
    client = MockHardcoverClient(add_response={"id": 999})
    h = _make_handler(client)
    result = h.push(FakeAnnotation(), _book_with_isbn(), FakeUser())
    assert result.status == "synced"
    assert result.target_record_id == "999"
    assert client.calls[0][0] == "add"


def test_push_existing_uses_update_journal_entry():
    """If annotation has an existing sync_target with record id, call update."""
    client = MockHardcoverClient(update_response={"id": 555})
    h = _make_handler(client)
    existing = SimpleNamespace(target="hardcover", target_record_id="555", status="synced")
    ann = FakeAnnotation(_sync_target_row=existing)
    result = h.push(ann, _book_with_isbn(), FakeUser())
    assert result.status == "synced"
    assert result.target_record_id == "555"
    assert client.calls[0][0] == "update"


def test_push_failed_on_empty_response():
    client = MockHardcoverClient(add_response={})
    h = _make_handler(client)
    result = h.push(FakeAnnotation(), _book_with_isbn(), FakeUser())
    assert result.status == "failed"
    assert result.error_message is not None


def test_push_catches_exception_as_failed():
    client = MockHardcoverClient(add_raises=RuntimeError("boom"))
    h = _make_handler(client)
    result = h.push(FakeAnnotation(), _book_with_isbn(), FakeUser())
    assert result.status == "failed"
    assert "boom" in (result.error_message or "")


def test_push_skipped_when_no_text():
    client = MockHardcoverClient()
    h = _make_handler(client)
    ann = FakeAnnotation(highlighted_text=None, note_text=None)
    result = h.push(ann, _book_with_isbn(), FakeUser())
    assert result.status == "failed"
    assert "no text" in (result.error_message or "").lower()
    assert client.calls == []


def test_push_skipped_when_blacklisted():
    client = MockHardcoverClient()
    h = _make_handler(client, blacklisted=True)
    result = h.push(FakeAnnotation(), _book_with_isbn(), FakeUser())
    assert result.status == "failed"
    assert "blacklisted" in (result.error_message or "").lower()
    assert client.calls == []


def test_push_skipped_when_no_identifiers():
    client = MockHardcoverClient()
    h = HardcoverHandler(
        client_factory=lambda token: client,
        config_getter=lambda: True,
        book_identifiers_getter=lambda b: {},  # no identifiers
        blacklist_check=lambda book_id: False,
    )
    result = h.push(FakeAnnotation(), _book_with_isbn(), FakeUser())
    assert result.status == "failed"
    assert "identifier" in (result.error_message or "").lower()


def test_delete_returns_tombstone_on_success():
    client = MockHardcoverClient(delete_response=123)
    h = _make_handler(client)
    st = SimpleNamespace(target_record_id="123", target="hardcover", status="synced")
    result = h.delete(st, FakeUser())
    assert result.status == "tombstone"
    assert result.target_record_id == "123"


def test_delete_treats_not_found_as_tombstone():
    class NotFound(Exception):
        pass
    client = MockHardcoverClient(delete_raises=NotFound("404"))
    h = _make_handler(client, not_found_exc=NotFound)
    st = SimpleNamespace(target_record_id="999", target="hardcover", status="synced")
    result = h.delete(st, FakeUser())
    assert result.status == "tombstone"
    assert "already deleted" in (result.error_message or "").lower()


def test_delete_failed_on_unrelated_exception():
    client = MockHardcoverClient(delete_raises=RuntimeError("network"))
    h = _make_handler(client)
    st = SimpleNamespace(target_record_id="123", target="hardcover", status="synced")
    result = h.delete(st, FakeUser())
    assert result.status == "failed"
    assert "network" in (result.error_message or "")


def test_is_enabled_requires_user_token_and_global_config():
    client = MockHardcoverClient()
    h = _make_handler(client, config_on=True)
    assert h.is_enabled(FakeUser(hardcover_token="t")) is True
    assert h.is_enabled(FakeUser(hardcover_token=None)) is False
    h2 = _make_handler(client, config_on=False)
    assert h2.is_enabled(FakeUser(hardcover_token="t")) is False
