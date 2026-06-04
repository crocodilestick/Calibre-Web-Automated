# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pin the container HEALTHCHECK target to /health with bounded curl flags.

The previous probe was `curl -fsL http://localhost:8083/`, which only
checked that the homepage responded — that route returns 200 even when
Calibre's metadata.db is unreachable (it just serves the login
redirect). Container orchestration thought everything was fine while
OPDS, the book grid, and downloads were broken.

`/health` (cps/web.py:1051) opens metadata.db, runs `SELECT 1`, and
returns 503 if the connection fails, so a HEALTHCHECK pointed at it
actually reports the right thing to Docker / Kubernetes / Compose.

PR #356 moved the inline `curl ...` from the Dockerfile CMD line into a
`/usr/local/bin/cwa-healthcheck` helper so the helper can auto-switch
to https:// when a cert/key is configured in app.db. The pinned
invariants below — /health target, port override, bounded
--connect-timeout and --max-time — still hold; they just moved from the
Dockerfile to the helper. Each test inspects the union of the two so
either form passes.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
HEALTHCHECK_HELPER = REPO_ROOT / "root" / "usr" / "local" / "bin" / "cwa-healthcheck"


@pytest.fixture(scope="module")
def healthcheck_sources() -> str:
    """Concatenate the Dockerfile HEALTHCHECK CMD line + (if present) the
    cwa-healthcheck helper script. Each pin asserts against the union, so a
    refactor that moves an invariant from inline to the helper stays green
    while a real removal of the invariant still goes red."""
    text = DOCKERFILE.read_text()
    # The HEALTHCHECK declaration spans the directive line + the indented
    # CMD continuation. Grab from `HEALTHCHECK` through the CMD body.
    import re
    match = re.search(r"^HEALTHCHECK[^\n]*\n  CMD ([^\n]+)", text, re.MULTILINE)
    assert match, "Dockerfile must declare a HEALTHCHECK with a CMD"
    cmd = match.group(1)
    helper = HEALTHCHECK_HELPER.read_text() if HEALTHCHECK_HELPER.exists() else ""
    return cmd + "\n" + helper


def test_healthcheck_targets_health_endpoint(healthcheck_sources: str) -> None:
    assert "/health" in healthcheck_sources, (
        "HEALTHCHECK must probe /health (cps/web.py:1051) so Docker only "
        "reports healthy when metadata.db is reachable. Search covers the "
        "Dockerfile CMD line + cwa-healthcheck helper."
    )


def test_healthcheck_does_not_probe_bare_root(healthcheck_sources: str) -> None:
    # Bare-root probe would be `:${port}/ ` (port followed by a slash then
    # whitespace/pipe/end-of-string). Any path segment after the slash
    # (e.g. `/health`) keeps us safe.
    import re
    assert not re.search(r":\$\{(?:CWA_)?[Pp]ort[^}]*\}/(\s|\||$|\")", healthcheck_sources), (
        "Probing bare '/' returns 200 even when the DB is down — Docker "
        "would falsely report the container healthy."
    )


def test_healthcheck_respects_port_override(healthcheck_sources: str) -> None:
    assert "CWA_PORT_OVERRIDE" in healthcheck_sources and "8083" in healthcheck_sources, (
        "HEALTHCHECK must thread CWA_PORT_OVERRIDE (defaulting to 8083) so "
        "non-default ports still get probed."
    )


def test_healthcheck_curl_has_bounded_connect_timeout(healthcheck_sources: str) -> None:
    """curl must set --connect-timeout so a wedged listen-accept loop
    surfaces as a probe failure within a bounded interval instead of
    blocking the Docker daemon's healthcheck collector."""
    assert "--connect-timeout" in healthcheck_sources, (
        "HEALTHCHECK curl must pass --connect-timeout so probes fail fast "
        "when the listen-accept loop is starved."
    )


def test_healthcheck_curl_has_bounded_max_time(healthcheck_sources: str) -> None:
    """curl must set --max-time so a slow /health response surfaces as a
    probe failure deterministically rather than relying on Docker's outer
    --timeout to SIGTERM the curl process. See fork issue #193 (droM4X),
    backport of CWA PR #1335 by @I-Would-Like-To-Report-A-Bug-Please."""
    assert "--max-time" in healthcheck_sources, (
        "HEALTHCHECK curl must pass --max-time so a wedged gevent loop "
        "produces a deterministic, bounded probe failure."
    )
