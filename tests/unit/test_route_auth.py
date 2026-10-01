# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Auth on CWA routes: internal-only endpoints, admin-only services, Kobo token ownership."""

import ast
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden
from werkzeug.middleware.proxy_fix import ProxyFix

import cwa_internal_auth

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "cwa_internal_token"
    monkeypatch.setenv("CWA_INTERNAL_TOKEN_FILE", str(path))
    return path


@pytest.mark.unit
class TestInternalToken:
    def test_token_is_created_once_and_private(self, token_file):
        first = cwa_internal_auth.get_internal_token()
        assert len(first) == 64
        assert cwa_internal_auth.get_internal_token() == first
        assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
        assert not list(token_file.parent.glob("*.new"))

    def test_existing_token_is_reused(self, token_file):
        token_file.write_text("abc123\n")
        assert cwa_internal_auth.get_internal_token() == "abc123"

    def test_validation(self, token_file):
        token = cwa_internal_auth.get_internal_token()
        assert cwa_internal_auth.is_valid_internal_token(token)
        assert not cwa_internal_auth.is_valid_internal_token(token[:-1] + "x")
        assert not cwa_internal_auth.is_valid_internal_token("")
        assert not cwa_internal_auth.is_valid_internal_token(None)


@pytest.fixture
def internal_client(token_file):
    from cps.internal_api import internal_only

    app = Flask(__name__)
    # Same middleware setup as cps/__init__.py with the default TRUSTED_PROXY_COUNT=1.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    @app.route("/internal", methods=["POST"])
    @internal_only
    def internal():
        return "ok"

    return app.test_client()


@pytest.mark.unit
class TestInternalOnly:
    def test_loopback_with_token_is_allowed(self, internal_client):
        resp = internal_client.post("/internal", headers=cwa_internal_auth.internal_headers(),
                                    environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 200

    def test_ipv6_loopback_with_token_is_allowed(self, internal_client):
        resp = internal_client.post("/internal", headers=cwa_internal_auth.internal_headers(),
                                    environ_base={"REMOTE_ADDR": "::ffff:127.0.0.1"})
        assert resp.status_code == 200

    def test_spoofed_forwarded_for_is_rejected(self, internal_client):
        # The old check trusted this header; ProxyFix also copies it into remote_addr.
        resp = internal_client.post("/internal", headers={"X-Forwarded-For": "127.0.0.1"},
                                    environ_base={"REMOTE_ADDR": "203.0.113.9"})
        assert resp.status_code == 403

    def test_loopback_without_token_is_rejected(self, internal_client):
        resp = internal_client.post("/internal", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 403

    def test_remote_with_valid_token_is_rejected(self, internal_client):
        resp = internal_client.post("/internal", headers=cwa_internal_auth.internal_headers(),
                                    environ_base={"REMOTE_ADDR": "203.0.113.9"})
        assert resp.status_code == 403


@pytest.mark.unit
class TestKoboTokenOwnership:
    @pytest.fixture
    def check(self, monkeypatch):
        import cps.kobo_auth as kobo_auth

        def as_user(user_id, admin=False):
            monkeypatch.setattr(kobo_auth, "current_user",
                                SimpleNamespace(id=user_id, role_admin=lambda: admin))
            return kobo_auth._require_self_or_admin
        return as_user

    def test_own_token_is_allowed(self, check):
        check(5)(5)

    def test_other_users_token_is_forbidden(self, check):
        with pytest.raises(Forbidden):
            check(5)(1)

    def test_admin_may_manage_any_token(self, check):
        check(1, admin=True)(5)

    def test_both_routes_use_the_check(self):
        tree = ast.parse((REPO / "cps/kobo_auth.py").read_text())
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("generate_auth_token", "delete_auth_token"):
            first = funcs[name].body[0]
            assert isinstance(first, ast.Expr) and first.value.func.id == "_require_self_or_admin", name


# (file, function) pairs that are intentionally reachable without these decorators. None today.
PUBLIC_ROUTES = set()
AUTH_DECORATORS = {"login_required_if_no_ano", "user_login_required", "admin_required",
                   "internal_only", "admin_or_edit_required"}


def _routes(relpath):
    tree = ast.parse((REPO / relpath).read_text())
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        names = []
        for d in node.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            names.append(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ""))
        if "route" in names:
            yield node.name, set(names)


@pytest.mark.unit
@pytest.mark.parametrize("relpath", ["cps/cwa_functions.py", "cps/duplicates.py"])
def test_every_route_has_an_auth_decorator(relpath):
    missing = [name for name, decos in _routes(relpath)
               if not decos & AUTH_DECORATORS and (relpath, name) not in PUBLIC_ROUTES]
    assert not missing, f"routes without auth in {relpath}: {missing}"


@pytest.mark.unit
def test_admin_services_require_admin():
    admin_only = {"show_convert_library_page", "show_convert_library_logs", "start_conversion",
                  "cancel_convert_library", "show_epub_fixer_page", "show_epub_fixer_logs",
                  "start_epub_fixer", "cancel_epub_fixer", "download_log", "read_log"}
    routes = dict(_routes("cps/cwa_functions.py"))
    for name in admin_only:
        assert {"login_required_if_no_ano", "admin_required"} <= routes[name], name
