# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for ``cps.gevent_wsgi.MyWSGIHandler.format_request``.

Issue new-usemame/Calibre-Web-NextGen#147: gevent calls ``format_request``
from its access-log path even for requests that never parsed as HTTP
(e.g. a TLS ClientHello arriving on a plain-HTTP listener — bytes
``\\x16\\x03\\x01...``). In that case ``get_environ`` is never invoked,
so ``self.environ`` is ``None`` and our override raised
``AttributeError: 'NoneType' object has no attribute 'get'`` before
producing the access-log line. The greenlet died on every such request.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("gevent")

from cps.gevent_wsgi import MyWSGIHandler  # noqa: E402


def _stub(**overrides):
    """Build a SimpleNamespace with every attribute ``format_request`` reads.

    We bypass ``MyWSGIHandler.__init__`` (which needs a real socket) and
    invoke the unbound method against the stub. Test caller overrides
    only the fields it cares about.
    """
    base = dict(
        time_start=0.0,
        time_finish=0.0,
        response_length=None,
        environ=None,
        client_address=("::1", 12345),
        requestline=None,
        _orig_status=None,
        status=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_format_request_does_not_crash_when_environ_is_none():
    handler = _stub(environ=None, requestline=None, status="400 Bad Request")
    result = MyWSGIHandler.format_request(handler)
    assert isinstance(result, str)
    assert "400" in result


def test_format_request_uses_forwarded_for_when_present():
    handler = _stub(
        environ={"HTTP_X_FORWARDED_FOR": "203.0.113.7"},
        client_address=("::1", 12345),
        requestline="GET / HTTP/1.1",
        _orig_status="200 OK",
        response_length=42,
    )
    result = MyWSGIHandler.format_request(handler)
    assert "203.0.113.7" in result


def test_format_request_falls_back_to_client_address_without_forwarded_for():
    handler = _stub(
        environ={},
        client_address=("198.51.100.4", 12345),
        requestline="GET / HTTP/1.1",
        _orig_status="200 OK",
        response_length=42,
    )
    result = MyWSGIHandler.format_request(handler)
    assert "198.51.100.4" in result


def test_format_request_handles_none_client_address_with_none_environ():
    handler = _stub(environ=None, client_address=None, status="400 Bad Request")
    result = MyWSGIHandler.format_request(handler)
    assert isinstance(result, str)
    assert result.startswith("- ")


def test_read_request_forces_connection_close():
    """``MyWSGIHandler.read_request`` must set ``close_connection = True``
    on every parsed request.

    Reverse-proxy keepalive sockets can stay attached to the gevent
    process after the client side has gone away — when the app is
    overloaded or restarted, those stale sockets prevent the gevent
    process from accepting new work, and the healthcheck wedges because
    no greenlet can run. Forcing connection-close after each response
    means the proxy renegotiates a fresh socket on the next request,
    which avoids the stuck-keepalive failure mode.

    Backport of CWA #1335 by @I-Would-Like-To-Report-A-Bug-Please. Pins
    the source-level invariant so a future refactor (or upstream PR
    pulling the underlying ``WSGIHandler`` apart) can't silently revert
    the close-after-response behaviour.
    """
    import inspect

    source = inspect.getsource(MyWSGIHandler)
    assert "def read_request" in source, (
        "MyWSGIHandler must override read_request to force "
        "self.close_connection = True after each parsed request."
    )
    assert "self.close_connection = True" in source, (
        "MyWSGIHandler.read_request must set self.close_connection = True "
        "so stale reverse-proxy keepalive sockets don't accumulate against "
        "the gevent process. See fork issue #193 + CWA #1335."
    )
