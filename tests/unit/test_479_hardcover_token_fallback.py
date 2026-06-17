# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #479 — Hardcover metadata search must fall back to
the next configured token when one is rejected.

Reporter (@WasabiBurns): the search picks the per-user token first, then the
global one. An EXPIRED per-user token shadowed a VALID global token, so search
returned HTTP 401 "Unable to verify token" and gave up — even though a valid
token was configured globally. Fix: try each distinct configured token
(per-user → global → env) until one is accepted, with "Bearer " / whitespace
trimmed. (The per-user-write progress-sync path is intentionally NOT changed —
falling back there would push progress under the wrong account.)
"""

import types

import pytest

pytestmark = pytest.mark.unit


def _resp(status, data=None):
    import requests

    class _R:
        def raise_for_status(self):
            if status == 401:
                err = requests.exceptions.HTTPError("401 Unauthorized")
                err.response = types.SimpleNamespace(status_code=401)
                raise err

        def json(self):
            return data

    return _R()


def test_search_falls_back_to_global_when_user_token_rejected(monkeypatch):
    from cps.metadata_provider import hardcover as hc

    monkeypatch.setattr(hc, "current_user", types.SimpleNamespace(hardcover_token="EXPIRED_USER"))
    monkeypatch.setattr(hc, "config", types.SimpleNamespace(config_hardcover_token="VALID_GLOBAL"))
    monkeypatch.delenv("HARDCOVER_TOKEN", raising=False)

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        auth = headers["Authorization"]
        calls.append(auth)
        if "EXPIRED_USER" in auth:
            return _resp(401)
        return _resp(200, {"data": {"search": {"results": []}}})

    monkeypatch.setattr(hc.requests, "post", fake_post)

    provider = hc.Hardcover()
    provider.active = True
    result = provider.search("dune")

    # fork #479: after the user token's 401, search must try the global token
    assert any("VALID_GLOBAL" in c for c in calls), \
        f"search did not fall back to the global token after a 401; calls={calls}"
    assert isinstance(result, list)  # parsed (empty) results — not a token-failure abort


def test_search_aborts_only_when_every_token_rejected(monkeypatch):
    from cps.metadata_provider import hardcover as hc

    monkeypatch.setattr(hc, "current_user", types.SimpleNamespace(hardcover_token="BAD1"))
    monkeypatch.setattr(hc, "config", types.SimpleNamespace(config_hardcover_token="BAD2"))
    monkeypatch.delenv("HARDCOVER_TOKEN", raising=False)

    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        return _resp(401)

    monkeypatch.setattr(hc.requests, "post", fake_post)

    provider = hc.Hardcover()
    provider.active = True
    result = provider.search("dune")

    assert result == []
    # both distinct tokens were attempted before giving up
    assert sum(1 for c in calls if "BAD1" in c) == 1
    assert sum(1 for c in calls if "BAD2" in c) == 1


def test_token_bearer_prefix_and_whitespace_trimmed(monkeypatch):
    from cps.metadata_provider import hardcover as hc

    monkeypatch.setattr(hc, "current_user", types.SimpleNamespace(hardcover_token="  Bearer abc123\n"))
    monkeypatch.setattr(hc, "config", types.SimpleNamespace(config_hardcover_token=None))
    monkeypatch.delenv("HARDCOVER_TOKEN", raising=False)

    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(headers["Authorization"])
        return _resp(200, {"data": {"search": {"results": []}}})

    monkeypatch.setattr(hc.requests, "post", fake_post)

    provider = hc.Hardcover()
    provider.active = True
    provider.search("dune")

    # a stray "Bearer " prefix and surrounding whitespace from a paste must be
    # trimmed → exactly one clean "Bearer abc123" header
    assert sent == ["Bearer abc123"], sent
