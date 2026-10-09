# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Endpoint shapes follow Calibre-Web NextGen's /api/v1/books
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Library list and book detail.

The list mirrors web.render_books_list for the index page and the detail mirrors
web.show_book: the same queries, so permission filters (denied/allowed tags, language,
custom column restrictions, archived books) apply exactly as in the classic UI.
"""

from flask import jsonify, request
from flask_babel import get_locale

from . import api_v1, api_error, paging
from .serializers import serialize_book_detail, serialize_pagination, serialize_rows
from .. import calibre_db, config, db, isoLanguages
from ..cw_login import current_user
from ..usermanagement import login_required_if_no_ano

DEFAULT_SORT = "new"

# The index page's options from web.get_sort_function, which can't be called here
# because it also stores the choice in the user's view settings. The hot* orders
# are left out: they need a join on app.db downloads that the index query lacks.
SORT_ORDERS = {
    "new": [db.Books.timestamp.desc()],
    "old": [db.Books.timestamp],
    "abc": [db.Books.sort],
    "zyx": [db.Books.sort.desc()],
    "pubnew": [db.Books.pubdate.desc()],
    "pubold": [db.Books.pubdate],
    "authaz": [db.Books.author_sort.asc(), db.Series.name, db.Books.series_index],
    "authza": [db.Books.author_sort.desc(), db.Series.name.desc(), db.Books.series_index.desc()],
    "seriesasc": [db.Books.series_index.asc()],
    "seriesdesc": [db.Books.series_index.desc()],
}


def _sort_key():
    """?sort= key; "stored" reads the classic index's saved choice without changing it."""
    key = (request.args.get("sort") or DEFAULT_SORT).lower()
    if key == "stored":
        key = current_user.get_view_property("newest", "stored")
    return key if key in SORT_ORDERS else DEFAULT_SORT


def _visible_tags(tags):
    """Tags shown on the classic detail page: sorted, minus the user's denied or non-allowed ones."""
    tags = sorted(tags, key=lambda tag: tag.name)
    if current_user.is_authenticated:
        allowed = current_user.list_allowed_tags()
        denied = current_user.list_denied_tags()
        if allowed and allowed != ['']:
            tags = [tag for tag in tags if tag.name in allowed]
        if denied and denied != ['']:
            tags = [tag for tag in tags if tag.name not in denied]
    return tags


@api_v1.route("/books")
@login_required_if_no_ano
def list_books():
    page, per_page = paging()
    sort = _sort_key()
    entries, __, pagination = calibre_db.fill_indexpage(page, per_page, db.Books, True, SORT_ORDERS[sort],
                                                        True, config.config_read_column,
                                                        db.books_series_link,
                                                        db.Books.id == db.books_series_link.c.book,
                                                        db.Series)
    result = serialize_pagination(pagination, serialize_rows(entries))
    result["sort"] = sort
    return jsonify(result)


@api_v1.route("/books/<int:book_id>")
@login_required_if_no_ano
def get_book(book_id):
    entries = calibre_db.get_book_read_archived(book_id, config.config_read_column, allow_show_archived=True)
    if not entries:
        return api_error("not_found", "Book not found", 404)
    book, read_status, archived = entries
    locale = get_locale()
    for lang in book.languages:
        lang.language_name = isoLanguages.get_language_name(locale, lang.lang_code)
    result = serialize_book_detail(book, read_status=read_status, archived=archived,
                                   custom_column_definitions=calibre_db.get_cc_columns(
                                       config, filter_config_custom_read=True))
    # Filtered here rather than on book.tags: assigning the relationship would mark it dirty.
    result["tags"] = [{"id": t.id, "name": t.name} for t in _visible_tags(book.tags)]
    return jsonify(result)
