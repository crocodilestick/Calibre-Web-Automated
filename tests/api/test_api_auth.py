# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""/api/v1 gate, error format and session auth."""

import re

import pytest

from conftest import login


@pytest.mark.unit
class TestGate:
    def test_health_is_public(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok", "api": "v1"}

    def test_protected_route_returns_json_401_not_redirect(self, client):
        resp = client.get("/api/v1/books")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "unauthorized"

    def test_unknown_route_is_json_404(self, admin_client):
        resp = admin_client.get("/api/v1/nope")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "not_found"

    def test_responses_are_private(self, client):
        resp = client.get("/api/v1/health")
        assert resp.headers["Cache-Control"] == "private, no-store"
        assert "Cookie" in resp.headers["Vary"]

    def test_cross_site_post_is_rejected(self, admin_client):
        resp = admin_client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "cross_site_request"

    def test_lookalike_origin_is_rejected(self, admin_client):
        resp = admin_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost.evil.example"})
        assert resp.status_code == 403

    def test_same_origin_post_is_allowed(self, admin_client):
        resp = admin_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost"})
        assert resp.status_code == 204


@pytest.mark.unit
class TestAuth:
    def test_login_returns_user(self, client):
        data = login(client, "admin").get_json()
        assert data["name"] == "admin"
        assert data["role"]["admin"] is True
        assert data["anonymous"] is False

    def test_me_after_login(self, client):
        login(client, "reader")
        data = client.get("/api/v1/auth/me").get_json()
        assert data["name"] == "reader"
        assert data["role"]["admin"] is False

    def test_me_when_logged_out(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_wrong_password(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "invalid_credentials"

    def test_guest_cannot_log_in(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "Guest", "password": ""})
        assert resp.status_code == 401

    def test_username_is_case_insensitive(self, client):
        assert client.post("/api/v1/auth/login",
                           json={"username": " ADMIN ", "password": "admin123"}).status_code == 200

    def test_non_string_fields_fail_cleanly(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": ["admin"], "password": 5})
        assert resp.status_code == 401

    def test_logout_ends_session(self, client):
        login(client, "admin")
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.get("/api/v1/books").status_code == 401

    def test_standard_login_can_be_disabled(self, client):
        from cps import config
        config.config_disable_standard_login = True
        try:
            resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        finally:
            config.config_disable_standard_login = False
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "standard_login_disabled"

    def test_auth_config(self, client):
        data = client.get("/api/v1/auth/config").get_json()
        assert data["login_type"] == "standard"
        assert data["standard_login"] is True
        assert data["oauth_providers"] == []


@pytest.mark.unit
class TestCsrf:
    def test_post_without_token_is_rejected(self, client, csrf_enabled):
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "bad_request"

    def test_post_with_token_from_csrf_endpoint(self, client, csrf_enabled):
        token = client.get("/api/v1/auth/csrf").get_json()["csrf_token"]
        assert re.fullmatch(r"[\w.\-]+", token)
        resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"},
                           headers={"X-CSRFToken": token})
        assert resp.status_code == 200
