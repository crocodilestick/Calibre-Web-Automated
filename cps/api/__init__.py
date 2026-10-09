# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
#
# The blueprint layout, auth gate, Origin check and JSON error format are adapted from
# Calibre-Web NextGen (https://github.com/new-usemame/Calibre-Web-NextGen, GPL-3.0-or-later).

"""Versioned JSON API (/api/v1) for frontends and other clients.

Every route reuses the same CalibreDB filters and user roles as the server-rendered UI,
so a user can see and do exactly the same things through either surface.
"""

import os
import traceback
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request, g
from werkzeug.exceptions import HTTPException

from .. import logger, config
from ..cw_login import current_user
from ..usermanagement import load_user_from_reverse_proxy_header

log = logger.create()

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Endpoints reachable without a session. auth_me answers the anonymous case itself.
_PUBLIC_ENDPOINTS = {
    "api_v1.health",
    "api_v1.auth_csrf",
    "api_v1.auth_login",
    "api_v1.auth_me",
    "api_v1.auth_logout",
    "api_v1.auth_config",
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def api_error(code, message, status):
    """The one error shape every /api/v1 route returns."""
    return jsonify({"error": {"code": code, "message": message}}), status


MAX_PER_PAGE = 200


def paging():
    """(page, per_page) from ?page=&per_page=, clamped; per_page defaults to the admin's setting."""
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", config.config_books_per_page, type=int) or config.config_books_per_page
    return max(page, 1), min(max(per_page, 1), MAX_PER_PAGE)


def _parse_trusted_origins(raw):
    return tuple(o.strip() for o in (raw or "").split(",") if o.strip())


# For a reverse proxy that rewrites Host without sending X-Forwarded-Host, e.g.
# CWA_TRUSTED_ORIGINS=https://books.example.com. Not needed for normal deployments.
_EXTRA_TRUSTED_ORIGINS = _parse_trusted_origins(os.environ.get("CWA_TRUSTED_ORIGINS"))


def _origin_key(value):
    """(scheme, host) of `value`, or None when it names no usable origin.

    Structured comparison keeps `books.example.com.evil.test` and userinfo tricks
    (`http://books.example.com@evil.test`) from matching. Ports are ignored on purpose:
    proxies commonly strip them from X-Forwarded-Host.
    """
    try:
        parts = urlsplit(value)
        parts.port  # raises on a malformed port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    return parts.scheme.lower(), parts.hostname.lower()


@api_v1.before_request
def _require_api_auth():
    """Answer unauthenticated calls with JSON 401 instead of a redirect to the login page.

    Mirrors usermanagement.login_required_if_no_ano: reverse-proxy header login, then
    anonymous browsing, then the session.
    """
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return None
    if config.config_allow_reverse_proxy_header_login:
        user = load_user_from_reverse_proxy_header(request)
        if user:
            g.flask_httpauth_user = user
            return None
        g.flask_httpauth_user = None
    if config.config_anonbrowse == 1:
        return None
    if current_user.is_authenticated:
        return None
    return api_error("unauthorized", "Authentication required", 401)


@api_v1.before_request
def _reject_cross_site_mutation():
    """Refuse a state-changing request whose stated Origin/Referer is another site.

    The CSRF token is enforced by the global CSRFProtect; this is a second layer
    because WTF_CSRF_SSL_STRICT is off. Requests without Origin/Referer (curl, native
    clients) carry no ambient browser credentials and pass. Registered after the auth
    gate so an unauthenticated call still gets 401 and the check can't be used to
    probe which origins are trusted.
    """
    if request.method in _SAFE_METHODS:
        return None
    stated = request.headers.get("Origin") or request.headers.get("Referer")
    if not stated:
        return None
    stated_key = _origin_key(stated)
    if stated_key is not None:
        expected_key = _origin_key(request.host_url)
        if (stated_key == expected_key
                # TLS terminated before the trusted proxy hop
                or (stated_key[0] == "https" and expected_key == ("http", stated_key[1]))
                or any(stated_key == _origin_key(extra) for extra in _EXTRA_TRUSTED_ORIGINS)):
            return None
    log.warning("Rejected cross-site %s %.128s (stated origin %.128r, expected %.128r). "
                "Check TRUSTED_PROXY_COUNT, or set CWA_TRUSTED_ORIGINS if your proxy rewrites Host.",
                request.method, request.path, stated, request.host_url)
    return api_error("cross_site_request", "Cross-site request rejected", 403)


@api_v1.before_request
def _require_library():
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return None
    if not config.db_configured:
        return api_error("library_not_configured", "The Calibre library is not configured", 503)
    return None


@api_v1.after_request
def _private_responses(response):
    # Every answer depends on who is asking; never let a shared cache keep one.
    response.headers.setdefault("Cache-Control", "private, no-store")
    response.vary.add("Cookie")
    return response


@api_v1.errorhandler(HTTPException)
def _handle_http_exception(exc):
    return api_error(exc.name.lower().replace(" ", "_"), exc.description, exc.code)


@api_v1.errorhandler(Exception)
def _handle_exception(exc):
    log.error("Unhandled exception in api_v1: %s", traceback.format_exc())
    return api_error("internal_server_error", "An unexpected error occurred", 500)


@api_v1.route("/health")
def health():
    return jsonify({"status": "ok", "api": "v1"})


@api_v1.route("/<path:_unknown>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def not_found(_unknown):
    # Without this, an unknown /api/v1 path falls through to the classic UI's
    # catch-all routes (e.g. /<data>/<sort_param>) and answers with HTML.
    return api_error("not_found", "No such API endpoint", 404)


# Route modules attach their views to api_v1 on import.
from . import auth     # noqa: E402,F401
from . import books    # noqa: E402,F401
from . import browse   # noqa: E402,F401
from . import search   # noqa: E402,F401
from . import shelves  # noqa: E402,F401
