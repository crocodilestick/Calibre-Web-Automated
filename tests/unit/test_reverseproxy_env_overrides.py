# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Backport of janeczku/calibre-web #3369 (@chtzvt) — env-var fallbacks
for the ReverseProxied middleware.

Background. The middleware reads `X-Script-Name`, `X-Scheme`, and
`X-Forwarded-Host` from request headers to handle path-prefix
mounting, scheme override (HTTP→HTTPS at the proxy), and host
rewriting. Several deployment scenarios can't set those headers:

- Tailscale Funnel exposes the app as-is with no header rewriting.
- Cloudflare Tunnel and similar opaque TLS terminators.
- Container orchestration where the operator can't reach the proxy
  config.

@chtzvt's PR adds `PROXY_SCRIPT_NAME`, `PROXY_SCHEME`, `PROXY_HOST`,
and `PROXY_PORT` env-var fallbacks so the same effect can be achieved
from the docker-compose / systemd environment. It also adds
`X-Forwarded-Proto` (the de-facto standard) as a recognized header
alongside `X-Scheme`.

These tests pin:

1. Header takes precedence over env var when both are set.
2. Env var is used when no header is present.
3. Neither set → no rewriting.
4. `X-Forwarded-Proto` is recognized as a scheme source.
5. `PROXY_PORT` is appended to the host when no port is in
   `HTTP_X_FORWARDED_HOST` / `PROXY_HOST`.
6. The middleware's `is_proxied` property still reports True after
   env-var-driven rewriting (so downstream code that gates on it
   behaves correctly).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
REVPROXY_PY = REPO_ROOT / "cps" / "reverseproxy.py"


def _revproxy_source() -> str:
    return REVPROXY_PY.read_text()


def test_source_imports_os_and_documents_env_vars():
    src = _revproxy_source()
    assert re.search(r"^import os$", src, re.MULTILINE), (
        "cps/reverseproxy.py must `import os` so the env-var fallbacks "
        "can read PROXY_SCRIPT_NAME / PROXY_SCHEME / PROXY_HOST / PROXY_PORT."
    )
    for var in ("PROXY_SCRIPT_NAME", "PROXY_SCHEME", "PROXY_HOST", "PROXY_PORT"):
        assert var in src, (
            f"cps/reverseproxy.py must reference `{var}` so operators "
            f"can configure reverse-proxy behavior without the X-* "
            f"headers. See janeczku PR #3369 (@chtzvt)."
        )


def _make_environ(**headers):
    base = {"PATH_INFO": "/", "REQUEST_METHOD": "GET"}
    base.update(headers)
    return base


def _call_middleware(monkeypatch, env_vars, environ):
    """Helper: instantiate ReverseProxied with the given env vars,
    call it with the given environ, return the mutated environ +
    is_proxied flag."""
    from cps import reverseproxy

    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)
    # Ensure others are unset so test order doesn't leak.
    for k in ("PROXY_SCRIPT_NAME", "PROXY_SCHEME", "PROXY_HOST", "PROXY_PORT"):
        if k not in env_vars:
            monkeypatch.delenv(k, raising=False)

    inner = MagicMock(return_value=[b""])
    middleware = reverseproxy.ReverseProxied(inner)
    middleware(environ, MagicMock())
    return environ, middleware.is_proxied


def test_env_script_name_sets_script_name(monkeypatch):
    environ = _make_environ(PATH_INFO="/myprefix/books")
    environ, proxied = _call_middleware(
        monkeypatch,
        {"PROXY_SCRIPT_NAME": "/myprefix"},
        environ,
    )
    assert environ.get("SCRIPT_NAME") == "/myprefix"
    assert environ.get("PATH_INFO") == "/books", (
        f"PATH_INFO must have the script-name prefix stripped. Got "
        f"{environ.get('PATH_INFO')!r}."
    )
    assert proxied is True


def test_header_script_name_overrides_env(monkeypatch):
    environ = _make_environ(
        HTTP_X_SCRIPT_NAME="/header_prefix",
        PATH_INFO="/header_prefix/books",
    )
    environ, _ = _call_middleware(
        monkeypatch,
        {"PROXY_SCRIPT_NAME": "/env_prefix"},
        environ,
    )
    assert environ.get("SCRIPT_NAME") == "/header_prefix", (
        "When the X-Script-Name header is present, it must take "
        "precedence over PROXY_SCRIPT_NAME env var."
    )


def test_env_scheme_sets_wsgi_url_scheme(monkeypatch):
    environ = _make_environ()
    environ, proxied = _call_middleware(
        monkeypatch,
        {"PROXY_SCHEME": "https"},
        environ,
    )
    assert environ.get("wsgi.url_scheme") == "https"
    assert proxied is True


def test_x_forwarded_proto_recognized_as_scheme(monkeypatch):
    """X-Forwarded-Proto is the de-facto standard — not in the
    original CW middleware. The upstream PR adds it alongside X-Scheme.
    """
    environ = _make_environ(HTTP_X_FORWARDED_PROTO="https")
    environ, proxied = _call_middleware(monkeypatch, {}, environ)
    assert environ.get("wsgi.url_scheme") == "https", (
        f"X-Forwarded-Proto must be honored as a scheme source. "
        f"Got wsgi.url_scheme={environ.get('wsgi.url_scheme')!r}."
    )


def test_env_host_sets_http_host_and_port(monkeypatch):
    environ = _make_environ()
    environ, proxied = _call_middleware(
        monkeypatch,
        {"PROXY_HOST": "books.example.com", "PROXY_PORT": "8443"},
        environ,
    )
    assert environ.get("HTTP_HOST") == "books.example.com:8443", (
        f"PROXY_HOST + PROXY_PORT must combine into HTTP_HOST. "
        f"Got {environ.get('HTTP_HOST')!r}."
    )
    assert proxied is True


def test_header_host_already_has_port_skips_env_port(monkeypatch):
    """If X-Forwarded-Host already includes a port (`host:443`),
    PROXY_PORT must not be appended again."""
    environ = _make_environ(HTTP_X_FORWARDED_HOST="books.example.com:1234")
    environ, _ = _call_middleware(
        monkeypatch,
        {"PROXY_PORT": "8443"},
        environ,
    )
    assert environ.get("HTTP_HOST") == "books.example.com:1234", (
        f"If the host already has a port, PROXY_PORT must NOT be "
        f"appended. Got {environ.get('HTTP_HOST')!r}."
    )


def test_no_env_no_header_no_rewriting(monkeypatch):
    """If neither env vars nor headers are set, the environ stays
    untouched and is_proxied stays False."""
    environ = _make_environ()
    environ, proxied = _call_middleware(monkeypatch, {}, environ)
    assert "SCRIPT_NAME" not in environ
    assert environ.get("HTTP_HOST") is None
    assert proxied is False, (
        f"With no env vars and no proxy headers, is_proxied must be "
        f"False so downstream code (Kobo download URL builder, etc.) "
        f"can detect direct-access mode. Got proxied={proxied!r}."
    )
