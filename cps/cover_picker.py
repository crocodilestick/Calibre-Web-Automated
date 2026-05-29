# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Flask blueprint for the focused cover-picker UI.

A user-facing surface dedicated to setting/replacing a book's cover. The
existing metadata-search modal stays untouched; this is a separate path
for users who only want to swap a cover. See notes/COVER-PICKER-DESIGN.md
for the full rationale.

Routes (all gated by edit permission):

    GET  /book/<book_id>/cover                  -> picker page
    POST /book/<book_id>/cover/candidates       -> JSON: gather candidates
    POST /book/<book_id>/cover/preview          -> JSON: validate URL
    POST /book/<book_id>/cover/extract          -> JSON: data-URL of embedded
    POST /book/<book_id>/cover/apply            -> applies chosen cover
    POST /book/<book_id>/cover/lock             -> toggle BookCoverLock

The blueprint is thin — orchestration lives in cps.services.cover_picker
and cps.services.cover_url_validator. Adding a new candidate source
means adding a metadata provider in cps/metadata_provider/, not editing
this file.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from functools import wraps
from typing import Optional

from flask import Blueprint, abort, flash, jsonify, make_response, redirect, request, url_for
from flask_babel import gettext as _
from flask_babel import get_locale

from . import calibre_db, config, helper, kobo_sync_status, logger, ub
from .cw_login import current_user
from .render_template import render_title_template
from .services import cover_extract, cover_preview, cover_picker as cover_picker_svc, cover_url_validator
from .usermanagement import user_login_required


log = logger.create()

cover_picker = Blueprint("cover_picker", __name__)


def edit_required(f):
    """Mirrors editbooks.edit_required — admin or edit-role only."""
    @wraps(f)
    def inner(*args, **kwargs):
        if current_user.role_edit() or current_user.role_admin():
            return f(*args, **kwargs)
        abort(403)
    return inner


def _load_book(book_id: int):
    """Fetch book + 404 if absent. Matches editbooks.py conventions."""
    book = calibre_db.get_filtered_book(book_id)
    if not book:
        abort(404)
    return book


def _book_query_for_search(book) -> str:
    """Build the metadata-search query the picker fires off behind the
    scenes. Title + first author hits the right edition for most books;
    if an ISBN is present in the book identifiers we use that for
    higher-precision results."""
    isbn_ids = [i.val for i in (book.identifiers or []) if (i.type or "").lower() in ("isbn", "isbn_10", "isbn_13")]
    if isbn_ids:
        return isbn_ids[0]
    title = book.title or ""
    authors = [a.name for a in (book.authors or [])]
    return (title + " " + (authors[0] if authors else "")).strip()


def _is_provider_enabled_for_user(provider) -> bool:
    """Honor both per-user and global provider toggles, same as
    cps.search_metadata.metadata_search."""
    try:
        from .search_metadata import _get_global_provider_enabled_map
        global_enabled = _get_global_provider_enabled_map()
    except Exception:
        global_enabled = {}
    user_settings = current_user.view_settings.get("metadata", {}) if current_user else {}
    return bool(global_enabled.get(provider.__id__, True)) and bool(user_settings.get(provider.__id__, True))


@cover_picker.route("/book/<int:book_id>/cover", methods=["GET"])
@user_login_required
@edit_required
def cover_picker_page(book_id):
    """Render the picker page. Candidates are loaded asynchronously so
    the page itself returns instantly; the JS hits the candidates
    endpoint immediately on load."""
    book = _load_book(book_id)
    locked = _get_lock_state(book_id)
    return render_title_template(
        "cover_picker.html",
        book=book,
        cover_locked=locked,
        config=config,
        title=_(u"Change cover — %(title)s", title=book.title),
        page="coverpicker",
    )


@cover_picker.route("/book/<int:book_id>/cover/candidates", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_candidates(book_id):
    """Run the provider pool + cover_booster; return candidate list +
    per-provider status. Same JSON shape pattern as /metadata/search."""
    book = _load_book(book_id)
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip() or _book_query_for_search(book)

    from .search_metadata import (
        cl as providers,
        _classify_empty_provider,
        _classify_provider_failure,
    )

    static_cover = url_for("static", filename="generic_cover.svg")

    candidates, statuses = cover_picker_svc.gather_cover_candidates(
        providers=providers,
        query=query,
        static_cover=static_cover,
        locale=get_locale(),
        is_provider_enabled=_is_provider_enabled_for_user,
        classify_failure=_classify_provider_failure,
        classify_empty=_classify_empty_provider,
        extract_embedded=lambda: cover_extract.extract_embedded_cover(book),
    )

    return jsonify({
        "candidates": [c.to_dict() for c in candidates],
        "providers": [s.to_dict() for s in statuses],
        "query": query,
    })


@cover_picker.route("/book/<int:book_id>/cover/preview", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_preview(book_id):
    """Validate a URL the user pasted (in the picker URL panel OR the
    inline cover_url field on the edit page). Same code path; the inline
    field hits /metadata/cover/preview for the global variant."""
    _load_book(book_id)  # 404s if book is missing or hidden
    body = request.get_json(silent=True) or {}
    result = cover_url_validator.validate_cover_url(body.get("url") or "")
    return jsonify(result.to_dict())


@cover_picker.route("/book/<int:book_id>/cover/extract", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_extract(book_id):
    """Re-render the embedded-cover candidate as a data URL. Used when
    the picker page wants to refresh just the embedded cover after an
    upload changed the book file."""
    book = _load_book(book_id)
    extracted = cover_extract.extract_embedded_cover(book)
    if extracted is None:
        return jsonify({"available": False})
    data_url = "data:" + extracted.mime_type + ";base64," + base64.b64encode(extracted.data).decode("ascii")
    return jsonify({
        "available": True,
        "cover_url": data_url,
        "source_format": extracted.source_format,
    })


@cover_picker.route("/book/<int:book_id>/cover/apply", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_apply(book_id):
    """Apply a chosen cover. Accepts a JSON payload describing the
    source: a remote URL, a candidate from the grid (just a URL really),
    an uploaded file (multipart), or 'embedded' to apply the embedded
    cover from the book file.

    Returns JSON {ok, error?} for AJAX callers; the picker page swaps
    the preview image without a full reload on success.
    """
    book = _load_book(book_id)
    if _get_lock_state(book_id):
        return _json_error("locked", _(u"This book's cover is locked. Unlock it first."), 409)

    # Multipart upload from the picker's file panel.
    if request.files.get("file"):
        ok, message = _apply_uploaded_file(book, request.files["file"])
        return _apply_response(ok, message, book)

    body = request.get_json(silent=True) or {}
    kind = body.get("kind") or "url"

    if kind == "url":
        url = (body.get("url") or "").strip()
        if not url:
            return _json_error("empty_url", _(u"Provide a cover URL."), 400)
        ok, message = helper.save_cover_from_url(url, book.path)
        return _apply_response(ok, message, book)

    if kind == "embedded":
        extracted = cover_extract.extract_embedded_cover(book)
        if extracted is None:
            return _json_error("no_embedded", _(u"This book doesn't have an embedded cover we can extract."), 400)
        ok, message = _apply_bytes(book, extracted.data, extracted.extension)
        return _apply_response(ok, message, book)

    return _json_error("bad_kind", _(u"Unknown cover source."), 400)


@cover_picker.route("/book/<int:book_id>/cover/lock", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_lock(book_id):
    """Toggle (or explicitly set) the BookCoverLock for this book. Body:
    {locked: true|false}. Returns the new state."""
    _load_book(book_id)
    body = request.get_json(silent=True) or {}
    desired = bool(body.get("locked"))
    record = ub.session.query(ub.BookCoverLock).filter_by(book_id=book_id).first()
    now = datetime.now(timezone.utc)
    if record is None:
        record = ub.BookCoverLock(
            book_id=book_id, locked=desired,
            locked_by=current_user.id, locked_at=now,
        )
        ub.session.add(record)
    else:
        record.locked = desired
        record.locked_by = current_user.id
        record.locked_at = now
    try:
        ub.session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        log.error("cover_picker_lock commit failed: %s", exc)
        ub.session.rollback()
        return _json_error("commit_failed", _(u"Could not save lock state."), 500)
    return jsonify({"locked": record.locked})


# ---- E-reader cover preview (was Kobo, generalized 2026-05) --------------


@cover_picker.route("/book/<int:book_id>/cover/ereader-preview", methods=["POST"])
@user_login_required
@edit_required
def cover_picker_ereader_preview(book_id):
    """Re-render an image through the e-reader cover-padding pipeline and
    return a base64 data URL the picker page can drop straight into an
    ``<img src>``. Picker-session-local: aspect / fill_mode / color come
    from the request, not from global config, so users can preview
    variations without mutating admin defaults.

    Body shape (JSON):
        {
            "candidate_url": "https://...",   # OR
            "embedded": true,                 # use the book's embedded cover
            "aspect":    "kobo_libra_color",
            "fill_mode": "edge_mirror",
            "color":     "#1a1a1a"            # only used when fill_mode == manual
        }

    With neither ``candidate_url`` nor ``embedded`` set, the book's
    current saved cover is used as the source.
    """
    book = _load_book(book_id)
    body = request.get_json(silent=True) or {}

    candidate_url = (body.get("candidate_url") or "").strip()
    use_embedded = bool(body.get("embedded"))
    aspect = body.get("aspect") or ""
    fill_mode = body.get("fill_mode") or ""
    color = body.get("color") or ""

    # Belt-and-suspenders: cw_advocate (the SSRF guard) is the primary line
    # of defense, but it's a vendored library we don't actively maintain.
    # Reject anything that's not http(s) here so a future cw_advocate parser
    # bug can't widen the attack surface.
    if candidate_url:
        scheme = urlparse(candidate_url).scheme.lower()
        if scheme not in ("http", "https"):
            return _json_error(
                "bad_scheme",
                _(u"Only http(s) URLs can be previewed."),
                400,
            )

    # Run the whole fetch+pad pipeline on the gevent-aware threadpool. The
    # external cover fetch (`requests` via cw_advocate) does a blocking SSL
    # read on the calling thread; if that thread is the gevent MainThread,
    # every other greenlet stalls for the duration of the fetch. Confirmed
    # live with py-spy: MainThread stuck in ssl.py:read inside
    # `_fetch_url_bytes`, while login + static + metadata-search piled up.
    # Offloading the source-resolve step to the same pool that does the
    # Wand work lets the gevent hub keep serving other endpoints.
    def _resolve_then_render():
        blob = _resolve_preview_source(book, candidate_url, use_embedded)
        if blob is None:
            return None
        return cover_preview.render_preview_data_url(
            blob, aspect=aspect, fill_mode=fill_mode, color=color,
        )

    try:
        data_url = cover_preview._run_in_pool(_resolve_then_render)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("cover_picker_ereader_preview render failed: %s", exc)
        return _json_error("render_failed", _(u"Could not render the e-reader preview."), 500)

    if data_url is None:
        return _json_error("source_unavailable", _(u"Could not load a source image to preview."), 502)

    return jsonify({"ok": True, "data_url": data_url})


# Backwards-compat alias. Remove in the release AFTER the one that
# ships this rename. Kept so in-flight client bookmarks don't 404.
@cover_picker.route("/book/<int:book_id>/cover/kobo-preview", methods=["POST"])
@user_login_required
def cover_picker_kobo_preview_legacy(book_id):
    return redirect(
        url_for("cover_picker.cover_picker_ereader_preview", book_id=book_id),
        code=308,
    )


def _resolve_preview_source(book, candidate_url: str, use_embedded: bool) -> Optional[bytes]:
    """Pick the right bytes to feed pad_blob: a SSRF-safe fetch of an
    external URL, the embedded cover from the book file, or the book's
    on-disk current cover. Returns None when none of those resolve."""
    if candidate_url:
        return _fetch_url_bytes(candidate_url)
    if use_embedded:
        extracted = cover_extract.extract_embedded_cover(book)
        return extracted.data if extracted else None
    return _read_current_cover_bytes(book)


# URL → fetched bytes cache. The picker re-renders covers on every settings
# change (toggle on, aspect dropdown, fill-mode dropdown, color input). Each
# refresh re-fetches the same set of external candidate URLs from Amazon,
# OpenLibrary, Google Books, etc — at 1-30 seconds per fetch. The Wand work
# is fast (~0.2s); the SSL handshakes are the bottleneck. A small in-process
# LRU keyed by URL collapses the second-and-subsequent settings change down
# to "Wand work only" (sub-second per cover instead of 5+ minutes for the
# whole grid). Bytes are bounded by total size so a malicious cover URL
# can't exhaust process memory.
import threading as _threading
_FETCH_CACHE_MAX_BYTES = 64 * 1024 * 1024  # 64 MB ≈ 60 covers @ ~1 MB each
_FETCH_CACHE_LOCK = _threading.Lock()
_FETCH_CACHE = {}  # url -> (bytes, last_used_ts)
_FETCH_CACHE_TOTAL = [0]  # mutable so the closure can update


def _fetch_cache_get(url):
    with _FETCH_CACHE_LOCK:
        entry = _FETCH_CACHE.get(url)
        if entry is None:
            return None
        # Refresh LRU position by re-inserting.
        del _FETCH_CACHE[url]
        _FETCH_CACHE[url] = entry
        return entry[0]


def _fetch_cache_put(url, data):
    if not data:
        return
    size = len(data)
    if size > _FETCH_CACHE_MAX_BYTES:
        # Single oversized blob — don't cache.
        return
    with _FETCH_CACHE_LOCK:
        # Evict LRU entries until we fit.
        while _FETCH_CACHE_TOTAL[0] + size > _FETCH_CACHE_MAX_BYTES and _FETCH_CACHE:
            _, (old_data, _ts) = _FETCH_CACHE.popitem(last=False) if hasattr(_FETCH_CACHE, "popitem") else (None, (b"", 0))
            # dict.popitem(last=False) doesn't exist on a regular dict pre-3.7
            # but our minimum is 3.13 — and we use insertion order via the
            # plain dict for FIFO. Force a manual oldest-key pop:
            break
        # Manual eviction loop (insertion-order dict yields FIFO via iter()):
        while _FETCH_CACHE_TOTAL[0] + size > _FETCH_CACHE_MAX_BYTES and _FETCH_CACHE:
            oldest = next(iter(_FETCH_CACHE))
            _, _ = _FETCH_CACHE.pop(oldest), None
            _FETCH_CACHE_TOTAL[0] -= len(_)
            if _FETCH_CACHE_TOTAL[0] < 0:
                _FETCH_CACHE_TOTAL[0] = 0
        _FETCH_CACHE[url] = (data, 0)
        _FETCH_CACHE_TOTAL[0] += size


def _fetch_url_bytes(url: str) -> Optional[bytes]:
    """Fetch up to ~10 MB through cw_advocate. Mirrors the SSRF guard +
    timeout shape used by helper.save_cover_from_url so external image
    URLs in the picker get the same treatment everywhere.

    Cached per URL so subsequent settings changes don't re-fetch. Tighter
    timeout than save_cover_from_url because the picker is a live UX path
    (a 30 s laggard blocks the user's entire grid), not a save flow.
    """
    cached = _fetch_cache_get(url)
    if cached is not None:
        return cached
    try:
        from . import cw_advocate
    except Exception:  # pragma: no cover - defensive
        return None
    try:
        # (5 s connect, 8 s read) — picker context is interactive, so prefer
        # to drop a slow URL fast and let the user move on. The full 10/30
        # timeout still applies on the save path (helper.save_cover_from_url).
        resp = cw_advocate.get(url, timeout=(5, 8), allow_redirects=True, stream=True)
        if resp.status_code != 200:
            return None
        max_bytes = 10 * 1024 * 1024
        # Pre-stream cap: trust Content-Length when the server bothers to
        # send one. This drops the worker fast when an attacker advertises
        # a 1 GB image instead of waiting to stream past max_bytes.
        size_hint = resp.headers.get("Content-Length")
        if size_hint and size_hint.isdigit() and int(size_hint) > max_bytes:
            log.info("cover_picker_ereader_preview rejecting %s — Content-Length %s exceeds cap", url, size_hint)
            return None
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
        data = b"".join(chunks)
        _fetch_cache_put(url, data)
        return data
    except Exception as exc:
        log.warning("cover_picker_ereader_preview fetch failed for %s: %s", url, exc)
        return None


def _read_current_cover_bytes(book) -> Optional[bytes]:
    """Load the book's on-disk cover.jpg. Returns None if the book has
    no saved cover or the read fails."""
    if not getattr(book, "has_cover", False):
        return None
    try:
        cover_path = os.path.join(config.config_calibre_dir, book.path, "cover.jpg")
        if not os.path.isfile(cover_path):
            return None
        with open(cover_path, "rb") as fh:
            return fh.read()
    except Exception as exc:
        log.warning("cover_picker_ereader_preview disk-cover read failed: %s", exc)
        return None


# ---- helpers --------------------------------------------------------------


def _get_lock_state(book_id: int) -> bool:
    record = ub.session.query(ub.BookCoverLock).filter_by(book_id=book_id).first()
    return bool(record and record.locked)


def _apply_uploaded_file(book, file_storage):
    """Apply a user-uploaded image file to the book. Reuses
    helper.save_cover so the conversion + size limit checks match the
    existing upload-cover-from-disk path on the edit page."""
    return helper.save_cover(file_storage, book.path)


def _apply_bytes(book, raw: bytes, extension: str):
    """Apply raw image bytes (e.g. from the embedded-cover extract). Wraps
    the bytes in a FileStorage-like object so the existing helper.save_cover
    path can process them without changes."""
    import io
    from werkzeug.datastructures import FileStorage
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(extension.lower(), "application/octet-stream")
    storage = FileStorage(
        stream=io.BytesIO(raw),
        filename=f"embedded_cover{extension}",
        content_type=mime,
    )
    return helper.save_cover(storage, book.path)


def _apply_response(ok: bool, message, book):
    if ok:
        try:
            book.has_cover = 1
            # A new cover IS a metadata change: bump last_modified (drives the
            # web cover cache-buster on every cover URL + Kobo sync
            # re-selection) and queue the metadata write-back. remove_synced_book
            # runs post-commit below (best-effort) so a commit failure can't
            # leave it half-applied. Single source of truth: helper.mark_book_modified.
            helper.mark_book_modified(book)
            calibre_db.session.commit()
        except Exception as exc:
            # The cover bytes are on disk but we could not record the change.
            # Do NOT report success — the UI must not show a stale "saved"
            # state when last_modified never persisted.
            log.error("cover apply: failed to record cover change for book %s: %s", book.id, exc)
            try:
                calibre_db.session.rollback()
            except Exception:
                pass
            return _json_error("commit_failed", _(u"Cover save failed."), 500)
        # Post-commit best-effort: the cover is applied and the last_modified
        # bump above already drives both the web cache-bust and Kobo
        # re-selection, so a failure here self-heals on the next sync /
        # thumbnail access. Log loudly but still report success.
        try:
            kobo_sync_status.remove_synced_book(book.id, all=True)
            helper.replace_cover_thumbnail_cache(book.id)
        except Exception as exc:
            log.error("post-apply cover housekeeping failed for book %s: %s", book.id, exc)
        return jsonify({
            "ok": True,
            "cover_url": url_for("web.get_cover", book_id=book.id, resolution="og") + f"?ts={int(datetime.now(timezone.utc).timestamp())}",
        })
    return _json_error("save_failed", str(message) if message else _(u"Cover save failed."), 400)


def _json_error(code: str, message: str, status: int):
    return make_response(jsonify({"ok": False, "error_code": code, "error_message": message}), status)
