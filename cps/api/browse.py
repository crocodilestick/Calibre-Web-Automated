# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Endpoint shapes follow Calibre-Web NextGen's /api/v1 browse lists
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Browse by author, series, tag, publisher, language, rating and format.

The lists mirror web.author_list, series_list, category_list, publisher_list,
language_overview, ratings_list and formats_list (ascending order), and the per-entity
book lists mirror web.render_author_books and its siblings: the same queries, sidebar
checks and permission filters, so counts match the classic UI. Like the classic lists,
books without a series, tag, publisher, language, rating or format are counted under a
"None" entry whose id is -1 ("none" for languages).
"""

from flask import abort, jsonify, request
from flask_babel import gettext as _, get_locale
from sqlalchemy.sql.expression import func, or_, text
from sqlalchemy.sql.functions import coalesce

from . import api_v1, api_error, paging
from .books import SORT_ORDERS
from .serializers import serialize_pagination, serialize_rows
from .. import calibre_db, config, constants, db, isoLanguages
from ..cw_login import current_user
from ..usermanagement import login_required_if_no_ano

NONE_ID = "-1"


def _entry(item_id, name, count):
    return {"id": item_id, "name": name, "count": count}


def _list_authors():
    rows = (calibre_db.session.query(db.Authors, func.count('books_authors_link.book').label('count'))
            .join(db.books_authors_link).join(db.Books).filter(calibre_db.common_filters())
            .group_by(text('books_authors_link.author')).order_by(db.Authors.sort.asc()).all())
    return [_entry(a.id, a.name.replace('|', ','), count) for a, count in rows]


def _list_series():
    rows = (calibre_db.session.query(db.Series, func.count('books_series_link.book').label('count'))
            .join(db.books_series_link).join(db.Books).filter(calibre_db.common_filters())
            .group_by(text('books_series_link.series')).all())
    entries = [_entry(s.id, s.name, count) for s, count in rows]
    none_count = (calibre_db.session.query(db.Books).outerjoin(db.books_series_link).outerjoin(db.Series)
                  .filter(db.Series.name == None).filter(calibre_db.common_filters()).count())  # noqa: E711
    if none_count:
        entries.append(_entry(int(NONE_ID), _("None"), none_count))
    return sorted(entries, key=lambda x: x["name"].lower())


def _list_tags():
    rows = (calibre_db.session.query(db.Tags, func.count('books_tags_link.book').label('count'))
            .join(db.books_tags_link).join(db.Books).filter(calibre_db.common_filters())
            .group_by(db.Tags.id).all())
    entries = [_entry(t.id, t.name, count) for t, count in rows]
    none_count = (calibre_db.session.query(db.Books).outerjoin(db.books_tags_link).outerjoin(db.Tags)
                  .filter(db.Tags.name == None).filter(calibre_db.common_filters()).count())  # noqa: E711
    if none_count:
        entries.append(_entry(int(NONE_ID), _("None"), none_count))
    return sorted(entries, key=lambda x: x["name"].lower())


def _list_publishers():
    rows = (calibre_db.session.query(db.Publishers, func.count(db.books_publishers_link.c.book).label('count'))
            .join(db.books_publishers_link, db.Publishers.id == db.books_publishers_link.c.publisher)
            .join(db.Books, db.books_publishers_link.c.book == db.Books.id)
            .filter(calibre_db.common_filters())
            .group_by(db.Publishers.id).order_by(db.Publishers.name.asc()).all())
    entries = [_entry(p.id, p.name, count) for p, count in rows]
    none_count = (calibre_db.session.query(func.count(db.Books.id)).outerjoin(db.books_publishers_link)
                  .filter(db.books_publishers_link.c.book == None)  # noqa: E711
                  .filter(calibre_db.common_filters()).scalar())
    if none_count:
        entries.insert(0, _entry(int(NONE_ID), _("None"), none_count))
    return entries


def _list_languages():
    # The classic overview is hidden from users restricted to one language.
    if current_user.filter_language() != "all":
        abort(404)
    return [_entry(lang.id, lang.name, count) for lang, count in calibre_db.speaking_language(with_count=True)]


def _list_ratings():
    rows = (calibre_db.session.query(db.Ratings, func.count(db.books_ratings_link.c.book).label('count'))
            .join(db.books_ratings_link, db.Ratings.id == db.books_ratings_link.c.rating)
            .join(db.Books, db.books_ratings_link.c.book == db.Books.id)
            .filter(calibre_db.common_filters()).filter(db.Ratings.rating > 0)
            .group_by(db.Ratings.id).order_by(db.Ratings.rating.asc()).all())
    # Calibre stores 0-10 (half stars); the name is in stars.
    entries = [_entry(r.id, "%g★" % (r.rating / 2), count) for r, count in rows]
    none_count = (calibre_db.session.query(func.count(db.Books.id))
                  .outerjoin(db.books_ratings_link, db.Books.id == db.books_ratings_link.c.book)
                  .outerjoin(db.Ratings, db.books_ratings_link.c.rating == db.Ratings.id)
                  .filter(calibre_db.common_filters())
                  .filter(or_(db.books_ratings_link.c.rating == None, db.Ratings.rating == 0))  # noqa: E711
                  .scalar())
    if none_count:
        entries.insert(0, _entry(int(NONE_ID), _("None"), none_count))
    return entries


def _list_formats():
    rows = (calibre_db.session.query(db.Data.format, func.count('data.book').label('count'))
            .join(db.Books).filter(calibre_db.common_filters())
            .group_by(db.Data.format).order_by(db.Data.format.asc()).all())
    # The format string is the id, as in the classic /formats/<format> links.
    entries = [_entry(fmt, fmt, count) for fmt, count in rows]
    none_count = (calibre_db.session.query(db.Books).outerjoin(db.Data)
                  .filter(db.Data.format == None).filter(calibre_db.common_filters()).count())  # noqa: E711
    if none_count:
        entries.append(_entry(NONE_ID, _("None"), none_count))
    return entries


def _int_id(item_id):
    try:
        return int(item_id)
    except ValueError:
        abort(404)


def _fill(page, per_page, db_filter, order, *join, **kwargs):
    entries, __, pagination = calibre_db.fill_indexpage(page, per_page, db.Books, db_filter, order,
                                                        True, config.config_read_column, *join, **kwargs)
    return entries, pagination


_SERIES_JOIN = (db.books_series_link, db.Books.id == db.books_series_link.c.book, db.Series)


def _author_books(item_id, page, per_page, order):
    author = calibre_db.session.query(db.Authors).filter(db.Authors.id == _int_id(item_id)).first()
    if not author:
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.authors.any(db.Authors.id == author.id),
                                [order, db.Series.name, db.Books.series_index], *_SERIES_JOIN)
    # The classic page treats an author with no visible books as unavailable.
    if not pagination.total_count:
        abort(404)
    return entries, pagination, author.name.replace('|', ',')


def _series_books(item_id, page, per_page, order):
    if item_id == NONE_ID:
        entries, pagination = _fill(page, per_page, db.Series.name == None, [order], *_SERIES_JOIN)  # noqa: E711
        return entries, pagination, _("None")
    series = calibre_db.session.query(db.Series).filter(db.Series.id == _int_id(item_id)).first()
    if not series:
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.series.any(db.Series.id == series.id), [order])
    return entries, pagination, series.name


def _tag_books(item_id, page, per_page, order):
    if item_id == NONE_ID:
        entries, pagination = _fill(page, per_page, db.Tags.name == None,  # noqa: E711
                                    [order, db.Series.name, db.Books.series_index],
                                    db.books_tags_link, db.Books.id == db.books_tags_link.c.book, db.Tags,
                                    *_SERIES_JOIN)
        return entries, pagination, _("None")
    tag = calibre_db.session.query(db.Tags).filter(db.Tags.id == _int_id(item_id)).first()
    if not tag:
        abort(404)
    # viewing_tag_id: the classic view lets a tag's own page through the allowed-tags filter (#906).
    entries, pagination = _fill(page, per_page, db.Books.tags.any(db.Tags.id == tag.id),
                                [order, db.Series.name, db.Books.series_index], *_SERIES_JOIN,
                                viewing_tag_id=tag.id)
    return entries, pagination, tag.name


def _publisher_books(item_id, page, per_page, order):
    if item_id == NONE_ID:
        entries, pagination = _fill(page, per_page, db.Publishers.name == None,  # noqa: E711
                                    [db.Series.name, order, db.Books.series_index],
                                    db.books_publishers_link, db.Books.id == db.books_publishers_link.c.book,
                                    db.Publishers, *_SERIES_JOIN)
        return entries, pagination, _("None")
    publisher = calibre_db.session.query(db.Publishers).filter(db.Publishers.id == _int_id(item_id)).first()
    if not publisher:
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.publishers.any(db.Publishers.id == publisher.id),
                                [db.Series.name, order, db.Books.series_index], *_SERIES_JOIN)
    return entries, pagination, publisher.name


def _language_books(item_id, page, per_page, order):
    if item_id.lower() == "none":
        entries, pagination = _fill(page, per_page, db.Languages.lang_code == None, [order],  # noqa: E711
                                    db.books_languages_link, db.Books.id == db.books_languages_link.c.book,
                                    db.Languages)
        return entries, pagination, _("None")
    try:
        name = isoLanguages.get_language_name(get_locale(), item_id)
    except KeyError:
        abort(404)
    if name == "Unknown":
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.languages.any(db.Languages.lang_code == item_id), [order])
    return entries, pagination, name


def _rating_books(item_id, page, per_page, order):
    if item_id == NONE_ID:
        entries, pagination = _fill(page, per_page, coalesce(db.Ratings.rating, 0) < 1, [order],
                                    db.books_ratings_link, db.Books.id == db.books_ratings_link.c.book,
                                    db.Ratings)
        return entries, pagination, _("None")
    rating = calibre_db.session.query(db.Ratings).filter(db.Ratings.id == _int_id(item_id)).first()
    if not rating:
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.ratings.any(db.Ratings.id == rating.id), [order])
    return entries, pagination, "%g★" % (rating.rating / 2)


def _format_books(item_id, page, per_page, order):
    if item_id == NONE_ID:
        entries, pagination = _fill(page, per_page, db.Data.format == None, [order], db.Data)  # noqa: E711
        return entries, pagination, _("None")
    fmt = item_id.upper()
    if not calibre_db.session.query(db.Data).filter(db.Data.format == fmt).first():
        abort(404)
    entries, pagination = _fill(page, per_page, db.Books.data.any(db.Data.format == fmt), [order])
    return entries, pagination, fmt


# kind: (sidebar bit, classic view-settings key for the stored sort, list, books)
KINDS = {
    "authors": (constants.SIDEBAR_AUTHOR, "author", _list_authors, _author_books),
    "series": (constants.SIDEBAR_SERIES, "series", _list_series, _series_books),
    "tags": (constants.SIDEBAR_CATEGORY, "category", _list_tags, _tag_books),
    "publishers": (constants.SIDEBAR_PUBLISHER, "publisher", _list_publishers, _publisher_books),
    "languages": (constants.SIDEBAR_LANGUAGE, "language", _list_languages, _language_books),
    "ratings": (constants.SIDEBAR_RATING, "ratings", _list_ratings, _rating_books),
    "formats": (constants.SIDEBAR_FORMAT, "formats", _list_formats, _format_books),
}


def _sort_key(kind, view_key):
    """?sort= key; series default to series order. "stored" reads the classic choice without changing it."""
    default = "seriesasc" if kind == "series" else "new"
    key = (request.args.get("sort") or default).lower()
    if key == "stored":
        key = current_user.get_view_property(view_key, "stored")
    return key if key in SORT_ORDERS else default


@api_v1.route("/browse/<kind>")
@login_required_if_no_ano
def browse_list(kind):
    if kind not in KINDS:
        return api_error("not_found", "Unknown browse kind", 404)
    bit, __, list_items, __ = KINDS[kind]
    if not current_user.check_visibility(bit):
        abort(404)
    return jsonify({"items": list_items()})


@api_v1.route("/browse/<kind>/<item_id>/books")
@login_required_if_no_ano
def browse_books(kind, item_id):
    # Like the classic per-entity pages, reachable from book links even when the
    # sidebar list is hidden; the book filters still apply.
    if kind not in KINDS:
        return api_error("not_found", "Unknown browse kind", 404)
    __, view_key, __, books = KINDS[kind]
    page, per_page = paging()
    sort = _sort_key(kind, view_key)
    # The classic per-entity views sort by the first column of the chosen order only.
    entries, pagination, name = books(item_id, page, per_page, SORT_ORDERS[sort][0])
    result = serialize_pagination(pagination, serialize_rows(entries))
    result.update({"id": item_id, "name": name, "sort": sort})
    return jsonify(result)
