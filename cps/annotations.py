# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Annotations blueprint — H1 Phases 3 + 4.

User-facing routes for the Kobo highlight feature. P3 ships the import
endpoint; P4 adds the view + export surface; P5 adds the web-reader
create/edit path.

Routes shipped so far:

    GET  /annotations/import                 -> upload form           (P3)
    POST /annotations/import                 -> ingest .sqlite        (P3)
    GET  /annotations/<book_id>              -> per-book view         (P4)
    GET  /annotations/<book_id>/export.md    -> Markdown download     (P4)
    GET  /annotations/<book_id>/export.csv   -> CSV download          (P4)
    GET  /annotations/<book_id>/export.json  -> JSON download         (P4)

Auth: ``@user_login_required`` — annotation data is per-user-private.

CSRF: protected via Flask-WTF's global middleware on mutating routes
(POST /annotations/import). Export GETs are idempotent and need no CSRF.

The import path NEVER persists the uploaded SQLite to disk. The file is
parsed in-place via a temp file that's deleted before the request
returns. The file's contents are PII (the user's reading history,
search queries, every bookmark they ever made) — we read what we need
+ throw away the rest.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, Response, abort, flash, jsonify, redirect, request, url_for
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
        existing = session.query(ub.Annotation.id).filter(
            ub.Annotation.user_id == user_id,
            ub.Annotation.annotation_id == bm.bookmark_id,
        ).first()
        if existing is not None:
            skipped_existing += 1
            continue

        row = ub.Annotation(
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


# ---------------------------------------------------------------------------
# P4 — view + export
# ---------------------------------------------------------------------------

# Stable export column order — JSON keys + CSV columns + Markdown
# template all consume this order so the three formats stay in sync.
_EXPORT_FIELDS = (
    "annotation_id",
    "book_id",
    "highlighted_text",
    "highlight_color",
    "note_text",
    "content_id",
    "chapter_progress",
    "context_string",
    "cfi_range",
    "source",
    "created_at",
    "last_synced",
)


def _load_user_annotations(user_id: int, book_id: int) -> list:
    """Per-user-per-book read of ``kobo_annotation_sync``. Filters out
    soft-deleted rows so the view shows the live set. Stable order by
    chapter_progress so the export round-trips a sensible reading
    order even for books with hundreds of highlights."""
    return (
        ub.session.query(ub.Annotation)
        .filter(
            ub.Annotation.user_id == user_id,
            ub.Annotation.book_id == book_id,
        )
        .filter(
            (ub.Annotation.hidden.is_(None))
            | (ub.Annotation.hidden == False)  # noqa: E712 — SQLA needs ==
        )
        .order_by(
            ub.Annotation.chapter_progress.asc().nullslast(),
            ub.Annotation.created_at.asc().nullslast(),
            ub.Annotation.id.asc(),
        )
        .all()
    )


def _row_to_dict(row) -> dict:
    """Project a ``KoboAnnotationSync`` row to the export payload shape."""
    return {
        "annotation_id": row.annotation_id,
        "book_id": row.book_id,
        "highlighted_text": row.highlighted_text,
        "highlight_color": row.highlight_color,
        "note_text": row.note_text,
        "content_id": row.content_id,
        "chapter_progress": row.chapter_progress,
        "context_string": row.context_string,
        "cfi_range": row.cfi_range,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_synced": row.last_synced.isoformat() if row.last_synced else None,
    }


def render_markdown(book_title: str, rows) -> str:
    """Render rows as a Markdown document — single H1 with the book
    title, then one block per highlight (the quoted passage, then a
    bulleted attribution line for color/note/source/chapter)."""
    out = [f"# {book_title}", ""]
    for r in rows:
        text = (r.highlighted_text or "").strip()
        # Markdown blockquote — every line of the highlight gets `> `.
        quoted = "\n".join("> " + line for line in text.splitlines() or [""])
        out.append(quoted)
        meta_bits = []
        if r.highlight_color:
            meta_bits.append(f"color: **{r.highlight_color}**")
        if r.note_text:
            note_oneline = r.note_text.replace("\n", " ").strip()
            meta_bits.append(f"note: {note_oneline}")
        if r.chapter_progress is not None:
            meta_bits.append(f"chapter progress: {int(r.chapter_progress * 100)}%")
        if r.source:
            meta_bits.append(f"source: {r.source}")
        if meta_bits:
            out.append("> ")
            out.append("> *" + " — ".join(meta_bits) + "*")
        out.append("")
    return "\n".join(out) + "\n"


def render_csv(rows) -> str:
    """Render rows as RFC-4180-compatible CSV. Stable column order
    matches ``_EXPORT_FIELDS`` so round-trip parsers don't have to
    detect the order from the header."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_EXPORT_FIELDS), quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in rows:
        writer.writerow(_row_to_dict(r))
    return buf.getvalue()


def render_json(book_title: str, book_id: int, user_id: int, rows) -> str:
    """Render rows as a JSON envelope identical in shape to the
    annotation-backup snapshot format, so a power user can use either
    format interchangeably."""
    payload = {
        "schema_version": 1,
        "user_id": user_id,
        "book_id": book_id,
        "book_title": book_title,
        "annotation_count": len(rows),
        "annotations": [_row_to_dict(r) for r in rows],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, indent=2) + "\n"


def _safe_filename_part(s: str, default: str = "book") -> str:
    """Slugify the book title for the Content-Disposition filename so
    a user-readable name doesn't trip the header parser. Strips
    everything except [A-Za-z0-9._-], collapses runs."""
    if not s:
        return default
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")
    return cleaned or default


def _resolve_book_or_404(book_id: int):
    """Load the Book row + enforce visibility. Returns the Book."""
    book = calibre_db.get_filtered_book(book_id, allow_show_archived=True)
    if not book:
        abort(404)
    return book


def _resolve_epub_path(book) -> Optional[str]:
    """Find the on-disk EPUB file for a book — mirrors the lookup
    pattern in ``cps/web.py``'s serve_book. Returns ``None`` if no
    EPUB/KEPUB format exists or the file is missing on disk.

    Prefers KEPUB: Kobo highlights anchor on KoboSpan ids, which only
    exist in the kepub. A plain EPUB has no KoboSpans, so computing a
    CFI against it would never resolve the anchor."""
    from . import config

    def _disk_path(fmt):
        ext = (fmt.format or "").upper()
        if ext not in ("EPUB", "KEPUB"):
            return None
        path = os.path.join(config.get_book_path(), book.path, fmt.name + "." + ext.lower())
        return path if os.path.isfile(path) else None

    data = book.data or []
    # KEPUB first (carries KoboSpans), then any EPUB as a fallback.
    for fmt in data:
        if (fmt.format or "").upper() == "KEPUB":
            p = _disk_path(fmt)
            if p:
                return p
    for fmt in data:
        if (fmt.format or "").upper() == "EPUB":
            p = _disk_path(fmt)
            if p:
                return p
    return None


def _ensure_cfi_range(row, book) -> Optional[str]:
    """If ``row.cfi_range`` is missing, try to compute it on the fly
    via P2's converter, persist back to the DB, and return the new
    value. Returns None when computation isn't possible (no EPUB on
    disk, malformed position data, etc.) — caller renders the
    annotation in the sidebar without an overlay."""
    if row.cfi_range:
        return row.cfi_range
    if not row.content_id or "!!" not in (row.content_id or ""):
        return None
    epub_path = _resolve_epub_path(book)
    if not epub_path:
        return None
    from pathlib import Path as _Path
    from .services.kobo_position import compute_cfi_range, KoboPosition
    try:
        cfi = compute_cfi_range(_Path(epub_path), KoboPosition(
            content_id=row.content_id,
            start_container_path=row.start_container_path or "",
            start_container_child_index=row.start_container_child_index,
            start_offset=row.start_offset or 0,
            end_container_path=row.end_container_path or "",
            end_container_child_index=row.end_container_child_index,
            end_offset=row.end_offset or 0,
            context_string=row.context_string,
        ))
    except Exception as e:
        log.warning("annotations: cfi compute failed for %s: %s", row.annotation_id, e)
        return None
    if cfi:
        row.cfi_range = cfi
        try:
            ub.session_commit()
        except Exception as e:
            log.error("annotations: cfi persist failed: %s", e)
            ub.session.rollback()
    return cfi


def _data_json_row(r, cfi, pdf_quad) -> dict:
    """Project one annotation row to the web-reader's data.json shape.

    Emits the canonical KoboSpan anchor (``start_kobospan`` /
    ``end_kobospan`` + offsets + ``content_id``) — the reader regenerates
    a wrapper-aware CFI client-side from these, because a server-authored
    CFI can't account for epub.js's render-time wrapper divs. ``cfi_range``
    is the portable source CFI, kept for the sidebar "jump" fallback and
    export parity. Pure + dependency-free so the payload contract is
    unit-testable without a Flask request context."""
    from .services.kobo_position import _extract_kobospan_id
    return {
        "annotation_id": r.annotation_id,
        "cfi_range": cfi,
        "content_id": r.content_id,
        "start_kobospan": _extract_kobospan_id(r.start_container_path or ""),
        "start_offset": r.start_offset,
        "end_kobospan": _extract_kobospan_id(r.end_container_path or ""),
        "end_offset": r.end_offset,
        "highlighted_text": r.highlighted_text,
        "highlight_color": r.highlight_color or "yellow",
        "note_text": r.note_text,
        "chapter_progress": r.chapter_progress,
        "source": r.source,
        "position_type": getattr(r, "position_type", None),
        "pdf_page": getattr(r, "pdf_page", None),
        "pdf_quad": pdf_quad,
        "comic_page": getattr(r, "comic_page", None),
    }


@annotations_bp.route("/annotations/<int:book_id>/data.json", methods=["GET"])
@user_login_required
def annotations_data(book_id):
    """Lightweight JSON list for the web reader — every visible
    annotation for the current user + book, with cfi_range computed on
    the fly + cached if missing. Excludes hidden rows.

    Sub-projects (3)/(4): also emits ``position_type``, ``pdf_page``,
    ``pdf_quad`` (parsed from ``pdf_quad_json``) and ``comic_page`` so the
    PDF / comic reader JS can decide how to overlay each row.
    """
    book = _resolve_book_or_404(book_id)
    rows = _load_user_annotations(current_user.id, book_id)
    out = []
    for r in rows:
        # CFI computation only applies to EPUB-origin rows. For PDF/comic
        # rows, skip the lookup — they have their own position fields.
        cfi = None
        if getattr(r, "position_type", None) in (None, "cfi"):
            cfi = _ensure_cfi_range(r, book)
        pdf_quad = None
        if r.pdf_quad_json:
            try:
                pdf_quad = json.loads(r.pdf_quad_json)
            except (ValueError, TypeError):
                pdf_quad = None
        out.append(_data_json_row(r, cfi, pdf_quad))
    return jsonify({"annotations": out, "annotation_count": len(out)})


@annotations_bp.route("/annotations/<int:book_id>", methods=["GET"])
@user_login_required
def annotations_view(book_id):
    """Per-book view — every annotation the current user has for this
    book, grouped by chapter, sorted by chapter_progress."""
    book = _resolve_book_or_404(book_id)
    rows = _load_user_annotations(current_user.id, book_id)
    return render_title_template(
        "annotations_view.html",
        title=_(u"Annotations: %(title)s", title=book.title),
        page="annotations_view",
        book=book,
        annotations=rows,
        export_md_url=url_for("annotations.annotations_export_markdown", book_id=book_id),
        export_csv_url=url_for("annotations.annotations_export_csv", book_id=book_id),
        export_json_url=url_for("annotations.annotations_export_json", book_id=book_id),
    )


@annotations_bp.route("/annotations/<int:book_id>/export.md", methods=["GET"])
@user_login_required
def annotations_export_markdown(book_id):
    book = _resolve_book_or_404(book_id)
    rows = _load_user_annotations(current_user.id, book_id)
    body = render_markdown(book.title, rows)
    fname = f"{_safe_filename_part(book.title)}-highlights.md"
    return Response(
        body,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@annotations_bp.route("/annotations/<int:book_id>/export.csv", methods=["GET"])
@user_login_required
def annotations_export_csv(book_id):
    book = _resolve_book_or_404(book_id)
    rows = _load_user_annotations(current_user.id, book_id)
    body = render_csv(rows)
    fname = f"{_safe_filename_part(book.title)}-highlights.csv"
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@annotations_bp.route("/annotations/<int:book_id>/export.json", methods=["GET"])
@user_login_required
def annotations_export_json(book_id):
    book = _resolve_book_or_404(book_id)
    rows = _load_user_annotations(current_user.id, book_id)
    body = render_json(book.title, book_id, current_user.id, rows)
    fname = f"{_safe_filename_part(book.title)}-highlights.json"
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# P5 — web-reader create / edit / delete
# ---------------------------------------------------------------------------

# Web-created highlights get an origin-tagged id so logs/exports can tell them
# apart from a Kobo device's BookmarkID UUID, and so Phase 2's device bridge
# can recognize a row it should materialize on a device.
WEBREADER_ID_PREFIX = "cwn-web-"

# The colors the web reader offers — the set a Kobo round-trips (Color 0..3).
# Anything else is rejected so we never store a color a device can't represent.
WEBREADER_COLORS = ("yellow", "red", "green", "blue")


def create_annotation(payload, *, user_id, book, session, commit):
    """Create a ``source='webreader'`` annotation from a reader selection.

    ``payload`` carries the KoboSpan anchors the reader derived from the live
    kepub DOM: ``start_kobospan`` / ``end_kobospan`` (bare ids like
    ``kobo.4.1``), ``start_offset`` / ``end_offset``, ``content_id``,
    ``highlighted_text``, ``highlight_color``, optional ``note_text``.

    Stores the selection as Kobo-native fields (``span#<id>`` selector + the
    ``-99`` kepub child-index sentinel) so the same converter that renders
    device highlights renders these, and so Phase 2 can push them to a device.
    Computes a portable ``cfi_range`` when the kepub is on disk; a missing CFI
    is fine (the reader rebuilds one client-side from the KoboSpan id).

    Pure-ish: dependencies are explicit so it's unit-testable without a Flask
    request context — mirrors :func:`ingest_bookmarks`. Raises ``ValueError``
    on a payload with no usable anchor.
    """
    start_span = (payload.get("start_kobospan") or "").strip()
    if not start_span:
        raise ValueError("create_annotation: missing start_kobospan anchor")
    end_span = (payload.get("end_kobospan") or "").strip() or start_span

    color = (payload.get("highlight_color") or "yellow").strip().lower()
    if color not in WEBREADER_COLORS:
        color = "yellow"

    # content_id is "<book_uuid>!!<chapter_file>". The reader knows the chapter
    # href but not the book uuid, so when it sends a bare chapter_filename we
    # build the Kobo-valid form here (the server has the Book). A directly
    # supplied content_id wins.
    content_id = payload.get("content_id")
    if not content_id:
        chapter = (payload.get("chapter_filename") or "").strip()
        book_uuid = getattr(book, "uuid", None)
        if chapter and book_uuid:
            content_id = f"{book_uuid}!!{chapter}"

    row = ub.Annotation(
        user_id=user_id,
        annotation_id=WEBREADER_ID_PREFIX + uuid.uuid4().hex,
        book_id=book.id,
        source="webreader",
        highlighted_text=payload.get("highlighted_text"),
        highlight_color=color,
        note_text=payload.get("note_text"),
        content_id=content_id,
        start_container_path="span#" + start_span,
        start_container_child_index=-99,
        start_offset=int(payload.get("start_offset") or 0),
        end_container_path="span#" + end_span,
        end_container_child_index=-99,
        end_offset=int(payload.get("end_offset") or 0),
        context_string=payload.get("context_string"),
        hidden=False,
    )
    session.add(row)
    # Compute the portable CFI for export. Never fatal — the row stands on its
    # KoboSpan anchor regardless. _ensure_cfi_range persists it itself.
    try:
        _ensure_cfi_range(row, book)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("annotations: cfi compute on create failed: %s", e)
    commit()
    return row


# Sentinel for "field not supplied" so edit can distinguish "set note to None"
# (clear it) from "don't touch the note".
_UNSET = object()


def _find_owned_annotation(annotation_id, user_id, book_id, session):
    """Resolve a single annotation scoped to its owner — the IDOR guard. A row
    that belongs to another user (or doesn't exist) is invisible: returns
    ``None`` so callers 404 rather than leaking/mutating a foreign row."""
    return (
        session.query(ub.Annotation)
        .filter(
            ub.Annotation.user_id == user_id,
            ub.Annotation.book_id == book_id,
            ub.Annotation.annotation_id == annotation_id,
        )
        .first()
    )


def edit_annotation(annotation_id, *, user_id, book_id, session, commit,
                    color=_UNSET, note=_UNSET):
    """Update an annotation's color and/or note. Position is immutable.

    Returns the row, or ``None`` if no annotation with that id belongs to
    ``(user_id, book_id)``. Raises ``ValueError`` on an unsupported color.
    """
    row = _find_owned_annotation(annotation_id, user_id, book_id, session)
    if row is None:
        return None
    if color is not _UNSET:
        normalized = (color or "").strip().lower()
        if normalized not in WEBREADER_COLORS:
            raise ValueError(f"edit_annotation: unsupported color {color!r}")
        row.highlight_color = normalized
    if note is not _UNSET:
        row.note_text = note
    row.last_synced = datetime.now(timezone.utc)
    commit()
    return row


def delete_annotation(annotation_id, *, user_id, book_id, session, commit):
    """Soft-delete an annotation (``hidden=True``). Idempotent: deleting an
    already-hidden row resolves + returns it (route 200). Returns ``None`` when
    no such row belongs to ``(user_id, book_id)`` (route 404)."""
    row = _find_owned_annotation(annotation_id, user_id, book_id, session)
    if row is None:
        return None
    row.hidden = True
    row.last_synced = datetime.now(timezone.utc)
    commit()
    return row


def _fanout_to_sync_targets(row, book):
    """Push a freshly created/edited web-reader row to enabled sync targets
    (Hardcover today). Never fatal — a remote being down must not fail the
    local highlight."""
    try:
        from .services import annotation_sync
        annotation_sync.dispatch_existing_annotation_sync(row, book, current_user)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("annotations: sync-target fan-out failed: %s", e)


@annotations_bp.route("/annotations/<int:book_id>", methods=["POST"])
@user_login_required
def annotations_create(book_id):
    """Create a highlight from a web-reader selection (source='webreader')."""
    book = _resolve_book_or_404(book_id)
    payload = request.get_json(silent=True) or {}
    try:
        row = create_annotation(
            payload, user_id=current_user.id, book=book,
            session=ub.session, commit=ub.session_commit,
        )
    except ValueError as e:
        return jsonify({"error": "bad_anchor", "message": str(e)}), 400
    _fanout_to_sync_targets(row, book)
    return jsonify(_data_json_row(row, row.cfi_range, None)), 201


@annotations_bp.route("/annotations/<int:book_id>/<annotation_id>", methods=["PATCH"])
@user_login_required
def annotations_edit(book_id, annotation_id):
    """Edit a highlight's color and/or note (position immutable)."""
    book = _resolve_book_or_404(book_id)
    data = request.get_json(silent=True) or {}
    kwargs = {}
    if "highlight_color" in data:
        kwargs["color"] = data.get("highlight_color")
    if "note_text" in data:
        kwargs["note"] = data.get("note_text")
    try:
        row = edit_annotation(
            annotation_id, user_id=current_user.id, book_id=book_id,
            session=ub.session, commit=ub.session_commit, **kwargs,
        )
    except ValueError as e:
        return jsonify({"error": "bad_color", "message": str(e)}), 400
    if row is None:
        abort(404)
    _fanout_to_sync_targets(row, book)
    return jsonify(_data_json_row(row, row.cfi_range, None)), 200


@annotations_bp.route("/annotations/<int:book_id>/<annotation_id>", methods=["DELETE"])
@user_login_required
def annotations_delete(book_id, annotation_id):
    """Soft-delete a highlight + tombstone any remote sync targets."""
    _resolve_book_or_404(book_id)
    row = delete_annotation(
        annotation_id, user_id=current_user.id, book_id=book_id,
        session=ub.session, commit=ub.session_commit,
    )
    if row is None:
        abort(404)
    # Propagate the delete to any remote sync targets (Hardcover) — no-op when
    # the row has none. Idempotent (re-sets hidden=True, skips tombstones).
    try:
        from .services import annotation_sync
        annotation_sync.dispatch_annotation_deletes([annotation_id], current_user)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("annotations: delete fan-out failed: %s", e)
    return jsonify({"status": "deleted", "annotation_id": annotation_id}), 200
