# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# SPDX-License-Identifier: GPL-3.0-or-later
#
# SPA shell / fragment-switch foundation.
#
# Direct browser navigations to any non-excluded URL receive a layout-only
# "shell" (navbar + sidebar + script tags, empty body). The actual content
# is fetched client-side via partial-nav.js (wired in Step 3) with the
# X-CWA-Fragment header set, in which case render_title_template flips the
# parent template to fragment.html so only the body+js blocks come back.

import flask
from .cw_login import current_user


EXCLUDED_PATH_PREFIXES = [
    '/login',
    '/logout',
    '/register',
    '/remote/login',
    '/verify/',
    '/login/link',
    '/login/unlink',
    '/opds',
    '/kobo/',
    '/kobo_auth',
    '/ajax/',
    '/gdrive',
    '/api/v3',
    '/api/UserStorage',
    '/static/',
    # File downloads under /admin — no Content-Disposition 'download' attr in templates.
    '/admin/logdownload/', '/admin/debug',
    # JSON API + SSE stream under /cwa-library-refresh.
    '/cwa-library-refresh',
    # File downloads under /cwa- prefixes.
    '/cwa-logs/download/',
    '/cwa-convert-library/download-current-log/',
    '/cwa-epub-fixer/download-current-log/',
    '/sw.js',
    '/manifest.json',
]

# Endpoints whose first segment overlaps a list-page sort_param: only exclude
# when the second segment is numeric.
#   /read/123/epub          -> reader            (excluded)
#   /read/stored            -> books_list view   (NOT excluded)
#   /download/42/epub       -> file download     (excluded)
#   /download/stored        -> books_list view   (NOT excluded)
NUMERIC_EXCLUDED_ROOTS = ('/read', '/download')


def is_excluded_path(path: str) -> bool:
    if not path:
        return False
    for prefix in EXCLUDED_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    for root in NUMERIC_EXCLUDED_ROOTS:
        if path.startswith(root + '/'):
            tail = path[len(root) + 1:].split('/', 1)[0]
            if tail.isdigit():
                return True
    return False


def is_fragment_request() -> bool:
    try:
        return flask.request.headers.get('X-CWA-Fragment') == '1'
    except RuntimeError:
        return False


def spa_before_request():
    req = flask.request

    if req.method != 'GET':
        return None

    if is_fragment_request():
        return None

    # XHR / jQuery AJAX calls (e.g. the bookDetailsModal $.get, /ajax endpoints
    # called from page scripts) must not be shelled — they expect the real
    # endpoint response.
    if req.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return None

    # Modern browsers tell us the destination of every fetch. Only top-level
    # document navigations get the shell; images, scripts, stylesheets,
    # XHR/fetch, etc. fall through to the real route.
    sec_fetch_dest = req.headers.get('Sec-Fetch-Dest')
    if sec_fetch_dest:
        if sec_fetch_dest != 'document':
            return None
    else:
        # Older browsers / non-browser clients: require an explicit text/html
        # in Accept (not just */*) to qualify as a document request.
        accept = req.headers.get('Accept', '')
        if 'text/html' not in accept:
            return None

    if is_excluded_path(req.path):
        return None

    # Don't render the shell for unauthenticated users hitting a protected
    # route — otherwise the user sees the empty shell + loading overlay
    # while the fragment XHR follows the /login redirect, then a full nav
    # to /login swaps it out. Skipping the shell lets Flask-Login redirect
    # directly so the only thing the user sees is /login.
    try:
        authed = current_user.is_authenticated
    except Exception:
        authed = False
    allow_anon = bool(flask.g.get('allow_anonymous', False))
    if not authed and not allow_anon:
        return None

    from .render_template import render_title_template
    return render_title_template('cwa_spa_shell.html', title='', page='spa_shell')
