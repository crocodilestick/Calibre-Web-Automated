# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Docker healthcheck's curl calls must carry their own time limits, so a hung
web server fails the check cleanly instead of Docker killing curl mid-request."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def _healthcheck_command():
    text = DOCKERFILE.read_text(encoding="utf-8")
    block = text.split("\nHEALTHCHECK", 1)[1]
    return block.split("exit 1", 1)[0]


def test_every_healthcheck_curl_is_time_bounded():
    command = _healthcheck_command()
    calls = command.count("curl ")
    assert calls == 2  # http, then https for TLS-enabled setups
    assert command.count("--connect-timeout") == calls
    assert command.count("--max-time") == calls


def test_healthcheck_still_follows_the_login_redirect():
    assert _healthcheck_command().count("-fsL") == 2
