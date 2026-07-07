# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_docker_healthcheck_curl_has_own_timeout():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    healthcheck = dockerfile.split("HEALTHCHECK", 1)[1]

    assert "--connect-timeout" in healthcheck
    assert "--max-time" in healthcheck
    assert "curl -f http://localhost" not in healthcheck
