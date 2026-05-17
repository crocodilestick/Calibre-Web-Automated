# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import atexit
import os
import sys
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import itertools
import uuid
from flask import session as flask_session, has_request_context, g
from binascii import hexlify

from .cw_login import AnonymousUserMixin, current_user
from .cw_login import user_logged_in

try:
    from flask_dance.consumer.backend.sqla import OAuthConsumerMixin  # pyright: ignore[reportMissingImports]
    oauth_support = True
except ImportError as e:
    # fails on flask-dance >1.3, due to renaming
    try:
        from flask_dance.consumer.storage.sqla import OAuthConsumerMixin
        oauth_support = True
    except ImportError as e:
        OAuthConsumerMixin = BaseException
        oauth_support = False
from sqlalchemy import create_engine, exc, exists, event, text
from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy import String, Integer, SmallInteger, Boolean, DateTime, Float, JSON
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import func
try:
    # Compatibility with sqlalchemy 2.0
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref, relationship, sessionmaker, Session, scoped_session
from werkzeug.security import generate_password_hash

from . import constants, logger
from .string_helper import strip_whitespaces

log = logger.create()

session: Session | None = None
app_DB_path = None
Base = declarative_base()
searched_ids = {}

logged_in = dict()


def _safe_session_rollback(_session, label=""):
    try:
        _session.rollback()
    except Exception as e:
        if label:
            log.debug("Failed to rollback session after %s migration check: %s", label, e)


def _run_ddl_with_retry(engine, statements, retries=5, base_delay=0.25):
    if isinstance(statements, str):
        statements = [statements]

    last_error = None
    for attempt in range(retries):
        try:
            with engine.begin() as conn:
                conn.execute(text("PRAGMA busy_timeout=5000"))
                for stmt in statements:
                    conn.execute(text(stmt))
            return True
        except exc.OperationalError as e:
            last_error = e
            if "database is locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    if last_error:
        raise last_error
    return False


def signal_store_user_session(object, user):
    store_user_session()


def store_user_session():
    _user = flask_session.get('_user_id', "")
    _id = flask_session.get('_id', "")
    _random = flask_session.get('_random', "")
    if flask_session.get('_user_id', ""):
        try:
            if not check_user_session(_user, _id, _random):
                expiry = int((datetime.now()  + timedelta(days=31)).timestamp())
                user_session = User_Sessions(_user, _id, _random, expiry)
                session.add(user_session)
                session.commit()
                log.debug("Login and store session : " + _id)
            else:
                log.debug("Found stored session: " + _id)
        except (exc.OperationalError, exc.InvalidRequestError) as e:
            session.rollback()
            log.exception(e)
    else:
        log.error("No user id in session")


def delete_user_session(user_id, session_key):
    try:
        log.debug("Deleted session_key: " + session_key)
        session.query(User_Sessions).filter(User_Sessions.user_id == user_id,
                                            User_Sessions.session_key == session_key).delete()
        session.commit()
    except (exc.OperationalError, exc.InvalidRequestError) as ex:
        session.rollback()
        log.exception(ex)


def check_user_session(user_id, session_key, random):
    try:
        found = session.query(User_Sessions).filter(User_Sessions.user_id==user_id,
                                                    User_Sessions.session_key==session_key,
                                                    User_Sessions.random == random,
                                                    ).one_or_none()
        if found is not None:
            new_expiry = int((datetime.now()  + timedelta(days=31)).timestamp())
            if new_expiry - found.expiry > 86400:
                found.expiry = new_expiry
                session.merge(found)
                session.commit()
        return bool(found)
    except (exc.OperationalError, exc.InvalidRequestError) as e:
        session.rollback()
        log.exception(e)
        return False


user_logged_in.connect(signal_store_user_session)

def store_ids(result):
    ids = list()
    for element in result:
        ids.append(element.id)
    searched_ids[current_user.id] = ids

def store_combo_ids(result):
    ids = list()
    for element in result:
        ids.append(element[0].id)
    searched_ids[current_user.id] = ids


class UserBase:

    @property
    def is_authenticated(self):
        return self.is_active

    def _has_role(self, role_flag):
        return constants.has_flag(self.role, role_flag)

    def role_admin(self):
        return self._has_role(constants.ROLE_ADMIN)

    def role_download(self):
        return self._has_role(constants.ROLE_DOWNLOAD)

    def role_upload(self):
        return self._has_role(constants.ROLE_UPLOAD)

    def role_edit(self):
        return self._has_role(constants.ROLE_EDIT)

    def role_passwd(self):
        return self._has_role(constants.ROLE_PASSWD)

    def role_anonymous(self):
        return self._has_role(constants.ROLE_ANONYMOUS)

    def role_edit_shelfs(self):
        return self._has_role(constants.ROLE_EDIT_SHELFS)

    def role_delete_books(self):
        return self._has_role(constants.ROLE_DELETE_BOOKS)

    def role_viewer(self):
        return self._has_role(constants.ROLE_VIEWER)

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return self.role_anonymous()

    def get_id(self):
        return str(self.id)

    def filter_language(self):
        return self.default_language

    def check_visibility(self, value):
        if value == constants.SIDEBAR_RECENT:
            return True
        return constants.has_flag(self.sidebar_view, value)

    def show_detail_random(self):
        return self.check_visibility(constants.DETAIL_RANDOM)

    def list_denied_tags(self):
        mct = self.denied_tags or ""
        return [strip_whitespaces(t) for t in mct.split(",")]

    def list_allowed_tags(self):
        mct = self.allowed_tags or ""
        return [strip_whitespaces(t) for t in mct.split(",")]

    def list_denied_column_values(self):
        mct = self.denied_column_value or ""
        return [strip_whitespaces(t) for t in mct.split(",")]

    def list_allowed_column_values(self):
        mct = self.allowed_column_value or ""
        return [strip_whitespaces(t) for t in mct.split(",")]

    def get_view_property(self, page, prop):
        if not self.view_settings.get(page):
            return None
        return self.view_settings[page].get(prop)

    def set_view_property(self, page, prop, value):
        if not self.view_settings.get(page):
            self.view_settings[page] = dict()
        self.view_settings[page][prop] = value
        try:
            flag_modified(self, "view_settings")
        except AttributeError:
            pass
        try:
            session.commit()
        except (exc.OperationalError, exc.InvalidRequestError) as e:
            session.rollback()
            log.error_or_exception(e)

    def __repr__(self):
        return '<User %r>' % self.name


# Baseclass for Users in Calibre-Web, settings which are depending on certain users are stored here. It is derived from
# User Base (all access methods are declared there)
class User(UserBase, Base):
    __tablename__ = 'user'
    __table_args__ = {'sqlite_autoincrement': True}

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
    email = Column(String(120), unique=True, default="")
    role = Column(SmallInteger, default=constants.ROLE_USER)
    password = Column(String)
    kindle_mail = Column(String(120), default="")
    kindle_mail_subject = Column(String(256), default="", doc="Subject line for eReader email sending, empty=default")
    shelf = relationship('Shelf', backref='user', lazy='dynamic', order_by='Shelf.name')
    magic_shelf = relationship('MagicShelf', backref='user', lazy='dynamic', order_by='MagicShelf.name')
    downloads = relationship('Downloads', backref='user', lazy='dynamic')
    locale = Column(String(2), default="en")
    sidebar_view = Column(Integer, default=1)
    default_language = Column(String(3), default="all")
    denied_tags = Column(String, default="")
    allowed_tags = Column(String, default="")
    denied_column_value = Column(String, default="")
    allowed_column_value = Column(String, default="")
    remote_auth_token = relationship('RemoteAuthToken', backref='user', lazy='dynamic')
    view_settings = Column(JSON, default={})
    kobo_only_shelves_sync = Column(Integer, default=0)
    opds_only_shelves_sync = Column(Integer, default=0)
    hardcover_token = Column(String, unique=True, default=None)
    # New per-user theme (0=default/light, 1=caliBlur) replacing global-only behavior
    theme = Column(Integer, default=1)
    # Auto-send settings for new books
    auto_send_enabled = Column(Boolean, default=False)
    # Allow entering additional email addresses on send-to-eReader
    allow_additional_ereader_emails = Column(Boolean, default=True)
    # Cover-preview rendering (eReader-shape previews on book detail / shelf).
    # Defaults match cps.services.cover_preview.DEFAULT_PRESET +
    # DEFAULT_FILL_MODE. New users opt-in; the Phase-2 migration in Task 2
    # sets show_ereader_previews=False for existing users so behavior is
    # unchanged on upgrade.
    show_ereader_previews = Column(Boolean, default=True)
    preview_preset = Column(String, default="kobo_libra_color")
    preview_default_fill = Column(String, default="edge_mirror")
    preview_default_color = Column(String, nullable=True)


if oauth_support:
    class OAuth(OAuthConsumerMixin, Base):
        provider_user_id = Column(String(256))
        user_id = Column(Integer, ForeignKey(User.id))
        user = relationship(User)


class OAuthProvider(Base):
    __tablename__ = 'oauthProvider'

    id = Column(Integer, primary_key=True)
    provider_name = Column(String)
    oauth_client_id = Column(String)
    oauth_client_secret = Column(String)
    oauth_base_url = Column(String, default=None)
    oauth_authorize_url = Column(String, default=None)
    oauth_token_url = Column(String, default=None)
    oauth_userinfo_url = Column(String, default=None)
    oauth_admin_group = Column(String, default=None)
    metadata_url = Column(String, default=None)  # For OIDC auto-discovery
    scope = Column(String, default="openid profile email")  # Customizable OAuth scopes
    username_mapper = Column(String, default="preferred_username")  # JWT field for username
    email_mapper = Column(String, default="email")  # JWT field for email
    login_button = Column(String, default="OpenID Connect")  # Custom button text
    active = Column(Boolean)


# Class for anonymous user is derived from User base and completely overrides methods and properties for the
# anonymous user
class Anonymous(AnonymousUserMixin, UserBase):
    def __init__(self):
        self.hardcover_token = None
        self.kobo_only_shelves_sync = None
        self.opds_only_shelves_sync = None
        self.view_settings = None
        self.allowed_column_value = None
        self.allowed_tags = None
        self.denied_tags = None
        self.kindle_mail = None
        self.kindle_mail_subject = None
        self.locale = None
        self.default_language = None
        self.sidebar_view = None
        self.id = None
        self.role = None
        self.name = None
        self.auto_send_enabled = False
        self.loadSettings()

    def loadSettings(self):
        data = session.query(User).filter(User.role.op('&')(constants.ROLE_ANONYMOUS) == constants.ROLE_ANONYMOUS)\
            .first()  # type: User
        self.name = data.name
        self.role = data.role
        self.id=data.id
        self.sidebar_view = data.sidebar_view
        self.default_language = data.default_language
        self.locale = data.locale
        self.kindle_mail = data.kindle_mail
        self.kindle_mail_subject = data.kindle_mail_subject
        self.denied_tags = data.denied_tags
        self.allowed_tags = data.allowed_tags
        self.denied_column_value = data.denied_column_value
        self.allowed_column_value = data.allowed_column_value
        self.view_settings = data.view_settings
        self.kobo_only_shelves_sync = data.kobo_only_shelves_sync
        self.opds_only_shelves_sync = data.opds_only_shelves_sync
        self.hardcover_token = data.hardcover_token
        self.auto_send_enabled = data.auto_send_enabled
    def role_admin(self):
        return False

    @property
    def is_active(self):
        return False

    @property
    def is_anonymous(self):
        return True

    @property
    def is_authenticated(self):
        return False

    def get_view_property(self, page, prop):
        if 'view' in flask_session:
            if not flask_session['view'].get(page):
                return None
            return flask_session['view'][page].get(prop)
        return None

    def set_view_property(self, page, prop, value):
        if not 'view' in flask_session:
            flask_session['view'] = dict()
        if not flask_session['view'].get(page):
            flask_session['view'][page] = dict()
        flask_session['view'][page][prop] = value

class User_Sessions(Base):
    __tablename__ = 'user_session'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    session_key = Column(String, default="")
    random = Column(String, default="")
    expiry = Column(Integer)


    def __init__(self, user_id, session_key, random, expiry):
        super().__init__()
        self.user_id = user_id
        self.session_key = session_key
        self.random = random
        self.expiry = expiry


class UserAppPassword(Base):
    """Per-user app passwords for HTTP Basic auth on OPDS / KOSync endpoints.

    OAuth users (Authentik / Authelia / Keycloak) can authenticate to the web UI
    via the IdP redirect flow but have no usable password for HTTP Basic auth.
    LDAP users may prefer not to expose their directory password to OPDS / KOSync
    clients. App passwords let any user mint a long random token bound to a
    label (e.g. "Kobo", "KOReader iPad"); the cleartext is shown once at create
    time and then only its `werkzeug` hash is stored.

    See `notes/oauth-opds-app-passwords-DESIGN.md` and fork issue #95.
    """
    __tablename__ = 'user_app_password'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    label = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime)
    revoked = Column(Boolean, nullable=False, default=False)


# Baseclass representing Shelfs in calibre-web in app.db
class Shelf(Base):
    __tablename__ = 'shelf'

    id = Column(Integer, primary_key=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    is_public = Column(Integer, default=0)
    user_id = Column(Integer, ForeignKey('user.id'))
    kobo_sync = Column(Boolean, default=False)
    books = relationship("BookShelf", backref="ub_shelf", cascade="all, delete-orphan", lazy="dynamic")
    created = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return '<Shelf %d:%r>' % (self.id, self.name)


# Baseclass representing Magic Shelfs in calibre-web in app.db
class MagicShelf(Base):
    __tablename__ = 'magic_shelf'

    id = Column(Integer, primary_key=True)
    uuid = Column(String, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    is_public = Column(Integer, default=0)
    is_system = Column(Boolean, default=False)  # System-created template shelves
    user_id = Column(Integer, ForeignKey('user.id'))
    icon = Column(String, default="glyphicon-star")
    rules = Column(JSON, default={})
    kobo_sync = Column(Boolean, default=False)  # Sync to Kobo devices
    created = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('user_id', 'name', 'is_system', name='unique_user_system_shelf_name'),
    )

    def __repr__(self):
        return '<MagicShelf %d:%r>' % (self.id, self.name)


class MagicShelfCache(Base):
    __tablename__ = 'magic_shelf_cache'

    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer, ForeignKey('magic_shelf.id'), index=True)
    user_id = Column(Integer, ForeignKey('user.id'), index=True)
    sort_param = Column(String, default='stored')
    book_ids = Column(JSON)  # Stores [1, 45, 2, ...]
    total_count = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Composite index for fast lookups
    __table_args__ = (
        Index('ix_magic_shelf_cache_lookup', 'shelf_id', 'user_id', 'sort_param'),
    )


class OpdsShelfExposure(Base):
    __tablename__ = 'opds_shelf_exposure'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    shelf_id = Column(Integer, ForeignKey('shelf.id'), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint('user_id', 'shelf_id', name='unique_user_opds_shelf_exposure'),
    )


class OpdsMagicShelfExposure(Base):
    __tablename__ = 'opds_magic_shelf_exposure'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    shelf_id = Column(Integer, ForeignKey('magic_shelf.id'), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint('user_id', 'shelf_id', name='unique_user_opds_magic_shelf_exposure'),
    )


class HiddenMagicShelfTemplate(Base):
    __tablename__ = 'hidden_magic_shelf_templates'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    template_key = Column(String, nullable=True)  # For system templates: 'recently_added', 'highly_rated', etc.
    shelf_id = Column(Integer, ForeignKey('magic_shelf.id'), nullable=True)  # For custom public shelves
    hidden_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Either template_key OR shelf_id must be set, but not both
        # User can only hide the same template/shelf once
        UniqueConstraint('user_id', 'template_key', name='unique_user_template_hidden'),
        UniqueConstraint('user_id', 'shelf_id', name='unique_user_shelf_hidden'),
    )

    def __repr__(self):
        if self.template_key:
            return '<HiddenMagicShelfTemplate %d: user=%d template=%s>' % (self.id, self.user_id, self.template_key)
        else:
            return '<HiddenMagicShelfTemplate %d: user=%d shelf_id=%d>' % (self.id, self.user_id, self.shelf_id)


class DismissedDuplicateGroup(Base):
    __tablename__ = 'dismissed_duplicate_groups'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    group_hash = Column(String(32), nullable=False)  # MD5 hash of title+author combo
    dismissed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # User can only dismiss the same duplicate group once
        UniqueConstraint('user_id', 'group_hash', name='unique_user_duplicate_dismissed'),
    )

    def __repr__(self):
        return '<DismissedDuplicateGroup %d: user=%d hash=%s>' % (self.id, self.user_id, self.group_hash)


# Baseclass representing Relationship between books and Shelfs in Calibre-Web in app.db (N:M)
class BookShelf(Base):
    __tablename__ = 'book_shelf_link'

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer)
    order = Column(Integer)
    shelf = Column(Integer, ForeignKey('shelf.id'))
    date_added = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return '<Book %r>' % self.id


# This table keeps track of deleted Shelves so that deletes can be propagated to any paired Kobo device.
class ShelfArchive(Base):
    __tablename__ = 'shelf_archive'

    id = Column(Integer, primary_key=True)
    uuid = Column(String)
    user_id = Column(Integer, ForeignKey('user.id'))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReadBook(Base):
    __tablename__ = 'book_read_link'

    STATUS_UNREAD = 0
    STATUS_FINISHED = 1
    STATUS_IN_PROGRESS = 2

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, unique=False)
    user_id = Column(Integer, ForeignKey('user.id'), unique=False)
    read_status = Column(Integer, unique=False, default=STATUS_UNREAD, nullable=False)
    kobo_reading_state = relationship("KoboReadingState", uselist=False,
                                      primaryjoin="and_(ReadBook.user_id == foreign(KoboReadingState.user_id), "
                                                  "ReadBook.book_id == foreign(KoboReadingState.book_id))",
                                      cascade="all",
                                      backref=backref("book_read_link",
                                                      uselist=False))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_time_started_reading = Column(DateTime, nullable=True)
    times_started_reading = Column(Integer, default=0, nullable=False)

    # Audit 2026-05-11: enforce per-(user, book) uniqueness so concurrent
    # Kobo PUTs can't produce duplicate rows. The Kobo state handler reads
    # via .one_or_none(); duplicates would surface as MultipleResultsFound.
    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uq_book_read_link_user_book'),
    )


class Bookmark(Base):
    __tablename__ = 'bookmark'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    book_id = Column(Integer)
    format = Column(String(collation='NOCASE'))
    bookmark_key = Column(String)


class BookCoverLock(Base):
    """Per-book flag that prevents the cover from being overwritten by the
    metadata-fetch path on the edit page. Set/cleared from the cover-picker
    page at /book/<id>/cover. Resolves janeczku/calibre-web#2165 ("Option
    to keep existing book cover when fetching metadata", 8 hearts).

    Lock is per book, not per user — a cover is a property of the book,
    not of the viewer. ``locked_by`` and ``locked_at`` are audit metadata
    only; reads check ``locked``.
    """
    __tablename__ = 'book_cover_lock'

    book_id = Column(Integer, primary_key=True)
    locked = Column(Boolean, nullable=False, default=False)
    locked_by = Column(Integer)
    locked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BookCoverPreview(Base):
    """Per-user-per-book override of the cover-preview fill style + color.

    Row exists only when the user has explicitly set fill/color for this
    book OR toggled the lock. No row = follows the user's default fill +
    default color (stored on the User row).

    user_id has FK with ON DELETE CASCADE.
    book_id references metadata.db's books.id but cannot be a SQL-level
    FK because the two databases are separate SQLite files; orphaned
    rows are swept by the daily cleanup task in
    cps/services/cover_preview_cleanup.py.
    """
    __tablename__ = "book_cover_preview"

    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    book_id = Column(Integer, primary_key=True)
    fill_mode = Column(String, nullable=False)
    custom_color = Column(String, nullable=True)
    locked = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", lazy="joined", backref="cover_previews")


# Baseclass representing books that are archived on the user's Kobo device.
class ArchivedBook(Base):
    __tablename__ = 'archived_book'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    book_id = Column(Integer)
    is_archived = Column(Boolean, unique=False)
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Audit 2026-05-11: enforce per-(user, book) uniqueness. Without it two
    # concurrent Kobo PUTs could create duplicate rows; later reads
    # (which use .one_or_none()) raise MultipleResultsFound -> 500.
    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uq_archived_book_user_book'),
    )


class UserHiddenBook(Base):
    """Per-user hidden books — fork issue #64.

    Distinct from ArchivedBook: archived is a deletion-track / sync-pause
    semantic; hidden is a personal-library declutter. Same shape (user_id +
    book_id pair, last_modified) but a separate table so the two semantics
    don't bleed into each other. The web UI exposes hide/unhide on the book
    detail page and a dedicated `/hidden` listing for un-hiding.

    common_filters() in cps/db.py reads this table and excludes hidden
    books from index, search, OPDS, and shelf listings (the same code path
    that already handles archived books).
    """
    __tablename__ = 'user_hidden_book'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    book_id = Column(Integer, nullable=False, index=True)
    hidden_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uq_user_hidden_book'),
    )


class KoboSyncedBooks(Base):
    __tablename__ = 'kobo_synced_books'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    book_id = Column(Integer)

    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uq_kobo_synced_books_user_book'),
    )


class KoboDeletedBook(Base):
    """Tombstone table for books deleted from CW that need to be reported
    to Kobo devices as DeletedEntitlement on next sync.

    Why we need it: calibre's metadata.db row goes away the moment the
    book is deleted (cps/editbooks.py:delete_whole_book), and the
    KoboSyncedBooks table carries only (user_id, book_id) — no UUID. The
    Kobo protocol needs the book's UUID to address the DeletedEntitlement
    on the device. So we snapshot (user_id, book_uuid, deleted_at) at
    delete time, before the book row is gone.

    Lifecycle: rows live as long as the deletion is "newer than" any
    device's sync cursor. With cursor-based emission (advance
    archive_last_modified past deleted_at on emit), each device sees
    each DeletedEntitlement exactly once. Rows can be GC'd by a
    periodic cleanup once they're older than the oldest active sync
    token's archive_last_modified — left as a follow-up; current
    storage cost is one short row per deleted book per affected user.
    """
    __tablename__ = 'kobo_deleted_book'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    book_uuid = Column(String, nullable=False)
    deleted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        UniqueConstraint('user_id', 'book_uuid', name='uq_kobo_deleted_book_user_uuid'),
    )


# CWA #1258 (backport for fork #153): per-user OPDS shelf-exposure helpers.
# Mirrors the kobo_only_shelves_sync pattern — the User-side flag is added
# in the User class above; the helpers below maintain the two exposure
# tables (regular shelves + magic shelves).
def is_opds_shelf_exposed_for_user(user_id, shelf_id, _session=None):
    s = _session if _session else session
    return s.query(OpdsShelfExposure).filter_by(user_id=user_id, shelf_id=shelf_id).first() is not None


def set_opds_shelf_exposed_for_user(user_id, shelf_id, exposed, _session=None):
    s = _session if _session else session
    existing = s.query(OpdsShelfExposure).filter_by(user_id=user_id, shelf_id=shelf_id).first()
    if exposed:
        if existing is None:
            s.add(OpdsShelfExposure(user_id=user_id, shelf_id=shelf_id))
    elif existing is not None:
        s.delete(existing)


def is_opds_magic_shelf_exposed_for_user(user_id, shelf_id, _session=None):
    s = _session if _session else session
    return s.query(OpdsMagicShelfExposure).filter_by(user_id=user_id, shelf_id=shelf_id).first() is not None


def set_opds_magic_shelf_exposed_for_user(user_id, shelf_id, exposed, _session=None):
    s = _session if _session else session
    existing = s.query(OpdsMagicShelfExposure).filter_by(user_id=user_id, shelf_id=shelf_id).first()
    if exposed:
        if existing is None:
            s.add(OpdsMagicShelfExposure(user_id=user_id, shelf_id=shelf_id))
    elif existing is not None:
        s.delete(existing)

# The Kobo ReadingState API keeps track of 4 timestamped entities:
#   ReadingState, StatusInfo, Statistics, CurrentBookmark
# Which we map to the following 4 tables:
#   KoboReadingState, ReadBook, KoboStatistics and KoboBookmark
class KoboReadingState(Base):
    __tablename__ = 'kobo_reading_state'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    book_id = Column(Integer)
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    priority_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    current_bookmark = relationship("KoboBookmark", uselist=False, backref="kobo_reading_state", cascade="all, delete")
    statistics = relationship("KoboStatistics", uselist=False, backref="kobo_reading_state", cascade="all, delete")

    __table_args__ = (
        UniqueConstraint('user_id', 'book_id', name='uq_kobo_reading_state_user_book'),
    )


class KoboBookmark(Base):
    __tablename__ = 'kobo_bookmark'

    id = Column(Integer, primary_key=True)
    kobo_reading_state_id = Column(Integer, ForeignKey('kobo_reading_state.id'))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    location_source = Column(String)
    location_type = Column(String)
    location_value = Column(String)
    progress_percent = Column(Float)
    content_source_progress_percent = Column(Float)


class KoboStatistics(Base):
    __tablename__ = 'kobo_statistics'

    id = Column(Integer, primary_key=True)
    kobo_reading_state_id = Column(Integer, ForeignKey('kobo_reading_state.id'))
    last_modified = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    remaining_time_minutes = Column(Integer)
    spent_reading_minutes = Column(Integer)


class KoboAnnotationSync(Base):
    """Track which Kobo annotations have been synced to external services (e.g., Hardcover)."""
    __tablename__ = 'kobo_annotation_sync'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    annotation_id = Column(String, nullable=False)  # Kobo annotation UUID
    book_id = Column(Integer, nullable=False)  # Calibre book ID
    synced_to_hardcover = Column(Boolean, default=False)
    hardcover_journal_id = Column(Integer)  # Hardcover journal entry ID
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_synced = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    highlighted_text = Column(String, nullable=True)
    highlight_color = Column(String, nullable=True)
    note_text = Column(String, nullable=True)
    
    __table_args__ = (
        Index('ix_kobo_annotation_sync_user_annotation', 'user_id', 'annotation_id'),
        Index('ix_kobo_annotation_sync_user_book', 'user_id', 'book_id'),
    )

    def __repr__(self):
        return f'<KoboAnnotationSync annotation_id={self.annotation_id} book_id={self.book_id}>'


class HardcoverBookBlacklist(Base):
    """Track book-level blacklisting for hardcover sync features."""
    __tablename__ = 'hardcover_book_blacklist'

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, nullable=False, unique=True)  # Calibre book ID
    blacklist_annotations = Column(Boolean, default=False)  # Block annotation syncing
    blacklist_reading_progress = Column(Boolean, default=False)  # Block reading progress syncing

    def __repr__(self):
        return f'<HardcoverBookBlacklist book_id={self.book_id} annotations={self.blacklist_annotations} progress={self.blacklist_reading_progress}>'


class HardcoverMatchQueue(Base):
    """Queue for ambiguous Hardcover metadata matches requiring manual review."""
    __tablename__ = 'hardcover_match_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(Integer, nullable=False)
    book_title = Column(String, nullable=False)
    book_authors = Column(String, nullable=False)
    search_query = Column(String, nullable=False)
    hardcover_results = Column(String, nullable=False)  # JSON array of MetaRecord candidates
    confidence_scores = Column(String, nullable=False)  # JSON array of [score, reason] tuples
    created_at = Column(String, nullable=False)
    reviewed = Column(Integer, default=0, nullable=False)  # 0=pending, 1=reviewed
    selected_result_id = Column(String, default=None)  # Hardcover ID if manually selected
    review_action = Column(String, default=None)  # 'accept', 'reject', 'skip'
    reviewed_at = Column(String, default=None)
    reviewed_by = Column(String, default=None)

    def __repr__(self):
        return f'<HardcoverMatchQueue book_id={self.book_id} title="{self.book_title}" reviewed={bool(self.reviewed)}>'


# Updates the last_modified timestamp in the KoboReadingState table if any of its children tables are modified.
@event.listens_for(Session, 'before_flush')
def receive_before_flush(session, flush_context, instances):
    for change in itertools.chain(session.new, session.dirty):
        if isinstance(change, (ReadBook, KoboStatistics, KoboBookmark)):
            if change.kobo_reading_state:
                ts = (g.kobo_reading_state_lm
                      if has_request_context() and getattr(g, 'kobo_reading_state_lm', None)
                      else datetime.now(timezone.utc))
                change.kobo_reading_state.last_modified = ts
                change.kobo_reading_state.priority_timestamp = ts
    # Maintain the last_modified_bit for the Shelf table.
    for change in itertools.chain(session.new, session.deleted):
        if isinstance(change, BookShelf):
            change.ub_shelf.last_modified = datetime.now(timezone.utc)


# Baseclass representing Downloads from calibre-web in app.db
class Downloads(Base):
    __tablename__ = 'downloads'

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer)
    user_id = Column(Integer, ForeignKey('user.id'))

    def __repr__(self):
        return '<Download %r' % self.book_id


# Baseclass representing allowed domains for registration
class Registration(Base):
    __tablename__ = 'registration'

    id = Column(Integer, primary_key=True)
    domain = Column(String)
    allow = Column(Integer)

    def __repr__(self):
        return "<Registration('{0}')>".format(self.domain)


class RemoteAuthToken(Base):
    __tablename__ = 'remote_auth_token'

    id = Column(Integer, primary_key=True)
    auth_token = Column(String, unique=True)
    user_id = Column(Integer, ForeignKey('user.id'))
    verified = Column(Boolean, default=False)
    expiration = Column(DateTime)
    token_type = Column(Integer, default=0)

    def __init__(self):
        super().__init__()
        self.auth_token = (hexlify(os.urandom(16))).decode('utf-8')
        self.expiration = datetime.now() + timedelta(minutes=10)  # 10 min from now

    def __repr__(self):
        return '<Token %r>' % self.id


def filename(context):
    """Generate deterministic filename for thumbnails.

    Prefer the pattern:
        cover thumbnails:  book_<entity_id>_r<resolution>.<ext>
        series thumbnails: series_<entity_id>_r<resolution>.<ext>

    Fallback to legacy uuid-based naming if required fields are missing.
    This keeps previously generated files valid while making new ones easier
    to reason about and purge selectively.
    """
    params = context.get_current_parameters()
    file_format = params.get('format', 'jpeg')
    entity_id = params.get('entity_id')
    resolution = params.get('resolution')
    thumb_type = params.get('type')  # cover or series
    uuid_val = params.get('uuid')

    # map format 'jpeg' -> extension jpg
    if file_format == 'jpeg':
        ext = 'jpg'
    else:
        ext = file_format

    try:
        if entity_id is not None and resolution is not None and thumb_type is not None:
            if thumb_type == constants.THUMBNAIL_TYPE_COVER:
                return f"book_{entity_id}_r{resolution}.{ext}"
            elif thumb_type == constants.THUMBNAIL_TYPE_SERIES:
                return f"series_{entity_id}_r{resolution}.{ext}"
    except Exception:
        # fall back to uuid naming if anything unexpected occurs
        pass

    # legacy fallback
    return f"{uuid_val}.{ext}" if uuid_val else f"legacy_unknown.{ext}"


class Thumbnail(Base):
    __tablename__ = 'thumbnail'

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer)
    uuid = Column(String, default=lambda: str(uuid.uuid4()), unique=True)
    format = Column(String, default='jpeg')
    type = Column(SmallInteger, default=constants.THUMBNAIL_TYPE_COVER)
    resolution = Column(SmallInteger, default=constants.COVER_THUMBNAIL_SMALL)
    filename = Column(String, default=filename)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expiration = Column(DateTime, nullable=True)


# Add missing tables during migration of database
def add_missing_tables(engine, _session):
    if not engine.dialect.has_table(engine.connect(), "archived_book"):
        ArchivedBook.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "thumbnail"):
        Thumbnail.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "kosync_progress"):
        KOSyncProgress.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "magic_shelf"):
        MagicShelf.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "magic_shelf_cache"):
        MagicShelfCache.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "opds_shelf_exposure"):
        OpdsShelfExposure.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "opds_magic_shelf_exposure"):
        OpdsMagicShelfExposure.__table__.create(bind=engine, checkfirst=True)
    if not engine.dialect.has_table(engine.connect(), "hidden_magic_shelf_templates"):
        HiddenMagicShelfTemplate.__table__.create(bind=engine, checkfirst=True)


# migrate all settings missing in registration table
def migrate_registration_table(engine, _session):
    try:
        # Handle table exists, but no content
        cnt = _session.query(Registration).count()
        if not cnt:
            with engine.connect() as conn:
                trans = conn.begin()
                conn.execute(text("insert into registration (domain, allow) values('%.%',1)"))
                trans.commit()
    except exc.OperationalError:  # Database is not writeable
        print('Settings database is not writeable. Exiting...')
        sys.exit(2)


def migrate_user_session_table(engine, _session):
    try:
        _session.query(exists().where(User_Sessions.random)).scalar()
        _session.commit()
    except exc.OperationalError:  # Database is not compatible, some columns are missing
        _safe_session_rollback(_session, "user_session")
        _run_ddl_with_retry(
            engine,
            [
                "ALTER TABLE user_session ADD column 'random' String",
                "ALTER TABLE user_session ADD column 'expiry' Integer",
            ],
        )

def migrate_user_table(engine, _session):
    try:
        _session.query(exists().where(User.hardcover_token)).scalar()
        _session.commit()
    except exc.OperationalError:  # Database is not compatible, some columns are missing
        _safe_session_rollback(_session, "user.hardcover_token")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'hardcover_token' String")

    try:
        _session.query(exists().where(User.opds_only_shelves_sync)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.opds_only_shelves_sync")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'opds_only_shelves_sync' Integer DEFAULT 0")
    # Migration for per-user theme column
    try:
        _session.query(exists().where(User.theme)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.theme")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'theme' Integer DEFAULT 0")

    # Force migration: All users to caliBlur theme (theme=1) for v5.0.0 frontend development
    try:
        users_migrated = _session.query(User).filter(User.theme == 0).update({User.theme: 1})
        if users_migrated > 0:
            _session.commit()
            print(f"[theme-migration] Migrated {users_migrated} user(s) from light theme (0) to caliBlur theme (1). The light/legacy theme has been temporarily disabled from v3.2.0 and won't be re-enabled until the release of a new CWA frontend in v5.0.0.", flush=True)
    except Exception as e:
        print(f"[theme-migration] Error migrating users to caliBlur theme: {e}", flush=True)
        _session.rollback()

    # Migration for auto-send feature columns
    try:
        _session.query(exists().where(User.auto_send_enabled)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.auto_send_enabled")
        try:
            _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'auto_send_enabled' Boolean DEFAULT 0")
        except Exception as e:
            db_hint = app_DB_path or str(engine.url)
            log.error(
                "Failed to add auto_send_enabled column to user table in app.db (%s). "
                "Check file permissions, locks, and CALIBRE_DBPATH mapping. Error: %s",
                db_hint,
                e,
            )

    # Migration for per-user additional eReader email address permission
    try:
        _session.query(exists().where(User.allow_additional_ereader_emails)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.allow_additional_ereader_emails")
        try:
            _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'allow_additional_ereader_emails' Boolean DEFAULT 1")
        except Exception as e:
            db_hint = app_DB_path or str(engine.url)
            log.error(
                "Failed to add allow_additional_ereader_emails column to user table in app.db (%s). "
                "Check file permissions, locks, and CALIBRE_DBPATH mapping. Error: %s",
                db_hint,
                e,
            )

    # Migration to add per-user email subject for Kindle sending
    try:
        _session.query(exists().where(User.kindle_mail_subject)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.kindle_mail_subject")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'kindle_mail_subject' String DEFAULT ''")

    # Migration to enable duplicates sidebar for existing admin users (one-time)
    try:
        from . import constants
        SIDEBAR_DUPLICATES = constants.SIDEBAR_DUPLICATES

        migration_dir = os.path.join(constants.CONFIG_DIR, ".cwa_migrations")
        migration_marker = os.path.join(migration_dir, "duplicates_sidebar_v1")

        if not os.path.isfile(migration_marker):
            # Check if any admin users don't have duplicates enabled
            admin_users = _session.query(User).filter(
                User.role.op('&')(constants.ROLE_ADMIN) == constants.ROLE_ADMIN
            ).all()
            for user in admin_users:
                if not (user.sidebar_view & SIDEBAR_DUPLICATES):
                    user.sidebar_view |= SIDEBAR_DUPLICATES
                    print(f"[Migration] Enabled duplicates sidebar for admin user: {user.name}")

            _session.commit()
            try:
                os.makedirs(migration_dir, exist_ok=True)
                with open(migration_marker, "w", encoding="utf-8") as marker:
                    marker.write(datetime.now(timezone.utc).isoformat())
            except Exception as marker_error:
                print(
                    f"[Migration] Warning: Could not persist duplicates sidebar migration marker: {marker_error}",
                    flush=True,
                )
    except Exception as e:
        print(f"[Migration] Warning: Could not update duplicates sidebar setting: {e}")
        _session.rollback()

    # Migration for cover-preview per-user preference columns (Phase 2 of
    # cover-normalization — see notes/COVER-NORMALIZATION-DESIGN.md).
    # Existing users default to False on upgrade so the rollout is silent;
    # new users default True per the column-level default.
    try:
        _session.query(exists().where(User.show_ereader_previews)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.show_ereader_previews")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'show_ereader_previews' Boolean DEFAULT 1")
        try:
            updated = _session.query(User).update({User.show_ereader_previews: 0})
            _session.commit()
            print(f"[cover-preview-migration] Defaulted show_ereader_previews=0 for {updated} existing user(s) to preserve current view on upgrade.", flush=True)
        except Exception as e:
            print(f"[cover-preview-migration] Could not back-fill show_ereader_previews=0 for existing users: {e}", flush=True)
            _session.rollback()

    try:
        _session.query(exists().where(User.preview_preset)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.preview_preset")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'preview_preset' String DEFAULT 'kobo_libra_color'")

    try:
        _session.query(exists().where(User.preview_default_fill)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.preview_default_fill")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'preview_default_fill' String DEFAULT 'edge_mirror'")

    try:
        _session.query(exists().where(User.preview_default_color)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "user.preview_default_color")
        _run_ddl_with_retry(engine, "ALTER TABLE user ADD column 'preview_default_color' String")

def migrate_oauth_provider_table(engine, _session):
    try:
        _session.query(exists().where(OAuthProvider.oauth_base_url)).scalar()
        _session.commit()
    except exc.OperationalError:  # Database is not compatible, some columns are missing
        _safe_session_rollback(_session, "oauthProvider.base_urls")
        _run_ddl_with_retry(
            engine,
            [
                "ALTER TABLE oauthProvider ADD column 'oauth_base_url' String DEFAULT NULL",
                "ALTER TABLE oauthProvider ADD column 'oauth_authorize_url' String DEFAULT NULL",
                "ALTER TABLE oauthProvider ADD column 'oauth_token_url' String DEFAULT NULL",
                "ALTER TABLE oauthProvider ADD column 'oauth_userinfo_url' String DEFAULT NULL",
                "ALTER TABLE oauthProvider ADD column 'oauth_admin_group' String DEFAULT NULL",
            ],
        )

    # Add new OAuth enhancement fields
    try:
        _session.query(exists().where(OAuthProvider.metadata_url)).scalar()
        _session.commit()
    except exc.OperationalError:  # New columns are missing
        _safe_session_rollback(_session, "oauthProvider.metadata_url")
        _run_ddl_with_retry(
            engine,
            [
                "ALTER TABLE oauthProvider ADD column 'metadata_url' String DEFAULT NULL",
                "ALTER TABLE oauthProvider ADD column 'scope' String DEFAULT 'openid profile email'",
                "ALTER TABLE oauthProvider ADD column 'username_mapper' String DEFAULT 'preferred_username'",
                "ALTER TABLE oauthProvider ADD column 'email_mapper' String DEFAULT 'email'",
                "ALTER TABLE oauthProvider ADD column 'login_button' String DEFAULT 'OpenID Connect'",
            ],
        )


def migrate_config_table(engine, _session):
    """Migrate configuration table to add new authentication columns"""
    if not engine or not _session:
            _safe_session_rollback(_session, "settings.config_reverse_proxy_auto_create_users")
            _run_ddl_with_retry(
                engine,
                "ALTER TABLE settings ADD column 'config_reverse_proxy_auto_create_users' Boolean DEFAULT 0",
            )
    try:
        # Test if the new column exists
        _session.execute(text("SELECT config_oauth_redirect_host FROM settings LIMIT 1"))
        _session.commit()
    except exc.OperationalError:  # Column doesn't exist
        try:
            with engine.connect() as conn:
                trans = conn.begin()
                conn.execute(text("ALTER TABLE settings ADD column 'config_oauth_redirect_host' String DEFAULT ''"))
                trans.commit()
        except Exception as e:
            log.error("Failed to add config_oauth_redirect_host column: %s", e)
            # Don't raise - let CWA continue without this feature
            pass

    # Add reverse proxy auto-create users configuration
    try:
        # Test if the new column exists
        _session.execute(text("SELECT config_reverse_proxy_auto_create_users FROM settings LIMIT 1"))
        _session.commit()
    except exc.OperationalError:  # Column doesn't exist
        try:
            with engine.connect() as conn:
                trans = conn.begin()
                conn.execute(text("ALTER TABLE settings ADD column 'config_reverse_proxy_auto_create_users' Boolean DEFAULT 0"))
                trans.commit()
        except Exception as e:
            log.error("Failed to add config_reverse_proxy_auto_create_users column: %s", e)
            # Don't raise - let CWA continue without this feature
            pass

    # Add LDAP auto-create users configuration
    try:
        # Test if the new column exists
        _session.execute(text("SELECT config_ldap_auto_create_users FROM settings LIMIT 1"))
        _session.commit()
    except exc.OperationalError:  # Column doesn't exist
        try:
            _safe_session_rollback(_session, "settings.config_ldap_auto_create_users")
            _run_ddl_with_retry(
                engine,
                "ALTER TABLE settings ADD column 'config_ldap_auto_create_users' Boolean DEFAULT 1",
            )
        except Exception as e:
            log.error("Failed to add config_ldap_auto_create_users column: %s", e)
            # Don't raise - let CWA continue without this feature
            pass


def migrate_magic_shelf_table(engine, _session):
    """Migrate magic_shelf table to add new columns."""
    # Check and add is_system column
    try:
        _session.query(exists().where(MagicShelf.is_system)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "magic_shelf.is_system")
        _run_ddl_with_retry(engine, "ALTER TABLE magic_shelf ADD column 'is_system' Boolean DEFAULT 0")
    
    # Check and add kobo_sync column
    try:
        _session.query(exists().where(MagicShelf.kobo_sync)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "magic_shelf.kobo_sync")
        _run_ddl_with_retry(engine, "ALTER TABLE magic_shelf ADD column 'kobo_sync' Boolean DEFAULT 0")


def migrate_kobo_unique_constraints(engine, _session):
    """One-time migration: dedupe + uniquify (user_id, book_id) on Kobo
    state tables (audit 2026-05-11).

    Race condition: ``get_or_create_reading_state`` does read-then-write
    without locking, so two concurrent Kobo PUTs to /v1/library/<uuid>/state
    can both miss the existing row and both insert. The next read returns
    multiple rows -> ``.one_or_none()`` raises MultipleResultsFound ->
    500 to the device, which then retries forever.

    The fix has two parts:

    1. This migration: dedupe any existing duplicates, then create a
       UNIQUE index on (user_id, book_id) so the DB rejects future races.
       Winner per duplicate group is the row with the newest
       ``last_modified`` (so the user's most recent reading position
       survives). Child rows (KoboBookmark, KoboStatistics) are
       reparented to the winning KoboReadingState; orphaned child rows
       (the losers' children) are deleted only after their non-null
       fields are merged into the winner's children — newest LM wins
       per child too.

    2. ``get_or_create_reading_state`` switches to an atomic
       INSERT ... ON CONFLICT(user_id, book_id) DO NOTHING upsert so
       the race itself can't produce a duplicate even before the DB
       constraint trips.

    Idempotent: gated by a marker file in CONFIG_DIR/.cwa_migrations/
    so it runs at most once per install.
    """
    from sqlalchemy import inspect as sa_inspect
    marker_path = os.path.join(constants.CONFIG_DIR, ".cwa_migrations",
                               "kobo_unique_constraints_v1")
    if os.path.isfile(marker_path):
        return

    inspector = sa_inspect(engine)
    tables_present = set(inspector.get_table_names())

    # All four tables share the (user_id, book_id) shape. Dedupe rules
    # differ slightly per table; see _dedupe_* helpers below.
    plan = [
        ("kobo_reading_state", _dedupe_kobo_reading_state,
         "uq_kobo_reading_state_user_book"),
        ("book_read_link", _dedupe_book_read_link,
         "uq_book_read_link_user_book"),
        ("kobo_synced_books", _dedupe_kobo_synced_books,
         "uq_kobo_synced_books_user_book"),
        ("archived_book", _dedupe_archived_book,
         "uq_archived_book_user_book"),
    ]

    try:
        for table_name, dedupe_fn, index_name in plan:
            if table_name not in tables_present:
                continue
            removed = dedupe_fn(_session)
            if removed:
                log.info(
                    "[kobo-unique-migration] %s: merged %d duplicate row(s)",
                    table_name, removed,
                )
        _session.commit()
    except Exception as e:
        log.error("[kobo-unique-migration] dedupe failed: %s", e)
        _safe_session_rollback(_session, "kobo_unique_constraints/dedupe")
        return

    # Now that duplicates are gone, create the UNIQUE indexes. SQLite
    # doesn't support ALTER TABLE ADD CONSTRAINT; a UNIQUE INDEX has
    # equivalent semantics for INSERT ... ON CONFLICT routing and is
    # what SQLAlchemy's UniqueConstraint generates on new installs.
    ddl = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kobo_reading_state_user_book "
        "ON kobo_reading_state(user_id, book_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_book_read_link_user_book "
        "ON book_read_link(user_id, book_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kobo_synced_books_user_book "
        "ON kobo_synced_books(user_id, book_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_archived_book_user_book "
        "ON archived_book(user_id, book_id)",
    ]
    # Skip statements for tables that don't exist yet (fresh install path
    # where add_missing_tables hasn't run create_all on a particular
    # table — defensive only; current order has add_missing_tables first).
    ddl = [s for s in ddl
           if s.split(" ON ")[1].split("(")[0] in tables_present]
    try:
        _run_ddl_with_retry(engine, ddl)
    except Exception as e:
        log.error("[kobo-unique-migration] index creation failed: %s", e)
        return

    try:
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
    except OSError as e:
        # Marker is a perf optimization, not correctness — the migration
        # is idempotent because the indexes already exist and dedupe is
        # a no-op on a clean DB. Log but continue.
        log.warning(
            "[kobo-unique-migration] could not write marker %s: %s",
            marker_path, e,
        )


def _dedupe_kobo_reading_state(_session):
    """Pick winner per (user, book): newest last_modified. Reparent
    KoboBookmark + KoboStatistics children to the winner, merging
    non-null fields from losers' children (newest LM wins per child).
    Returns count of losing rows deleted.
    """
    dup_groups = _find_duplicate_groups(_session, KoboReadingState)
    deleted = 0
    for (user_id, book_id), rows in dup_groups.items():
        # Sort by last_modified DESC, NULL last; then id DESC as tiebreak.
        rows.sort(
            key=lambda r: (
                r.last_modified or datetime.min.replace(tzinfo=timezone.utc),
                r.id,
            ),
            reverse=True,
        )
        winner, losers = rows[0], rows[1:]
        for loser in losers:
            _merge_kobo_bookmark(_session, winner, loser)
            _merge_kobo_statistics(_session, winner, loser)
            _session.delete(loser)
            deleted += 1
    if deleted:
        _session.flush()
    return deleted


def _merge_kobo_bookmark(_session, winner, loser):
    """Merge loser.current_bookmark into winner.current_bookmark.
    Newest last_modified wins per field; non-null beats null when LM
    is missing. Loser's bookmark is left dangling (will be cascade-
    deleted when loser KoboReadingState is deleted).
    """
    if loser.current_bookmark is None:
        return
    if winner.current_bookmark is None:
        # Steal the row outright. Re-point its FK.
        loser.current_bookmark.kobo_reading_state_id = winner.id
        winner.current_bookmark = loser.current_bookmark
        loser.current_bookmark = None
        return
    w, l = winner.current_bookmark, loser.current_bookmark
    if _loser_wins_lm(l, w):
        for attr in ("location_source", "location_type", "location_value",
                     "progress_percent", "content_source_progress_percent",
                     "last_modified"):
            setattr(w, attr, getattr(l, attr))
    else:
        # Even if winner's bookmark is newer overall, prefer non-null
        # losing fields if the winner has nulls there (defensive).
        for attr in ("location_source", "location_type", "location_value",
                     "progress_percent", "content_source_progress_percent"):
            if getattr(w, attr) is None and getattr(l, attr) is not None:
                setattr(w, attr, getattr(l, attr))


def _merge_kobo_statistics(_session, winner, loser):
    if loser.statistics is None:
        return
    if winner.statistics is None:
        loser.statistics.kobo_reading_state_id = winner.id
        winner.statistics = loser.statistics
        loser.statistics = None
        return
    w, l = winner.statistics, loser.statistics
    if _loser_wins_lm(l, w):
        for attr in ("remaining_time_minutes", "spent_reading_minutes",
                     "last_modified"):
            setattr(w, attr, getattr(l, attr))
    else:
        for attr in ("remaining_time_minutes", "spent_reading_minutes"):
            if getattr(w, attr) is None and getattr(l, attr) is not None:
                setattr(w, attr, getattr(l, attr))


def _dedupe_book_read_link(_session):
    """ReadBook winner: prefer rows with the highest read_status (FINISHED
    > IN_PROGRESS > UNREAD), tiebreak by newest last_modified, then by
    highest times_started_reading. Sum times_started_reading from losers
    into the winner so the user doesn't lose their read-counter total.
    """
    dup_groups = _find_duplicate_groups(_session, ReadBook)
    deleted = 0
    for (user_id, book_id), rows in dup_groups.items():
        rows.sort(
            key=lambda r: (
                r.read_status or 0,
                r.last_modified or datetime.min.replace(tzinfo=timezone.utc),
                r.times_started_reading or 0,
                r.id,
            ),
            reverse=True,
        )
        winner, losers = rows[0], rows[1:]
        for loser in losers:
            winner.times_started_reading = (
                (winner.times_started_reading or 0)
                + (loser.times_started_reading or 0)
            )
            if (loser.last_time_started_reading is not None and
                (winner.last_time_started_reading is None or
                 loser.last_time_started_reading > winner.last_time_started_reading)):
                winner.last_time_started_reading = loser.last_time_started_reading
            _session.delete(loser)
            deleted += 1
    if deleted:
        _session.flush()
    return deleted


def _dedupe_kobo_synced_books(_session):
    """No payload to merge — just keep one row (lowest id) per (user, book)."""
    dup_groups = _find_duplicate_groups(_session, KoboSyncedBooks)
    deleted = 0
    for (user_id, book_id), rows in dup_groups.items():
        rows.sort(key=lambda r: r.id)
        for loser in rows[1:]:
            _session.delete(loser)
            deleted += 1
    if deleted:
        _session.flush()
    return deleted


def _dedupe_archived_book(_session):
    """ArchivedBook winner: is_archived=True takes precedence over False
    (archived is the more-recent semantic signal), then newest LM, then
    highest id.
    """
    dup_groups = _find_duplicate_groups(_session, ArchivedBook)
    deleted = 0
    for (user_id, book_id), rows in dup_groups.items():
        rows.sort(
            key=lambda r: (
                1 if r.is_archived else 0,
                r.last_modified or datetime.min.replace(tzinfo=timezone.utc),
                r.id,
            ),
            reverse=True,
        )
        for loser in rows[1:]:
            _session.delete(loser)
            deleted += 1
    if deleted:
        _session.flush()
    return deleted


def _find_duplicate_groups(_session, model):
    """Return dict {(user_id, book_id): [rows]} for groups with size >= 2."""
    from sqlalchemy import func as sa_func
    dup_keys = (
        _session.query(model.user_id, model.book_id)
        .group_by(model.user_id, model.book_id)
        .having(sa_func.count(model.id) > 1)
        .all()
    )
    groups = {}
    for user_id, book_id in dup_keys:
        rows = (
            _session.query(model)
            .filter(model.user_id == user_id, model.book_id == book_id)
            .all()
        )
        groups[(user_id, book_id)] = rows
    return groups


def _loser_wins_lm(loser, winner):
    """True if loser.last_modified > winner.last_modified (strictly newer)."""
    lo = getattr(loser, "last_modified", None)
    wn = getattr(winner, "last_modified", None)
    if lo is None:
        return False
    if wn is None:
        return True
    return lo > wn


def migrate_kobo_deleted_book(engine, _session):
    """Create the kobo_deleted_book tombstone table if it doesn't exist.

    Idempotent: gated by a marker file in CONFIG_DIR/.cwa_migrations/ so
    it runs at most once per install. The marker is a perf optimization,
    not correctness — the underlying DDL uses CREATE TABLE IF NOT EXISTS
    so re-running is safe.

    Why this table exists: see the KoboDeletedBook model docstring.
    Captures (user_id, book_uuid, deleted_at) at the moment a book is
    deleted, so HandleSyncRequest can emit DeletedEntitlement on the
    next sync per affected user — the existing two-way deletion logic
    can only handle books removed from kobo_sync shelves, not hard
    deletes from the calibre library.
    """
    from sqlalchemy import inspect as sa_inspect
    marker_path = os.path.join(constants.CONFIG_DIR, ".cwa_migrations",
                               "kobo_deleted_book_v1")
    if os.path.isfile(marker_path):
        return

    inspector = sa_inspect(engine)
    if "kobo_deleted_book" not in inspector.get_table_names():
        try:
            KoboDeletedBook.__table__.create(engine, checkfirst=True)
        except Exception as e:
            log.error("[kobo-deleted-book-migration] create_all failed: %s", e)
            return

    # Indexes for the sync query path: (user_id, deleted_at) covers the
    # "rows for current_user where deleted_at > cursor" pattern.
    try:
        _run_ddl_with_retry(
            engine,
            "CREATE INDEX IF NOT EXISTS idx_kobo_deleted_book_user_deleted "
            "ON kobo_deleted_book(user_id, deleted_at)",
        )
    except Exception as e:
        log.warning("[kobo-deleted-book-migration] index creation failed: %s", e)

    try:
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat())
    except OSError as e:
        log.warning(
            "[kobo-deleted-book-migration] could not write marker %s: %s",
            marker_path, e,
        )


def migrate_shelf_table(engine, _session):
    """Ensure Shelf.kobo_sync column exists; backfill DDL if not (legacy
    fork branch — predates the dedicated kobo_sync migrations elsewhere).
    Called from migrate_Database below."""
    try:
        _session.query(exists().where(Shelf.kobo_sync)).scalar()
        _session.commit()
    except exc.OperationalError:
        _safe_session_rollback(_session, "shelf.kobo_sync")
        _run_ddl_with_retry(engine, "ALTER TABLE shelf ADD column 'kobo_sync' Boolean DEFAULT 0")


# Migrate database to current version, has to be updated after every database change. Currently migration from
# maybe 4/5 versions back to current should work.
# Migration is done by checking if relevant columns are existing, and then adding rows with SQL commands
def migrate_book_cover_preview_table(engine, _session):
    """Create the book_cover_preview table if it doesn't exist.
    Idempotent — `BookCoverPreview.__table__.create(engine, checkfirst=True)`
    no-ops if the table already exists.
    """
    try:
        with engine.connect() as conn:
            has_table = engine.dialect.has_table(conn, "book_cover_preview")
    except Exception:
        # Fall back to the SQLAlchemy 2.0-friendly form if dialect.has_table
        # signature differs across versions.
        has_table = False
    if not has_table:
        BookCoverPreview.__table__.create(engine, checkfirst=True)
        try:
            _run_ddl_with_retry(
                engine,
                "CREATE INDEX IF NOT EXISTS idx_bcp_user_locked ON book_cover_preview(user_id, locked)",
            )
        except Exception as e:
            print(f"[cover-preview-migration] Could not create idx_bcp_user_locked: {e}", flush=True)


def migrate_Database(_session):
    engine = _session.bind
    add_missing_tables(engine, _session)
    migrate_registration_table(engine, _session)
    migrate_user_session_table(engine, _session)
    migrate_user_table(engine, _session)
    migrate_shelf_table(engine, _session)
    migrate_oauth_provider_table(engine, _session)
    migrate_config_table(engine, _session)
    migrate_magic_shelf_table(engine, _session)
    migrate_kobo_unique_constraints(engine, _session)
    migrate_kobo_deleted_book(engine, _session)
    migrate_book_cover_preview_table(engine, _session)

    # Ensure progress syncing tables in app.db (user-related tables)
    from .progress_syncing.models import ensure_app_db_tables
    from .progress_syncing.settings import is_koreader_sync_enabled
    if is_koreader_sync_enabled():
        ensure_app_db_tables(engine.raw_connection())
    
    # Migrate system magic shelves for existing users
    try:
        from . import magic_shelf
        
        # Get all valid current template names
        current_template_names = {template['name'] for template in magic_shelf.SYSTEM_SHELF_TEMPLATES.values()}
        
        log.info("Migrating system magic shelves...")
        users = _session.query(User).filter(User.role != constants.ROLE_ANONYMOUS).all()
        total_deleted = 0
        total_created = 0
        
        for user in users:
            # Get all system shelves for this user
            user_system_shelves = _session.query(MagicShelf).filter(
                MagicShelf.user_id == user.id,
                MagicShelf.is_system == True
            ).all()
            
            # Delete system shelves that don't match current templates
            for shelf in user_system_shelves:
                if shelf.name not in current_template_names:
                    # This is an old/deprecated system shelf - delete it
                    _session.query(MagicShelfCache).filter_by(shelf_id=shelf.id).delete()
                    _session.query(HiddenMagicShelfTemplate).filter_by(shelf_id=shelf.id).delete()
                    _session.delete(shelf)
                    total_deleted += 1
                    log.debug(f"Deleted deprecated system shelf '{shelf.name}' (ID: {shelf.id}) for user {user.id}")
            
            # Get user's template-based hide preferences (not shelf-specific)
            hidden_templates = _session.query(HiddenMagicShelfTemplate.template_key).filter(
                HiddenMagicShelfTemplate.user_id == user.id,
                HiddenMagicShelfTemplate.template_key.isnot(None)
            ).all()
            hidden_keys = {ht.template_key for ht in hidden_templates}
            
            # Create missing current templates
            templates_to_create = []
            for template_key, template_data in magic_shelf.SYSTEM_SHELF_TEMPLATES.items():
                # Skip if user has hidden this template type
                if template_key in hidden_keys:
                    continue
                
                # Check if user already has this current template
                has_template = _session.query(MagicShelf).filter(
                    MagicShelf.user_id == user.id,
                    MagicShelf.name == template_data['name'],
                    MagicShelf.is_system == True
                ).first()
                
                if not has_template:
                    templates_to_create.append(template_key)
            
            # Create missing templates
            if templates_to_create:
                created = magic_shelf.create_system_magic_shelves(user.id, templates_to_create)
                total_created += created
        
        if total_deleted > 0 or total_created > 0:
            _session.commit()
            log.info(f"System shelf migration complete: {total_deleted} old shelves removed, {total_created} new shelves created")
    except Exception as e:
        log.error(f"Error during system shelf migration: {e}")
        _session.rollback()


def clean_database(_session):
    # Remove expired remote login tokens
    now = datetime.now()
    try:
        _session.query(RemoteAuthToken).filter(now > RemoteAuthToken.expiration).\
            filter(RemoteAuthToken.token_type != 1).delete()
        _session.commit()
    except exc.OperationalError:  # Database is not writeable
        print('Settings database is not writeable. Exiting...')
        sys.exit(2)


# Save downloaded books per user in calibre-web's own database
def update_download(book_id, user_id):
    check = session.query(Downloads).filter(Downloads.user_id == user_id).filter(Downloads.book_id == book_id).first()

    if not check:
        new_download = Downloads(user_id=user_id, book_id=book_id)
        session.add(new_download)
        try:
            session.commit()
        except exc.OperationalError:
            session.rollback()


# Delete non existing downloaded books in calibre-web's own database
def delete_download(book_id):
    session.query(Downloads).filter(book_id == Downloads.book_id).delete()
    try:
        session.commit()
    except exc.OperationalError:
        session.rollback()

# Generate user Guest (translated text), as anonymous user, no rights
def create_anonymous_user(_session):
    user = User()
    user.name = "Guest"
    user.email = 'no@email'
    user.role = constants.ROLE_ANONYMOUS
    user.password = ''

    _session.add(user)
    try:
        _session.commit()
        # Note: Anonymous users don't get system shelves
        # They will be created if/when the user registers
    except Exception:
        _session.rollback()


# Generate User admin with admin123 password, and access to everything
def create_admin_user(_session):
    user = User()
    user.name = "admin"
    user.email = "admin@example.org"
    user.role = constants.ADMIN_USER_ROLES
    user.sidebar_view = constants.ADMIN_USER_SIDEBAR

    user.password = generate_password_hash(constants.DEFAULT_PASSWORD)

    _session.add(user)
    try:
        _session.commit()
        # Create system magic shelves for admin user
        try:
            from . import magic_shelf
            magic_shelf.create_system_magic_shelves(user.id)
        except Exception as e:
            log.error(f"Failed to create system magic shelves for admin: {e}")
    except Exception:
        _session.rollback()


def create_system_magic_shelves_for_user(user_id):
    """
    Create system magic shelves for a user if they don't already exist.
    Should be called after user creation.
    """
    try:
        from . import magic_shelf
        return magic_shelf.create_system_magic_shelves(user_id)
    except Exception as e:
        log.error(f"Failed to create system magic shelves for user {user_id}: {e}")
        return 0


def init_db_thread():
    global app_DB_path
    engine = create_engine('sqlite:///{0}'.format(app_DB_path), echo=False,
                           connect_args={'timeout': 30})

    Session = scoped_session(sessionmaker())
    Session.configure(bind=engine)
    return Session()


def init_db(app_db_path):
    # Open session for database connection
    global session
    global app_DB_path

    app_DB_path = app_db_path
    engine = create_engine('sqlite:///{0}'.format(app_db_path), echo=False,
                           connect_args={'timeout': 30})

    Session = scoped_session(sessionmaker())
    Session.configure(bind=engine)
    session = Session()

    _healthcheck_app_db(app_db_path)

    if os.path.exists(app_db_path):
        Base.metadata.create_all(engine)
        migrate_Database(session)
        clean_database(session)
    else:
        Base.metadata.create_all(engine)
        create_admin_user(session)
        create_anonymous_user(session)


def _healthcheck_app_db(app_db_path: str) -> None:
    """Basic startup checks for app.db path, permissions, and integrity."""
    try:
        if not app_db_path:
            log.error("app.db path is empty; cannot validate settings database")
            return
        if os.path.isdir(app_db_path):
            log.error("app.db path points to a directory: %s", app_db_path)
            return
        if not os.path.exists(app_db_path):
            log.warning("app.db not found at %s; it will be created on first run", app_db_path)
            return
        if not os.access(app_db_path, os.W_OK):
            log.error("app.db is not writable: %s", app_db_path)
        network_share_mode = os.environ.get("NETWORK_SHARE_MODE", "false").lower() in ("1", "true", "yes")
        if network_share_mode:
            log.info("Skipping PRAGMA quick_check for app.db due to NETWORK_SHARE_MODE=true")
            return
        try:
            with sqlite3.connect(app_db_path, timeout=5) as con:
                con.execute("PRAGMA quick_check;")
        except sqlite3.OperationalError as e:
            log.error("app.db integrity/lock check failed for %s: %s", app_db_path, e)
    except Exception as e:
        log.error("app.db healthcheck failed for %s: %s", app_db_path, e)

def password_change(user_credentials=None):
    if user_credentials:
        username, password = user_credentials.split(':', 1)
        user = session.query(User).filter(func.lower(User.name) == username.lower()).first()
        if user:
            if not password:
                print("Empty password is not allowed")
                sys.exit(4)
            try:
                from .helper import valid_password
                user.password = generate_password_hash(valid_password(password))
            except Exception:
                print("Password doesn't comply with password validation rules")
                sys.exit(4)
            if session_commit() == "":
                print("Password for user '{}' changed".format(username))
                sys.exit(0)
            else:
                print("Failed changing password")
                sys.exit(3)
        else:
            print("Username '{}' not valid, can't change password".format(username))
            sys.exit(3)


def get_new_session_instance():
    new_engine = create_engine('sqlite:///{0}'.format(app_DB_path), echo=False,
                               connect_args={'timeout': 30})
    new_session = scoped_session(sessionmaker())
    new_session.configure(bind=new_engine)

    atexit.register(lambda: new_session.remove() if new_session else True)

    return new_session


def dispose():
    global session

    old_session = session
    session = None
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

def session_commit(success=None, _session=None):
    s = _session if _session else session
    try:
        s.commit()
        if success:
            log.info(success)
    except (exc.OperationalError, exc.InvalidRequestError) as e:
        s.rollback()
        log.error_or_exception(e)
    return ""
