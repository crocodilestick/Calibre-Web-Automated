# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pin the Dockerfile HEALTHCHECK target to /health.

The previous probe was `curl -fsL http://localhost:8083/`, which only
checked that the homepage responded — that route returns 200 even when
Calibre's metadata.db is unreachable (it just serves the login
redirect). Container orchestration thought everything was fine while
OPDS, the book grid, and downloads were broken.

`/health` (cps/web.py:1051) opens metadata.db, runs `SELECT 1`, and
returns 503 if the connection fails, so a HEALTHCHECK pointed at it
actually reports the right thing to Docker / Kubernetes / Compose.
"""

import re
from pathlib import Path

import pytest


DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


@pytest.fixture(scope="module")
def healthcheck_line() -> str:
    text = DOCKERFILE.read_text()
    match = re.search(r"^HEALTHCHECK[^\n]*\n  CMD ([^\n]+)", text, re.MULTILINE)
    assert match, "Dockerfile must declare a HEALTHCHECK with a CMD"
    return match.group(1)


def test_healthcheck_targets_health_endpoint(healthcheck_line: str) -> None:
    assert "/health" in healthcheck_line, (
        "HEALTHCHECK CMD must probe /health (cps/web.py:1051) so Docker only "
        f"reports healthy when metadata.db is reachable; got: {healthcheck_line!r}"
    )


def test_healthcheck_does_not_probe_bare_root(healthcheck_line: str) -> None:
    assert not re.search(r":\$\{CWA_PORT_OVERRIDE:-8083\}/(\s|\||$)", healthcheck_line), (
        "Probing bare '/' returns 200 even when the DB is down — Docker would "
        f"falsely report the container healthy. Got: {healthcheck_line!r}"
    )


def test_healthcheck_respects_port_override(healthcheck_line: str) -> None:
    assert "${CWA_PORT_OVERRIDE:-8083}" in healthcheck_line, (
        "HEALTHCHECK must substitute CWA_PORT_OVERRIDE so non-default ports "
        f"still get probed; got: {healthcheck_line!r}"
    )


def test_healthcheck_curl_has_bounded_connect_timeout(healthcheck_line: str) -> None:
    """curl must set --connect-timeout so a wedged listen-accept loop
    surfaces as a probe failure within a bounded interval instead of
    blocking the Docker daemon's healthcheck collector. Without it, a
    starved gevent loop produces curl processes that hang for the full
    --timeout window and accumulate across probes.
    """
    assert "--connect-timeout" in healthcheck_line, (
        "HEALTHCHECK curl must pass --connect-timeout so probes fail fast "
        "when the listen-accept loop is starved; got: "
        f"{healthcheck_line!r}"
    )


def test_healthcheck_curl_has_bounded_max_time(healthcheck_line: str) -> None:
    """curl must set --max-time so a slow /health response surfaces as a
    probe failure deterministically (rather than relying on Docker's
    outer --timeout to SIGTERM the curl process and possibly leak it
    when signal propagation is unreliable).

    With --max-time 2 and gevent loop starvation, curl exits within 2s
    and Docker counts the probe as failed — flipping the container to
    UNHEALTHY and letting autoheal / k8s / Compose restart it. See fork
    issue #193 (droM4X), backport of CWA PR #1335 by
    @I-Would-Like-To-Report-A-Bug-Please.
    """
    assert "--max-time" in healthcheck_line, (
        "HEALTHCHECK curl must pass --max-time so a wedged gevent loop "
        "produces a deterministic, bounded probe failure; got: "
        f"{healthcheck_line!r}"
    )
