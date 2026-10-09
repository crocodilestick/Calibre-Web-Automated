# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Field names follow Calibre-Web NextGen's /api/v1 serializers
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later) so clients
# written against either fork need few changes.

"""JSON serializers for /api/v1. Pure functions: no Flask request or DB access."""

from datetime import date, datetime

from .. import constants, ub
from ..clean_html import clean_string

# Keys a client uses to hide sidebar entries the admin or user switched off; the same
# bits the classic sidebar and OPDS check with user.check_visibility().
SIDEBAR_VISIBILITY_BITS = {
    "author": constants.SIDEBAR_AUTHOR,
    "series": constants.SIDEBAR_SERIES,
    "category": constants.SIDEBAR_CATEGORY,
    "publisher": constants.SIDEBAR_PUBLISHER,
    "language": constants.SIDEBAR_LANGUAGE,
    "rating": constants.SIDEBAR_RATING,
    "format": constants.SIDEBAR_FORMAT,
    "hot": constants.SIDEBAR_HOT,
    "random": constants.SIDEBAR_RANDOM,
    "best_rated": constants.SIDEBAR_BEST_RATED,
    "read_and_unread": constants.SIDEBAR_READ_AND_UNREAD,
    "archived": constants.SIDEBAR_ARCHIVED,
    "download": constants.SIDEBAR_DOWNLOAD,
    "list": constants.SIDEBAR_LIST,
}

READ_STATUS_NAMES = {
    ub.ReadBook.STATUS_UNREAD: "unread",
    ub.ReadBook.STATUS_FINISHED: "finished",
    ub.ReadBook.STATUS_IN_PROGRESS: "in_progress",
}


def read_status_name(value):
    """Map a ReadBook.read_status int, or a boolean read custom column, to a name."""
    if value is None or value is False:
        return "unread"
    if value is True:
        return "finished"
    return READ_STATUS_NAMES.get(value, "unread")


def iso_datetime(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else None


def calibre_date(value):
    """Calibre stores 'no date' as year 101; report that as None."""
    if value is None or getattr(value, "year", 0) <= 101:
        return None
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()


def author_name(author):
    # Calibre escapes a comma inside one author's name as '|'.
    return author.name.replace("|", ",")


def cover_url_for(book, resolution):
    """`/cover/<id>/<resolution>?c=<last_modified>`, or None when the book has no cover.

    The `c` parameter matches the classic templates' cache buster, so a replaced cover
    gets a new URL in both UIs.
    """
    if not getattr(book, "has_cover", 0):
        return None
    url = f"/cover/{book.id}/{resolution}"
    modified = getattr(book, "last_modified", None)
    return f"{url}?c={int(modified.timestamp())}" if isinstance(modified, datetime) else url


def serialize_pagination(pagination, items):
    """List envelope shared by every paged endpoint."""
    return {
        "items": items,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total_count,
        "pages": pagination.pages,
    }


def serialize_user(user):
    check = getattr(user, "check_visibility", None)
    return {
        "id": user.id,
        "name": user.name,
        "locale": user.locale,
        "anonymous": bool(user.role_anonymous()),
        "role": {
            "admin": bool(user.role_admin()),
            "upload": bool(user.role_upload()),
            "edit": bool(user.role_edit()),
            "download": bool(user.role_download()),
            "delete_books": bool(user.role_delete_books()),
            "edit_shelfs": bool(user.role_edit_shelfs()),
            "viewer": bool(user.role_viewer()),
            "passwd": bool(user.role_passwd()),
        },
        "sidebar": {key: bool(check(bit)) if callable(check) else True
                    for key, bit in SIDEBAR_VISIBILITY_BITS.items()},
    }


def serialize_book_list_item(book, read_status=None, archived=False):
    series = (getattr(book, "series", None) or [None])[0]
    status = read_status_name(read_status)
    return {
        "id": book.id,
        "title": book.title,
        "authors": [author_name(a) for a in (getattr(book, "authors", None) or [])],
        "series": series.name if series else None,
        "series_id": series.id if series else None,
        "series_index": book.series_index,
        "cover_url": cover_url_for(book, "sm"),
        "formats": [d.format for d in (getattr(book, "data", None) or [])],
        "date_added": iso_datetime(getattr(book, "timestamp", None)),
        "last_modified": iso_datetime(getattr(book, "last_modified", None)),
        "read": status == "finished",
        "read_status": status,
        "archived": bool(archived),
    }


def serialize_rows(entries):
    """List items from fill_indexpage(..., join_archive_read=True) rows.

    Those rows are (Books, is_archived, read_status); plain Books objects are accepted too.
    """
    items = []
    for entry in entries:
        book = getattr(entry, "Books", None)
        if book is None:
            items.append(serialize_book_list_item(entry))
        else:
            items.append(serialize_book_list_item(book, read_status=entry[2], archived=entry[1]))
    return items


def serialize_custom_columns(book, definitions):
    result = []
    for column in definitions or []:
        values = getattr(book, "custom_column_{}".format(column.id), None) or []
        if not isinstance(values, list):
            values = [values]
        if not values:
            continue
        serialized = []
        for entry in values:
            value = getattr(entry, "value", None)
            if column.datatype == "datetime":
                value = calibre_date(value)
            item = {"value": value}
            if column.datatype == "series":
                item["extra"] = getattr(entry, "extra", None)
            if column.datatype == "comments" and isinstance(value, str):
                item = {"value": None, "value_html": clean_string(value, book.id)}
            serialized.append(item)
        result.append({
            "id": column.id,
            "label": column.label,
            "name": column.name,
            "datatype": column.datatype,
            "is_multiple": bool(column.is_multiple),
            "values": serialized,
        })
    return result


def serialize_book_detail(book, read_status=None, archived=False, custom_column_definitions=None):
    """Full detail. Callers set `.language_name` on each language for display names."""
    bid = book.id
    status = read_status_name(read_status)
    series = (getattr(book, "series", None) or [None])[0]
    ratings = getattr(book, "ratings", None) or []
    comments = getattr(book, "comments", None) or []

    identifiers = []
    for ident in getattr(book, "identifiers", None) or []:
        try:
            link = repr(ident)
        except Exception:
            link = None
        # Only real http(s) links; never a javascript: or data: URL from crafted metadata.
        url = link if link and link.startswith(("http://", "https://")) else None
        try:
            label = ident.format_type()
        except Exception:
            label = ident.type
        identifiers.append({"type": ident.type, "val": ident.val, "url": url, "label": label})

    formats = [{
        "format": d.format,
        "size_bytes": d.uncompressed_size,
        "download_url": f"/download/{bid}/{d.format.lower()}/{d.name}",
        "read_url": f"/read/{bid}/{d.format.lower()}",
    } for d in getattr(book, "data", None) or []]

    cover = cover_url_for(book, "md")
    cover_1x = cover_url_for(book, "sm")
    return {
        "id": bid,
        "title": book.title,
        "authors": [{"id": a.id, "name": author_name(a)} for a in getattr(book, "authors", None) or []],
        "series": {"id": series.id, "name": series.name} if series else None,
        "series_index": book.series_index,
        # Calibre stores 0-10 (half stars); None when unrated.
        "rating": ratings[0].rating if ratings else None,
        "cover_url": cover,
        "cover_srcset": f"{cover_1x} 1x, {cover} 2x" if cover else None,
        "pubdate": calibre_date(getattr(book, "pubdate", None)),
        "date_added": iso_datetime(getattr(book, "timestamp", None)),
        "last_modified": iso_datetime(getattr(book, "last_modified", None)),
        # Comments come from editors and metadata providers: always sanitized.
        "description_html": clean_string(comments[0].text, bid) if comments else None,
        "tags": [{"id": t.id, "name": t.name} for t in getattr(book, "tags", None) or []],
        "languages": [{"id": lang.lang_code, "name": getattr(lang, "language_name", None) or lang.lang_code}
                      for lang in getattr(book, "languages", None) or []],
        "publishers": [{"id": p.id, "name": p.name} for p in getattr(book, "publishers", None) or []],
        "identifiers": identifiers,
        "custom_columns": serialize_custom_columns(book, custom_column_definitions),
        "formats": formats,
        "read": status == "finished",
        "read_status": status,
        "archived": bool(archived),
    }


def serialize_shelf(shelf, count, is_owner):
    return {
        "id": shelf.id,
        "name": shelf.name,
        "is_public": bool(shelf.is_public),
        "is_owner": bool(is_owner),
        "kobo_sync": bool(getattr(shelf, "kobo_sync", False)),
        "count": count,
    }
