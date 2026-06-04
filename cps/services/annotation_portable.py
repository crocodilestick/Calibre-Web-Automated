# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Device-agnostic portable annotation projection (Phase 2).

The KOReader-bridge endpoints speak a portable annotation shape that is
independent of any device kind; the plugin's device provider maps it to
device-native fields (KoboReader.sqlite Bookmark columns, etc.).

  - :func:`to_portable` — project an Annotation ORM row to the wire dict
    (pull: server → device).
  - :func:`apply_portable` — upsert an Annotation from a pushed wire dict
    (push: device → server), recording ``device_origin_id`` for feedback-loop
    suppression and soft-deleting on ``hidden``.

Kept dependency-light + explicit so it's unit-testable without a Flask
request context (mirrors cps/annotations.py's pure helpers).

See notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md §4.1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

_VALID_SOURCES = {"kobo", "webreader", "koreader"}


def _now():
    return datetime.now(timezone.utc)


def to_portable(row) -> dict:
    """Project an Annotation row to the portable wire dict."""
    from .kobo_position import _extract_kobospan_id
    return {
        "annotation_id": row.annotation_id,
        "highlighted_text": row.highlighted_text,
        "note_text": row.note_text,
        "color": row.highlight_color,
        "content_id": row.content_id,
        "start_kobospan": _extract_kobospan_id(row.start_container_path or ""),
        "start_offset": row.start_offset,
        "end_kobospan": _extract_kobospan_id(row.end_container_path or ""),
        "end_offset": row.end_offset,
        "context_string": row.context_string,
        "chapter_progress": row.chapter_progress,
        "source": row.source,
        "hidden": bool(row.hidden),
        "device_origin_id": row.device_origin_id,
        "last_synced": row.last_synced.isoformat() if row.last_synced else None,
    }


def apply_portable(payload, *, user_id, book, session, commit) -> Tuple[Optional[object], str]:
    """Upsert an Annotation from a device-pushed portable dict.

    Find-or-create keyed on ``(user_id, annotation_id)``. New rows take the
    payload's ``source`` (coerced to ``koreader`` if absent/invalid). Position
    fields are built from the KoboSpan anchors like the web-reader create path.
    ``device_origin_id`` is recorded so the next pull won't echo the row back to
    the device. ``hidden: true`` soft-deletes.

    Returns ``(row, action)`` where action ∈ {created, updated, deleted, skipped}.
    """
    from cps import ub

    annotation_id = payload.get("annotation_id")
    if not annotation_id:
        return None, "skipped"

    row = (
        session.query(ub.Annotation)
        .filter(ub.Annotation.user_id == user_id,
                ub.Annotation.annotation_id == annotation_id)
        .first()
    )
    created = False
    if row is None:
        source = payload.get("source")
        if source not in _VALID_SOURCES:
            source = "koreader"
        row = ub.Annotation(
            user_id=user_id, annotation_id=annotation_id,
            book_id=book.id, source=source,
        )
        session.add(row)
        created = True
    elif payload.get("source") in _VALID_SOURCES:
        row.source = payload.get("source")

    # Content fields (only overwrite when present in the payload).
    if "highlighted_text" in payload:
        row.highlighted_text = payload.get("highlighted_text")
    if "note_text" in payload:
        row.note_text = payload.get("note_text")
    if "color" in payload:
        row.highlight_color = payload.get("color")
    if payload.get("content_id"):
        row.content_id = payload.get("content_id")
    if payload.get("context_string"):
        row.context_string = payload.get("context_string")
    if payload.get("chapter_progress") is not None:
        row.chapter_progress = payload.get("chapter_progress")

    # Position — build the Kobo-native selector form from the KoboSpan anchor.
    start_span = payload.get("start_kobospan")
    if start_span:
        end_span = payload.get("end_kobospan") or start_span
        row.start_container_path = "span#" + start_span
        row.start_container_child_index = -99
        row.start_offset = int(payload.get("start_offset") or 0)
        row.end_container_path = "span#" + end_span
        row.end_container_child_index = -99
        row.end_offset = int(payload.get("end_offset") or 0)

    if payload.get("device_origin_id"):
        row.device_origin_id = payload.get("device_origin_id")

    if payload.get("hidden"):
        row.hidden = True
        action = "deleted"
    else:
        row.hidden = False
        action = "created" if created else "updated"

    row.last_synced = _now()
    commit()
    return row, action
