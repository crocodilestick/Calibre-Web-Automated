# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Annotation sync target dispatcher.

Public API:
  - register_handler(handler): plug in a new target
  - available_targets(): list registered target names
  - dispatch_annotation_sync(payload_annotations, book, user): push every annotation
  - dispatch_annotation_deletes(deleted_ids, user): delete every annotation

The dispatcher owns all DB persistence — Annotation rows + AnnotationSyncTarget
rows + the status state machine. Handlers are stateless: they make remote
calls and return SyncResult.

See notes/2026-05-21-annotation-decouple-source-target-DESIGN.md §3.4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from .base import AnnotationSyncTargetHandler, SyncResult

log = logging.getLogger(__name__)

_HANDLERS: Dict[str, AnnotationSyncTargetHandler] = {}


def register_handler(handler: AnnotationSyncTargetHandler) -> None:
    """Register a handler. Replaces any previous handler with the same target_name."""
    _HANDLERS[handler.target_name] = handler


def available_targets() -> List[str]:
    return list(_HANDLERS.keys())


def _registered_handlers():
    return list(_HANDLERS.values())


def reset_registry_for_testing() -> None:
    """Test-only: clear registered handlers between tests."""
    _HANDLERS.clear()


def _now():
    return datetime.now(timezone.utc)


def _book_uuid(book):
    """Best-effort UUID extraction for the book (used to build content_id)."""
    uuid_attr = getattr(book, "uuid", None)
    if uuid_attr:
        return uuid_attr
    return None


def _upsert_annotation(session, payload, book, user):
    """Find-or-create Annotation row keyed on (user_id, annotation_id).

    Populates content fields AND position fields from the Kobo PATCH payload
    so subsequent CFI computation has everything it needs.  This is the
    sub-project (2) work: annotation persistence happens unconditionally —
    independent of any registered sync target (Hardcover etc.).
    """
    from cps import ub
    annotation_id = payload.get("id")
    if not annotation_id:
        return None
    ann = (
        session.query(ub.Annotation)
        .filter(
            ub.Annotation.user_id == user.id,
            ub.Annotation.annotation_id == annotation_id,
        )
        .first()
    )
    if ann is None:
        ann = ub.Annotation(
            user_id=user.id,
            annotation_id=annotation_id,
            book_id=book.id,
            source="kobo",
        )
        session.add(ann)
    # If a previously soft-deleted (hidden) annotation comes back, un-hide it.
    ann.hidden = False
    # Content fields
    if "highlightedText" in payload:
        ann.highlighted_text = payload.get("highlightedText")
    if "noteText" in payload:
        ann.note_text = payload.get("noteText")
    if "highlightColor" in payload:
        ann.highlight_color = payload.get("highlightColor")
    # Position fields — pulled from Kobo's location.span block.
    span = (payload.get("location") or {}).get("span") or {}
    chapter_progress = span.get("chapterProgress")
    if chapter_progress is not None:
        ann.chapter_progress = chapter_progress
    chapter_filename = span.get("chapterFilename")
    if chapter_filename:
        uuid = _book_uuid(book)
        if uuid:
            ann.content_id = f"{uuid}!!{chapter_filename}"
    if "startPath" in span:
        ann.start_container_path = span.get("startPath")
    if "endPath" in span:
        ann.end_container_path = span.get("endPath")
    if "startChar" in span:
        ann.start_offset = span.get("startChar")
    if "endChar" in span:
        ann.end_offset = span.get("endChar")
    if "contextString" in span or "context" in span:
        ann.context_string = span.get("contextString") or span.get("context")
    ann.last_synced = _now()
    session.flush()
    return ann


def _apply_result(st, result):
    """Mutate AnnotationSyncTarget in place from a SyncResult + log transition."""
    prior = st.status
    st.status = result.status
    if result.target_record_id:
        st.target_record_id = result.target_record_id
    if result.status == "synced":
        st.last_synced = _now()
        st.error_message = None
    else:
        st.error_message = result.error_message
    st.last_attempt = _now()
    st.updated_at = _now()
    log.info(
        "annotation_sync transition: annotation_id=%s target=%s %s->%s err=%r",
        st.annotation_id, st.target, prior, result.status, result.error_message,
    )


def _upsert_sync_target(session, annotation, target_name, result):
    """Find-or-create the (annotation_id, target) row, race-safe under
    concurrent INSERT via IntegrityError recovery."""
    from cps import ub
    st = (
        session.query(ub.AnnotationSyncTarget)
        .filter(
            ub.AnnotationSyncTarget.annotation_id == annotation.id,
            ub.AnnotationSyncTarget.target == target_name,
        )
        .first()
    )
    if st is None:
        st = ub.AnnotationSyncTarget(
            annotation_id=annotation.id,
            target=target_name,
            status=result.status,
            target_record_id=result.target_record_id,
            error_message=result.error_message,
            last_attempt=_now(),
            last_synced=_now() if result.status == "synced" else None,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(st)
        try:
            session.flush()
        except IntegrityError:
            # Concurrent INSERT — recover by re-reading + applying result.
            session.rollback()
            st = (
                session.query(ub.AnnotationSyncTarget)
                .filter(
                    ub.AnnotationSyncTarget.annotation_id == annotation.id,
                    ub.AnnotationSyncTarget.target == target_name,
                )
                .first()
            )
            if st is not None:
                _apply_result(st, result)
        else:
            # Log new-row creation for parity with _apply_result on update.
            log.info(
                "annotation_sync transition: annotation_id=%s target=%s NEW->%s err=%r",
                annotation.id, target_name, result.status, result.error_message,
            )
        return st
    _apply_result(st, result)
    return st


def dispatch_annotation_sync(payload_annotations, book, user) -> None:
    """For each annotation in the PATCH payload, persist locally then push to each enabled handler."""
    from cps import ub
    if not payload_annotations:
        return
    for payload in payload_annotations:
        ann = _upsert_annotation(ub.session, payload, book, user)
        if ann is None:
            continue
        for handler in _registered_handlers():
            if not handler.is_enabled(user):
                continue
            existing = ann.sync_target(handler.target_name)
            if existing is not None and existing.status == "tombstone":
                # Terminal — never re-push a tombstoned annotation.
                continue
            try:
                result = handler.push(ann, book, user, payload=payload)
            except Exception as exc:
                log.exception("dispatcher: handler %s push raised", handler.target_name)
                result = SyncResult(status="failed", error_message=str(exc))
            _upsert_sync_target(ub.session, ann, handler.target_name, result)
    ub.session_commit()


def dispatch_existing_annotation_sync(annotation, book, user) -> None:
    """Push an already-persisted Annotation row to each enabled sync target.

    The Kobo PATCH path (``dispatch_annotation_sync``) upserts the row from a
    payload first; web-reader-created (and other non-PATCH origin) rows already
    exist, so this is their fan-out entry point. Same per-handler semantics:
    skip disabled handlers, never re-push a tombstoned target, record the
    result on the AnnotationSyncTarget row.
    """
    from cps import ub
    if annotation is None:
        return
    for handler in _registered_handlers():
        if not handler.is_enabled(user):
            continue
        existing = annotation.sync_target(handler.target_name)
        if existing is not None and existing.status == "tombstone":
            continue
        try:
            result = handler.push(annotation, book, user)
        except Exception as exc:
            log.exception("dispatcher: handler %s push raised", handler.target_name)
            result = SyncResult(status="failed", error_message=str(exc))
        _upsert_sync_target(ub.session, annotation, handler.target_name, result)
    ub.session_commit()


def dispatch_annotation_deletes(deleted_ids, user) -> None:
    """For each annotation_id, transition non-tombstone sync_targets via
    handler.delete AND soft-delete the local Annotation row by setting
    ``hidden=True``.

    Sub-project (2): local soft-delete happens unconditionally — independent
    of any enabled sync target. Recovery is symmetric: a subsequent
    create/update PATCH for the same annotation_id un-hides it via
    ``_upsert_annotation``.
    """
    from cps import ub
    if not deleted_ids:
        return
    for annotation_id in deleted_ids:
        ann = (
            ub.session.query(ub.Annotation)
            .filter(
                ub.Annotation.user_id == user.id,
                ub.Annotation.annotation_id == annotation_id,
            )
            .first()
        )
        if ann is None:
            continue
        # Push delete through any non-tombstone sync targets first.
        for st in list(ann.sync_targets):
            if st.status == "tombstone":
                continue
            handler = _HANDLERS.get(st.target)
            if handler is None or not handler.is_enabled(user):
                continue
            try:
                result = handler.delete(st, user)
            except Exception as exc:
                log.exception("dispatcher: handler %s delete raised", handler.target_name)
                result = SyncResult(status="failed", error_message=str(exc))
            _apply_result(st, result)
        # Soft-delete the local row regardless of sync target outcome.
        ann.hidden = True
        log.info(
            "annotation_sync: soft-delete annotation_id=%s (hidden=True)",
            annotation_id,
        )
    ub.session_commit()


# Auto-register Hardcover at import time.
from .hardcover import HardcoverHandler  # noqa: E402
register_handler(HardcoverHandler())
