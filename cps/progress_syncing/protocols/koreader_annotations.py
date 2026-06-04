#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""KOReader annotation bridge — device-agnostic pull/push API (Phase 2).

Two routes on the existing ``kosync`` blueprint, reusing its auth + book
resolution verbatim (no new credentials for users):

    GET /kosync/syncs/annotations/<document>  -> pull (server -> device)
    PUT /kosync/syncs/annotations             -> push (device -> server)

``<document>`` is the KOReader partial-MD5 digest, resolved to a calibre book
via ``get_book_by_checksum`` exactly as progress sync does, so annotations
converge on the same book across formats/checksums.

The wire shape is the portable annotation dict (see
``cps/services/annotation_portable.py``); the plugin's device provider maps it
to device-native fields (KoboReader.sqlite). Pull includes ``hidden`` rows so
the device can delete locally; push records ``device_origin_id`` to suppress
feedback loops and fans out to enabled sync targets (Hardcover).

The route handlers are thin; ``build_pull_payload`` + ``apply_push`` hold the
testable logic. See notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md §4.
"""

from __future__ import annotations

from flask import request

from ... import csrf, logger, ub
from .kosync import (
    kosync,
    authenticate_user,
    get_book_by_checksum,
    create_sync_response,
    is_valid_key_field,
    _require_kosync_enabled,
    ERROR_UNAUTHORIZED_USER,
    ERROR_DOCUMENT_FIELD_MISSING,
)

log = logger.create()


# ---------------------------------------------------------------------------
# Testable core
# ---------------------------------------------------------------------------


def build_pull_payload(user_id: int, book_id: int, session) -> dict:
    """Portable annotations for one user + book, INCLUDING hidden rows so the
    device can mirror deletions locally."""
    from ...services.annotation_portable import to_portable
    rows = (
        session.query(ub.Annotation)
        .filter(ub.Annotation.user_id == user_id, ub.Annotation.book_id == book_id)
        .order_by(ub.Annotation.id.asc())
        .all()
    )
    annotations = [to_portable(r) for r in rows]
    return {"annotations": annotations, "annotation_count": len(annotations)}


def apply_push(annotations, *, user, book, session, commit) -> dict:
    """Upsert each pushed portable annotation, fan out to enabled sync targets,
    and return a counts summary keyed by action (created/updated/deleted/skipped)."""
    from ...services.annotation_portable import apply_portable
    from ...services import annotation_sync

    summary = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    for payload in (annotations or []):
        row, action = apply_portable(
            payload, user_id=user.id, book=book, session=session, commit=commit,
        )
        summary[action] = summary.get(action, 0) + 1
        if row is None:
            continue
        try:
            if action == "deleted":
                annotation_sync.dispatch_annotation_deletes([row.annotation_id], user)
            else:
                annotation_sync.dispatch_existing_annotation_sync(row, book, user)
        except Exception:  # pragma: no cover - fan-out must never fail the push
            log.exception("koreader annotation push fan-out failed for %s", row.annotation_id)
    return summary


# ---------------------------------------------------------------------------
# Routes (thin; reuse kosync auth + book resolution)
# ---------------------------------------------------------------------------


@csrf.exempt
@kosync.route("/kosync/syncs/annotations/<document>", methods=["GET"])
def pull_annotations(document: str):
    """Pull annotations for the book the digest resolves to (server -> device)."""
    blocked = _require_kosync_enabled()
    if blocked:
        return blocked
    user = authenticate_user()
    if not user:
        return create_sync_response({"error": ERROR_UNAUTHORIZED_USER, "message": "Unauthorized"}, 401)
    if not is_valid_key_field(document):
        return create_sync_response({"error": ERROR_DOCUMENT_FIELD_MISSING, "message": "Invalid document field"}, 400)

    book_id, _fmt, _title, _path, _ver = get_book_by_checksum(document)
    if not book_id:
        # Unknown book: empty set, not an error (the device may have a book the
        # server doesn't know yet).
        return create_sync_response({"document": document, "annotations": [], "annotation_count": 0})

    payload = build_pull_payload(user.id, book_id, ub.session)
    payload["document"] = document
    payload["calibre_book_id"] = book_id
    return create_sync_response(payload)


@csrf.exempt
@kosync.route("/kosync/syncs/annotations", methods=["PUT"])
def push_annotations():
    """Accept device-created/changed/deleted annotations (device -> server)."""
    blocked = _require_kosync_enabled()
    if blocked:
        return blocked
    user = authenticate_user()
    if not user:
        return create_sync_response({"error": ERROR_UNAUTHORIZED_USER, "message": "Unauthorized"}, 401)

    data = request.get_json(silent=True) or {}
    document = data.get("document")
    if not is_valid_key_field(document):
        return create_sync_response({"error": ERROR_DOCUMENT_FIELD_MISSING, "message": "Invalid document field"}, 400)

    book_id, _fmt, _title, _path, _ver = get_book_by_checksum(document)
    if not book_id:
        return create_sync_response({"document": document, "matched": False,
                                     "created": 0, "updated": 0, "deleted": 0, "skipped": 0})

    from ... import calibre_db
    book = calibre_db.get_book(book_id)
    if book is None:
        return create_sync_response({"document": document, "matched": False,
                                     "created": 0, "updated": 0, "deleted": 0, "skipped": 0})

    summary = apply_push(
        data.get("annotations"), user=user, book=book,
        session=ub.session, commit=ub.session_commit,
    )
    summary["document"] = document
    summary["calibre_book_id"] = book_id
    summary["matched"] = True
    return create_sync_response(summary)
