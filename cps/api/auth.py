# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# Endpoint shapes follow Calibre-Web NextGen's /api/v1/auth
# (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Session login for API clients: CSRF token, login, logout, current user, login options.

The rules mirror web.login_post: the same rate limits, "disable standard login" switch,
LDAP bind with local fallback when the directory is unreachable, LDAP auto-creation,
and CWA login activity logging.
"""

import json

from flask import jsonify, request, session as flask_session, url_for
from flask_limiter import RateLimitExceeded
from sqlalchemy.sql.expression import func
from werkzeug.security import check_password_hash

from . import api_v1, api_error
from .serializers import serialize_user
from .. import config, constants, limiter, logger, services, ub
from ..cw_login import current_user, login_user, logout_user
from ..string_helper import strip_whitespaces

try:
    from flask_wtf.csrf import generate_csrf
except ImportError:
    generate_csrf = None

log = logger.create()


def _request_data():
    return request.get_json(silent=True) or request.form.to_dict() or {}


def _username(data):
    value = data.get("username")
    if not isinstance(value, str):
        return ""
    return strip_whitespaces(value).lower().replace("\n", "").replace("\r", "")


def _login_rate_key():
    return _username(_request_data())


def _log_activity(event_type, user=None, username_attempted=None, method=None):
    try:
        from cwa_db import CWA_DB
        extra = None
        if username_attempted is not None:
            extra = json.dumps({"username_attempted": username_attempted, "ip": request.remote_addr,
                                "method": method})
        CWA_DB().log_activity(user_id=int(user.id) if user else None,
                              user_name=user.name if user else "Anonymous",
                              event_type=event_type, extra_data=extra)
    except Exception as e:
        log.debug("Failed to log %s activity: %s", event_type, e)


def _complete_login(user, remember):
    login_user(user, remember=remember)
    _log_activity("LOGIN", user=user)
    [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
    flask_session.pop('_login_redirect_count', None)
    return jsonify(serialize_user(user))


def _invalid_credentials(username, method):
    log.warning('API login failed for user "%s" IP-address: %s', username, request.remote_addr)
    _log_activity("LOGIN_FAILED", username_attempted=username, method=method)
    return api_error("invalid_credentials", "Wrong username or password", 401)


def _ldap_login(user, username, password, remember):
    login_result, error = services.ldap.bind_user(username, password)
    if login_result:
        if user:
            return _complete_login(user, remember)
        if not getattr(config, "config_ldap_auto_create_users", True):
            return api_error("no_local_account", "Authenticated, but no local account exists", 403)
        try:
            details = services.ldap.get_object_details(username)
            if details:
                from .. import admin
                created, __ = admin.ldap_import_create_user(username, details)
                if created:
                    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username).first()
                    if user:
                        log.info("LDAP auto-created user: '%s'", username)
                        return _complete_login(user, remember)
        except Exception as ex:
            log.error("LDAP auto-creation error for user '%s': %s", username, ex)
        return api_error("account_creation_failed", "Authenticated, but account creation failed", 500)
    if login_result is None:
        # Directory unreachable or user unknown: same local fallback as the classic login.
        if user and user.name != "Guest" and check_password_hash(str(user.password), password):
            log.info("Local Fallback Login as: '%s'", user.name)
            return _complete_login(user, remember)
        log.info(error)
        return api_error("ldap_unavailable", "Could not log in: {}".format(error), 503)
    return _invalid_credentials(username, "LDAP")


@api_v1.route("/auth/csrf")
def auth_csrf():
    """Token to send as the X-CSRFToken header on every POST, PUT, PATCH and DELETE."""
    return jsonify({"csrf_token": generate_csrf() if generate_csrf else ""})


@api_v1.route("/auth/config")
def auth_config():
    """What a login screen needs: which login methods are on."""
    from ..web import feature_support
    oauth = []
    if feature_support.get("oauth") and config.config_login_type == constants.LOGIN_OAUTH:
        from .. import oauth_bb
        endpoints = {1: "oauth.github_login", 2: "oauth.google_login", 3: "oauth.generic_login"}
        for provider_id, name in oauth_bb.oauth_check.items():
            if provider_id in endpoints:
                oauth.append({"id": provider_id, "name": name, "login_url": url_for(endpoints[provider_id])})
    return jsonify({
        "login_type": {constants.LOGIN_STANDARD: "standard", constants.LOGIN_LDAP: "ldap",
                       constants.LOGIN_OAUTH: "oauth"}.get(config.config_login_type, "standard"),
        "standard_login": not config.config_disable_standard_login,
        "oauth_providers": oauth,
        "registration": bool(config.config_public_reg),
        "password_reset": bool(config.get_mail_server_configured()),
        "remote_login": bool(config.config_remote_login),
        "anonymous_browsing": config.config_anonbrowse == 1,
    })


@api_v1.route("/auth/me")
def auth_me():
    # Public so a client can ask "am I logged in?"; with anonymous browsing on, the
    # Guest user is a valid answer.
    if not current_user.is_authenticated and config.config_anonbrowse != 1:
        return api_error("unauthorized", "Authentication required", 401)
    return jsonify(serialize_user(current_user))


@api_v1.route("/auth/login", methods=["POST"])
@limiter.limit("40/day", key_func=_login_rate_key)
@limiter.limit("3/minute", key_func=_login_rate_key)
def auth_login():
    if config.config_disable_standard_login:
        return api_error("standard_login_disabled", "Standard login is disabled", 403)
    try:
        limiter.check()
    except RateLimitExceeded:
        return api_error("rate_limited", "Please wait one minute before the next login", 429)
    except Exception as e:
        log.error("Connection error to limiter backend: %s", e)
        return api_error("limiter_unavailable", "Connection error to limiter backend", 503)

    data = _request_data()
    username = _username(data)
    password = data.get("password")
    password = password if isinstance(password, str) else ""
    remember = bool(data.get("remember"))
    if current_user.is_authenticated:
        return jsonify(serialize_user(current_user))
    if not username:
        return _invalid_credentials(username, "standard")

    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username).first()
    if config.config_login_type == constants.LOGIN_LDAP and services.ldap and password:
        return _ldap_login(user, username, password, remember)
    if user and user.name != "Guest" and check_password_hash(str(user.password), password):
        config.config_is_initial = False
        return _complete_login(user, remember)
    return _invalid_credentials(username, "standard")


@api_v1.route("/auth/logout", methods=["POST"])
def auth_logout():
    if current_user.is_authenticated:
        from ..web import feature_support, logout_oauth_user
        if feature_support.get("oauth") and config.config_login_type in (2, 3):
            logout_oauth_user()
        ub.delete_user_session(current_user.id, flask_session.get('_id', ""))
        logout_user()
    flask_session.pop('_login_redirect_count', None)
    return "", 204
