# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Guard for endpoints that only CWA's own processes may call (ingest processor, scheduler)."""

import ipaddress
import os
import sys
from functools import wraps

from flask import abort, request

sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from cwa_internal_auth import INTERNAL_TOKEN_HEADER, internal_headers, is_valid_internal_token  # noqa: E402

__all__ = ["internal_only", "internal_headers"]


def _peer_is_loopback() -> bool:
    # ProxyFix rewrites REMOTE_ADDR from X-Forwarded-For, which any client can send, so check
    # the address of the socket that actually connected.
    orig = request.environ.get("werkzeug.proxy_fix.orig") or {}
    addr = (orig.get("REMOTE_ADDR") or request.environ.get("REMOTE_ADDR") or "").split("%")[0]
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or bool(mapped and mapped.is_loopback)


def internal_only(f):
    """Allow the request only from a loopback socket carrying the shared internal token."""
    @wraps(f)
    def inner(*args, **kwargs):
        if not (_peer_is_loopback() and is_valid_internal_token(request.headers.get(INTERNAL_TOKEN_HEADER))):
            abort(403)
        return f(*args, **kwargs)
    return inner
