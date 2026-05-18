# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Annotations blueprint — H1 Phase 3.

User-facing routes for the Kobo highlight feature. P3 ships the
import endpoint; P4 adds the view + export surface; P5 adds the
web-reader create/edit path.

Routes shipped in this PR:

    GET  /annotations/import          -> upload form
    POST /annotations/import          -> accept KoboReader.sqlite,
                                          parse, INSERT into kobo_annotation_sync

Auth: ``@user_login_required`` — annotation data is per-user-private.
Anonymous users have nothing to import + nowhere to store imported data,
so the route rejects them at the auth layer.

CSRF: protected via Flask-WTF's global middleware (we do NOT call
``@csrf.exempt`` — this is a browser-driven endpoint, not a device-
protocol endpoint).

The import path NEVER persists the uploaded SQLite to disk. The file is
parsed in-place via a temp file that's deleted before the request
returns. The file's contents are PII (the user's reading history,
search queries, every bookmark they ever made) — we read what we need
+ throw away the rest.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, abort, flash, jsonify, redirect, request, url_for
from flask_babel import gettext as _

from . import calibre_db, logger, ub
from .cw_login import current_user
from .render_template import render_title_template
from .services.kobo_import import looks_like_sqlite, parse_kobo_bookmarks
from .usermanagement import user_login_required

log = logger.create()

annotations_bp = Blueprint("annotations", __name__)

# Defense-in-depth file-size cap. Typical real-device KoboReader.sqlite
# files are 30-50 MB; reject anything over 100 MB.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


@annotations_bp.route("/annotations/import", methods=["GET"])
@user_login_required
def annotations_import_form():
    """Render the upload form."""
    return render_title_template(
        "annotations_import.html",
        title=_(u"Import Kobo annotations"),
        page="annotations_import",
    )


@annotations_bp.route("/annotations/import", methods=["POST"])
@user_login_required
def annotations_import_submit():
    """Accept an uploaded ``KoboReader.sqlite``, parse the Bookmark
    table, and INSERT each highlight into ``kobo_annotation_sync``
    for the current user.

    Returns a JSON summary: ``{imported, skipped_existing, skipped_orphan,
    skipped_hidden, total_seen}`` — the upload form swaps to a result
    pane without a page reload.
    """
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "no_file", "message": _("No file uploaded.")}), 400

    # Size precheck via Content-Length. Some clients omit it; we also
    # bound the actual read below.
    content_length = request.content_length or 0
    if content_length > MAX_UPLOAD_BYTES:
        return jsonify({
            "error": "too_large",
            "message": _("File exceeds %(max)d MB.", max=MAX_UPLOAD_BYTES // (1024 * 1024)),
        }), 413

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".sqlite", delete=False
        ) as tmp:
            tmp_path = tmp.name
            total = 0
            # Stream-copy so we can cap mid-read on clients that lied
            # about Content-Length.
            while True:
                chunk = upload.stream.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    tmp.close()
                    os.unlink(tmp_path)
                    return jsonify({
                        "error": "too_large",
                        "message": _("File exceeds %(max)d MB.",
                                     max=MAX_UPLOAD_BYTES // (1024 * 1024)),
                    }), 413
                tmp.write(chunk)

        if not looks_like_sqlite(tmp_path):
            return jsonify({
                "error": "not_sqlite",
                "message": _("Uploaded file is not a SQLite database."),
            }), 400

        summary = _ingest_bookmarks(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as e:
                log.warning("annotations: failed to remove temp %s: %s", tmp_path, e)

    return jsonify(summary), 200


def _ingest_bookmarks(sqlite_path: str) -> dict:
    """Adapter around :func:`ingest_bookmarks` that pulls dependencies
    from the Flask request context (current_user, ub.session,
    calibre_db). Lives so the request handler is one line; the
    actual work happens in the pure function below."""
    return ingest_bookmarks(
        sqlite_path,
        user_id=current_user.id,
        session=ub.session,
        book_lookup=lambda uuid: (
            calibre_db.get_book_by_uuid(uuid) if "-" in (uuid or "") else None
        ),
        commit=ub.session_commit,
    )


def ingest_bookmarks(sqlite_path, user_id, session, book_lookup, commit) -> dict:
    """Walk the parsed bookmarks, resolve VolumeIDs via ``book_lookup``,
    INSERT new highlights into ``kobo_annotation_sync``. Dependencies
    are explicit so this function is unit-testable without a Flask app.

    The annotation-backup hook fires automatically on commit so the
    user already has a recoverable snapshot before the next import
    overwrites anything.

    Returns a counts dict the JSON endpoint hands back to the browser.
    """
    imported = 0
    skipped_existing = 0
    skipped_orphan = 0
    skipped_hidden = 0
    total_seen = 0

    # Cache: VolumeID -> CW book_id (or None for not-in-library).
    # Same VolumeID often appears across many bookmarks; resolve once.
    uuid_cache: dict[str, Optional[int]] = {}

    for bm in parse_kobo_bookmarks(sqlite_path):
        total_seen += 1
        if bm.hidden:
            skipped_hidden += 1
            continue

        # Resolve VolumeID -> CW book.id. Kobo writes either a UUID or
        # ``file:///mnt/onboard/...`` for sideloaded books. We only
        # accept UUIDs; sideloaded books CW doesn't know about are
        # skipped (design doc §11 row 2).
        volume_uuid = bm.volume_id
        if volume_uuid in uuid_cache:
            book_id = uuid_cache[volume_uuid]
        else:
            book = book_lookup(volume_uuid)
            book_id = book.id if book else None
            uuid_cache[volume_uuid] = book_id

        if book_id is None:
            skipped_orphan += 1
            continue

        # Dedup: (user_id, annotation_id) is already indexed; one
        # SELECT covers the existence check.
        existing = session.query(ub.KoboAnnotationSync.id).filter(
            ub.KoboAnnotationSync.user_id == user_id,
            ub.KoboAnnotationSync.annotation_id == bm.bookmark_id,
        ).first()
        if existing is not None:
            skipped_existing += 1
            continue

        row = ub.KoboAnnotationSync(
            user_id=user_id,
            annotation_id=bm.bookmark_id,
            book_id=book_id,
            highlighted_text=bm.text,
            highlight_color=bm.color,
            note_text=bm.annotation,
            content_id=bm.content_id,
            start_container_path=bm.start_container_path,
            start_container_child_index=bm.start_container_child_index,
            start_offset=bm.start_offset,
            end_container_path=bm.end_container_path,
            end_container_child_index=bm.end_container_child_index,
            end_offset=bm.end_offset,
            context_string=bm.context_string,
            chapter_progress=bm.chapter_progress,
            source="kobo",
            hidden=False,
        )
        session.add(row)
        imported += 1

    try:
        commit()
    except Exception as e:
        log.error("annotations: import commit failed: %s", e)
        session.rollback()
        imported = 0

    return {
        "imported": imported,
        "skipped_existing": skipped_existing,
        "skipped_orphan": skipped_orphan,
        "skipped_hidden": skipped_hidden,
        "total_seen": total_seen,
    }
