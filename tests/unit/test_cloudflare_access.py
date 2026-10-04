# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Cloudflare Access token check in front of reverse-proxy header login."""

import base64
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from cps import cloudflare_access, config, usermanagement

pytestmark = pytest.mark.unit

TEAM = "https://example.cloudflareaccess.com"
AUD = "0123456789abcdef"
EMAIL = "reader@example.com"

REAL_JWK_CLIENT = cloudflare_access._jwk_client

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = PRIVATE.public_key()
OTHER_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _claims(**overrides):
    now = int(time.time())
    claims = {"aud": [AUD], "iss": TEAM, "email": EMAIL, "iat": now, "nbf": now, "exp": now + 600}
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _token(private=PRIVATE, **overrides):
    return jwt.encode(_claims(**overrides), private, algorithm="RS256", headers={"kid": "k1"})


def _req(token=None):
    return SimpleNamespace(headers={} if token is None else {cloudflare_access.ACCESS_JWT_HEADER: token})


def _config(team=TEAM, aud=AUD):
    return SimpleNamespace(config_reverse_proxy_access_team_domain=team, config_reverse_proxy_access_aud=aud)


def _permitted(token, header=EMAIL, config=None):
    return cloudflare_access.header_login_permitted(_req(token), header, config or _config())


@pytest.fixture(autouse=True)
def fresh_state():
    cloudflare_access._fetch_failed_at.clear()
    yield
    cloudflare_access._fetch_failed_at.clear()


@pytest.fixture(autouse=True)
def signing_key():
    """Serve PUBLIC as the signing key instead of fetching Cloudflare's certs."""
    client = mock.Mock()
    client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=PUBLIC)
    with mock.patch.object(cloudflare_access, "_jwk_client", return_value=client):
        yield client


def test_unconfigured_keeps_trusting_the_header():
    assert _permitted(None, config=_config(team=None, aud=None))


@pytest.mark.parametrize("team, aud", [(TEAM, None), (None, AUD), (TEAM, "  "), ("", AUD)])
def test_half_configured_refuses(team, aud):
    assert not _permitted(_token(), config=_config(team, aud))


def test_valid_token_matching_the_header_is_accepted():
    assert _permitted(_token())


def test_header_match_ignores_case():
    assert _permitted(_token(), header="Reader@Example.COM")


def test_header_naming_someone_else_is_refused():
    assert not _permitted(_token(), header="admin@example.com")


def test_missing_token_is_refused():
    assert not _permitted(None)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(aud=["some-other-app"]), id="wrong-audience"),
        pytest.param(lambda: _token(iss="https://evil.cloudflareaccess.com"), id="wrong-issuer"),
        pytest.param(lambda: _token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: _token(private=OTHER_PRIVATE), id="signed-by-another-key"),
        pytest.param(lambda: _token(exp=None), id="no-exp"),
        pytest.param(lambda: _token(email=None), id="no-email"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
def test_bad_tokens_are_refused(token):
    assert not _permitted(token())


def test_hs256_signed_with_the_public_key_is_refused():
    """Algorithm confusion: an HS256 token keyed with the public key must not verify."""
    pem = PUBLIC.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    payload = b64(json.dumps(_claims()).encode())
    signature = b64(hmac.new(pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    assert not _permitted(f"{header}.{payload}.{signature}")


def test_key_fetch_failure_is_refused(signing_key):
    signing_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("down")
    assert not _permitted(_token())


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.cloudflareaccess.com", TEAM),
        ("https://example.cloudflareaccess.com/", TEAM),
        ("  https://example.cloudflareaccess.com  ", TEAM),
        ("", ""),
        (None, ""),
    ],
)
def test_team_domain_is_normalized(raw, expected):
    assert cloudflare_access.normalize_team_domain(raw) == expected


def test_jwk_client_is_built_once_per_team_from_the_certs_url():
    with mock.patch.object(cloudflare_access.jwt, "PyJWKClient") as client_cls, mock.patch.dict(
        cloudflare_access._clients, clear=True
    ):
        first = REAL_JWK_CLIENT(TEAM)
        second = REAL_JWK_CLIENT(TEAM)
    client_cls.assert_called_once()
    assert client_cls.call_args.args[0] == TEAM + "/cdn-cgi/access/certs"
    assert first is second


def test_reverse_proxy_login_stops_before_the_user_lookup_when_refused():
    """The check sits in load_user_from_reverse_proxy_header, ahead of any DB query."""
    req = SimpleNamespace(headers={"Cf-Access-Authenticated-User-Email": EMAIL})
    with mock.patch.object(config, "config_reverse_proxy_login_header_name", "Cf-Access-Authenticated-User-Email", create=True), \
            mock.patch.object(config, "config_reverse_proxy_access_team_domain", TEAM, create=True), \
            mock.patch.object(config, "config_reverse_proxy_access_aud", AUD, create=True), \
            mock.patch.object(usermanagement.ub, "session") as session:
        assert usermanagement.load_user_from_reverse_proxy_header(req) is None
    session.query.assert_not_called()


def test_small_clock_skew_is_accepted():
    """A token issued a couple of seconds 'in the future' by Cloudflare's clock still works."""
    now = int(time.time())
    assert _permitted(_token(iat=now + 5, nbf=now + 5))


def test_skew_beyond_the_leeway_is_refused():
    now = int(time.time())
    assert not _permitted(_token(iat=now + 600, nbf=now + 600))


def test_team_domain_check_passes_when_keys_load():
    with mock.patch.object(cloudflare_access.jwt, "PyJWKClient") as client_cls:
        client_cls.return_value.get_signing_keys.return_value = [object()]
        assert cloudflare_access.team_domain_problem("example.cloudflareaccess.com") is None
    assert client_cls.call_args.args[0] == TEAM + "/cdn-cgi/access/certs"


@pytest.mark.parametrize("error", [
    jwt.PyJWKClientConnectionError("Fail to fetch data from the url, err: Name or service not known"),
    jwt.PyJWKClientError("The JWKS endpoint did not contain any signing keys"),
])
def test_team_domain_check_reports_why_keys_did_not_load(error):
    with mock.patch.object(cloudflare_access.jwt, "PyJWKClient") as client_cls:
        client_cls.return_value.get_signing_keys.side_effect = error
        assert cloudflare_access.team_domain_problem(TEAM) == str(error)


def test_team_domain_check_skips_an_empty_domain():
    with mock.patch.object(cloudflare_access.jwt, "PyJWKClient") as client_cls:
        assert cloudflare_access.team_domain_problem("  ") is None
    client_cls.assert_not_called()


# --- saving the settings -----------------------------------------------------
# A refused save does not roll back values already set on config, so the Access
# fields are validated before they're applied. These check that a refusal leaves
# the live settings exactly as they were.


@pytest.fixture
def admin_save():
    from cps import admin as cps_admin
    with mock.patch.object(config, "config_reverse_proxy_access_team_domain", "", create=True), \
            mock.patch.object(config, "config_reverse_proxy_access_aud", "", create=True), \
            mock.patch.object(cps_admin, "_", lambda s, **kw: s % kw if kw else s), \
            mock.patch.object(cloudflare_access, "team_domain_problem", return_value=None) as problem:
        yield cps_admin, problem


def _live():
    return config.config_reverse_proxy_access_team_domain, config.config_reverse_proxy_access_aud


def test_save_with_only_one_access_field_is_refused_and_changes_nothing(admin_save):
    cps_admin, problem = admin_save
    error = cps_admin._cloudflare_access_error({"config_reverse_proxy_access_team_domain": TEAM,
                                                "config_reverse_proxy_access_aud": ""})
    assert "both a team domain and an AUD tag" in error
    assert _live() == ("", "")
    problem.assert_not_called()


def test_save_with_an_unreachable_team_domain_is_refused_and_changes_nothing(admin_save):
    cps_admin, problem = admin_save
    problem.return_value = "Fail to fetch data from the url"
    error = cps_admin._cloudflare_access_error({"config_reverse_proxy_access_team_domain": TEAM,
                                                "config_reverse_proxy_access_aud": AUD})
    assert "Fail to fetch data from the url" in error
    assert _live() == ("", "")


def test_save_with_a_working_team_domain_is_accepted(admin_save):
    cps_admin, problem = admin_save
    assert cps_admin._cloudflare_access_error({"config_reverse_proxy_access_team_domain": TEAM,
                                               "config_reverse_proxy_access_aud": AUD}) is None
    problem.assert_called_once_with(TEAM)


def test_unchanged_team_domain_is_not_fetched_again(admin_save):
    cps_admin, problem = admin_save
    config.config_reverse_proxy_access_team_domain = TEAM
    config.config_reverse_proxy_access_aud = AUD
    assert cps_admin._cloudflare_access_error({"config_reverse_proxy_access_team_domain": TEAM,
                                               "config_reverse_proxy_access_aud": AUD}) is None
    problem.assert_not_called()


def test_clearing_both_fields_is_accepted(admin_save):
    cps_admin, problem = admin_save
    assert cps_admin._cloudflare_access_error({"config_reverse_proxy_access_team_domain": "",
                                               "config_reverse_proxy_access_aud": ""}) is None


# --- real PyJWKClient against a local certs endpoint -------------------------
# These don't mock the key lookup, so they cover what PyJWT does with the response.

@pytest.fixture
def certs_server():
    """Serve whatever ``server.body`` holds at any path; ``server.hits`` counts requests."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.hits += 1
            body = self.server.body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.hits = 0
    server.body = ""
    server.url = "http://127.0.0.1:%d" % server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def _jwks(public, kid):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return json.dumps({"keys": [jwk]})


@pytest.fixture
def real_client():
    with mock.patch.object(cloudflare_access, "_jwk_client", REAL_JWK_CLIENT), \
            mock.patch.dict(cloudflare_access._clients, clear=True):
        yield


def test_non_json_certs_response_is_reported_on_save(certs_server):
    certs_server.body = "<html>not json</html>"
    problem = cloudflare_access.team_domain_problem(certs_server.url)
    assert problem and "JSON" in problem


def test_non_json_certs_response_refuses_the_login_without_raising(certs_server, real_client):
    certs_server.body = "<html>not json</html>"
    team = certs_server.url
    assert not cloudflare_access.header_login_permitted(_req(_token(iss=team)), EMAIL, _config(team=team))


def test_failed_key_fetch_is_not_retried_straight_away(signing_key):
    signing_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("down")
    assert not _permitted(_token())
    assert not _permitted(_token())
    assert signing_key.get_signing_key_from_jwt.call_count == 1


def test_failed_key_fetch_is_retried_after_the_cooldown(signing_key):
    signing_key.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("down")
    assert not _permitted(_token())
    later = time.monotonic() + cloudflare_access.FETCH_FAILURE_COOLDOWN_SECONDS + 1
    with mock.patch.object(cloudflare_access.time, "monotonic", return_value=later):
        signing_key.get_signing_key_from_jwt.side_effect = None
        signing_key.get_signing_key_from_jwt.return_value = SimpleNamespace(key=PUBLIC)
        assert _permitted(_token())


def test_bad_token_does_not_start_a_cooldown(signing_key):
    assert not _permitted("not-a-jwt")
    assert _permitted(_token())


def test_a_key_dropped_from_the_certs_stops_being_trusted_after_the_cache_lifetime(certs_server, real_client):
    team = certs_server.url
    certs_server.body = _jwks(PUBLIC, "k1")
    config = _config(team=team)
    token = _token(iss=team)
    with mock.patch.object(cloudflare_access, "KEY_CACHE_SECONDS", 0.2):
        assert cloudflare_access.header_login_permitted(_req(token), EMAIL, config)
        certs_server.body = _jwks(OTHER_PRIVATE.public_key(), "k2")
        time.sleep(0.4)
        assert not cloudflare_access.header_login_permitted(_req(token), EMAIL, config)
