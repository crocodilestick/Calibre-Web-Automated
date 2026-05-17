# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""/health must report 503 — not a silent 302 — when db_configured is False.

The Dockerfile HEALTHCHECK probes /health with `curl -fsS`. Pre-fix, the
``admin.before_app_request`` hook would short-circuit /health with a 302 to
the DB-configuration wizard whenever ``config.db_configured`` was False (no
metadata.db, corrupt library, mounted-but-empty, etc.).

`curl -fsS` does not treat 3xx as failure (no -L, no -f at 3xx), so it exited 0.
Docker / Kubernetes / Compose all reported the container HEALTHY while the app
was functionally broken — the user landed on the DB-config page for everything,
OPDS clients got redirects they could not follow, and the reverse proxy passed
useless responses through to end users. Orchestration would never page on-call,
never roll back, never failover.

The fix has two parts, both pinned below:

1. ``admin.before_request``'s allowlist must include ``'web.health_check'`` so
   /health is reachable even in the unconfigured state.
2. /health itself must early-return ``503`` with ``status: 'unconfigured'`` when
   ``config.db_configured`` is False, so probes correctly see the broken state.

Issue #147 (reporter @iroQuai). The original report — TLS bytes on the plain
HTTP port causing the access-log greenlet to crash — was fixed in v4.0.54 (None
guard in ``cps/gevent_wsgi.py``) and the HEALTHCHECK retarget in v4.0.61 (#197)
removed the HTTPS-fallback probe that was sending those bytes. This test pins
the third and final gap: the silent false-positive HEALTHY state that #197 left
open.
"""

import ast
import inspect


def test_admin_before_request_allowlist_includes_health_check():
    """Source-pin: the db_configured=False redirect must NOT intercept /health.

    Walks ``admin.before_request`` AST for the tuple compared against
    ``request.endpoint``. The tuple is the allowlist of endpoints that
    survive the redirect. ``'web.health_check'`` must be present.
    """
    from cps import admin as admin_module

    source = inspect.getsource(admin_module)
    tree = ast.parse(source)

    found_allowlist = False
    allowlist_endpoints: set[str] = set()

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "before_request"):
            continue

        for sub in ast.walk(node):
            if not isinstance(sub, ast.Compare):
                continue
            for op, comp in zip(sub.ops, sub.comparators):
                if not isinstance(op, ast.NotIn) or not isinstance(comp, ast.Tuple):
                    continue
                literals = {
                    elt.value for elt in comp.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
                if "admin.db_configuration" in literals:
                    allowlist_endpoints = literals
                    found_allowlist = True

    assert found_allowlist, (
        "admin.before_request's endpoint allowlist (the tuple compared against "
        "request.endpoint with `not in`) was not found in the function source. "
        "A refactor likely moved it — re-pin this test against the new shape."
    )

    assert "web.health_check" in allowlist_endpoints, (
        "admin.before_request's allowlist for the db_configured=False redirect "
        "must include 'web.health_check'. Without it, Docker's HEALTHCHECK "
        "probe (curl -fsS /health) follows the 302 to /admin/db_configuration, "
        "sees a 2xx/3xx, exits 0, and falsely reports the container HEALTHY "
        "while the app is broken. Orchestration loses its ability to detect "
        "and recover from the unconfigured-DB state. Current allowlist: "
        f"{sorted(allowlist_endpoints)}"
    )


def test_health_check_returns_503_when_db_unconfigured():
    """Source-pin: /health must short-circuit to 503 when config.db_configured
    is False.

    Even with the allowlist exemption (other test above) in place, /health
    will still run its normal body. That body opens metadata.db, runs
    SELECT 1, and returns 503 only on connect/query failure — but in the
    unconfigured state ``config.config_calibre_dir`` may be empty, joining
    that with 'metadata.db' yields a relative path that sqlite happily opens
    and SELECT 1 returns success, so /health would say "ok" even when the
    app is unconfigured.

    The /health handler must therefore check ``config.db_configured`` itself
    and return 503 with ``status: 'unconfigured'`` early, before touching
    metadata.db. Pin both the check and the 503.
    """
    from cps import web as web_module

    source = inspect.getsource(web_module.health_check)

    assert "config.db_configured" in source, (
        "health_check() must read config.db_configured to detect the "
        "unconfigured state. Without this check, /health reports 'ok' even "
        "when the app is in the unconfigured-DB state, defeating the entire "
        "purpose of having a healthcheck."
    )

    assert "503" in source, (
        "health_check() must return HTTP 503 in some code path so that probes "
        "see the broken state. After this regression, the 503 branch must "
        "exist for the unconfigured state."
    )

    assert "unconfigured" in source, (
        "health_check() must report status='unconfigured' (distinct from "
        "'degraded' for DB-connect failures) so operators reading the JSON "
        "body know whether the cause is config-missing vs DB-down. Without "
        "this distinct status, post-mortem of healthcheck failures becomes "
        "ambiguous."
    )


def test_health_check_unconfigured_branch_short_circuits_before_db_open():
    """Source-pin: the unconfigured check must happen BEFORE any sqlite3.connect.

    The unconfigured state often coincides with the library mount being empty
    or read-only, where opening metadata.db would either fail noisily, succeed
    against an auto-created empty file, or block on a locked file. Either way
    the early-503 branch is the honest answer; doing it before any DB I/O also
    means /health stays cheap and observable in degraded states.
    """
    from cps import web as web_module

    source = inspect.getsource(web_module.health_check)

    # The line that checks db_configured must appear before any sqlite3.connect.
    db_check_pos = source.find("config.db_configured")
    sqlite_pos = source.find("sqlite3.connect")

    assert db_check_pos != -1, "Expected db_configured check in health_check"
    if sqlite_pos != -1:
        assert db_check_pos < sqlite_pos, (
            "config.db_configured check must appear BEFORE sqlite3.connect in "
            "health_check() so the unconfigured state short-circuits without "
            "touching the (possibly missing/locked) metadata.db file. "
            f"db_check at char {db_check_pos}, sqlite3.connect at char {sqlite_pos}."
        )


def test_health_check_view_returns_503_when_unconfigured(monkeypatch):
    """Behavioral: call the health_check view function directly with
    ``config.db_configured = False``; assert HTTP 503 with status='unconfigured'.

    Doesn't go through the admin.before_request redirect — that path is
    pinned by the allowlist test above. This test pins the OTHER half: that
    /health's own body correctly reports 503 in the unconfigured state.
    Together the two pins block both the silent-302 and silent-200 false
    positives.
    """
    from flask import Flask

    from cps import config
    from cps import web as web_module

    app = Flask(__name__)
    app.register_blueprint(web_module.web)

    monkeypatch.setattr(config, "db_configured", False, raising=False)

    with app.test_request_context("/health"):
        resp = web_module.health_check()

    # Flask view returning (response, status) tuple.
    if isinstance(resp, tuple):
        body_resp, status = resp[0], resp[1]
    else:
        body_resp, status = resp, 200

    assert status == 503, (
        "health_check() must return HTTP 503 when config.db_configured is "
        f"False; got {status}. A 200 means the early-return branch is "
        "missing — Docker HEALTHCHECK would falsely report the container "
        "as healthy while the app is functionally broken."
    )

    body = body_resp.get_json() or {}
    assert body.get("status") == "unconfigured", (
        "/health 503 body must include status='unconfigured' so it is "
        "distinguishable from a DB-down 503 (status='degraded'). Without "
        f"this distinction, operators can't tell which 503 they got. Body: {body!r}"
    )
