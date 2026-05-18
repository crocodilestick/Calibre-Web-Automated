# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import re
import json
import threading
from datetime import datetime, timezone
from urllib.parse import quote
import unidecode
from weakref import WeakSet
from uuid import uuid4

from sqlite3 import OperationalError as sqliteOperationalError
from sqlalchemy import create_engine, event
from sqlalchemy import Table, Column, ForeignKey, CheckConstraint
from sqlalchemy import String, Integer, Boolean, TIMESTAMP, Float
from sqlalchemy.orm import relationship, sessionmaker, scoped_session, joinedload, object_session
from sqlalchemy.orm.collections import InstrumentedList
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.exc import OperationalError
try:
    # Compatibility with sqlalchemy 2.0
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.expression import and_, true, false, text, func, or_
from sqlalchemy.ext.associationproxy import association_proxy
from .cw_login import current_user
from flask_babel import gettext as _
from flask_babel import get_locale
from flask import flash

from . import logger, ub, isoLanguages
from .pagination import Pagination
from .string_helper import strip_whitespaces

log = logger.create()

# Rate-limit author-sort drift diagnostics. Books.author_sort is denormalized
# from Authors.sort and can drift after an Authors edit; the divergence is
# visual-only (within-book ordering falls back to Authors.id), but the log
# fires from every page render. Module-level set so we warn once per process
# per drifted sort string. See fork issue #108.
_AUTHOR_SORT_DRIFT_WARNED: set = set()


def _register_sqlite_udfs(dbapi_connection, _connection_record):
    """Register Python UDFs (lower, uuid4, title_sort) once per SQLite
    connection — installed as a SQLAlchemy ``connect`` event listener.

    Eliminates the GIL+SQLite deadlock vector behind CWA #1256: previously,
    request handlers (``cps/web.py:get_matching_tags``, edit-book paths,
    admin config saves, search/typeahead/check_exists) called
    ``calibre_db.create_functions()`` mid-request. With ``StaticPool``
    sharing one connection across all threads, that ``conn.create_function``
    call held the GIL while a concurrent worker thread mid-query (e.g.
    duplicate-scan SQL using ``func.lower``) was waiting for the GIL to
    invoke the registered UDF. Classic deadlock — neither thread could
    proceed and the gevent hub stalled.

    Registering UDFs at connection time means they're available for every
    SQL statement on the connection, no per-request re-registration needed.
    ``StaticPool`` reuses one connection for the engine's lifetime, so this
    listener fires exactly once unless the engine is disposed and
    re-created (e.g. via ``setup_db`` after config changes).

    ``title_sort`` reads ``CalibreDB.config.config_title_regex`` at call
    time via a closure, so admin updates to the regex are picked up without
    needing to re-register the UDF.
    """
    try:
        dbapi_connection.create_function("lower", 1, lcase)
    except Exception:
        pass
    try:
        dbapi_connection.create_function("uuid4", 0, lambda: str(uuid4()))
    except Exception:
        pass

    def _title_sort(title):
        if title is None:
            return ''
        cfg = CalibreDB.config
        try:
            regex = getattr(cfg, 'config_title_regex', None) if cfg is not None else None
            if regex:
                title_pat = re.compile(regex, re.IGNORECASE)
                match = title_pat.search(title)
                if match:
                    prep = match.group(1)
                    title = title[len(prep):] + ', ' + prep
        except Exception:
            pass
        return strip_whitespaces(title)

    try:
        dbapi_connection.create_function("title_sort", 1, _title_sort)
    except Exception:
        pass

cc_exceptions = ['composite', 'series']
cc_classes = {}

Base = declarative_base()

books_authors_link = Table('books_authors_link', Base.metadata,
                           Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                           Column('author', Integer, ForeignKey('authors.id'), primary_key=True)
                           )

books_tags_link = Table('books_tags_link', Base.metadata,
                        Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                        Column('tag', Integer, ForeignKey('tags.id'), primary_key=True)
                        )

books_series_link = Table('books_series_link', Base.metadata,
                          Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                          Column('series', Integer, ForeignKey('series.id'), primary_key=True)
                          )

books_ratings_link = Table('books_ratings_link', Base.metadata,
                           Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                           Column('rating', Integer, ForeignKey('ratings.id'), primary_key=True)
                           )

books_languages_link = Table('books_languages_link', Base.metadata,
                             Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                             Column('lang_code', Integer, ForeignKey('languages.id'), primary_key=True)
                             )

books_publishers_link = Table('books_publishers_link', Base.metadata,
                              Column('book', Integer, ForeignKey('books.id'), primary_key=True),
                              Column('publisher', Integer, ForeignKey('publishers.id'), primary_key=True)
                              )


class Library_Id(Base):
    __tablename__ = 'library_id'
    id = Column(Integer, primary_key=True)
    uuid = Column(String, nullable=False)


class Identifiers(Base):
    __tablename__ = 'identifiers'

    id = Column(Integer, primary_key=True)
    type = Column(String(collation='NOCASE'), nullable=False, default="isbn")
    val = Column(String(collation='NOCASE'), nullable=False)
    book = Column(Integer, ForeignKey('books.id'), nullable=False)

    def __init__(self, val, id_type, book):
        super().__init__()
        self.val = val
        self.type = id_type
        self.book = book

    def format_type(self):
        format_type = self.type.lower()
        if format_type == 'amazon':
            return "Amazon"
        elif format_type.startswith("amazon_"):
            return "Amazon.{0}".format(format_type[7:].lower().replace("uk","co.uk"))
        elif format_type == "isbn":
            return "ISBN"
        elif format_type == "doi":
            return "DOI"
        elif format_type == "douban":
            return "Douban"
        elif format_type == "goodreads":
            return "Goodreads"
        elif format_type == "babelio":
            return "Babelio"
        elif format_type == "google":
            return "Google Books"
        elif format_type == "kobo":
            return "Kobo"
        elif format_type == "barnesnoble":
            return "Barnes & Noble"
        elif format_type == "litres":
            return "ЛитРес"
        elif format_type == "issn":
            return "ISSN"
        elif format_type == "isfdb":
            return "ISFDB"
        elif format_type == "lubimyczytac":
            return "Lubimyczytac"
        elif format_type == "databazeknih":
            return "Databáze knih"
        elif format_type == "hardcover-slug":
            return "Hardcover"
        elif format_type == "storygraph":
            return "StoryGraph"
        elif format_type == "smashwords":
            return "Smashwords"
        elif format_type == "ebooks":
            return "Ebooks.com"
        else:
            return self.type

    def __repr__(self):
        format_type = self.type.lower()
        if format_type == "amazon" or format_type == "asin":
            return "https://amazon.com/dp/{0}".format(self.val)
        elif format_type.startswith('amazon_'):
            return "https://amazon.{0}/dp/{1}".format(format_type[7:].lower().replace("uk","co.uk"), self.val)
        elif format_type == "isbn":
            return "https://www.worldcat.org/isbn/{0}".format(self.val)
        elif format_type == "doi":
            return "https://dx.doi.org/{0}".format(self.val)
        elif format_type == "goodreads":
            return "https://www.goodreads.com/book/show/{0}".format(self.val)
        elif format_type == "babelio":
            return "https://www.babelio.com/livres/titre/{0}".format(self.val)
        elif format_type == "douban":
            return "https://book.douban.com/subject/{0}".format(self.val)
        elif format_type == "google":
            return "https://books.google.com/books?id={0}".format(self.val)
        elif format_type == "kobo":
            return "https://www.kobo.com/ebook/{0}".format(self.val)
        elif format_type == "barnesnoble":
            return "https://www.barnesandnoble.com/w/{0}".format(self.val)
        elif format_type == "lubimyczytac":
            return "https://lubimyczytac.pl/ksiazka/{0}/ksiazka".format(self.val)
        elif format_type == "litres":
            return "https://www.litres.ru/{0}".format(self.val)
        elif format_type == "issn":
            return "https://portal.issn.org/resource/ISSN/{0}".format(self.val)
        elif format_type == "isfdb":
            return "https://www.isfdb.org/cgi-bin/pl.cgi?{0}".format(self.val)
        elif format_type == "databazeknih":
            return "https://www.databazeknih.cz/knihy/{0}".format(self.val)
        elif format_type == "hardcover-slug":
            return "https://hardcover.app/books/{0}".format(self.val)
        elif format_type == "ibdb":
            return "https://ibdb.dev/book/{0}".format(self.val)
        elif format_type == "storygraph":
            return "https://app.thestorygraph.com/books/{0}".format(self.val)
        elif format_type == "smashwords":
            return "https://www.smashwords.com/books/view/{0}".format(self.val)
        elif format_type == "ebooks":
            return "https://www.ebooks.com/en-{0}".format(self.val)
        elif self.val.lower().startswith("javascript:"):
            return quote(self.val)
        elif self.val.lower().startswith("data:"):
            link, __, __ = str.partition(self.val, ",")
            return link
        else:
            return "{0}".format(self.val)


class Comments(Base):
    __tablename__ = 'comments'

    id = Column(Integer, primary_key=True)
    book = Column(Integer, ForeignKey('books.id'), nullable=False, unique=True)
    text = Column(String(collation='NOCASE'), nullable=False)

    def __init__(self, comment, book):
        super().__init__()
        self.text = comment
        self.book = book

    def get(self):
        return self.text

    def __repr__(self):
        return "<Comments({0})>".format(self.text)


class Tags(Base):
    __tablename__ = 'tags'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(collation='NOCASE'), unique=True, nullable=False)

    def __init__(self, name):
        super().__init__()
        self.name = name

    def get(self):
        return self.name

    def __eq__(self, other):
        return self.name == other

    def __repr__(self):
        return "<Tags('{0})>".format(self.name)


class Authors(Base):
    __tablename__ = 'authors'

    id = Column(Integer, primary_key=True)
    name = Column(String(collation='NOCASE'), unique=True, nullable=False)
    sort = Column(String(collation='NOCASE'))
    link = Column(String, nullable=False, default="")

    def __init__(self, name, sort, link=""):
        super().__init__()
        self.name = name
        self.sort = sort
        self.link = link

    def get(self):
        return self.name

    def __eq__(self, other):
        return self.name == other

    def __repr__(self):
        return "<Authors('{0},{1}{2}')>".format(self.name, self.sort, self.link)


class Series(Base):
    __tablename__ = 'series'

    id = Column(Integer, primary_key=True)
    name = Column(String(collation='NOCASE'), unique=True, nullable=False)
    sort = Column(String(collation='NOCASE'))

    def __init__(self, name, sort):
        super().__init__()
        self.name = name
        self.sort = sort

    def get(self):
        return self.name

    def __eq__(self, other):
        return self.name == other

    def __repr__(self):
        return "<Series('{0},{1}')>".format(self.name, self.sort)


class Ratings(Base):
    __tablename__ = 'ratings'

    id = Column(Integer, primary_key=True)
    rating = Column(Integer, CheckConstraint('rating>-1 AND rating<11'), unique=True)

    def __init__(self, rating):
        super().__init__()
        self.rating = rating

    def get(self):
        return self.rating

    def __eq__(self, other):
        return self.rating == other

    def __repr__(self):
        return "<Ratings('{0}')>".format(self.rating)


class Languages(Base):
    __tablename__ = 'languages'

    id = Column(Integer, primary_key=True)
    lang_code = Column(String(collation='NOCASE'), nullable=False, unique=True)

    def __init__(self, lang_code):
        super().__init__()
        self.lang_code = lang_code

    def get(self):
        if hasattr(self, "language_name"):
            return self.language_name
        else:
            return self.lang_code

    def __eq__(self, other):
        return self.lang_code == other

    def __repr__(self):
        return "<Languages('{0}')>".format(self.lang_code)


class Publishers(Base):
    __tablename__ = 'publishers'

    id = Column(Integer, primary_key=True)
    name = Column(String(collation='NOCASE'), nullable=False, unique=True)
    sort = Column(String(collation='NOCASE'))

    def __init__(self, name, sort):
        super().__init__()
        self.name = name
        self.sort = sort

    def get(self):
        return self.name

    def __eq__(self, other):
        return self.name == other

    def __repr__(self):
        return "<Publishers('{0},{1}')>".format(self.name, self.sort)


class Data(Base):
    __tablename__ = 'data'
    __table_args__ = {'schema': 'calibre'}

    id = Column(Integer, primary_key=True)
    book = Column(Integer, ForeignKey('books.id'), nullable=False)
    format = Column(String(collation='NOCASE'), nullable=False)
    uncompressed_size = Column(Integer, nullable=False)
    name = Column(String, nullable=False)

    def __init__(self, book, book_format, uncompressed_size, name):
        super().__init__()
        self.book = book
        self.format = book_format
        self.uncompressed_size = uncompressed_size
        self.name = name

    # ToDo: Check
    def get(self):
        return self.name

    def __repr__(self):
        return "<Data('{0},{1}{2}{3}')>".format(self.book, self.format, self.uncompressed_size, self.name)


class Metadata_Dirtied(Base):
    __tablename__ = 'metadata_dirtied'
    id = Column(Integer, primary_key=True, autoincrement=True)
    book = Column(Integer, ForeignKey('books.id'), nullable=False, unique=True)

    def __init__(self, book):
        super().__init__()
        self.book = book


# Import BookFormatChecksum from progress_syncing.models to keep model definition centralized
# Import directly from models module to avoid triggering progress_syncing/__init__.py chain
# which would cause circular import (models needs Base from db, but progress_syncing imports kosync)
from .progress_syncing import models as _progress_models  # noqa: E402
BookFormatChecksum = _progress_models.BookFormatChecksum


class Books(Base):
    __tablename__ = 'books'

    DEFAULT_PUBDATE = datetime(101, 1, 1, 0, 0, 0, 0)  # ("0101-01-01 00:00:00+00:00")
    _has_isbn_column = None

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(collation='NOCASE'), nullable=False, default='Unknown')
    sort = Column(String(collation='NOCASE'))
    author_sort = Column(String(collation='NOCASE'))
    timestamp = Column(TIMESTAMP, default=lambda: datetime.now(timezone.utc))
    pubdate = Column(TIMESTAMP, default=DEFAULT_PUBDATE)
    series_index = Column(String, nullable=False, default="1.0")
    last_modified = Column(TIMESTAMP, default=lambda: datetime.now(timezone.utc))
    path = Column(String, default="", nullable=False)
    has_cover = Column(Integer, default=0)
    uuid = Column(String)

    # Eager loading strategy: selectin, not subquery. Fork issues #184 + #185.
    # `lazy='selectin'` (introduced upstream PR #1279, fork PR #40 / bc9386c)
    # produced intermittent empty .authors / .tags / .languages / .comments on
    # books returned through `fill_indexpage`-shaped queries — the post-load's
    # inner subselect reproduces the parent FROM/WHERE/ORDER/LIMIT, so any
    # query-compile-state leak across the captured `CalibreDB.session` could
    # cause some books' relationships to be skipped (template renders missing
    # <summary> / <author> / <dcterms:language> / <category>). `lazy='selectin'`
    # is the modern SQLAlchemy 2.0 recommendation for collection eager loads:
    # one extra `WHERE parent_id IN (...)` query per relationship, atomic, no
    # dependence on parent SQL. Still eager, so PR #40's DetachedInstanceError
    # case (upstream #1067 / #1130 / #1139) remains covered. See
    # notes/184-185-DESIGN.md for the live SQL trace + verification.
    authors = relationship(Authors, secondary=books_authors_link, backref='books', lazy='selectin')
    tags = relationship(Tags, secondary=books_tags_link, backref='books', order_by="Tags.name", lazy='selectin')
    comments = relationship(Comments, backref='books', lazy='selectin')
    data = relationship(Data, backref='books', lazy='selectin')
    series = relationship(Series, secondary=books_series_link, backref='books', lazy='selectin')
    ratings = relationship(Ratings, secondary=books_ratings_link, backref='books', lazy='selectin')
    languages = relationship(Languages, secondary=books_languages_link, backref='books', lazy='selectin')
    publishers = relationship(Publishers, secondary=books_publishers_link, backref='books', lazy='selectin')
    identifiers = relationship(Identifiers, backref='books', lazy='selectin')

    def __init__(self, title, sort, author_sort, timestamp, pubdate, series_index, last_modified, path, has_cover,
                 authors, tags, languages=None):
        super().__init__()
        self.title = title
        self.sort = sort
        self.author_sort = author_sort
        self.timestamp = timestamp
        self.pubdate = pubdate
        self.series_index = series_index
        self.last_modified = last_modified
        self.path = path
        self.has_cover = (has_cover is not None)

    def __repr__(self):
        return "<Books('{0},{1}{2}{3}{4}{5}{6}{7}{8}')>".format(self.title, self.sort, self.author_sort,
                                                                self.timestamp, self.pubdate, self.series_index,
                                                                self.last_modified, self.path, self.has_cover)

    @property
    def atom_timestamp(self):
        # OPDS atom:updated is defined as "the most recent instant in time
        # when the entry was modified". Books.timestamp is the date added and
        # never changes after import, so metadata and cover edits were
        # invisible to OPDS sync clients. Use last_modified, which Calibre
        # updates on every metadata or cover change; fall back to timestamp
        # only if last_modified happens to be missing.
        t = self.last_modified or self.timestamp
        if t is None:
            return ''
        return t.strftime('%Y-%m-%dT%H:%M:%S+00:00') or ''

    @property
    def isbn(self):
        for identifier in self.identifiers:
            if identifier.type and identifier.type.lower() == "isbn":
                return identifier.val or ""
        if self._has_isbn_column:
            session = object_session(self)
            if session is not None:
                try:
                    value = session.execute(text("SELECT isbn FROM books WHERE id = :id"),
                                            {"id": self.id}).scalar()
                    return value or ""
                except Exception:
                    Books._has_isbn_column = False
                    return ""
        return ""


class CustomColumns(Base):
    __tablename__ = 'custom_columns'

    id = Column(Integer, primary_key=True)
    label = Column(String)
    name = Column(String)
    datatype = Column(String)
    mark_for_delete = Column(Boolean)
    editable = Column(Boolean)
    display = Column(String)
    is_multiple = Column(Boolean)
    normalized = Column(Boolean)

    def get_display_dict(self):
        display_dict = json.loads(self.display)
        return display_dict

    def to_json(self, value, extra, sequence):
        content = dict()
        content['table'] = "custom_column_" + str(self.id)
        content['column'] = "value"
        content['datatype'] = self.datatype
        content['is_multiple'] = None if not self.is_multiple else "|"
        content['kind'] = "field"
        content['name'] = self.name
        content['search_terms'] = ['#' + self.label]
        content['label'] = self.label
        content['colnum'] = self.id
        content['display'] = self.get_display_dict()
        content['is_custom'] = True
        content['is_category'] = self.datatype in ['text', 'rating', 'enumeration', 'series']
        content['link_column'] = "value"
        content['category_sort'] = "value"
        content['is_csp'] = False
        content['is_editable'] = self.editable
        content['rec_index'] = sequence + 22     # toDo why ??
        if isinstance(value, datetime):
            content['#value#'] = {"__class__": "datetime.datetime",
                                  "__value__": value.strftime("%Y-%m-%dT%H:%M:%S+00:00")}
        else:
            content['#value#'] = value
        content['#extra#'] = extra
        content['is_multiple2'] = {} if not self.is_multiple else {"cache_to_list": "|", "ui_to_list": ",",
                                                                   "list_to_ui": ", "}
        return json.dumps(content, ensure_ascii=False)


class AlchemyEncoder(json.JSONEncoder):

    def default(self, o):
        if isinstance(o.__class__, DeclarativeMeta):
            # an SQLAlchemy class
            fields = {}
            for field in [x for x in dir(o) if not x.startswith('_') and x != 'metadata' and x != "password"]:
                if field == 'books':
                    continue
                data = o.__getattribute__(field)
                try:
                    if isinstance(data, str):
                        data = data.replace("'", "\'")
                    elif isinstance(data, InstrumentedList):
                        el = list()
                        # ele = None
                        for ele in data:
                            if hasattr(ele, 'value'):       # converter for custom_column values
                                if isinstance(ele.value, datetime):
                                    el.append(ele.value.date().isoformat())
                                else:
                                    el.append(str(ele.value))
                            elif ele.get:
                                el.append(ele.get())
                            else:
                                el.append(json.dumps(ele, cls=AlchemyEncoder))
                        if field == 'authors':
                            data = " & ".join(el)
                        else:
                            data = ",".join(el)
                        if data == '[]':
                            data = ""
                    else:
                        json.dumps(data)
                    fields[field] = data
                except Exception:
                    fields[field] = ""
            # a json-encodable dict
            return fields

        return json.JSONEncoder.default(self, o)


class CalibreDB:
    _init = False
    engine = None
    config = None
    session_factory = None
    # This is a WeakSet so that references here don't keep other CalibreDB
    # instances alive once they reach the end of their respective scopes
    instances = WeakSet()
    _reconnect_lock = threading.RLock()  # Reentrant lock to prevent concurrent reconnect operations

    def __init__(self, expire_on_commit=True, init=False):
        """ Initialize a new CalibreDB session
        """
        self.session = None
        if init:
            self.init_db(expire_on_commit)

    def init_db(self, expire_on_commit=True):
        if self._init:
            self.init_session(expire_on_commit)

        self.instances.add(self)

    def init_session(self, expire_on_commit=True):
        if self.session_factory is None:
            log.error("Cannot init session: session_factory is None")
            return
        self.session = self.session_factory()
        self.session.expire_on_commit = expire_on_commit
        # UDFs (lower/uuid4/title_sort) are registered once per SQLite
        # connection via the engine-level ``connect`` event listener
        # (``_register_sqlite_udfs``); no per-Session call needed.

    def ensure_session(self, expire_on_commit=True):
        """Ensure a valid SQLAlchemy session exists.
        This protects against brief windows where dispose() nulled the session during a reconnect.
        Holds lock during entire recreation to prevent race conditions.
        """
        if self.session is not None:
            return  # Fast path - session already exists
        
        # Session is None - need to recreate it
        # Acquire lock to ensure atomic recreation (no interruption by dispose)
        with self._reconnect_lock:
            # Double-check after acquiring lock (another thread may have recreated it)
            if self.session is not None:
                return
            
            # Try to recreate session from factory
            if self.session_factory is not None:
                try:
                    self.init_session(expire_on_commit)
                    return  # Success
                except Exception as ex:
                    log.error(f"Failed to init session from factory: {ex}")
            
            # Factory is None or init failed - try to rebuild entire database setup
            if self.config and getattr(self.config, 'config_calibre_dir', None):
                try:
                    log.warning("Session factory unavailable, attempting to rebuild database setup")
                    # Note: setup_db will call dispose() which is safe because we hold _reconnect_lock (RLock is reentrant)
                    self.setup_db(self.config.config_calibre_dir, ub.app_DB_path)
                    # After setup_db, session_factory should exist, try to init session
                    if self.session is None and self.session_factory is not None:
                        self.init_session(expire_on_commit)
                        if self.session is not None:
                            return
                except Exception as ex:
                    log.error(f"Failed to rebuild database setup in ensure_session: {ex}")

            # Fallback: attempt to initialize from app.db if config is missing or setup failed
            if self.session is None and ub.app_DB_path:
                try:
                    log.warning("Session still unavailable; attempting init from app.db")
                    from .calibre_init import init_calibre_db_from_app_db
                    if init_calibre_db_from_app_db(ub.app_DB_path):
                        self.init_session(expire_on_commit)
                        if self.session is not None:
                            return
                except Exception as ex:
                    log.error(f"Failed to init session from app.db in ensure_session: {ex}")
            
            # If we still don't have a session, log warning
            # Don't raise exception - let caller handle AttributeError if they try to use None session
            if self.session is None:
                log.error("ensure_session: Unable to create session - session factory and config unavailable")

    @classmethod
    def setup_db_cc_classes(cls, cc):
        cc_ids = []
        books_custom_column_links = {}
        for row in cc:
            if row.datatype not in cc_exceptions:
                if row.datatype == 'series':
                    dicttable = {'__tablename__': 'books_custom_column_' + str(row.id) + '_link',
                                 'id': Column(Integer, primary_key=True),
                                 'book': Column(Integer, ForeignKey('books.id'),
                                                primary_key=True),
                                 'map_value': Column('value', Integer,
                                                     ForeignKey('custom_column_' +
                                                                str(row.id) + '.id'),
                                                     primary_key=True),
                                 'extra': Column(Float),
                                 'asoc': relationship('custom_column_' + str(row.id), uselist=False),
                                 'value': association_proxy('asoc', 'value')
                                 }
                    books_custom_column_links[row.id] = type(str('books_custom_column_' + str(row.id) + '_link'),
                                                             (Base,), dicttable)
                if row.datatype in ['rating', 'text', 'enumeration']:
                    books_custom_column_links[row.id] = Table('books_custom_column_' + str(row.id) + '_link',
                                                              Base.metadata,
                                                              Column('book', Integer, ForeignKey('books.id'),
                                                                     primary_key=True),
                                                              Column('value', Integer,
                                                                     ForeignKey('custom_column_' +
                                                                                str(row.id) + '.id'),
                                                                     primary_key=True)
                                                              )
                cc_ids.append([row.id, row.datatype])

                ccdict = {'__tablename__': 'custom_column_' + str(row.id),
                          'id': Column(Integer, primary_key=True)}
                if row.datatype == 'float':
                    ccdict['value'] = Column(Float)
                elif row.datatype == 'int':
                    ccdict['value'] = Column(Integer)
                elif row.datatype == 'datetime':
                    ccdict['value'] = Column(TIMESTAMP)
                elif row.datatype == 'bool':
                    ccdict['value'] = Column(Boolean)
                else:
                    ccdict['value'] = Column(String)
                if row.datatype in ['float', 'int', 'bool', 'datetime', 'comments']:
                    ccdict['book'] = Column(Integer, ForeignKey('books.id'))
                cc_classes[row.id] = type(str('custom_column_' + str(row.id)), (Base,), ccdict)

        for cc_id in cc_ids:
            if cc_id[1] in ['bool', 'int', 'float', 'datetime', 'comments']:
                setattr(Books,
                        'custom_column_' + str(cc_id[0]),
                        relationship(cc_classes[cc_id[0]],
                                     primaryjoin=(
                                         Books.id == cc_classes[cc_id[0]].book),
                                     backref='books'))
            elif cc_id[1] == 'series':
                setattr(Books,
                        'custom_column_' + str(cc_id[0]),
                        relationship(books_custom_column_links[cc_id[0]],
                                     backref='books'))
            else:
                setattr(Books,
                        'custom_column_' + str(cc_id[0]),
                        relationship(cc_classes[cc_id[0]],
                                     secondary=books_custom_column_links[cc_id[0]],
                                     backref='books'))

        return cc_classes

    @classmethod
    def check_valid_db(cls, config_calibre_dir, app_db_path, config_calibre_uuid):
        if not config_calibre_dir:
            return False, False
        dbpath = os.path.join(config_calibre_dir, "metadata.db")
        if not os.path.exists(dbpath):
            return False, False
        db_writable = os.access(dbpath, os.W_OK)
        try:
            check_engine = create_engine('sqlite://',
                                         echo=False,
                                         isolation_level="SERIALIZABLE",
                                         connect_args={'check_same_thread': False, 'timeout': 30},
                                         poolclass=StaticPool)
            event.listen(check_engine, "connect", _register_sqlite_udfs)
            with check_engine.begin() as connection:
                connection.execute(text("attach database '{}' as calibre;".format(dbpath)))
                connection.execute(text("attach database '{}' as app_settings;".format(app_db_path)))
                # Try enabling WAL to improve concurrency unless running on a network share
                # Controlled by env var NETWORK_SHARE_MODE (default False)
                try:
                    nsm = os.getenv('NETWORK_SHARE_MODE', 'False').lower() in ('1', 'true', 'yes', 'on')
                    if not nsm and db_writable:
                        connection.execute(text("PRAGMA calibre.journal_mode=WAL"))
                        connection.execute(text("PRAGMA app_settings.journal_mode=WAL"))
                    else:
                        reason = "NETWORK_SHARE_MODE=true" if nsm else "metadata.db not writable"
                        log.warning("WAL mode disabled for calibre/app_settings (%s)", reason)
                except Exception:
                    pass
                # Wait up to 60s for any external writer (calibredb during
                # ingest) instead of failing fast on contention. Required
                # for fork issue #192 — without this, transient locks on
                # mergerfs/SMB/NFS surface as immediate OperationalError.
                try:
                    connection.execute(text("PRAGMA busy_timeout=60000"))
                except Exception:
                    pass
                local_session = scoped_session(sessionmaker())
                local_session.configure(bind=connection)
                database_uuid = local_session().query(Library_Id).one_or_none()
                # local_session.dispose()

            check_engine.connect()
            db_change = config_calibre_uuid != database_uuid.uuid
        except Exception:
            return False, False
        return True, db_change

    @classmethod
    def update_config(cls, config):
        cls.config = config

    @classmethod
    def setup_db(cls, config_calibre_dir, app_db_path):
        # Wrap entire method in lock to ensure atomic setup operation
        # RLock is reentrant, so nested calls (e.g., from reconnect_db) are safe
        with cls._reconnect_lock:
            # Always call dispose to clean up old sessions/connections
            cls.dispose()

            if not config_calibre_dir:
                log.error("setup_db failed: config_calibre_dir is None or empty")
                if cls.config:
                    cls.config.invalidate()
                return None

            dbpath = os.path.join(config_calibre_dir, "metadata.db")
            if not os.path.exists(dbpath):
                log.error(f"setup_db failed: metadata.db not found at {dbpath}")
                if cls.config:
                    if hasattr(cls.config, "invalidate"):
                        cls.config.invalidate()
                return None

            db_writable = os.access(dbpath, os.W_OK)

            try:
                cls.engine = create_engine('sqlite://',
                                           echo=False,
                                           isolation_level="SERIALIZABLE",
                                           connect_args={'check_same_thread': False, 'timeout': 30},
                                           poolclass=StaticPool)
                event.listen(cls.engine, "connect", _register_sqlite_udfs)
                with cls.engine.begin() as connection:
                    connection.execute(text("attach database '{}' as calibre;".format(dbpath)))
                    connection.execute(text("attach database '{}' as app_settings;".format(app_db_path)))
                    # Try enabling WAL to improve concurrency unless running on a network share
                    # Controlled by env var NETWORK_SHARE_MODE (default False)
                    try:
                        nsm = os.getenv('NETWORK_SHARE_MODE', 'False').lower() in ('1', 'true', 'yes', 'on')
                        if not nsm and db_writable:
                            connection.execute(text("PRAGMA calibre.journal_mode=WAL"))
                            connection.execute(text("PRAGMA app_settings.journal_mode=WAL"))
                        else:
                            reason = "NETWORK_SHARE_MODE=true" if nsm else "metadata.db not writable"
                            log.warning("WAL mode disabled for calibre/app_settings (%s)", reason)
                    except Exception:
                        pass
                    # Wait up to 60s for any external writer (calibredb
                    # during ingest) before failing the query. Required
                    # for fork issue #192 — without this, transient
                    # locks on mergerfs/SMB/NFS surface as immediate
                    # apsw.BusyError and crash the import.
                    try:
                        connection.execute(text("PRAGMA busy_timeout=60000"))
                    except Exception:
                        pass

                conn = cls.engine.connect()
                # conn.text_factory = lambda b: b.decode(errors = 'ignore') possible fix for #1302
            except Exception as ex:
                log.error(f"setup_db failed during engine creation: {ex}")
                if cls.config:
                    if hasattr(cls.config, "invalidate"):
                        cls.config.invalidate(ex)
                return None

            if cls.config:
                cls.config.db_configured = True

            if not cc_classes:
                try:
                    cc = conn.execute(text("SELECT id, datatype FROM custom_columns"))
                    cls.setup_db_cc_classes(cc)
                except OperationalError as e:
                    log.error_or_exception(e)
                    if cls.config:
                        if hasattr(cls.config, "invalidate"):
                            cls.config.invalidate(e)
                    return None

            try:
                cols = conn.execute(text("PRAGMA calibre.table_info(books)")).fetchall()
                Books._has_isbn_column = any(row[1] == "isbn" for row in cols)
            except Exception:
                Books._has_isbn_column = False

            cls.session_factory = scoped_session(sessionmaker(autocommit=False,
                                                              autoflush=True,
                                                              bind=cls.engine, future=True))
            for inst in cls.instances:
                inst.init_session()

            # Ensure progress syncing tables exist in metadata.db (book checksums)
            from .progress_syncing.models import ensure_calibre_db_tables
            from .progress_syncing.settings import is_koreader_sync_enabled
            if (
                db_writable
                and os.getenv('NETWORK_SHARE_MODE', 'False').lower() not in ('1', 'true', 'yes', 'on')
                and is_koreader_sync_enabled()
            ):
                ensure_calibre_db_tables(conn)

            cls._init = True
        # End of with cls._reconnect_lock

    def get_book(self, book_id):
        self.ensure_session()
        return self.session.query(Books).filter(Books.id == book_id).first()

    def get_filtered_book(self, book_id, allow_show_archived=False):
        self.ensure_session()
        # Eagerly load all relationships to prevent detached instance errors during editing
        return (self.session.query(Books)
                .options(joinedload(Books.authors),
                         joinedload(Books.tags),
                         joinedload(Books.comments),
                         joinedload(Books.data),
                         joinedload(Books.series),
                         joinedload(Books.ratings),
                         joinedload(Books.languages),
                         joinedload(Books.publishers),
                         joinedload(Books.identifiers))
                .filter(Books.id == book_id)
                .filter(self.common_filters(allow_show_archived))
                .first())

    def get_book_read_archived(self, book_id, read_column, allow_show_archived=False):
        self.ensure_session()
        if not read_column:
            bd = (self.session.query(Books, ub.ReadBook.read_status, ub.ArchivedBook.is_archived).select_from(Books)
                  .join(ub.ReadBook, and_(ub.ReadBook.user_id == int(current_user.id), ub.ReadBook.book_id == book_id),
                  isouter=True))
        else:
            try:
                read_column = cc_classes[read_column]
                bd = (self.session.query(Books, read_column.value, ub.ArchivedBook.is_archived).select_from(Books)
                      .join(read_column, read_column.book == book_id,
                      isouter=True))
            except (KeyError, AttributeError, IndexError):
                log.error("Custom Column No.{} does not exist in calibre database".format(read_column))
                # Skip linking read column and return None instead of read status
                bd = self.session.query(Books, None, ub.ArchivedBook.is_archived)
        # Eagerly load the data relationship to prevent session errors
        bd = bd.options(joinedload(Books.data))
        return (bd.filter(Books.id == book_id)
                .join(ub.ArchivedBook, and_(Books.id == ub.ArchivedBook.book_id,
                                            int(current_user.id) == ub.ArchivedBook.user_id), isouter=True)
                .filter(self.common_filters(allow_show_archived)).first())

    def get_book_by_uuid(self, book_uuid):
        self.ensure_session()
        return self.session.query(Books).filter(Books.uuid == book_uuid).first()

    def get_book_by_uuid_for_kobo(self, book_uuid, *, enforce_policy):
        """Return the Books row by uuid for the Kobo blueprint.

        ``enforce_policy=True``: applies ``common_filters`` (hidden,
        denied-tags, language, custom-column ACL) so policy-restricted
        books are invisible — symmetric with what the web UI / OPDS /
        sync push show. Pass on policy-boundary endpoints (metadata GET,
        shelf-add).

        ``enforce_policy=False``: bypasses filters. Use on device-
        trailing endpoints (state GET/PUT) and on destructive user-
        initiated ops (shelf-remove, book DELETE) so the device can
        always clean up and keep sync state working for books already
        on the device.

        ``allow_show_archived=True`` always on the Kobo path — the
        ``ArchivedBook`` table doubles as the Kobo's "deleted locally"
        track. Filtering on it would 404 the device's own deletions.

        Decision matrix: notes/KOBO-B4-COMMON-FILTERS-POLICY.md.
        """
        self.ensure_session()
        q = self.session.query(Books).filter(Books.uuid == book_uuid)
        if enforce_policy:
            q = q.filter(self.common_filters(allow_show_archived=True))
        return q.first()

    def get_book_format(self, book_id, file_format):
        self.ensure_session()
        return self.session.query(Data).filter(Data.book == book_id).filter(Data.format == file_format).first()

    def get_author_by_name(self, name):
        self.ensure_session()
        return self.session.query(Authors).filter(Authors.name == name).first()

    def get_tag_by_name(self, name):
        self.ensure_session()
        return self.session.query(Tags).filter(Tags.name == name).first()

    def get_series_by_name(self, name):
        self.ensure_session()
        return self.session.query(Series).filter(Series.name == name).first()

    def get_publisher_by_name(self, name):
        self.ensure_session()
        return self.session.query(Publishers).filter(Publishers.name == name).first()

    def set_metadata_dirty(self, book_id):
        self.ensure_session()
        if not self.session.query(Metadata_Dirtied).filter(Metadata_Dirtied.book == book_id).one_or_none():
            self.session.add(Metadata_Dirtied(book_id))

    def delete_dirty_metadata(self, book_id):
        self.ensure_session()
        try:
            self.session.query(Metadata_Dirtied).filter(Metadata_Dirtied.book == book_id).delete()
            self.session.commit()
        except (OperationalError) as e:
            self.session.rollback()
            log.error("Database error: {}".format(e))

    # Language and content filters for displaying in the UI
    def common_filters(
        self,
        allow_show_archived=False,
        return_all_languages=False,
        viewing_tag_id=None,
        allow_show_hidden=False,
        extra_filter=None,
    ):
        if not allow_show_archived:
            archived_books = (ub.session.query(ub.ArchivedBook)
                              .filter(ub.ArchivedBook.user_id==int(current_user.id))
                              .filter(ub.ArchivedBook.is_archived.is_(True))
                              .all())
            archived_book_ids = [archived_book.book_id for archived_book in archived_books]
            archived_filter = Books.id.notin_(archived_book_ids)
        else:
            archived_filter = true()

        # Per-user hidden books — fork issue #64. allow_show_hidden=True is the
        # /hidden listing's escape hatch (so users can see + unhide).
        if not allow_show_hidden and not current_user.is_anonymous:
            hidden_books = (ub.session.query(ub.UserHiddenBook)
                            .filter(ub.UserHiddenBook.user_id == int(current_user.id))
                            .all())
            hidden_book_ids = [h.book_id for h in hidden_books]
            hidden_filter = Books.id.notin_(hidden_book_ids)
        else:
            hidden_filter = true()

        if current_user.filter_language() == "all" or return_all_languages:
            lang_filter = true()
        else:
            lang_filter = Books.languages.any(Languages.lang_code == current_user.filter_language())
        negtags_list = current_user.list_denied_tags()
        postags_list = current_user.list_allowed_tags()
        neg_content_tags_filter = false() if negtags_list == [''] else Books.tags.any(Tags.name.in_(negtags_list))
        
        # Issue #906: When viewing a specific tag category, include that tag in allowed tags
        if viewing_tag_id is not None and postags_list != ['']:
            # Get the tag name for the viewing_tag_id
            viewing_tag = self.session.query(Tags).filter(Tags.id == viewing_tag_id).first()
            if viewing_tag and viewing_tag.name not in postags_list:
                # Temporarily add the viewed tag to the allowed list for this query
                postags_list = postags_list + [viewing_tag.name]
        
        pos_content_tags_filter = true() if postags_list == [''] else Books.tags.any(Tags.name.in_(postags_list))
        if self.config.config_restricted_column:
            try:
                pos_cc_list = current_user.allowed_column_value.split(',')
                pos_content_cc_filter = true() if pos_cc_list == [''] else \
                    getattr(Books, 'custom_column_' + str(self.config.config_restricted_column)). \
                    any(cc_classes[self.config.config_restricted_column].value.in_(pos_cc_list))
                neg_cc_list = current_user.denied_column_value.split(',')
                neg_content_cc_filter = false() if neg_cc_list == [''] else \
                    getattr(Books, 'custom_column_' + str(self.config.config_restricted_column)). \
                    any(cc_classes[self.config.config_restricted_column].value.in_(neg_cc_list))
            except (KeyError, AttributeError, IndexError):
                pos_content_cc_filter = false()
                neg_content_cc_filter = true()
                log.error("Custom Column No.{} does not exist in calibre database".format(
                    self.config.config_restricted_column))
                flash(_("Custom Column No.%(column)d does not exist in calibre database",
                        column=self.config.config_restricted_column),
                      category="error")

        else:
            pos_content_cc_filter = true()
            neg_content_cc_filter = false()
        if extra_filter is None:
            extra_filter = true()
        return and_(lang_filter, pos_content_tags_filter, ~neg_content_tags_filter,
                    pos_content_cc_filter, ~neg_content_cc_filter, archived_filter,
                    hidden_filter, extra_filter)

    def generate_linked_query(self, config_read_column, database):
        # Safety: session can be briefly None during DB reconnects
        self.ensure_session()
        if not config_read_column:
            query = (self.session.query(database, ub.ArchivedBook.is_archived, ub.ReadBook.read_status)
                     .select_from(Books)
                     .outerjoin(ub.ReadBook,
                                and_(ub.ReadBook.user_id == int(current_user.id), ub.ReadBook.book_id == Books.id)))
        else:
            try:
                read_column = cc_classes[config_read_column]
                query = (self.session.query(database, ub.ArchivedBook.is_archived, read_column.value)
                         .select_from(Books)
                         .outerjoin(read_column, read_column.book == Books.id))
            except (KeyError, AttributeError, IndexError):
                log.error("Custom Column No.{} does not exist in calibre database".format(config_read_column))
                # Skip linking read column and return None instead of read status
                query = self.session.query(database, None, ub.ArchivedBook.is_archived)
        return query.outerjoin(ub.ArchivedBook, and_(Books.id == ub.ArchivedBook.book_id,
                                                     int(current_user.id) == ub.ArchivedBook.user_id))

    @staticmethod
    def get_checkbox_sorted(inputlist, state, offset, limit, order, combo=False):
        outcome = list()
        if combo:
            elementlist = {ele[0].id: ele for ele in inputlist}
        else:
            elementlist = {ele.id: ele for ele in inputlist}
        for entry in state:
            try:
                outcome.append(elementlist[entry])
            except KeyError:
                pass
            del elementlist[entry]
        for entry in elementlist:
            outcome.append(elementlist[entry])
        if order == "asc":
            outcome.reverse()
        return outcome[offset:offset + limit]

    # Fill indexpage with all requested data from database
    def fill_indexpage(self, page, pagesize, database, db_filter, order,
                       join_archive_read=False, config_read_column=0, *join, **kwargs):
        self.ensure_session()
        return self.fill_indexpage_with_archived_books(page, database, pagesize, db_filter, order, False,
                                                       join_archive_read, config_read_column, *join, **kwargs)

    def fill_indexpage_with_archived_books(self, page, database, pagesize, db_filter, order, allow_show_archived,
                                           join_archive_read, config_read_column, *join, **kwargs):
        self.ensure_session()
        viewing_tag_id = kwargs.get('viewing_tag_id')
        allow_show_hidden = kwargs.get('allow_show_hidden', False)
        extra_filter = kwargs.get('extra_filter')
        pagesize = pagesize or self.config.config_books_per_page
        if current_user.show_detail_random():
            random_query = self.generate_linked_query(config_read_column, database)
            # Eagerly load template relationships to prevent detached lazy-load
            # failures if another request tears down the shared scoped session.
            if database == Books:
                random_query = random_query.options(
                    joinedload(Books.authors),
                    joinedload(Books.data),
                    joinedload(Books.series),
                    joinedload(Books.ratings),
                )
            randm = (random_query.filter(self.common_filters(allow_show_archived,
                                                             viewing_tag_id=viewing_tag_id,
                                                             allow_show_hidden=allow_show_hidden,
                                                             extra_filter=extra_filter))
                     .order_by(func.random())
                     .limit(self.config.config_random_books).all())
        else:
            randm = false()
        if join_archive_read:
            query = self.generate_linked_query(config_read_column, database)
        else:
            query = self.session.query(database)
        
        # Eagerly load template relationships to prevent DetachedInstanceError
        # during rendering under concurrent status/notification requests.
        if database == Books:
            query = query.options(
                joinedload(Books.authors),
                joinedload(Books.data),
                joinedload(Books.series),
                joinedload(Books.ratings),
            )
        
        off = int(int(pagesize) * (page - 1))

        indx = len(join)
        element = 0
        while indx:
            if indx >= 3:
                query = query.outerjoin(join[element], join[element+1]).outerjoin(join[element+2])
                indx -= 3
                element += 3
            elif indx == 2:
                query = query.outerjoin(join[element], join[element+1])
                indx -= 2
                element += 2
            elif indx == 1:
                query = query.outerjoin(join[element])
                indx -= 1
                element += 1
        query = query.filter(db_filter)\
            .filter(self.common_filters(allow_show_archived,
                                        viewing_tag_id=viewing_tag_id,
                                        allow_show_hidden=allow_show_hidden,
                                        extra_filter=extra_filter))
        entries = list()
        pagination = list()
        try:
            if database == Books:
                total_count = query.with_entities(Books.id).distinct().count()
            else:
                total_count = query.count()
            pagination = Pagination(page, pagesize, total_count)
            entries = query.order_by(*order).offset(off).limit(pagesize).all()
        except Exception as ex:
            log.error_or_exception(ex)
        # display authors in right order
        entries = self.order_authors(entries, True, join_archive_read)
        return entries, randm, pagination

    # Orders all Authors in the list according to authors sort
    def order_authors(self, entries, list_return=False, combined=False):
        self.ensure_session()
        for entry in entries:
            if combined:
                sort_authors = entry.Books.author_sort.split('&')
                ids = [a.id for a in entry.Books.authors]

            else:
                sort_authors = entry.author_sort.split('&')
                ids = [a.id for a in entry.authors]
            authors_ordered = list()
            # error = False
            for auth in sort_authors:
                auth = strip_whitespaces(auth)
                # Skip empty author strings to prevent spurious errors
                if not auth:
                    continue
                results = self.session.query(Authors).filter(Authors.sort == auth).all()
                if not len(results):
                    # Books.author_sort drifted from Authors.sort. Warn once
                    # per process per author so the log doesn't fill on every
                    # page render. The unmatched author still appears in the
                    # book — it falls through to the Authors.id loop below
                    # (continue, not break, so other authors on this same
                    # book that DO have a valid sort still get ordered).
                    if auth not in _AUTHOR_SORT_DRIFT_WARNED:
                        _AUTHOR_SORT_DRIFT_WARNED.add(auth)
                        log.warning(
                            "Author sort '%s' from Books.author_sort has no "
                            "match in Authors.sort. Falling back to Authors.id "
                            "order for this author. To fix: edit the author in "
                            "the admin UI so Authors.sort matches.", auth)
                    continue
                for r in results:
                    if r.id in ids:
                        authors_ordered.append(r)
                        ids.remove(r.id)
            for author_id in ids:
                result = self.session.query(Authors).filter(Authors.id == author_id).first()
                authors_ordered.append(result)

            if list_return:
                if combined:
                    entry.Books.authors = authors_ordered
                else:
                    entry.ordered_authors = authors_ordered
            else:
                return authors_ordered
        return entries

    def get_typeahead(self, database, query, replace=('', ''), tag_filter=true()):
        self.ensure_session()
        query = query or ''
        entries = self.session.query(database).filter(tag_filter). \
            filter(func.lower(database.name).ilike("%" + query + "%")).all()
        # json_dumps = json.dumps([dict(name=escape(r.name.replace(*replace))) for r in entries])
        json_dumps = json.dumps([dict(name=r.name.replace(*replace)) for r in entries])
        return json_dumps

    def check_exists_book(self, authr, title):
        self.ensure_session()
        q = list()
        author_terms = re.split(r'\s*&\s*', authr)
        for author_term in author_terms:
            q.append(Books.authors.any(func.lower(Authors.name).ilike("%" + author_term + "%")))

        return self.session.query(Books) \
            .filter(and_(Books.authors.any(and_(*q)), func.lower(Books.title).ilike("%" + title + "%"))).first()

    def search_query(self, term, config, *join):
        self.ensure_session()
        strip_whitespaces(term).lower()
        q = list()
        author_terms = re.split("[, ]+", term)
        for author_term in author_terms:
            q.append(Books.authors.any(func.lower(Authors.name).ilike("%" + author_term + "%")))
        query = self.generate_linked_query(config.config_read_column, Books)
        if len(join) == 6:
            query = query.outerjoin(join[0], join[1]).outerjoin(join[2]).outerjoin(join[3], join[4]).outerjoin(join[5])
        if len(join) == 3:
            query = query.outerjoin(join[0], join[1]).outerjoin(join[2])
        elif len(join) == 2:
            query = query.outerjoin(join[0], join[1])
        elif len(join) == 1:
            query = query.outerjoin(join[0])

        cc = self.get_cc_columns(config, filter_config_custom_read=True)
        filter_expression = [Books.tags.any(func.lower(Tags.name).ilike("%" + term + "%")),
                             Books.series.any(func.lower(Series.name).ilike("%" + term + "%")),
                             Books.authors.any(and_(*q)),
                             Books.publishers.any(func.lower(Publishers.name).ilike("%" + term + "%")),
                             func.lower(Books.title).ilike("%" + term + "%")]
        for c in cc:
            if c.datatype not in ["datetime", "rating", "bool", "int", "float"]:
                filter_expression.append(
                    getattr(Books,
                            'custom_column_' + str(c.id)).any(
                        func.lower(cc_classes[c.id].value).ilike("%" + term + "%")))
        # Eagerly load the data relationship to prevent session errors
        query = query.options(joinedload(Books.data))
        return query.filter(self.common_filters(True)).filter(or_(*filter_expression))

    def get_cc_columns(self, config, filter_config_custom_read=False):
        self.ensure_session()
        tmp_cc = self.session.query(CustomColumns).filter(CustomColumns.datatype.notin_(cc_exceptions)).all()
        cc = []
        r = None
        if config.config_columns_to_ignore:
            r = re.compile(config.config_columns_to_ignore)

        for col in tmp_cc:
            if filter_config_custom_read and config.config_read_column and config.config_read_column == col.id:
                continue
            if r and r.match(col.name):
                continue
            cc.append(col)

        return cc

    # read search results from calibre-database and return it (function is used for feed and simple search
    def get_search_results(self, term, config, offset=None, order=None, limit=None, *join):
        self.ensure_session()
        order = order[0] if order else [Books.sort]
        pagination = None
        result = self.search_query(term, config, *join).order_by(*order).all()
        result_count = len(result)
        if offset is not None and limit is not None:
            offset = int(offset)
            limit_all = offset + int(limit)
            pagination = Pagination((offset / (int(limit)) + 1), limit, result_count)
        else:
            offset = 0
            limit_all = result_count

        ub.store_combo_ids(result)
        entries = self.order_authors(result[offset:limit_all], list_return=True, combined=True)

        return entries, result_count, pagination

    # Creates for all stored languages a translated speaking name in the array for the UI
    def speaking_language(self, languages=None, return_all_languages=False, with_count=False, reverse_order=False):
        self.ensure_session()

        if with_count:
            if not languages:
                languages = self.session.query(Languages, func.count('books_languages_link.book'))\
                    .join(books_languages_link).join(Books)\
                    .filter(self.common_filters(return_all_languages=return_all_languages)) \
                    .group_by(text('books_languages_link.lang_code')).all()
            tags = list()
            for lang in languages:
                tag = Category(isoLanguages.get_language_name(get_locale(), lang[0].lang_code), lang[0].lang_code)
                tags.append([tag, lang[1]])
            # Append all books without language to list
            if not return_all_languages:
                no_lang_count = (self.session.query(Books)
                                 .outerjoin(books_languages_link).outerjoin(Languages)
                                 .filter(Languages.lang_code.is_(None))
                                 .filter(self.common_filters())
                                 .count())
                if no_lang_count:
                    tags.append([Category(_("None"), "none"), no_lang_count])
            return sorted(tags, key=lambda x: x[0].name.lower(), reverse=reverse_order)
        else:
            if not languages:
                languages = self.session.query(Languages) \
                    .join(books_languages_link) \
                    .join(Books) \
                    .filter(self.common_filters(return_all_languages=return_all_languages)) \
                    .group_by(text('books_languages_link.lang_code')).all()
            for lang in languages:
                lang.name = isoLanguages.get_language_name(get_locale(), lang.lang_code)
            return sorted(languages, key=lambda x: x.name, reverse=reverse_order)

    def create_functions(self, config=None):
        """Backward-compatible no-op.

        UDFs (lower/uuid4/title_sort) are now registered once per SQLite
        connection by ``_register_sqlite_udfs`` via the engine ``connect``
        event listener. Per-request callsites in ``cps/web.py``,
        ``cps/editbooks.py``, ``cps/admin.py``, ``cps/helper.py``, and
        ``cps/search.py`` previously called this method on hot paths,
        creating the GIL+SQLite deadlock vector behind CWA #1256 when a
        worker thread mid-``func.lower`` query collided with a request
        thread mid-``conn.create_function``. The new model registers UDFs
        at connect time so request handlers never re-register.

        Method is preserved as a no-op so any external caller (e.g.
        downstream plugins or tests) doesn't break. The class attribute
        ``config`` is updated if provided so legacy callers' intent (set
        the title-sort regex source) is preserved.
        """
        if config is not None:
            type(self).config = config

    @classmethod
    def dispose(cls):
        # global session
        # Use lock to prevent concurrent dispose/reconnect operations
        with cls._reconnect_lock:
            for inst in cls.instances:
                old_session = inst.session
                inst.session = None
                if old_session:
                    try:
                        old_session.close()
                    except Exception:
                        pass
                    if old_session.bind:
                        try:
                            old_session.bind.dispose()
                        except Exception:
                            pass

            for attr in list(Books.__dict__.keys()):
                if attr.startswith("custom_column_"):
                    setattr(Books, attr, None)

            for db_class in cc_classes.values():
                Base.metadata.remove(db_class.__table__)
            cc_classes.clear()

        for table in reversed(Base.metadata.sorted_tables):
            name = table.key
            if name.startswith("custom_column_") or name.startswith("books_custom_column_"):
                if table is not None:
                    Base.metadata.remove(table)

    def reconnect_db(self, config, app_db_path):
        # Use lock to ensure atomic reconnect operation
        with self._reconnect_lock:
            # Be resilient if database wasn't initialized yet
            try:
                self.dispose()
            except Exception:
                # Ignore dispose errors during reconnect
                pass

            # engine is a class-level attribute that may be None before first setup
            try:
                if getattr(self, 'engine', None) is not None:
                    self.engine.dispose()
            except Exception:
                # Ignore engine dispose errors; we'll rebuild below
                pass

            # Rebuild engine/session factory and update config
            self.setup_db(config.config_calibre_dir, app_db_path)
            self.update_config(config)

    @classmethod
    def refresh_for_new_data(cls):
        """Release the read transaction on every CalibreDB instance.

        Used after external writers (calibredb add during ingest) commit
        new rows to metadata.db. Without this, the web app's SQLAlchemy
        session sits on a stale read snapshot and the new book stays
        invisible until the session's transaction ends. Calling
        expire_all() + rollback() ends the transaction without
        disposing the engine — the next query starts fresh and sees
        the latest committed data.

        Replaces the prior async TaskReconnectDatabase path which
        disposed the shared engine on a worker thread and raced with
        in-flight request greenlets (fork issue #192).
        """
        with cls._reconnect_lock:
            for inst in list(cls.instances):
                try:
                    if inst.session is not None:
                        try:
                            inst.session.expire_all()
                        except Exception:
                            pass
                        try:
                            inst.session.rollback()
                        except Exception:
                            pass
                except Exception:
                    # One bad instance must not block the rest.
                    continue


def lcase(s):
    try:
        return unidecode.unidecode(s.lower())
    except Exception as ex:
        _log = logger.create()
        _log.error_or_exception(ex)
        return s.lower()


class Category:
    name = None
    id = None
    count = None
    rating = None

    def __init__(self, name, cat_id, rating=None):
        self.name = name
        self.id = cat_id
        self.rating = rating
        self.count = 1
