# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""/health must report 503 when a critical longrun s6 service is down.

Pre-fix, /health only verified that ``metadata.db`` could be opened and
``SELECT 1`` succeeded. droM4X (fork issue #193) and FRaccie (~200k-book
production library) both reported the same operational failure mode:
``cwa-ingest-service`` and/or ``metadata-change-detector`` had stopped
running, yet ``/health`` kept reporting ``{"status": "ok"}`` because the
DB was still readable. Container orchestration (autoheal / k8s liveness
probes / Compose) thought the box was fine while ingest + metadata-edit
writeback were silently broken.

This module pins the third 503 branch — "services degraded" — so a
future refactor can't silently delete it. Two halves:

1. ``health_check`` must invoke a helper that reads s6 supervise state
   for each critical longrun and surface the result in the JSON body
   under ``"services"``.
2. If any critical longrun reports ``"down"``, the response is HTTP 503
   with ``status: "degraded"`` and the offending service named in the
   ``services`` map.

Behavioral tests monkeypatch the helper so they don't require s6 to be
installed on the test host.
"""

import ast
import inspect
import json


_CRITICAL_LONGRUNS = ("cwa-ingest-service", "metadata-change-detector")


def test_health_check_calls_a_service_status_helper():
    """Source-pin: ``health_check`` reads service status via a named helper.

    Pinning the helper name decouples the test from the body of
    ``health_check``: anyone refactoring the route can move things around
    so long as the s6 probe still happens. The helper itself is pinned by
    the next test.
    """
    from cps import web as web_module

    source = inspect.getsource(web_module.health_check)
    assert "_check_s6_service_status" in source, (
        "health_check() must call _check_s6_service_status() to probe critical "
        "longrun s6 services. Without this call, /health only reflects DB "
        "readability and reports a healthy container while ingest / "
        "metadata-change-detector are crashed. See fork issue #193 (droM4X) "
        "and the production trace from @FRaccie."
    )


def test_check_s6_service_status_probes_critical_longruns():
    """Source-pin: the helper probes each critical longrun by name.

    The two critical longruns we care about are ``cwa-ingest-service``
    (auto-ingest from /cwa-book-ingest/) and ``metadata-change-detector``
    (metadata write-back to .opf / file). If either has died and isn't
    being restarted by s6, the container is functionally broken even with
    a readable DB.

    The probe iterates a module-level tuple of service names; pin both
    the helper's existence and the tuple's contents.
    """
    from cps import web as web_module

    helper = getattr(web_module, "_check_s6_service_status", None)
    assert helper is not None, (
        "cps.web must define a module-level _check_s6_service_status helper "
        "that returns a dict keyed by service name with status values."
    )

    critical = getattr(web_module, "_CRITICAL_LONGRUNS", None)
    assert critical is not None, (
        "cps.web must declare _CRITICAL_LONGRUNS at module level so the "
        "set of probed services is a single source of truth, not a string "
        "literal buried in the helper body."
    )

    for name in _CRITICAL_LONGRUNS:
        assert name in critical, (
            f"cps.web._CRITICAL_LONGRUNS must include '{name}' — it's one of "
            "the critical longrun s6 services whose failure leaves the "
            "container reporting healthy while the feature is broken. "
            f"Current contents: {tuple(critical)}"
        )


def test_check_s6_service_status_uses_s6_rc_list_primitive():
    """Source-pin: the helper uses ``s6-rc -a list`` to read live state.

    The Flask app runs as ``abc`` and cannot read
    ``/run/service/<svc>/supervise/`` (root-only in the lsio base image),
    so ``s6-svstat`` is unavailable. ``s6-rc -a list`` reads
    world-readable state under ``/run/s6/db`` and reflects the
    currently-active services — services taken down via ``s6-rc -d
    change`` disappear from the output, services brought back via
    ``s6-rc -u change`` reappear. That matches the precedent in
    ``scripts/check-cwa-services.sh`` already consumed by the admin UI's
    "Check NextGen Status" action.
    """
    from cps import web as web_module

    helper_source = inspect.getsource(web_module._check_s6_service_status)
    assert "s6-rc" in helper_source, (
        "_check_s6_service_status() must invoke 's6-rc -a list' to enumerate "
        "currently-active services. 's6-svstat' won't work — the supervise "
        "dirs are root-only in the lsio base image while the Flask app "
        "runs as abc, so the probe would always report 'down'."
    )
    assert "list" in helper_source, (
        "_check_s6_service_status() must call 's6-rc -a list' (not "
        "s6-rc -a change or s6-rc info) — list is the enumerate-active "
        "primitive whose output we parse for membership."
    )


def test_check_s6_service_status_degrades_gracefully_outside_container():
    """Behavioral: outside an s6 container (no s6-svstat on PATH), the helper
    must return ``status='unknown'`` for every probed service — never raise,
    never fail the test process, never silently return all-up.

    The unit-test runner doesn't have s6 installed. The same code path runs
    in dev environments and on CI. ``unknown`` is the honest answer: we
    can't tell, so we don't pretend.
    """
    from cps import web as web_module

    # Run the helper in a process that almost certainly has no s6-svstat.
    result = web_module._check_s6_service_status()

    assert isinstance(result, dict), (
        f"_check_s6_service_status() must return a dict; got {type(result)}"
    )
    for name in _CRITICAL_LONGRUNS:
        assert name in result, (
            f"_check_s6_service_status() must include '{name}' in its result "
            f"dict even when s6 is unavailable. Got keys: {sorted(result)}"
        )
        # When s6-svstat is missing, status should be 'unknown' — not 'up'
        # (which would be a false positive in dev/test) and not 'down'
        # (which would falsely 503 every test container).
        assert result[name] in ("up", "down", "unknown"), (
            f"_check_s6_service_status()[{name!r}] must be one of "
            f"'up'/'down'/'unknown'; got {result[name]!r}"
        )


def test_health_check_returns_503_when_a_critical_service_is_down(monkeypatch):
    """Behavioral: monkeypatch the service-status helper to return one
    'down' and assert /health returns 503 with status='degraded' and the
    offending service surfaced under 'services'.
    """
    from flask import Flask

    from cps import config
    from cps import web as web_module

    app = Flask(__name__)
    app.register_blueprint(web_module.web)

    monkeypatch.setattr(config, "db_configured", True, raising=False)

    # Stub the DB probe to "up" so this test isolates the service-status branch.
    def _fake_db_ok():
        return True

    monkeypatch.setattr(web_module, "_probe_metadata_db", _fake_db_ok, raising=False)

    def _fake_services():
        return {
            "cwa-ingest-service": "down",
            "metadata-change-detector": "up",
        }

    monkeypatch.setattr(web_module, "_check_s6_service_status", _fake_services)

    with app.test_request_context("/health"):
        resp = web_module.health_check()

    if isinstance(resp, tuple):
        body_resp, status = resp[0], resp[1]
    else:
        body_resp, status = resp, 200

    assert status == 503, (
        "/health must return 503 when any critical longrun is reported "
        f"'down'. Got status={status}. Pre-fix /health stayed 200 because "
        "the route didn't probe service liveness — that's exactly the bug "
        "from fork #193 and FRaccie's production trace."
    )

    body = body_resp.get_json() or {}
    assert body.get("status") == "degraded", (
        "/health 503 body for service-down state must report "
        f"status='degraded'; got {body.get('status')!r}. Body: {body!r}"
    )
    assert "services" in body, (
        "/health body must expose the 'services' map so operators can see "
        f"which service triggered the 503. Body keys: {sorted(body)}"
    )
    assert body["services"].get("cwa-ingest-service") == "down", (
        "services map must report 'down' for the offending service. Got: "
        f"{body['services']!r}"
    )


def test_health_check_stays_200_when_all_services_up(monkeypatch):
    """Behavioral: with DB ok AND all critical longruns 'up', /health is 200
    with status='ok' and the services map populated.

    Pins that adding the services check didn't accidentally regress the
    happy path.
    """
    from flask import Flask

    from cps import config
    from cps import web as web_module

    app = Flask(__name__)
    app.register_blueprint(web_module.web)

    monkeypatch.setattr(config, "db_configured", True, raising=False)
    monkeypatch.setattr(web_module, "_probe_metadata_db", lambda: True, raising=False)
    monkeypatch.setattr(
        web_module,
        "_check_s6_service_status",
        lambda: {name: "up" for name in _CRITICAL_LONGRUNS},
    )

    with app.test_request_context("/health"):
        resp = web_module.health_check()

    if isinstance(resp, tuple):
        body_resp, status = resp[0], resp[1]
    else:
        body_resp, status = resp, 200

    assert status == 200, (
        f"/health must return 200 when DB is reachable and all critical "
        f"longruns report 'up'; got {status}."
    )

    body = body_resp.get_json() or {}
    assert body.get("status") == "ok"
    assert body.get("services") == {name: "up" for name in _CRITICAL_LONGRUNS}, (
        "Happy-path body must surface the services map so operators can "
        "confirm coverage at a glance. Got: "
        f"{body.get('services')!r}"
    )


def test_health_check_unknown_service_status_does_not_503(monkeypatch):
    """Behavioral: when s6-svstat is unavailable (dev/test/non-s6 host), all
    services report 'unknown'. /health must NOT 503 on that — it must
    surface 'unknown' in the body and still report 200 (DB+config gates
    are the only ones that 503; 'unknown service status' is honestly not
    a known-bad state).

    This avoids false alarms in environments where we genuinely can't
    probe (k8s sidecar test, dev compose without s6, unit-test harness).
    """
    from flask import Flask

    from cps import config
    from cps import web as web_module

    app = Flask(__name__)
    app.register_blueprint(web_module.web)

    monkeypatch.setattr(config, "db_configured", True, raising=False)
    monkeypatch.setattr(web_module, "_probe_metadata_db", lambda: True, raising=False)
    monkeypatch.setattr(
        web_module,
        "_check_s6_service_status",
        lambda: {name: "unknown" for name in _CRITICAL_LONGRUNS},
    )

    with app.test_request_context("/health"):
        resp = web_module.health_check()

    if isinstance(resp, tuple):
        body_resp, status = resp[0], resp[1]
    else:
        body_resp, status = resp, 200

    assert status == 200, (
        "/health must NOT 503 on 'unknown' service status — that's our "
        "honest 'no s6 here' signal, not a known-bad state. Got "
        f"status={status}."
    )

    body = body_resp.get_json() or {}
    assert all(v == "unknown" for v in body.get("services", {}).values()), (
        "/health body must surface 'unknown' for each probed service when "
        "s6 is unreachable, so operators reading the JSON can tell why "
        "the services map is empty of useful info. Got: "
        f"{body.get('services')!r}"
    )
