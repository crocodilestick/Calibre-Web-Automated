# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Rename, merge and delete Calibre tags from the Tags list.

Ported from Calibre-Web-NextGen (new-usemame/Calibre-Web-NextGen#1368).
Routes are registered in editbooks.py; the handlers live here.

Every book that loses or gains a tag gets the same treatment as a normal
metadata edit: last_modified bumped, marked dirty, and a metadata change log
written after the commit so the enforcer embeds the new tags in the files.
"""

from datetime import datetime, timezone

from flask import jsonify, request
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import func

from . import calibre_db, db, logger
from .cw_login import current_user
from .metadata_change_log import write_metadata_change_log

log = logger.create()


def _error(status, code, message, **extra):
    body = {"code": code, "message": message}
    body.update(extra)
    return jsonify({"error": body}), status


def _require_metadata_editor():
    """Return an error response when the caller may not edit metadata, else None.

    The routes are already behind user_login_required + edit_required; this
    keeps the handlers safe on their own and answers in JSON.
    """
    if not current_user.is_authenticated or current_user.is_anonymous:
        return _error(401, "unauthorized", _("You must be signed in"))
    if not (current_user.role_edit() or current_user.role_admin()):
        return _error(403, "forbidden", _("You are not allowed to edit metadata"))
    return None


def _get_tag(tag_id):
    return calibre_db.session.query(db.Tags).filter(db.Tags.id == tag_id).first()


def _touch(book):
    book.last_modified = datetime.now(timezone.utc)
    calibre_db.set_metadata_dirty(book.id)


def _log_tag_changes(books):
    # Only called after a successful commit.
    for book in books:
        write_metadata_change_log(book, {"tags": ", ".join(item.name for item in book.tags)})


def rename_tag(tag_id):
    """Rename a tag on every linked book, or merge it into an existing tag.

    A case-insensitive name collision is the de-duplication case: the 409
    carries the other tag (id, name, book count) and the caller repeats the
    request with ``merge: true`` to fold this tag into it. merge must be the
    boolean true, since a merge cannot be undone.
    """
    guard = _require_metadata_editor()
    if guard is not None:
        return guard

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        return _error(400, "invalid_request", _("Tag name must be text"))
    name = payload["name"].strip()
    if not name:
        return _error(400, "invalid_request", _("Tag name cannot be empty"))
    if "," in name:
        return _error(400, "invalid_request", _("Tag name cannot contain commas"))
    merge = payload.get("merge") is True

    tag = _get_tag(tag_id)
    if tag is None:
        return _error(404, "not_found", _("Tag not found"))
    if tag.name == name:
        return jsonify({"id": tag.id, "name": tag.name})

    duplicate = (calibre_db.session.query(db.Tags)
                 .filter(func.lower(db.Tags.name) == name.lower(), db.Tags.id != tag_id)
                 .first())
    if duplicate is not None and not merge:
        # Raw link count: what a merge would actually move, not narrowed by
        # the viewer's library filters.
        return _error(409, "conflict", _("A tag with that name already exists"),
                      conflict={"id": duplicate.id, "name": duplicate.name, "count": len(duplicate.books)})

    affected_books = list(tag.books)
    try:
        if duplicate is not None:
            # Survivor's spelling wins. A book carrying both ends up with one link.
            for book in affected_books:
                if duplicate not in book.tags:
                    book.tags.append(duplicate)
                book.tags.remove(tag)
                _touch(book)
            calibre_db.session.delete(tag)
            result = {"id": duplicate.id, "name": duplicate.name,
                      "merged": True, "books": len(affected_books)}
        else:
            tag.name = name
            for book in affected_books:
                _touch(book)
            result = {"id": tag.id, "name": tag.name}
        calibre_db.session.commit()
    except IntegrityError as e:
        calibre_db.session.rollback()
        log.error_or_exception("Tag rename failed: {}".format(e))
        return _error(409, "conflict", _("A tag with that name already exists"))
    except Exception as e:
        calibre_db.session.rollback()
        log.error_or_exception("Tag rename failed: {}".format(e))
        return _error(500, "server_error", _("Tag could not be renamed"))

    _log_tag_changes(affected_books)
    return jsonify(result)


def delete_tag(tag_id):
    """Remove a tag from every book that carries it, then delete the tag.

    The books are otherwise untouched.
    """
    guard = _require_metadata_editor()
    if guard is not None:
        return guard

    tag = _get_tag(tag_id)
    if tag is None:
        return _error(404, "not_found", _("Tag not found"))

    name = tag.name
    affected_books = list(tag.books)
    try:
        for book in affected_books:
            book.tags.remove(tag)
            _touch(book)
        calibre_db.session.delete(tag)
        calibre_db.session.commit()
    except IntegrityError as e:
        calibre_db.session.rollback()
        log.error_or_exception("Tag delete failed: {}".format(e))
        return _error(409, "conflict", _("Tag could not be deleted"))
    except Exception as e:
        calibre_db.session.rollback()
        log.error_or_exception("Tag delete failed: {}".format(e))
        return _error(500, "server_error", _("Tag could not be deleted"))

    _log_tag_changes(affected_books)
    return jsonify({"id": tag_id, "name": name, "deleted": True, "books": len(affected_books)})
