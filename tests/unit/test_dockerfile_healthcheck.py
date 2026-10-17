# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Docker healthcheck must pass when the web server answers, even with a redirect
the container cannot follow, and fail on a server error. Its curl calls must carry their
own time limits, so a hung web server fails the check cleanly instead of Docker killing
curl mid-request."""

import os
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def _healthcheck_command():
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    instruction = next(line for line in text.splitlines() if line.startswith("HEALTHCHECK "))
    return instruction.split(" CMD ", 1)[1]


@contextmanager
def _web_server(status, location=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _run_healthcheck(port):
    env = {**os.environ, "CWA_PORT_OVERRIDE": str(port)}
    return subprocess.run(["/bin/sh", "-c", _healthcheck_command()], env=env, timeout=10).returncode


def test_every_healthcheck_curl_is_time_bounded():
    command = _healthcheck_command()
    calls = command.count("curl ")
    assert calls == 2  # http, then https for TLS-enabled setups
    assert command.count("--connect-timeout") == calls
    assert command.count("--max-time") == calls


def test_healthcheck_passes_on_a_login_redirect_to_an_unreachable_host():
    with _web_server(302, location="//127.0.0.1:1/login?next=%2F") as port:
        assert _run_healthcheck(port) == 0


def test_healthcheck_fails_on_a_server_error():
    with _web_server(500) as port:
        assert _run_healthcheck(port) == 1
