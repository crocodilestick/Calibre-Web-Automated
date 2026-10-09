# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Endpoint shapes follow Calibre-Web NextGen's /api/v1/search
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Simple search, advanced search and typeahead suggestions.

Simple search runs calibre_db.get_search_results like search.render_search_results;
advanced search builds its query like search.render_adv_search_results with the same
adv_search_* helpers; suggestions mirror web.get_*_json. Permission filters therefore
match the classic UI, including that both searches show archived books.
"""

import json
from datetime import datetime

from flask import jsonify, request
from flask_babel import get_locale
from sqlalchemy.sql.expression import func, not_

from . import api_v1, api_error, paging
from .books import SORT_ORDERS
from .serializers import serialize_pagination, serialize_rows
from .. import calibre_db, config, db, isoLanguages
from ..cw_login import current_user
from ..helper import tags_filters
from ..pagination import Pagination
from ..search import (adv_search_extension, adv_search_ratings, adv_search_read_status, adv_search_serie,
                      adv_search_tag)
from ..string_helper import strip_whitespaces
from ..usermanagement import login_required_if_no_ano

DEFAULT_SORT = "new"

# API read_status value -> the advanced search form's read_status value.
READ_STATUS_TERMS = {"read": "True", "unread": "False", "empty": ""}

SUGGEST_KINDS = {
    "authors": (db.Authors, ('|', ',')),
    "publishers": (db.Publishers, ('|', ',')),
    "series": (db.Series, ('', '')),
}

_SERIES_JOIN = (db.books_series_link, db.Books.id == db.books_series_link.c.book, db.Series)


class _BadParameter(ValueError):
    pass


def _sort_key(view):
    """?sort= key; "stored" reads the classic search page's saved choice without changing it."""
    key = (request.args.get("sort") or DEFAULT_SORT).lower()
    if key == "stored":
        key = current_user.get_view_property(view, "stored")
    return key if key in SORT_ORDERS else DEFAULT_SORT


def _text(name):
    return strip_whitespaces(request.args.get(name) or "").lower()


def _date(name):
    value = strip_whitespaces(request.args.get(name) or "")
    if value:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise _BadParameter("{} must be a date in YYYY-MM-DD format".format(name))
    return value


def _rating(name):
    value = request.args.get(name)
    if not value:
        return None
    try:
        stars = int(value)
    except ValueError:
        raise _BadParameter("{} must be a whole number of stars from 0 to 5".format(name))
    if not 0 <= stars <= 5:
        raise _BadParameter("{} must be a whole number of stars from 0 to 5".format(name))
    return stars


def _ids(name):
    try:
        return [int(v) for v in request.args.getlist(name) if v != ""]
    except ValueError:
        raise _BadParameter("{} must be numeric ids".format(name))


def _paged_response(rows, total, page, per_page, sort):
    result = serialize_pagination(Pagination(page, per_page, total), serialize_rows(rows))
    result["sort"] = sort
    return jsonify(result)


@api_v1.route("/search")
@login_required_if_no_ano
def search_books():
    page, per_page = paging()
    sort = _sort_key("search")
    term = strip_whitespaces(request.args.get("q") or "")
    if not term:
        return _paged_response([], 0, page, per_page, sort)
    entries, total, __ = calibre_db.get_search_results(term, config, (page - 1) * per_page,
                                                       [SORT_ORDERS[sort]], per_page, *_SERIES_JOIN)
    return _paged_response(entries, total, page, per_page, sort)


@api_v1.route("/search/advanced")
@login_required_if_no_ano
def advanced_search():
    """Query parameters mirror the classic advanced search form.

    title, author, publisher, description: substring match. pubdate_from, pubdate_to:
    YYYY-MM-DD, exclusive. rating_min, rating_max: stars 0-5. read_status: read, unread
    or empty (no value in the read custom column). tag, series and format (codes such as
    EPUB) include books having every given value, the exclude_* forms drop books having
    any; tag and series take ids, language and exclude_language take language codes.
    """
    page, per_page = paging()
    sort = _sort_key("advsearch")
    try:
        pub_start, pub_end = _date("pubdate_from"), _date("pubdate_to")
        rating_min, rating_max = _rating("rating_min"), _rating("rating_max")
        include_tags, exclude_tags = _ids("tag"), _ids("exclude_tag")
        include_series, exclude_series = _ids("series"), _ids("exclude_series")
    except _BadParameter as ex:
        return api_error("invalid_parameter", str(ex), 400)
    read_status = (request.args.get("read_status") or "any").lower()
    if read_status not in READ_STATUS_TERMS and read_status != "any":
        return api_error("invalid_parameter", "read_status must be any, read, unread or empty", 400)

    calibre_db.create_functions()
    q = calibre_db.generate_linked_query(config.config_read_column, db.Books) \
        .outerjoin(db.books_series_link, db.Books.id == db.books_series_link.c.book) \
        .outerjoin(db.Series) \
        .filter(calibre_db.common_filters(True))

    author = _text("author").replace(',', '|')
    title = _text("title")
    publisher = _text("publisher")
    description = strip_whitespaces(request.args.get("description") or "")
    if author:
        q = q.filter(db.Books.authors.any(func.lower(db.Authors.name).ilike("%" + author + "%")))
    if title:
        q = q.filter(func.lower(db.Books.title).ilike("%" + title + "%"))
    if publisher:
        q = q.filter(db.Books.publishers.any(func.lower(db.Publishers.name).ilike("%" + publisher + "%")))
    if description:
        q = q.filter(db.Books.comments.any(func.lower(db.Comments.text).ilike("%" + description + "%")))
    if pub_start:
        q = q.filter(func.datetime(db.Books.pubdate) > func.datetime(pub_start))
    if pub_end:
        q = q.filter(func.datetime(db.Books.pubdate) < func.datetime(pub_end))
    if read_status != "any":
        q = q.filter(adv_search_read_status(READ_STATUS_TERMS[read_status]))
    q = adv_search_tag(q, include_tags, exclude_tags)
    q = adv_search_serie(q, include_series, exclude_series)
    q = adv_search_extension(q, [f.upper() for f in request.args.getlist("format")],
                             [f.upper() for f in request.args.getlist("exclude_format")])
    # Like search.adv_search_language, but by code, and exclusion checks languages
    # (the classic helper checks Books.series there).
    if current_user.filter_language() != "all":
        q = q.filter(db.Books.languages.any(db.Languages.lang_code == current_user.filter_language()))
    else:
        for code in request.args.getlist("language"):
            q = q.filter(db.Books.languages.any(db.Languages.lang_code == code))
        for code in request.args.getlist("exclude_language"):
            q = q.filter(not_(db.Books.languages.any(db.Languages.lang_code == code)))
    q = adv_search_ratings(q, rating_max, rating_min)

    total = q.count()
    rows = q.order_by(*SORT_ORDERS[sort]).offset((page - 1) * per_page).limit(per_page).all()
    rows = calibre_db.order_authors(rows, list_return=True, combined=True)
    return _paged_response(rows, total, page, per_page, sort)


def _language_suggestions(query):
    # Same matching as web.get_languages_json: prefix matches first, topped up with
    # substring matches to five. Like the classic endpoint it lists every known
    # language, not only those in the library.
    names = isoLanguages.get_language_names(get_locale()) or {}
    matches = [(code, name) for code, name in names.items() if name.lower().startswith(query)]
    if len(matches) < 5:
        matches.extend(item for item in names.items() if query in item[1].lower() and item not in matches)
    return [{"id": code, "name": name} for code, name in matches[:5]]


@api_v1.route("/search/suggest")
@login_required_if_no_ano
def search_suggest():
    """Typeahead for the classic edit and search forms' inputs; ?kind=authors|tags|series|publishers|languages."""
    kind = (request.args.get("kind") or "").lower()
    query = request.args.get("q") or ""
    if kind == "languages":
        return jsonify({"kind": kind, "items": _language_suggestions(query.lower())})
    if kind == "tags":
        items = calibre_db.get_typeahead(db.Tags, query, tag_filter=tags_filters())
    elif kind in SUGGEST_KINDS:
        database, replace = SUGGEST_KINDS[kind]
        items = calibre_db.get_typeahead(database, query, replace)
    else:
        return api_error("invalid_parameter", "kind must be one of authors, tags, series, publishers, languages", 400)
    return jsonify({"kind": kind, "items": json.loads(items)})
