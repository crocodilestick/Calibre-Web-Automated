# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Endpoint shapes follow Calibre-Web NextGen's /api/v1 shelves and magic shelves
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Shelves and magic shelves, read-only.

Shelves mirror the classic sidebar (render_template.get_sidebar_config) and
shelf.render_show_shelf: the same visibility check, the same fill_indexpage query and
so the same common_filters. Magic shelves mirror the sidebar list the global
before_request builds (g.magic_shelves_access) and web.render_magic_shelf.
"""

from flask import g, jsonify, request
from sqlalchemy import func, or_

from . import api_v1, api_error, paging
from .serializers import serialize_pagination, serialize_rows, serialize_shelf
from .. import calibre_db, config, db, magic_shelf, ub
from ..cw_login import current_user
from ..pagination import Pagination
from ..shelf import check_shelf_view_permissions
from ..usermanagement import login_required_if_no_ano

_AUTHOR_SORT = [db.Books.author_sort.asc(), db.Series.name, db.Books.series_index]
_AUTHOR_SORT_DESC = [db.Books.author_sort.desc(), db.Series.name.desc(), db.Books.series_index.desc()]

# shelf.render_show_shelf's sort options. The classic view rewrites BookShelf.order and
# the user's stored sort; this read-only view only orders the result the same way.
SHELF_SORT_ORDERS = {
    "stored": [ub.BookShelf.order.asc()],
    "pubnew": [db.Books.pubdate.desc()],
    "pubold": [db.Books.pubdate],
    "shelfnew": [ub.BookShelf.date_added.desc()],
    "shelfold": [ub.BookShelf.date_added],
    "abc": [db.Books.sort],
    "zyx": [db.Books.sort.desc()],
    "new": [db.Books.timestamp.desc()],
    "old": [db.Books.timestamp],
    "authaz": _AUTHOR_SORT,
    "authza": _AUTHOR_SORT_DESC,
}

# web.get_sort_function's options for page "magicshelf", without storing the choice.
# The hot* orders need a downloads join the magic shelf query doesn't make.
MAGIC_SORT_ORDERS = {
    "new": [db.Books.timestamp.desc()],
    "old": [db.Books.timestamp],
    "abc": [db.Books.sort],
    "zyx": [db.Books.sort.desc()],
    "pubnew": [db.Books.pubdate.desc()],
    "pubold": [db.Books.pubdate],
    "authaz": _AUTHOR_SORT,
    "authza": _AUTHOR_SORT_DESC,
    "seriesasc": [db.Books.series_index.asc()],
    "seriesdesc": [db.Books.series_index.desc()],
}


def _visible_counts(shelf_ids):
    """{shelf_id: number of its books this user may see}."""
    if not shelf_ids:
        return {}
    rows = calibre_db.session.query(ub.BookShelf.shelf, func.count(db.Books.id)) \
        .join(db.Books, ub.BookShelf.book_id == db.Books.id) \
        .filter(ub.BookShelf.shelf.in_(shelf_ids)) \
        .filter(calibre_db.common_filters()) \
        .group_by(ub.BookShelf.shelf).all()
    return dict(rows)


def serialize_magic_shelf(shelf, count):
    return {
        "id": shelf.id,
        "name": shelf.name,
        "icon": shelf.icon,
        "is_public": bool(shelf.is_public),
        "is_system": bool(shelf.is_system),
        "is_owner": shelf.user_id == current_user.id,
        "count": count,
    }


@api_v1.route("/shelves")
@login_required_if_no_ano
def list_shelves():
    # The sidebar's query: own shelves plus public ones, by name.
    shelves = ub.session.query(ub.Shelf).filter(
        or_(ub.Shelf.is_public == 1, ub.Shelf.user_id == current_user.id)).order_by(ub.Shelf.name).all()
    counts = _visible_counts([s.id for s in shelves])
    return jsonify({"items": [serialize_shelf(s, counts.get(s.id, 0), s.user_id == current_user.id)
                              for s in shelves]})


@api_v1.route("/shelves/<int:shelf_id>")
@login_required_if_no_ano
def get_shelf(shelf_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if not shelf or not check_shelf_view_permissions(shelf):
        return api_error("not_found", "Shelf does not exist or is not accessible", 404)
    sort = request.args.get("sort", "stored")
    if sort not in SHELF_SORT_ORDERS:
        return api_error("invalid_sort", "Unknown sort: {}".format(sort), 400)
    page, per_page = paging()
    joins = []
    if sort in ("authaz", "authza"):
        # fill_indexpage takes joins in groups of 3, then 2: the series group goes first.
        joins = [db.books_series_link, db.Books.id == db.books_series_link.c.book, db.Series]
    joins += [ub.BookShelf, ub.BookShelf.book_id == db.Books.id]
    entries, __, pagination = calibre_db.fill_indexpage(page, per_page, db.Books,
                                                        ub.BookShelf.shelf == shelf_id,
                                                        SHELF_SORT_ORDERS[sort] + [ub.BookShelf.order.asc()],
                                                        True, config.config_read_column, *joins)
    data = serialize_shelf(shelf, pagination.total_count, shelf.user_id == current_user.id)
    data["sort"] = sort
    data["books"] = serialize_pagination(pagination, serialize_rows(entries))
    return jsonify(data)


@api_v1.route("/magic-shelves")
@login_required_if_no_ano
def list_magic_shelves():
    # Built for the sidebar by the app's before_request: visible, not hidden, sorted
    # by the user's setting, with cached counts that already respect common_filters.
    shelves = getattr(g, "magic_shelves_access", None) or []
    return jsonify({"items": [serialize_magic_shelf(s, getattr(s, "book_count", None)) for s in shelves]})


@api_v1.route("/magic-shelves/<int:shelf_id>/books")
@login_required_if_no_ano
def magic_shelf_books(shelf_id):
    shelf = ub.session.query(ub.MagicShelf).get(shelf_id)
    if not shelf or (shelf.user_id != current_user.id and shelf.is_public != 1):
        return api_error("not_found", "Magic shelf does not exist or is not accessible", 404)
    sort = request.args.get("sort", "stored")
    resolved = current_user.get_view_property("magicshelf", "stored") if sort == "stored" else sort
    if sort != "stored" and sort not in MAGIC_SORT_ORDERS:
        return api_error("invalid_sort", "Unknown sort: {}".format(sort), 400)
    page, per_page = paging()
    # `sort` is also the cache key, as in the classic view.
    books, total = magic_shelf.get_books_for_magic_shelf(
        shelf_id, page=page, page_size=per_page,
        sort_order=MAGIC_SORT_ORDERS.get(resolved, MAGIC_SORT_ORDERS["new"]), sort_param=sort,
        bypass_cache=request.args.get("refresh") == "1")
    data = serialize_magic_shelf(shelf, total)
    data["sort"] = sort
    data["books"] = serialize_pagination(Pagination(page, per_page, total), serialize_rows(books))
    return jsonify(data)
