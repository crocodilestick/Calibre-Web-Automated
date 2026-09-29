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
import time
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
