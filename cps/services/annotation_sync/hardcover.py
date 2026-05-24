# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""HardcoverHandler — push/delete annotations to Hardcover.

Extracted from cps/readingservices.py:process_annotation_for_sync as part
of the source/sync-target decoupling.

The handler is stateless — all DB writes happen in the dispatcher.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .base import AnnotationSyncTargetHandler, SyncResult

log = logging.getLogger(__name__)


def _default_client_factory(token):
    """Lazy import so unit tests don't need the full Hardcover service."""
    from cps.services import hardcover as _hardcover
    return _hardcover.HardcoverClient(token)


def _default_config_getter():
    from cps import config
    return bool(
        getattr(config, "config_hardcover_annotations_sync", False)
        and getattr(config, "config_kobo_sync", False)
    )


def _default_book_identifiers(book):
    """Mirror of readingservices.get_book_identifiers."""
    identifiers = {}
    if book and getattr(book, "identifiers", None):
        for identifier in book.identifiers:
            id_type = (identifier.type or "").lower()
            if id_type in ("hardcover-id", "hardcover-edition", "hardcover-slug", "isbn"):
                identifiers[id_type] = identifier.val
    return identifiers


def _default_blacklist_check(book_id):
    """True if this book is blacklisted for Hardcover annotation sync."""
    from cps import ub
    row = ub.session.query(ub.HardcoverBookBlacklist).filter(
        ub.HardcoverBookBlacklist.book_id == book_id,
    ).first()
    return bool(row and row.blacklist_annotations)


class HardcoverHandler(AnnotationSyncTargetHandler):
    """Push/delete annotations to Hardcover. Reads everything it needs
    from the Annotation ORM row + the optional payload."""

    target_name = "hardcover"

    def __init__(
        self,
        client_factory: Callable = _default_client_factory,
        config_getter: Callable[[], bool] = _default_config_getter,
        book_identifiers_getter: Callable = _default_book_identifiers,
        blacklist_check: Callable[[int], bool] = _default_blacklist_check,
        not_found_exception: Optional[type] = None,
    ):
        self._client_factory = client_factory
        self._config_getter = config_getter
        self._book_identifiers_getter = book_identifiers_getter
        self._blacklist_check = blacklist_check
        self._not_found_exception = not_found_exception

    def is_enabled(self, user) -> bool:
        if not self._config_getter():
            return False
        if not getattr(user, "hardcover_token", None):
            return False
        return True

    def push(self, annotation, book, user, payload=None) -> SyncResult:
        # Skip annotations with no text content — same as legacy behaviour.
        if not annotation.highlighted_text and not annotation.note_text:
            return SyncResult(
                status="failed",
                error_message="annotation has no text content",
            )

        if self._blacklist_check(book.id):
            return SyncResult(
                status="failed",
                error_message=f"book {book.id} blacklisted for Hardcover annotations",
            )

        identifiers = self._book_identifiers_getter(book)
        if not identifiers:
            return SyncResult(
                status="failed",
                error_message="book has no Hardcover-compatible identifiers",
            )

        # Decide: add (first time) or update (existing target_record_id).
        existing = annotation.sync_target("hardcover")
        existing_record_id = existing.target_record_id if existing else None

        try:
            client = self._client_factory(user.hardcover_token)
            if existing_record_id:
                response = client.update_journal_entry(
                    journal_id=int(existing_record_id),
                    note_text=annotation.note_text,
                    highlighted_text=annotation.highlighted_text,
                )
            else:
                progress_percent = None
                if payload:
                    span = (payload.get("location") or {}).get("span") or {}
                    progress_percent = span.get("chapterProgress")
                response = client.add_journal_entry(
                    identifiers=identifiers,
                    note_text=annotation.note_text,
                    progress_percent=progress_percent,
                    progress_page=None,
                    highlighted_text=annotation.highlighted_text,
                    highlight_color=annotation.highlight_color,
                )
        except Exception as exc:
            log.warning("HardcoverHandler.push raised: %s", exc)
            return SyncResult(
                status="failed",
                error_message=str(exc),
                target_record_id=existing_record_id,
            )

        if not response or "id" not in response:
            return SyncResult(
                status="failed",
                error_message=f"empty Hardcover response: {response!r}",
                target_record_id=existing_record_id,
            )
        return SyncResult(
            status="synced",
            target_record_id=str(response["id"]),
        )

    def delete(self, sync_target, user) -> SyncResult:
        record_id = sync_target.target_record_id
        if not record_id:
            return SyncResult(
                status="tombstone",
                error_message="no remote record to delete",
            )
        try:
            client = self._client_factory(user.hardcover_token)
            returned = client.delete_journal_entry(journal_id=int(record_id))
        except Exception as exc:
            if self._not_found_exception and isinstance(exc, self._not_found_exception):
                return SyncResult(
                    status="tombstone",
                    target_record_id=record_id,
                    error_message="already deleted on remote",
                )
            log.warning("HardcoverHandler.delete raised: %s", exc)
            return SyncResult(
                status="failed",
                error_message=str(exc),
                target_record_id=record_id,
            )
        if returned is None:
            return SyncResult(
                status="tombstone",
                target_record_id=record_id,
                error_message="remote returned no id; treating as deleted",
            )
        if str(returned) != str(record_id):
            return SyncResult(
                status="failed",
                error_message=f"remote returned mismatched id: {returned!r}",
                target_record_id=record_id,
            )
        return SyncResult(
            status="tombstone",
            target_record_id=record_id,
        )
