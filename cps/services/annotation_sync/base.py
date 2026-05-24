# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Handler abstraction for annotation sync targets.

Handlers are stateless: they receive ORM objects + payload metadata, call
remote APIs, return SyncResult. The dispatcher
(cps/services/annotation_sync/__init__.py) owns DB persistence —
handlers never write rows.

See notes/2026-05-21-annotation-decouple-source-target-DESIGN.md §3.3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a single push/delete attempt against a remote sync target.

    `status`: one of 'pending', 'synced', 'failed', 'tombstone'.
    `target_record_id`: remote-side ID (stringified) on success; None on first-time failure.
    `error_message`: failure detail when `status='failed'`; None otherwise.
    """

    status: str
    target_record_id: Optional[str] = None
    error_message: Optional[str] = None


class AnnotationSyncTargetHandler(ABC):
    """Pushes annotation changes to a single remote target.

    Subclass + register via ``register_handler()`` to wire a new target
    (Hardcover, Readwise, Notion, …) into the dispatcher.
    """

    target_name: str  # e.g. 'hardcover'

    @abstractmethod
    def is_enabled(self, user) -> bool:
        """True iff sync to this target is enabled globally + for this user."""

    @abstractmethod
    def push(self, annotation, book, user, payload=None) -> SyncResult:
        """Push or update the annotation on the remote.

        `payload` is the raw PATCH payload dict (when called from the
        PATCH path) — handlers MAY use it for fields not on the ORM row
        (e.g. chapterFilename for progress calculation). When the dispatcher
        is called outside a PATCH context, `payload` is None and handlers
        must work from the ORM row alone.

        Implementations must be idempotent on retry — re-pushing an
        already-synced annotation should result in `SyncResult(status='synced')`
        with the SAME target_record_id, not a duplicate remote record.
        """

    @abstractmethod
    def delete(self, sync_target, user) -> SyncResult:
        """Delete the annotation from the remote.

        Returns `SyncResult(status='tombstone')` on success — including when
        the remote responds with 404 (already deleted), making the operation
        idempotent.
        """
