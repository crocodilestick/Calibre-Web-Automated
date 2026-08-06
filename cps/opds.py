# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import datetime
import json
from urllib.parse import unquote_plus

from flask import Blueprint, request, render_template, make_response, abort, Response, g, url_for
from flask_babel import get_locale
from flask_babel import gettext as _


from sqlalchemy.sql.expression import func, text, or_, and_, true
from sqlalchemy.exc import InvalidRequestError, OperationalError

from . import logger, config, db, calibre_db, ub, isoLanguages, constants, magic_shelf
from .usermanagement import basic_auth_or_anonymous, auth
from .helper import get_download_link, get_book_cover
from .pagination import Pagination
from .web import render_read_books


opds = Blueprint('opds', __name__)

log = logger.create()

OPDS_ROOT_ORDER_DEFAULT = [
    'books',
    'hot',
    'top_rated',
    'recent',
    'random',
    'read',
    'unread',
    'authors',
    'publishers',
    'categories',
    'series',
    'languages',
    'ratings',
    'formats',
    'shelves',
    'magic_shelves',
]

OPDS_ROOT_ENTRY_DEFS = {
    'books': {
        'endpoint': 'opds.feed_booksindex',
        'title': 'Alphabetical Books',
        'description': 'Books sorted alphabetically',
        'visible': lambda user, allow_anonymous: True,
    },
    'hot': {
        'endpoint': 'opds.feed_hot',
        'title': 'Hot Books',
        'description': 'Popular publications from this catalog based on Downloads.',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_HOT),
    },
    'top_rated': {
        'endpoint': 'opds.feed_best_rated',
        'title': 'Top Rated Books',
        'description': 'Popular publications from this catalog based on Rating.',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_BEST_RATED),
    },
    'recent': {
        'endpoint': 'opds.feed_new',
        'title': 'Recently added Books',
        'description': 'The latest Books',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_RECENT),
    },
    'random': {
        'endpoint': 'opds.feed_discover',
        'title': 'Random Books',
        'description': 'Show Random Books',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_RANDOM),
    },
    'read': {
        'endpoint': 'opds.feed_read_books',
        'title': 'Read Books',
        'description': 'Read Books',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_READ_AND_UNREAD) and not user.is_anonymous,
    },
    'unread': {
        'endpoint': 'opds.feed_unread_books',
        'title': 'Unread Books',
        'description': 'Unread Books',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_READ_AND_UNREAD) and not user.is_anonymous,
    },
    'authors': {
        'endpoint': 'opds.feed_authorindex',
        'title': 'Authors',
        'description': 'Books ordered by Author',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_AUTHOR),
    },
    'publishers': {
        'endpoint': 'opds.feed_publisherindex',
        'title': 'Publishers',
        'description': 'Books ordered by publisher',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_PUBLISHER),
    },
    'categories': {
        'endpoint': 'opds.feed_categoryindex',
        'title': 'Categories',
        'description': 'Books ordered by category',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_CATEGORY),
    },
    'series': {
        'endpoint': 'opds.feed_seriesindex',
        'title': 'Series',
        'description': 'Books ordered by series',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_SERIES),
    },
    'languages': {
        'endpoint': 'opds.feed_languagesindex',
        'title': 'Languages',
        'description': 'Books ordered by Languages',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_LANGUAGE),
    },
    'ratings': {
        'endpoint': 'opds.feed_ratingindex',
        'title': 'Ratings',
        'description': 'Books ordered by Rating',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_RATING),
    },
    'formats': {
        'endpoint': 'opds.feed_formatindex',
        'title': 'File formats',
        'description': 'Books ordered by file formats',
        'visible': lambda user, __: user.check_visibility(constants.SIDEBAR_FORMAT),
    },
    'shelves': {
        'endpoint': 'opds.feed_shelfindex',
        'title': 'Shelves',
        'description': 'Books organized in shelves',
        'visible': lambda user, allow_anonymous: user.is_authenticated or allow_anonymous,
    },
    'magic_shelves': {
        'endpoint': 'opds.feed_magic_shelfindex',
        'title': 'Magic Shelves',
        'description': 'Books organized in magic shelves',
        'visible': lambda user, allow_anonymous: user.is_authenticated or allow_anonymous,
    },
}


def normalize_opds_root_order(order):
    if not isinstance(order, list):
        order = []
    seen = set()
    normalized = []
    for key in order:
        if key in OPDS_ROOT_ENTRY_DEFS and key not in seen:
            normalized.append(key)
            seen.add(key)
    for key in OPDS_ROOT_ORDER_DEFAULT:
        if key not in seen:
            normalized.append(key)
            seen.add(key)
    return normalized


def get_opds_root_order_for_user(user):
    try:
        order = (user.view_settings or {}).get('opds', {}).get('root_order', [])
    except Exception:
        order = []
    if not order:
        return OPDS_ROOT_ORDER_DEFAULT
    return normalize_opds_root_order(order)


def get_opds_hidden_entries_for_user(user):
    try:
        hidden = (user.view_settings or {}).get('opds', {}).get('hidden_entries', [])
    except Exception:
        hidden = []
    if not isinstance(hidden, list):
        return set()
    return {key for key in hidden if key in OPDS_ROOT_ENTRY_DEFS}


def get_opds_root_entries(user, allow_anonymous):
    hidden_entries = get_opds_hidden_entries_for_user(user)
    entries = []
    for key in get_opds_root_order_for_user(user):
        entry_def = OPDS_ROOT_ENTRY_DEFS.get(key)
        if not entry_def:
            continue
        if key in hidden_entries:
            continue
        if not entry_def['visible'](user, allow_anonymous):
            continue
        entries.append({
            'key': key,
            'title': _(entry_def['title']),
            'description': _(entry_def['description']),
            'url': url_for(entry_def['endpoint']),
        })
    return entries

@opds.before_request
def track_opds_access():
    """Track OPDS feed access for analytics"""
    try:
        from scripts.cwa_db import CWA_DB
        from .cw_login import current_user
        import json as json_lib
        
        # Only track if user is authenticated
        if current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            cwa_db = CWA_DB()
            cwa_db.log_activity(
                user_id=int(current_user.id),
                user_name=current_user.name,
                event_type='OPDS_ACCESS',
                extra_data=json_lib.dumps({
                    'endpoint': request.path,
                    'method': request.method
                })
            )
    except Exception as e:
        log.debug(f"Failed to log OPDS access: {e}")


@opds.route("/opds/")
@opds.route("/opds")
@basic_auth_or_anonymous
def feed_index():
    entries = get_opds_root_entries(auth.current_user(), g.allow_anonymous)
    return render_xml_template('index.xml', entries=entries)


@opds.route("/opds/osd")
@basic_auth_or_anonymous
def feed_osd():
    return render_xml_template('osd.xml', lang='en-EN')


# @opds.route("/opds/search", defaults={'query': ""})
@opds.route("/opds/search/<path:query>")
@basic_auth_or_anonymous
def feed_cc_search(query):
    # Handle strange query from Libera Reader with + instead of spaces
    plus_query = unquote_plus(request.environ['RAW_URI'].split('/opds/search/')[1]).strip()
    return feed_search(plus_query)


@opds.route("/opds/search", methods=["GET"])
@basic_auth_or_anonymous
def feed_normal_search():
    return feed_search(request.args.get("query", "").strip())


@opds.route("/opds/books")
@basic_auth_or_anonymous
def feed_booksindex():
    return render_element_index(db.Books.sort, None, 'opds.feed_letter_books')


@opds.route("/opds/books/letter/<book_id>")
@basic_auth_or_anonymous
def feed_letter_books(book_id):
    off = request.args.get("offset") or 0
    letter = true() if book_id == "00" else func.upper(db.Books.sort).startswith(book_id)
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books,
                                                        letter,
                                                        [db.Books.sort],
                                                        True, config.config_read_column)

    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/new")
@basic_auth_or_anonymous
def feed_new():
    if not auth.current_user().check_visibility(constants.SIDEBAR_RECENT):
        abort(404)
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books, True, [db.Books.timestamp.desc()],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/discover")
@basic_auth_or_anonymous
def feed_discover():
    if not auth.current_user().check_visibility(constants.SIDEBAR_RANDOM):
        abort(404)
    query = calibre_db.generate_linked_query(config.config_read_column, db.Books)
    entries = query.filter(calibre_db.common_filters()).order_by(func.random()).limit(config.config_books_per_page)
    pagination = Pagination(1, config.config_books_per_page, int(config.config_books_per_page))
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/rated")
@basic_auth_or_anonymous
def feed_best_rated():
    if not auth.current_user().check_visibility(constants.SIDEBAR_BEST_RATED):
        abort(404)
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books, db.Books.ratings.any(db.Ratings.rating > 9),
                                                        [db.Books.timestamp.desc()],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/hot")
@basic_auth_or_anonymous
def feed_hot():
    if not auth.current_user().check_visibility(constants.SIDEBAR_HOT):
        abort(404)
    off = request.args.get("offset") or 0
    all_books = ub.session.query(ub.Downloads, func.count(ub.Downloads.book_id)).order_by(
        func.count(ub.Downloads.book_id).desc()).group_by(ub.Downloads.book_id)
    hot_books = all_books.offset(off).limit(config.config_books_per_page)
    entries = list()
    for book in hot_books:
        query = calibre_db.generate_linked_query(config.config_read_column, db.Books)
        download_book = query.filter(calibre_db.common_filters()).filter(
            book.Downloads.book_id == db.Books.id).first()
        if download_book:
            entries.append(download_book)
        else:
            ub.delete_download(book.Downloads.book_id)
    num_books = entries.__len__()
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1),
                            config.config_books_per_page, num_books)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/author")
@basic_auth_or_anonymous
def feed_authorindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_AUTHOR):
        abort(404)
    return render_element_index(db.Authors.sort, db.books_authors_link, 'opds.feed_letter_author')


@opds.route("/opds/author/letter/<book_id>")
@basic_auth_or_anonymous
def feed_letter_author(book_id):
    if not auth.current_user().check_visibility(constants.SIDEBAR_AUTHOR):
        abort(404)
    off = request.args.get("offset") or 0
    letter = true() if book_id == "00" else func.upper(db.Authors.sort).startswith(book_id)
    entries = calibre_db.session.query(db.Authors).join(db.books_authors_link).join(db.Books)\
        .filter(calibre_db.common_filters()).filter(letter)\
        .group_by(text('books_authors_link.author'))\
        .order_by(db.Authors.sort)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            entries.count())
    entries = entries.limit(config.config_books_per_page).offset(off).all()
    return render_xml_template('feed.xml', listelements=entries, folder='opds.feed_author', pagination=pagination)


@opds.route("/opds/author/<int:book_id>")
@basic_auth_or_anonymous
def feed_author(book_id):
    return render_xml_dataset(db.Authors, book_id)


@opds.route("/opds/publisher")
@basic_auth_or_anonymous
def feed_publisherindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_PUBLISHER):
        abort(404)
    off = request.args.get("offset") or 0
    entries = calibre_db.session.query(db.Publishers)\
        .join(db.books_publishers_link)\
        .join(db.Books).filter(calibre_db.common_filters())\
        .group_by(text('books_publishers_link.publisher'))\
        .order_by(db.Publishers.sort)\
        .limit(config.config_books_per_page).offset(off)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            len(calibre_db.session.query(db.Publishers).all()))
    return render_xml_template('feed.xml', listelements=entries, folder='opds.feed_publisher', pagination=pagination)


@opds.route("/opds/publisher/<int:book_id>")
@basic_auth_or_anonymous
def feed_publisher(book_id):
    return render_xml_dataset(db.Publishers, book_id)


@opds.route("/opds/category")
@basic_auth_or_anonymous
def feed_categoryindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_CATEGORY):
        abort(404)
    return render_element_index(db.Tags.name, db.books_tags_link, 'opds.feed_letter_category')


@opds.route("/opds/category/letter/<book_id>")
@basic_auth_or_anonymous
def feed_letter_category(book_id):
    if not auth.current_user().check_visibility(constants.SIDEBAR_CATEGORY):
        abort(404)
    off = request.args.get("offset") or 0
    letter = true() if book_id == "00" else func.upper(db.Tags.name).startswith(book_id)
    entries = calibre_db.session.query(db.Tags)\
        .join(db.books_tags_link)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()).filter(letter)\
        .group_by(text('books_tags_link.tag'))\
        .order_by(db.Tags.name)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            entries.count())
    entries = entries.offset(off).limit(config.config_books_per_page).all()
    return render_xml_template('feed.xml', listelements=entries, folder='opds.feed_category', pagination=pagination)


@opds.route("/opds/category/<int:book_id>")
@basic_auth_or_anonymous
def feed_category(book_id):
    return render_xml_dataset(db.Tags, book_id)


@opds.route("/opds/series")
@basic_auth_or_anonymous
def feed_seriesindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_SERIES):
        abort(404)
    return render_element_index(db.Series.sort, db.books_series_link, 'opds.feed_letter_series')


@opds.route("/opds/series/letter/<book_id>")
@basic_auth_or_anonymous
def feed_letter_series(book_id):
    if not auth.current_user().check_visibility(constants.SIDEBAR_SERIES):
        abort(404)
    off = request.args.get("offset") or 0
    letter = true() if book_id == "00" else func.upper(db.Series.sort).startswith(book_id)
    entries = calibre_db.session.query(db.Series)\
        .join(db.books_series_link)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()).filter(letter)\
        .group_by(text('books_series_link.series'))\
        .order_by(db.Series.sort)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            entries.count())
    entries = entries.offset(off).limit(config.config_books_per_page).all()
    return render_xml_template('feed.xml', listelements=entries, folder='opds.feed_series', pagination=pagination)


@opds.route("/opds/series/<int:book_id>")
@basic_auth_or_anonymous
def feed_series(book_id):
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books,
                                                        db.Books.series.any(db.Series.id == book_id),
                                                        [db.Books.series_index],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/ratings")
@basic_auth_or_anonymous
def feed_ratingindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_RATING):
        abort(404)
    off = request.args.get("offset") or 0
    entries = calibre_db.session.query(db.Ratings, func.count('books_ratings_link.book').label('count'),
                                       (db.Ratings.rating / 2).label('name')) \
        .join(db.books_ratings_link)\
        .join(db.Books)\
        .filter(calibre_db.common_filters()) \
        .group_by(text('books_ratings_link.rating'))\
        .order_by(db.Ratings.rating).all()

    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            len(entries))
    element = list()
    for entry in entries:
        element.append(FeedObject(entry[0].id, _("{} Stars").format(entry.name)))
    return render_xml_template('feed.xml', listelements=element, folder='opds.feed_ratings', pagination=pagination)


@opds.route("/opds/ratings/<book_id>")
@basic_auth_or_anonymous
def feed_ratings(book_id):
    return render_xml_dataset(db.Ratings, book_id)


@opds.route("/opds/formats")
@basic_auth_or_anonymous
def feed_formatindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_FORMAT):
        abort(404)
    off = request.args.get("offset") or 0
    entries = calibre_db.session.query(db.Data).join(db.Books)\
        .filter(calibre_db.common_filters()) \
        .group_by(db.Data.format)\
        .order_by(db.Data.format).all()
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            len(entries))
    element = list()
    for entry in entries:
        element.append(FeedObject(entry.format, entry.format))
    return render_xml_template('feed.xml', listelements=element, folder='opds.feed_format', pagination=pagination)


@opds.route("/opds/formats/<book_id>")
@basic_auth_or_anonymous
def feed_format(book_id):
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books,
                                                        db.Books.data.any(db.Data.format == book_id.upper()),
                                                        [db.Books.timestamp.desc()],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/language")
@opds.route("/opds/language/")
@basic_auth_or_anonymous
def feed_languagesindex():
    if not auth.current_user().check_visibility(constants.SIDEBAR_LANGUAGE):
        abort(404)
    off = request.args.get("offset") or 0
    if auth.current_user().filter_language() == "all":
        languages = calibre_db.speaking_language()
    else:
        languages = calibre_db.session.query(db.Languages).filter(
            db.Languages.lang_code == auth.current_user().filter_language()).all()
        languages[0].name = isoLanguages.get_language_name(get_locale(), languages[0].lang_code)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            len(languages))
    return render_xml_template('feed.xml', listelements=languages, folder='opds.feed_languages', pagination=pagination)


@opds.route("/opds/language/<int:book_id>")
@basic_auth_or_anonymous
def feed_languages(book_id):
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books,
                                                        db.Books.languages.any(db.Languages.id == book_id),
                                                        [db.Books.timestamp.desc()],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/shelfindex")
@basic_auth_or_anonymous
def feed_shelfindex():
    if not (auth.current_user().is_authenticated or g.allow_anonymous):
        abort(404)
    off = request.args.get("offset") or 0
    if auth.current_user().is_anonymous:
        shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.is_public == 1).order_by(ub.Shelf.name).all()
    else:
        shelf = ub.session.query(ub.Shelf).filter(
            or_(ub.Shelf.is_public == 1, ub.Shelf.user_id == auth.current_user().id)).order_by(ub.Shelf.name).all()
    number = len(shelf)
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            number)
    return render_xml_template('feed.xml', listelements=shelf, folder='opds.feed_shelf', pagination=pagination)


@opds.route("/opds/magicshelfindex")
@basic_auth_or_anonymous
def feed_magic_shelfindex():
    if not (auth.current_user().is_authenticated or g.allow_anonymous):
        abort(404)
    off = request.args.get("offset") or 0

    if auth.current_user().is_anonymous:
        magic_shelves = ub.session.query(ub.MagicShelf).filter(
            ub.MagicShelf.is_public == 1).order_by(ub.MagicShelf.name).all()
    else:
        magic_shelves = ub.session.query(ub.MagicShelf).filter(
            or_(ub.MagicShelf.is_public == 1, ub.MagicShelf.user_id == auth.current_user().id)
        ).order_by(ub.MagicShelf.name).all()

    class OpdsMagicShelfEntry:
        def __init__(self, magic):
            self.id = magic.id
            self.name = magic.name
            self.is_public = magic.is_public
            self.icon = magic.icon
            self.is_magic_shelf = True
            self.opds_url = url_for('opds.feed_magic_shelf', shelf_id=magic.id)

    listelements = [OpdsMagicShelfEntry(magic) for magic in magic_shelves]
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1),
                            config.config_books_per_page,
                            len(listelements))
    return render_xml_template('feed.xml', listelements=listelements, folder='opds.feed_magic_shelf', pagination=pagination)


@opds.route("/opds/shelf/<int:book_id>")
@basic_auth_or_anonymous
def feed_shelf(book_id):
    if not (auth.current_user().is_authenticated or g.allow_anonymous):
        abort(404)
    off = request.args.get("offset") or 0
    if auth.current_user().is_anonymous:
        shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.is_public == 1,
                                                  ub.Shelf.id == book_id).first()
    else:
        shelf = ub.session.query(ub.Shelf).filter(or_(and_(ub.Shelf.user_id == int(auth.current_user().id),
                                                           ub.Shelf.id == book_id),
                                                      and_(ub.Shelf.is_public == 1,
                                                           ub.Shelf.id == book_id))).first()
    result = list()
    pagination = list()
    # user is allowed to access shelf
    if shelf:
        result, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1),
                                                           config.config_books_per_page,
                                                           db.Books,
                                                           ub.BookShelf.shelf == shelf.id,
                                                           [ub.BookShelf.order.asc()],
                                                           True, config.config_read_column,
                                                           ub.BookShelf, ub.BookShelf.book_id == db.Books.id)
        # delete shelf entries where book is not existent anymore, can happen if book is deleted outside calibre-web
        wrong_entries = calibre_db.session.query(ub.BookShelf) \
            .join(db.Books, ub.BookShelf.book_id == db.Books.id, isouter=True) \
            .filter(db.Books.id == None).all()
        for entry in wrong_entries:
            log.info('Not existing book {} in {} deleted'.format(entry.book_id, shelf))
            try:
                ub.session.query(ub.BookShelf).filter(ub.BookShelf.book_id == entry.book_id).delete()
                ub.session.commit()
            except (OperationalError, InvalidRequestError) as e:
                ub.session.rollback()
                log.error_or_exception("Settings Database error: {}".format(e))
    return render_xml_template('feed.xml', entries=result, pagination=pagination)


@opds.route("/opds/magicshelf/<int:shelf_id>")
@basic_auth_or_anonymous
def feed_magic_shelf(shelf_id):
    if not (auth.current_user().is_authenticated or g.allow_anonymous):
        abort(404)
    off = request.args.get("offset") or 0

    shelf = ub.session.query(ub.MagicShelf).get(shelf_id)
    if not shelf:
        abort(404)

    if auth.current_user().is_anonymous:
        if shelf.is_public != 1:
            abort(404)
    else:
        if shelf.user_id != auth.current_user().id and shelf.is_public != 1:
            abort(403)

    per_page = int(config.config_books_per_page) if config.config_books_per_page else 20
    page = int(off) // per_page + 1
    sort_order = [db.Books.timestamp.desc()]

    books, total_count = magic_shelf.get_books_for_magic_shelf(
        shelf_id,
        page=page,
        page_size=per_page,
        sort_order=sort_order,
        sort_param='opds',
        bypass_cache=True
    )

    class Entry:
        def __init__(self, book):
            self.Books = book

    entries = [Entry(book) for book in books]
    pagination = Pagination(page, per_page, total_count)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


@opds.route("/opds/download/<book_id>/<book_format>/")
@basic_auth_or_anonymous
def opds_download_link(book_id, book_format):
    if not auth.current_user().role_download():
        return abort(401)
    client = "kobo" if "Kobo" in request.headers.get('User-Agent') else ""
    return get_download_link(book_id, book_format.lower(), client)


@opds.route("/ajax/book/<string:uuid>/<library>")
@opds.route("/ajax/book/<string:uuid>", defaults={'library': ""})
@basic_auth_or_anonymous
def get_metadata_calibre_companion(uuid, library):
    entry = calibre_db.session.query(db.Books).filter(db.Books.uuid.like("%" + uuid + "%")).first()
    if entry is not None:
        js = render_template('json.txt', entry=entry)
        response = make_response(js)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        return response
    else:
        return ""


@opds.route("/opds/stats")
@basic_auth_or_anonymous
def get_database_stats():
    stat = dict()
    stat['books'] = calibre_db.session.query(db.Books).count()
    stat['authors'] = calibre_db.session.query(db.Authors).count()
    stat['categories'] = calibre_db.session.query(db.Tags).count()
    stat['series'] = calibre_db.session.query(db.Series).count()
    return Response(json.dumps(stat), mimetype="application/json")


@opds.route("/opds/thumb_240_240/<book_id>")
@opds.route("/opds/cover_240_240/<book_id>")
@opds.route("/opds/cover_90_90/<book_id>")
@opds.route("/opds/cover/<book_id>")
@basic_auth_or_anonymous
def feed_get_cover(book_id):
    return get_book_cover(book_id)


@opds.route("/opds/readbooks")
@basic_auth_or_anonymous
def feed_read_books():
    if not (auth.current_user().check_visibility(constants.SIDEBAR_READ_AND_UNREAD) and not auth.current_user().is_anonymous):
        return abort(403)
    off = request.args.get("offset") or 0
    result, pagination = render_read_books(int(off) / (int(config.config_books_per_page)) + 1, True, True)
    return render_xml_template('feed.xml', entries=result, pagination=pagination)


@opds.route("/opds/unreadbooks")
@basic_auth_or_anonymous
def feed_unread_books():
    if not (auth.current_user().check_visibility(constants.SIDEBAR_READ_AND_UNREAD) and not auth.current_user().is_anonymous):
        return abort(403)
    off = request.args.get("offset") or 0
    result, pagination = render_read_books(int(off) / (int(config.config_books_per_page)) + 1, False, True)
    return render_xml_template('feed.xml', entries=result, pagination=pagination)


class FeedObject:
    def __init__(self, rating_id, rating_name):
        self.rating_id = rating_id
        self.rating_name = rating_name

    @property
    def id(self):
        return self.rating_id

    @property
    def name(self):
        return self.rating_name


def feed_search(term):
    if term:
        entries, __, ___ = calibre_db.get_search_results(term, config=config)
        entries_count = len(entries) if len(entries) > 0 else 1
        pagination = Pagination(1, entries_count, entries_count)
        return render_xml_template('feed.xml', searchterm=term, entries=entries, pagination=pagination)
    else:
        return render_xml_template('feed.xml', searchterm="")



def render_xml_template(*args, **kwargs):
    # ToDo: return time in current timezone similar to %z
    currtime = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    xml = render_template(current_time=currtime, instance=config.config_calibre_web_title, constants=constants.sidebar_settings, *args, **kwargs)
    response = make_response(xml)
    response.headers["Content-Type"] = "application/atom+xml; charset=utf-8"
    return response


def render_xml_dataset(data_table, book_id):
    off = request.args.get("offset") or 0
    entries, __, pagination = calibre_db.fill_indexpage((int(off) / (int(config.config_books_per_page)) + 1), 0,
                                                        db.Books,
                                                        getattr(db.Books, data_table.__tablename__).any(data_table.id == book_id),
                                                        [db.Books.timestamp.desc()],
                                                        True, config.config_read_column)
    return render_xml_template('feed.xml', entries=entries, pagination=pagination)


def render_element_index(database_column, linked_table, folder):
    shift = 0
    off = int(request.args.get("offset") or 0)
    entries = calibre_db.session.query(func.upper(func.substr(database_column, 1, 1)).label('id'), None, None)
    # query = calibre_db.generate_linked_query(config.config_read_column, db.Books)
    if linked_table is not None:
        entries = entries.join(linked_table).join(db.Books)
    entries = entries.filter(calibre_db.common_filters()).group_by(func.upper(func.substr(database_column, 1, 1))).all()
    elements = []
    if off == 0 and entries:
        elements.append({'id': "00", 'name': _("All")})
        shift = 1
    for entry in entries[
                 off + shift - 1:
                 int(off + int(config.config_books_per_page) - shift)]:
        elements.append({'id': entry.id, 'name': entry.id})
    pagination = Pagination((int(off) / (int(config.config_books_per_page)) + 1), config.config_books_per_page,
                            len(entries) + 1)
    return render_xml_template('feed.xml',
                               letterelements=elements,
                               folder=folder,
                               pagination=pagination)
