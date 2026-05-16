# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork issue #121 reopen — pins the load-bearing
invariants behind the OPDS anon/auth multiplex.

@droM4X reopened #121 on 2026-05-11 with two concerns:

1. ``If valid credentials are provided, show all content available to
   the authenticated user`` — claimed unfixed in v4.0.46.

2. ``In anonymous browsing mode strings are still shown in English`` —
   asked for a ``?lang=xx`` URL override.

Both halves of the reopen were addressed (see ``notes/2026-05-OPDS-DEEP-FIX-RETRO.md``
waves 1 + 2 for the lang work landed in v4.0.56/57; the auth multiplex
was already correct in v4.0.46, just not behaviourally pinned). This
file closes the gap on (1) — multiple load-bearing invariants in the
auth chain were untested at the source level, and a silent refactor of
any of them would re-introduce exactly the symptom @droM4X reported.

The 6-quadrant verification matrix this file pins:

| anon | creds  | result                            |
|------|--------|-----------------------------------|
| on   | none   | 200, Guest catalogue              |
| on   | bad    | 200, Guest catalogue (fallback)   |
| on   | valid  | 200, USER catalogue (USER locale) |
| off  | none   | 401                               |
| off  | bad    | 401                               |
| off  | valid  | 200, USER catalogue (USER locale) |

Live-verified against cwn-local under image
``calibre-web-nextgen:local`` (built off main @ 6b71e258) with admin /
Guest / cwng84test users — see ``notes/121-reopen-VERIFICATION.md`` for
the curl evidence. These tests source-pin the invariants that produce
that matrix so a future refactor can't silently regress without going
red.
"""

import inspect

import pytest


@pytest.mark.unit
class TestFlaskHttpAuthUserBridge:
    """The load-bearing invariant: ``cps.cw_login.utils._get_user()``
    must consult ``g.flask_httpauth_user`` BEFORE Flask-Login's session
    or cookie loader. Without this, OPDS requests authenticated via
    HTTP Basic auth would surface as Anonymous/Guest to every consumer
    of ``current_user`` — including ``CalibreDB.common_filters()`` —
    and valid credentials would silently render Guest content.

    The bridge was the missing piece for @droM4X's reopen concern (1):
    sidebar visibility worked because the OPDS routes pass
    ``auth.current_user()`` (flask_httpauth) into
    ``get_opds_root_entries``, but the actual book filtering goes
    through ``common_filters`` which reads ``current_user`` (flask-login).
    Only the bridge ties them together.
    """

    def test_get_user_checks_flask_httpauth_user_first(self):
        from cps.cw_login import utils
        src = inspect.getsource(utils._get_user)
        assert "flask_httpauth_user" in src, (
            "cps.cw_login.utils._get_user must consult g.flask_httpauth_user "
            "so HTTP-Basic-authenticated requests (OPDS, KOReader sync, app "
            "passwords) surface as the right user to current_user — without "
            "this, valid OPDS credentials silently see Guest content "
            "(fork issue #121, droM4X reopen)"
        )
        lines = src.splitlines()
        idx_httpauth = next(
            (i for i, ln in enumerate(lines) if "flask_httpauth_user" in ln),
            -1,
        )
        idx_load_user = next(
            (i for i, ln in enumerate(lines) if "_load_user" in ln),
            -1,
        )
        assert idx_httpauth != -1, "flask_httpauth_user check missing"
        assert idx_load_user != -1, "_load_user call missing"
        assert idx_httpauth < idx_load_user, (
            "_get_user must check g.flask_httpauth_user BEFORE falling "
            "through to Flask-Login's session/cookie load. Reordering "
            "would cause OPDS requests to always resolve to Anonymous "
            "regardless of Basic auth state (fork issue #121, droM4X "
            "reopen scenario)"
        )

    def test_get_user_returns_httpauth_user_when_set(self, mocker):
        """Behavioral: with ``g.flask_httpauth_user`` set, _get_user
        returns that value, not the Flask-Login-resolved one."""
        from cps.cw_login import utils

        sentinel_user = object()

        mocker.patch.object(utils, "has_request_context", return_value=True)
        fake_g = mocker.MagicMock()
        fake_g.__contains__ = lambda self, k: k == "flask_httpauth_user"
        fake_g.flask_httpauth_user = sentinel_user
        mocker.patch.object(utils, "g", fake_g)
        fake_app = mocker.MagicMock()
        fake_app.login_manager._load_user.side_effect = AssertionError(
            "should not be called when flask_httpauth_user is set"
        )
        mocker.patch.object(utils, "current_app", fake_app)

        result = utils._get_user()
        assert result is sentinel_user

    def test_get_user_falls_through_to_login_manager_when_no_httpauth_user(self, mocker):
        """Behavioral: with NO ``g.flask_httpauth_user`` and no
        cached login user, _get_user must trigger
        ``login_manager._load_user()`` and return ``g._login_user``.
        This is the fallback path that anonymous OPDS requests take.
        """
        from cps.cw_login import utils

        sentinel_anon = object()
        mocker.patch.object(utils, "has_request_context", return_value=True)
        fake_g = mocker.MagicMock()
        state = {"keys": set()}
        fake_g.__contains__ = lambda self, k: k in state["keys"]
        fake_g._login_user = sentinel_anon
        mocker.patch.object(utils, "g", fake_g)
        fake_app = mocker.MagicMock()

        def _populate_login_user():
            state["keys"].add("_login_user")
        fake_app.login_manager._load_user.side_effect = _populate_login_user
        mocker.patch.object(utils, "current_app", fake_app)

        result = utils._get_user()
        fake_app.login_manager._load_user.assert_called_once()
        assert result is sentinel_anon


@pytest.mark.unit
class TestAnonymousUserMirrorsGuestRow:
    """The second load-bearing invariant: ``ub.Anonymous`` must mirror
    EVERY field of the Guest DB row that ``CalibreDB.common_filters``
    and the OPDS visibility callbacks consume. If any field stops being
    propagated, anonymous OPDS requests start surfacing the WRONG
    restrictions — typically admin's, or none at all — and Guest
    content leaks or hides incorrectly.

    @droM4X's setup has Guest with restricted ``denied_tags`` to gate
    adult content from unauthenticated visitors. The 6-quadrant matrix
    only behaves correctly if Anonymous propagates that field.
    """

    REQUIRED_FIELDS = (
        # Fields read by CalibreDB.common_filters
        "denied_tags",
        "allowed_tags",
        "denied_column_value",
        "allowed_column_value",
        "default_language",
        # Fields read by OPDS visibility callbacks + sidebar checks
        "sidebar_view",
        "locale",
        # Fields read by OPDS shelf-exposure filter (#179 / v4.0.56)
        "kobo_only_shelves_sync",
        "opds_only_shelves_sync",
        "view_settings",
        # Identity fields read by per-user-state queries
        "id",
        "name",
        "role",
    )

    def test_anonymous_loadsettings_propagates_required_fields(self):
        """Source-pin: every field common_filters / OPDS callbacks
        consume must be copied from the Guest DB row in
        ``Anonymous.loadSettings``. If a future contributor adds a new
        per-user restriction column to ``User`` but forgets to mirror
        it on ``Anonymous``, the behaviour for anonymous OPDS requests
        silently diverges from what the admin configured for Guest.
        """
        from cps import ub
        src = inspect.getsource(ub.Anonymous.loadSettings)
        for field in self.REQUIRED_FIELDS:
            assert f"self.{field}" in src, (
                f"Anonymous.loadSettings is missing self.{field} = ... — "
                f"OPDS anonymous requests will not pick up the Guest row's "
                f"{field} field, breaking the per-user restriction model "
                f"(fork issue #121, droM4X reopen verification matrix)"
            )

    def test_anonymous_class_has_field_attributes(self):
        """Behavioral-adjacent: every required field must be declared
        as an attribute on the Anonymous class (typically initialised
        to None in __init__ before loadSettings populates from DB)."""
        from cps import ub
        init_src = inspect.getsource(ub.Anonymous.__init__)
        for field in self.REQUIRED_FIELDS:
            attr_set_in_init = f"self.{field}" in init_src
            load_src = inspect.getsource(ub.Anonymous.loadSettings)
            attr_set_in_load = f"self.{field}" in load_src
            assert attr_set_in_init or attr_set_in_load, (
                f"Anonymous class never sets self.{field} — neither in "
                f"__init__ nor loadSettings. common_filters or an OPDS "
                f"visibility callback that reads this will AttributeError "
                f"on anonymous requests"
            )

    def test_anonymous_is_anonymous_true_is_authenticated_false(self):
        """Behavioral: ``is_anonymous`` returns True, ``is_authenticated``
        returns False. The OPDS root entries gate the ``read`` /
        ``unread`` rows on ``not user.is_anonymous``; if these flip,
        Guest sees per-user read-status entries that have no meaning."""
        from cps.cw_login.mixins import AnonymousUserMixin
        from cps import ub
        assert AnonymousUserMixin().is_anonymous is True
        assert AnonymousUserMixin().is_authenticated is False
        anon_src = inspect.getsource(ub.Anonymous)
        assert "is_anonymous" in anon_src
        assert "is_authenticated" in anon_src


@pytest.mark.unit
class TestRequiresBasicAuthMultiplexFlow:
    """Source-pin the four mutually-exclusive branches of
    ``requires_basic_auth_if_no_ano``. Each branch handles one cell of
    the 6-quadrant matrix (the 6th — anon-off + valid creds — falls
    through the same successful-auth path as anon-on + valid creds).
    """

    def test_decorator_has_no_creds_anon_on_guest_substitution(self):
        """Quadrant 1 (anon-on + no creds): substitute Guest creds so
        ``auth.authenticate`` resolves to the Guest user.
        """
        from cps import usermanagement
        src = inspect.getsource(usermanagement.requires_basic_auth_if_no_ano)
        assert "config.config_anonbrowse == 1 and not authorisation" in src, (
            "Decorator must substitute Guest credentials when both "
            "(a) anonymous browsing is enabled AND (b) no Authorization "
            "header was sent. Without this, anon-enabled OPDS deployments "
            "return 401 to plain GET requests."
        )

    def test_decorator_has_failed_auth_anon_on_guest_fallback(self):
        """Quadrant 3 (anon-on + bad creds): after the auth attempt
        fails, fall through to Guest. This is the v4.0.46 fix that
        addressed @droM4X's original complaint."""
        from cps import usermanagement
        src = inspect.getsource(usermanagement.requires_basic_auth_if_no_ano)
        assert "user in (False, None) and config.config_anonbrowse == 1" in src, (
            "Decorator must fall back to Guest when (a) auth attempt "
            "returned None/False AND (b) anonymous browsing is on. This "
            "is the issue #121 'stale credentials still get Guest catalog' "
            "fix from v4.0.46."
        )

    def test_decorator_returns_401_when_anon_off_and_no_user(self):
        """Quadrant 4+5 (anon-off + no/bad creds): no Guest fallback,
        emit 401. The status path is reached only when ``user in
        (False, None)`` and the anon-fallback branch above did not
        rescue it (which means anon=0)."""
        from cps import usermanagement
        src = inspect.getsource(usermanagement.requires_basic_auth_if_no_ano)
        assert "status = 401" in src, "401 branch removed from decorator"
        idx_fallback = src.find("user in (False, None) and config.config_anonbrowse == 1")
        idx_401 = src.find("status = 401")
        assert idx_fallback != -1 and idx_401 != -1
        assert idx_fallback < idx_401, (
            "Anon-fallback to Guest must run BEFORE the 401 branch — "
            "reordering would 401 anon-enabled deployments before they "
            "got their Guest rescue."
        )

    def test_decorator_pins_authed_user_into_flask_httpauth_g(self):
        """After successful auth (any quadrant that lands a user), the
        user must be stored in ``g.flask_httpauth_user`` so the
        ``_get_user`` bridge can surface it as ``current_user``."""
        from cps import usermanagement
        src = inspect.getsource(usermanagement.requires_basic_auth_if_no_ano)
        assert "g.flask_httpauth_user" in src, (
            "Decorator must set g.flask_httpauth_user on every successful "
            "auth path — without this assignment the cw_login bridge "
            "has nothing to forward, and common_filters surfaces "
            "Anonymous restrictions to authenticated OPDS requests."
        )

    def test_decorator_runs_reverse_proxy_before_basic_auth(self):
        """Decorator order: reverse-proxy header lookup happens FIRST,
        but only when no Basic auth was sent. Basic auth always wins
        when both are present (otherwise a misconfigured reverse-proxy
        header could spoof identity)."""
        from cps import usermanagement
        src = inspect.getsource(usermanagement.requires_basic_auth_if_no_ano)
        idx_rp = src.find("config_allow_reverse_proxy_header_login")
        idx_basic = src.find("auth.authenticate(authorisation")
        assert idx_rp != -1 and idx_basic != -1
        assert idx_rp < idx_basic, (
            "Reverse-proxy header check should be evaluated first "
            "(when no Basic auth sent), then Basic auth as primary."
        )


@pytest.mark.unit
class TestVerifyPasswordGuestShortCircuit:
    """When a client sends ``Authorization: Basic Guest:anything`` and
    anonymous browsing is on, ``verify_password`` returns Guest without
    running the password hash check. This is what makes the Guest
    fallback in the decorator round-trip — the substituted credentials
    are valid by design.
    """

    def test_guest_with_anon_returns_user_short_circuit(self):
        from cps import usermanagement
        src = inspect.getsource(usermanagement.verify_password)
        assert "user.name.lower() == \"guest\"" in src, (
            "verify_password must special-case Guest when anon is on "
            "(no password check); otherwise the substituted Guest "
            "credentials in the decorator never validate."
        )
        idx_guest = src.find("user.name.lower() == \"guest\"")
        idx_anon = src.find("config.config_anonbrowse == 1", idx_guest)
        assert idx_anon != -1 and idx_anon - idx_guest < 200, (
            "Guest short-circuit must be gated on config_anonbrowse == 1 "
            "— without the gate, anon-off deployments would let any "
            "client log in as Guest with no password."
        )

    def test_empty_username_returns_none_without_db_or_log(self):
        """The pre-fix behaviour of @droM4X's original complaint
        (issue #121 bug 1) — already pinned in
        ``test_opds_bugs_121.py``; re-pinned here so the multiplex
        suite stands on its own and a future refactor that drops one
        copy can be detected by the other."""
        from cps import usermanagement
        src = inspect.getsource(usermanagement.verify_password)
        assert "if not username:\n        return None" in src


@pytest.mark.unit
class TestSixQuadrantBehavioralMatrix:
    """Behavioral assertions over a minimal Flask app with
    ``requires_basic_auth_if_no_ano`` wired up. We mock the
    ``auth.authenticate`` callsite so we can drive each quadrant
    without standing up a full DB — the goal is to pin the decorator's
    branching logic end-to-end at the HTTP-response level, mirroring
    what cwn-local verified.
    """

    @pytest.fixture
    def app_with_decorator(self, mocker):
        """A Flask app with a single ``/opds/`` route guarded by
        ``requires_basic_auth_if_no_ano``. The auth verifier and
        config knob are mockable per-test."""
        from flask import Flask, jsonify, g

        from cps import usermanagement

        app = Flask(__name__)
        app.config["TESTING"] = True

        def _error_cb(status=401):
            from flask import Response
            return Response("Unauthorized", status=status)

        mocker.patch.object(usermanagement.auth, "auth_error_callback", _error_cb)

        @app.route("/opds/")
        @usermanagement.requires_basic_auth_if_no_ano
        def feed_index():
            user = g.get("flask_httpauth_user")
            return jsonify({
                "user_name": getattr(user, "name", None),
                "is_anon": getattr(user, "is_anonymous", None),
            })

        return app, usermanagement

    def _make_user_stub(self, name, is_anonymous=False):
        class _U:
            pass
        u = _U()
        u.name = name
        u.is_anonymous = is_anonymous
        return u

    def test_q1_anon_on_no_creds_returns_guest(self, app_with_decorator, mocker):
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 1, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        guest = self._make_user_stub("Guest", is_anonymous=True)
        mocker.patch.object(um.auth, "authenticate", return_value=guest)

        client = app.test_client()
        resp = client.get("/opds/")
        assert resp.status_code == 200, "Q1: anon-on + no creds must serve Guest, not 401"
        assert resp.get_json()["user_name"] == "Guest"

    def test_q2_anon_on_valid_creds_returns_user(self, app_with_decorator, mocker):
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 1, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        user = self._make_user_stub("cwng84test", is_anonymous=False)
        mocker.patch.object(um.auth, "authenticate", return_value=user)

        client = app.test_client()
        resp = client.get("/opds/", headers={
            "Authorization": "Basic Y3duZzg0dGVzdDpjd25nLXRlc3QtODQ=",
        })
        assert resp.status_code == 200, "Q2: anon-on + valid creds must serve user catalog"
        body = resp.get_json()
        assert body["user_name"] == "cwng84test", (
            "Q2 regression: valid OPDS credentials surfaced as %r instead "
            "of the authenticated user — droM4X reopen scenario"
            % body["user_name"]
        )

    def test_q3_anon_on_bad_creds_falls_back_to_guest(self, app_with_decorator, mocker):
        """The v4.0.46 fix: stale/invalid creds + anon=1 → Guest, not 401."""
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 1, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        guest = self._make_user_stub("Guest", is_anonymous=True)
        mocker.patch.object(
            um.auth,
            "authenticate",
            side_effect=[None, guest],
        )

        client = app.test_client()
        resp = client.get("/opds/", headers={
            "Authorization": "Basic Y3duZzg0dGVzdDpXUk9OR1BBU1M=",
        })
        assert resp.status_code == 200, "Q3: anon-on + bad creds must fall back to Guest"
        assert resp.get_json()["user_name"] == "Guest"

    def test_q4_anon_off_no_creds_returns_401(self, app_with_decorator, mocker):
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 0, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        mocker.patch.object(um.auth, "authenticate", return_value=None)

        client = app.test_client()
        resp = client.get("/opds/")
        assert resp.status_code == 401, "Q4: anon-off + no creds must 401"

    def test_q5_anon_off_bad_creds_returns_401(self, app_with_decorator, mocker):
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 0, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        mocker.patch.object(um.auth, "authenticate", return_value=None)

        client = app.test_client()
        resp = client.get("/opds/", headers={
            "Authorization": "Basic Y3duZzg0dGVzdDpXUk9OR1BBU1M=",
        })
        assert resp.status_code == 401, "Q5: anon-off + bad creds must 401"

    def test_q6_anon_off_valid_creds_returns_user(self, app_with_decorator, mocker):
        app, um = app_with_decorator
        mocker.patch.object(um.config, "config_anonbrowse", 0, create=True)
        mocker.patch.object(um.config, "config_allow_reverse_proxy_header_login", 0, create=True)

        user = self._make_user_stub("cwng84test", is_anonymous=False)
        mocker.patch.object(um.auth, "authenticate", return_value=user)

        client = app.test_client()
        resp = client.get("/opds/", headers={
            "Authorization": "Basic Y3duZzg0dGVzdDpjd25nLXRlc3QtODQ=",
        })
        assert resp.status_code == 200
        assert resp.get_json()["user_name"] == "cwng84test"
