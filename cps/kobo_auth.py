#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""This module is used to control authentication/authorization of Kobo sync requests.
This module also includes research notes into the auth protocol used by Kobo devices.

Log-in:
When first booting a Kobo device the user must sign into a Kobo (or affiliate) account.
Upon successful sign-in, the user is redirected to
    https://auth.kobobooks.com/CrossDomainSignIn?id=<some id>
which serves the following response:
    <script type='text/javascript'>
        location.href='kobo://UserAuthenticated?userId=<redacted>&userKey<redacted>&email=<redacted>&returnUrl=https%3a%2f%2fwww.kobo.com';
    </script>
And triggers the insertion of a userKey into the device's User table.

Together, the device's DeviceId and UserKey act as an *irrevocable* authentication
token to most (if not all) Kobo APIs. In fact, in most cases only the UserKey is
required to authorize the API call.

Changing Kobo password *does not* invalidate user keys! This is apparently a known
issue for a few years now https://www.mobileread.com/forums/showpost.php?p=3476851&postcount=13
(although this poster hypothesised that Kobo could blacklist a DeviceId, many endpoints
will still grant access given the userkey.)

Official Kobo Store Api authorization:
* For most of the endpoints we care about (sync, metadata, tags, etc), the userKey is
passed in the x-kobo-userkey header, and is sufficient to authorize the API call.
* Some endpoints (e.g: AnnotationService) instead make use of Bearer tokens pass through
an authorization header. To get a BearerToken, the device makes a POST request to the
v1/auth/device endpoint with the secret UserKey and the device's DeviceId.
* The book download endpoint passes an auth token as a URL param instead of a header.

Our implementation:
We pretty much ignore all of the above. To authenticate the user, we generate a random
and unique token that they append to the CalibreWeb Url when setting up the api_store
setting on the device.
Thus, every request from the device to the api_store will hit CalibreWeb with the
auth_token in the url (e.g: https://mylibrary.com/<auth_token>/v1/library/sync).
In addition, once authenticated we also set the login cookie on the response that will
be sent back for the duration of the session to authorize subsequent API calls (in
particular calls to non-Kobo specific endpoints such as the CalibreWeb book download).
"""

from binascii import hexlify
from datetime import datetime, timezone
from os import urandom
from functools import wraps

from flask import g, Blueprint, abort, request, flash, redirect, url_for
from .cw_login import login_user, current_user
from flask_babel import gettext as _
from flask_limiter import RateLimitExceeded

from . import logger, config, calibre_db, db, helper, ub, lm, limiter
from .render_template import render_title_template
from .usermanagement import user_login_required


log = logger.create()

kobo_auth = Blueprint("kobo_auth", __name__, url_prefix="/kobo_auth")


@kobo_auth.route("/generate_auth_token/<int:user_id>")
@user_login_required
def generate_auth_token(user_id):
    warning = False
    host_list = request.host.rsplit(':')
    if len(host_list) == 1:
        host = ':'.join(host_list)
    else:
        host = ':'.join(host_list[0:-1])
    if host.startswith('127.') or host.lower() == 'localhost' or host.startswith('[::ffff:7f') or host == "[::1]":
        warning = _('Please access Calibre-Web Automated from non localhost to get valid api_endpoint for kobo device')

    # Generate auth token if none is existing for this user
    auth_token = ub.session.query(ub.RemoteAuthToken).filter(
        ub.RemoteAuthToken.user_id == user_id
    ).filter(ub.RemoteAuthToken.token_type==1).first()

    if not auth_token:
        auth_token = ub.RemoteAuthToken()
        auth_token.user_id = user_id
        auth_token.expiration = datetime.max
        auth_token.auth_token = (hexlify(urandom(16))).decode("utf-8")
        auth_token.token_type = 1

        ub.session.add(auth_token)
        ub.session_commit()

    books = calibre_db.session.query(db.Books).join(db.Data).all()

    for book in books:
        formats = [data.format for data in book.data]
        if 'KEPUB' not in formats and config.config_kepubifypath and 'EPUB' in formats:
            helper.convert_book_format(book.id, config.config_calibre_dir, 'EPUB', 'KEPUB', current_user.name)

    return render_title_template(
        "generate_kobo_auth_url.html",
        title=_("Kobo Setup"),
        auth_token=auth_token.auth_token,
        warning=warning
    )


@kobo_auth.route("/deleteauthtoken/<int:user_id>", methods=["POST"])
@user_login_required
def delete_auth_token(user_id):
    # Invalidate any previously generated Kobo Auth token for this user
    ub.session.query(ub.RemoteAuthToken).filter(ub.RemoteAuthToken.user_id == user_id)\
        .filter(ub.RemoteAuthToken.token_type==1).delete()

    return ub.session_commit()


@kobo_auth.route("/allow_excluded_book/<int:book_id>", methods=["POST"])
@user_login_required
def allow_excluded_book(book_id):
    from .kobo_dashboard import KOBO_EXCLUSION_SHELF_NAME

    shelves = ub.session.query(ub.Shelf).filter(
        ub.Shelf.user_id == current_user.id,
        ub.Shelf.name == KOBO_EXCLUSION_SHELF_NAME
    ).all()
    if not shelves:
        flash(_("Das Ausschlussregal wurde nicht gefunden."), category="warning")
        return redirect(url_for("kobo_auth.dashboard"))

    shelves_by_id = {shelf.id: shelf for shelf in shelves}
    book_shelves = ub.session.query(ub.BookShelf).filter(
        ub.BookShelf.shelf.in_(list(shelves_by_id)),
        ub.BookShelf.book_id == book_id
    ).all()
    if not book_shelves:
        flash(_("Dieses Buch ist bereits wieder für Kobo erlaubt."), category="info")
        return redirect(url_for("kobo_auth.dashboard"))

    try:
        from .magic_shelf import invalidate_magic_shelf_cache
        invalidate_magic_shelf_cache()
        now = datetime.now(timezone.utc)
        for book_shelf in book_shelves:
            shelf = shelves_by_id.get(book_shelf.shelf)
            if shelf:
                book_shelf.ub_shelf = shelf
                shelf.last_modified = now
            ub.session.delete(book_shelf)
        ub.session.commit()
        flash(_("Buch ist wieder für Kobo erlaubt."), category="success")
    except Exception as e:
        ub.session.rollback()
        log.error("Failed to allow excluded Kobo book %d: %s", book_id, e)
        flash(_("Das Buch konnte nicht wieder für Kobo erlaubt werden."), category="error")

    return redirect(url_for("kobo_auth.dashboard"))


@kobo_auth.route("/block_kobo_book/<int:book_id>", methods=["POST"])
@user_login_required
def block_kobo_book(book_id):
    if not current_user.kobo_only_shelves_sync:
        flash(_("Manuelles Blockieren ist nur im Zwei-Säulen-Sync verfügbar."), category="warning")
        return redirect(url_for("kobo_auth.dashboard"))

    try:
        from .kobo import get_kobo_allowed_book_ids, get_or_create_kobo_exclusion_shelf
        allowed_book_ids = get_kobo_allowed_book_ids(current_user.id)
        if allowed_book_ids is None or book_id not in allowed_book_ids:
            flash(_("Dieses Buch ist bereits nicht in der Kobo-Auswahl."), category="info")
            return redirect(url_for("kobo_auth.dashboard"))

        exclusion_shelf = get_or_create_kobo_exclusion_shelf(current_user.id)
        exclusion_shelf.books.append(ub.BookShelf(book_id=book_id))
        exclusion_shelf.last_modified = datetime.now(timezone.utc)

        from .magic_shelf import invalidate_magic_shelf_cache
        invalidate_magic_shelf_cache()
        ub.session.commit()
        flash(_("Buch wird beim nächsten Kobo-Sync ausgelassen."), category="success")
    except Exception as e:
        ub.session.rollback()
        log.error("Failed to block Kobo book %d: %s", book_id, e)
        flash(_("Das Buch konnte nicht aus der Kobo-Auswahl entfernt werden."), category="error")

    return redirect(url_for("kobo_auth.dashboard"))


def disable_failed_auth_redirect_for_blueprint(bp):
    lm.blueprint_login_views[bp.name] = None


def get_auth_token():
    if "auth_token" in g:
        return g.get("auth_token")
    else:
        return None


def register_url_value_preprocessor(kobo):
    @kobo.url_value_preprocessor
    # pylint: disable=unused-variable
    def pop_auth_token(__, values):
        g.auth_token = values.pop("auth_token")


def requires_kobo_auth(f):
    @wraps(f)
    def inner(*args, **kwargs):
        auth_token = get_auth_token()
        if auth_token is not None:
            try:
                limiter.check()
            except RateLimitExceeded:
                return abort(429)
            except (ConnectionError, Exception) as e:
                log.error("Connection error to limiter backend: %s", e)
                return abort(429)
            user = (
                ub.session.query(ub.User)
                .join(ub.RemoteAuthToken)
                .filter(ub.RemoteAuthToken.auth_token == auth_token).filter(ub.RemoteAuthToken.token_type==1)
                .first()
            )
            if user is not None:
                login_user(user)
                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                return f(*args, **kwargs)
        log.debug("Received Kobo request without a recognizable auth token.")
        return abort(401)
    return inner


@kobo_auth.route("/dashboard")
@user_login_required
def dashboard():
    from .kobo_dashboard import get_kobo_dashboard_data
    dashboard_data = get_kobo_dashboard_data(current_user)
    return render_title_template("kobo_dashboard.html", title=_("Kobo Sync Dashboard"), page="kobo_dashboard", **dashboard_data)
