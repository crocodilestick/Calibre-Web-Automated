# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Shared secret for calls from CWA's own processes to the web app's internal endpoints.

The web process and the s6 scripts (ingest processor etc.) run as the same user in the
same container, so they share a random token through a 0600 file in the temp dir. Callers
send it in the INTERNAL_TOKEN_HEADER header; the web app compares it in constant time.

Kept dependency-free so scripts can import it without pulling in the Flask app.
"""

import hmac
import os
import secrets
import tempfile

INTERNAL_TOKEN_HEADER = "X-CWA-Internal-Token"
_TOKEN_FILE_ENV = "CWA_INTERNAL_TOKEN_FILE"


def _token_path() -> str:
    return os.environ.get(_TOKEN_FILE_ENV) or os.path.join(tempfile.gettempdir(), "cwa_internal_token")


def get_internal_token() -> str:
    """Return the shared token, creating it atomically on first use."""
    path = _token_path()
    try:
        with open(path, "r", encoding="ascii") as f:
            token = f.read().strip()
        if token:
            return token
    except FileNotFoundError:
        pass

    # Write to a private temp file, then link it into place: os.link fails if another
    # process won the race, and readers never see a partially written token.
    token = secrets.token_hex(32)
    tmp_path = f"{path}.{os.getpid()}.new"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            with open(path, "r", encoding="ascii") as f:
                token = f.read().strip()
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
    return token


def internal_headers() -> dict:
    """Headers a CWA process must send when calling an internal endpoint."""
    return {INTERNAL_TOKEN_HEADER: get_internal_token()}


def is_valid_internal_token(candidate) -> bool:
    if not candidate:
        return False
    try:
        return hmac.compare_digest(str(candidate), get_internal_token())
    except OSError:
        return False
