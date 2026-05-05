# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_gevent_wsgi_handler_closes_connections_after_response():
    source = (PROJECT_ROOT / "cps/gevent_wsgi.py").read_text(encoding="utf-8")

    assert "def read_request" in source
    assert "self.close_connection = True" in source
