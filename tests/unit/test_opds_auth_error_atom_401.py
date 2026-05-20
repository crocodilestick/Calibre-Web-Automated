# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for the v4.0.92 #224 follow-up.

Background. Fork #224 (@droM4X) asked for consistent OPDS error
responses: every status from a ``/opds/*`` route must be Atom XML so
readers (Readest, KOReader, generic Atom clients) can parse the body.
v4.0.92 shipped four ``@opds.errorhandler`` callbacks for 401/403/404/
500. Source-pin tests verified the handlers were *registered*; E2E
against the deployed image revealed the 401 path still returns HTML
"Unauthorized Access" with ``WWW-Authenticate: Basic realm="Authentication
Required"``.

Root cause. ``requires_basic_auth_if_no_ano`` in ``cps/usermanagement.py``
calls ``auth.auth_error_callback(status)`` when the credentials check
fails. The default Flask-HTTPAuth callback returns a fully-formed
HTML ``Response`` — Flask's blueprint errorhandler pipeline never fires
because no ``HTTPException`` is raised. ``@opds.errorhandler(401)`` only
catches explicit ``abort(401)`` calls from inside route handlers.

Fix. Register a custom ``@auth.error_handler`` on the global
``HTTPBasicAuth`` instance that branches on ``request.path`` — Atom XML
+ ``WWW-Authenticate: Basic realm="OPDS"`` for ``/opds/*``, default
HTML for every other consumer (kosync, app passwords).

These tests pin the post-fix behavior end-to-end through a Flask
test_client. They will fail against pre-fix builds because the default
Flask-HTTPAuth callback fires.
"""

import pytest


def _build_app_with_real_auth_callback(mocker):
    """Minimal Flask app that goes through the real
    ``auth.auth_error_callback`` — explicitly NOT mocking it (unlike
    ``test_opds_auth_multiplex_121_reopen.py`` which patches the
    callback to a simple ``Response("Unauthorized", 401)``).

    Returns ``(app, usermanagement_module)``.
    """
    from flask import Flask

    from cps import usermanagement

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/opds/")
    @usermanagement.requires_basic_auth_if_no_ano
    def opds_feed_index():
        return "should not reach"

    @app.route("/opds/books")
    @usermanagement.requires_basic_auth_if_no_ano
    def opds_books_feed():
        return "should not reach"

    @app.route("/some-other-protected")
    @usermanagement.requires_basic_auth_if_no_ano
    def non_opds_endpoint():
        return "should not reach"

    mocker.patch.object(usermanagement.config, "config_anonbrowse", 0, create=True)
    mocker.patch.object(
        usermanagement.config,
        "config_allow_reverse_proxy_header_login",
        0,
        create=True,
    )
    mocker.patch.object(usermanagement.auth, "authenticate", return_value=None)

    return app, usermanagement


@pytest.mark.unit
class TestOpds401ReturnsAtom:
    """The shipped behavior: ``GET /opds/`` with no credentials and anon
    disabled must return Atom XML + ``WWW-Authenticate: Basic realm="OPDS"``.

    Pre-fix: Flask-HTTPAuth default returns ``Content-Type: text/html;
    charset=utf-8`` with body ``"Unauthorized Access\\n"``. OPDS readers
    silently fail or display "broken feed" — exactly the user-visible
    symptom @droM4X opened #224 about.
    """

    def test_opds_root_401_content_type_is_atom(self, mocker):
        app, _ = _build_app_with_real_auth_callback(mocker)

        client = app.test_client()
        resp = client.get("/opds/")

        assert resp.status_code == 401, (
            "Sanity: anon-off + no credentials must produce a 401, not "
            "redirect to login or 200."
        )
        ctype = resp.headers.get("Content-Type", "")
        assert ctype.startswith("application/atom+xml"), (
            f"v4.0.92 follow-up: /opds/ 401 must return Atom XML so "
            f"readers (Readest/KOReader) can parse the body. Got "
            f"Content-Type={ctype!r}, body starts with {resp.data[:80]!r}. "
            f"The default Flask-HTTPAuth `auth_error_callback` returns "
            f"HTML; the fork must override it via `@auth.error_handler` "
            f"and branch on `request.path.startswith('/opds')`."
        )

    def test_opds_root_401_www_authenticate_realm_is_opds(self, mocker):
        app, _ = _build_app_with_real_auth_callback(mocker)

        client = app.test_client()
        resp = client.get("/opds/")

        www = resp.headers.get("WWW-Authenticate", "")
        assert 'realm="OPDS"' in www, (
            f"OPDS 401 must advertise `WWW-Authenticate: Basic realm=\"OPDS\"` "
            f"so reader apps know which credential prompt to show the "
            f"user. Got WWW-Authenticate={www!r}. The default Flask-"
            f"HTTPAuth realm is `Authentication Required` — that's "
            f"generic Basic auth, not the OPDS-specific prompt readers "
            f"expect."
        )

    def test_opds_root_401_body_is_well_formed_atom_feed(self, mocker):
        import xml.etree.ElementTree as ET

        app, _ = _build_app_with_real_auth_callback(mocker)

        client = app.test_client()
        resp = client.get("/opds/")

        body = resp.data.decode("utf-8", errors="replace")
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            pytest.fail(
                f"OPDS 401 body must be a parseable Atom feed; XML parse "
                f"failed: {exc}. Body starts with {body[:200]!r}."
            )
        assert root.tag.endswith("feed"), (
            f"OPDS 401 body must be a `<feed>` element under the Atom "
            f"namespace. Parsed root tag: {root.tag!r}. Body: {body[:200]!r}."
        )

    def test_opds_subpath_401_also_atom(self, mocker):
        """The bug applies to every OPDS route, not just the index — pin
        a second path to prove the fix isn't accidentally scoped to ``/opds/``
        with a trailing slash.
        """
        app, _ = _build_app_with_real_auth_callback(mocker)

        client = app.test_client()
        resp = client.get("/opds/books")

        assert resp.status_code == 401
        ctype = resp.headers.get("Content-Type", "")
        assert ctype.startswith("application/atom+xml"), (
            f"/opds/books 401 must also return Atom XML. Got Content-Type="
            f"{ctype!r}. The fix's `request.path.startswith('/opds')` "
            f"branch must catch every OPDS subpath, not just the root."
        )
        assert 'realm="OPDS"' in resp.headers.get("WWW-Authenticate", "")


@pytest.mark.unit
class TestNonOpds401PreservesDefault:
    """The fix must NOT change the response shape for non-OPDS consumers
    of ``HTTPBasicAuth`` (kosync, app passwords endpoints, any future
    Basic-auth-gated route). Those callers send HTML-capable browsers /
    HTTP clients — Atom XML there would surprise them and break things.
    """

    def test_non_opds_401_does_not_advertise_opds_realm(self, mocker):
        app, _ = _build_app_with_real_auth_callback(mocker)

        client = app.test_client()
        resp = client.get("/some-other-protected")

        assert resp.status_code == 401
        ctype = resp.headers.get("Content-Type", "")
        assert not ctype.startswith("application/atom+xml"), (
            f"Non-OPDS 401 must NOT return Atom XML — only paths "
            f"starting with `/opds` should get the Atom shape. Got "
            f"Content-Type={ctype!r} for /some-other-protected which is "
            f"a regression for kosync clients."
        )
        www = resp.headers.get("WWW-Authenticate", "")
        assert 'realm="OPDS"' not in www, (
            f"Non-OPDS 401 must NOT advertise `realm=\"OPDS\"`. Got "
            f"WWW-Authenticate={www!r}. The path-branching logic in "
            f"`@auth.error_handler` is malformed if a /some-other- "
            f"protected request gets the OPDS realm."
        )

    def test_opds_prefix_path_is_not_a_substring_match(self, mocker):
        """``/opds-fake`` (or any path that merely starts with the
        characters ``opds`` but isn't an actual OPDS route) must NOT
        get the Atom shape. The path-branch must be an exact-equal or
        ``/opds/`` subpath check, not a substring match — otherwise a
        future route named ``/opds-experimental`` or ``/opds-stats``
        would silently flip to Atom and confuse browser clients.
        """
        from flask import Flask
        from cps import usermanagement

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/opds-fake")
        @usermanagement.requires_basic_auth_if_no_ano
        def opds_fake():
            return "should not reach"

        mocker.patch.object(usermanagement.config, "config_anonbrowse", 0, create=True)
        mocker.patch.object(
            usermanagement.config,
            "config_allow_reverse_proxy_header_login",
            0,
            create=True,
        )
        mocker.patch.object(usermanagement.auth, "authenticate", return_value=None)

        client = app.test_client()
        resp = client.get("/opds-fake")

        assert resp.status_code == 401
        ctype = resp.headers.get("Content-Type", "")
        assert not ctype.startswith("application/atom+xml"), (
            f"/opds-fake 401 must NOT be treated as an OPDS route by "
            f"the auth error handler. Got Content-Type={ctype!r}. The "
            f"path branch must require either exact match `/opds` or "
            f"prefix `/opds/`, not a bare `startswith('/opds')`."
        )
