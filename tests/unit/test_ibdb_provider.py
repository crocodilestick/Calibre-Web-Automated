# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import requests

from cps.metadata_provider import ibdb
from cps.metadata_provider.ibdb import IBDb


class _FakeResponse:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload


def _patch_get(monkeypatch, response):
    monkeypatch.setattr(ibdb.requests, "get", lambda *args, **kwargs: response)


def _capture_debug(monkeypatch):
    """CWA's logger does not propagate to the root logger, so caplog sees nothing."""
    messages = []

    def record(msg, *args):
        messages.append(msg % args if args else msg)

    monkeypatch.setattr(ibdb.log, "debug", record)
    return messages


def test_search_returns_empty_list_when_rate_limited(monkeypatch):
    messages = _capture_debug(monkeypatch)
    _patch_get(
        monkeypatch,
        _FakeResponse(
            429,
            headers={
                "Retry-After": "124",
                "RateLimit-Limit": "700",
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": "124",
            },
        ),
    )

    assert IBDb().search("dune") == []
    assert messages == [
        "IBDb rate limit exceeded (429), retry after 124s; skipping provider."
    ]


def test_search_logs_unknown_retry_after_when_header_missing(monkeypatch):
    messages = _capture_debug(monkeypatch)
    _patch_get(monkeypatch, _FakeResponse(429))

    assert IBDb().search("dune") == []
    assert messages == [
        "IBDb rate limit exceeded (429), retry after unknowns; skipping provider."
    ]


def test_search_returns_empty_list_when_not_implemented(monkeypatch):
    messages = _capture_debug(monkeypatch)
    _patch_get(monkeypatch, _FakeResponse(501))

    assert IBDb().search("dune") == []
    assert messages == ["IBDb search not implemented (501); skipping provider."]


def test_search_returns_empty_list_on_server_error(monkeypatch):
    _patch_get(monkeypatch, _FakeResponse(500))

    assert IBDb().search("dune") == []


def test_search_parses_results_on_success(monkeypatch):
    _patch_get(
        monkeypatch,
        _FakeResponse(
            200,
            payload={
                "books": [
                    {
                        "id": "abc123",
                        "title": "Dune",
                        "authors": [{"name": "Frank Herbert"}],
                        "isbn13": "9780441013593",
                        "publishedDate": "1965-08-01",
                    }
                ]
            },
        ),
    )

    results = IBDb().search("dune")

    assert len(results) == 1
    assert results[0].title == "Dune"
    assert results[0].authors == ["Frank Herbert"]
    assert results[0].url == IBDb.BOOK_URL + "abc123"
    assert results[0].identifiers == {"ibdb": "abc123", "isbn": "9780441013593"}
