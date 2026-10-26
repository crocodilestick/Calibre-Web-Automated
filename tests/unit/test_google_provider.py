# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging

import requests

from cps.metadata_provider.google import Google


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {"items": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                "%s Error for url: https://www.googleapis.com/books/v1/volumes?q=dune&key=secret-key" % self.status_code,
                response=self,
            )

    def json(self):
        return self.payload


def record_requests(monkeypatch, response):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params})
        return response

    monkeypatch.setattr(Google.session, "get", fake_get)
    return calls


def test_api_key_is_sent_when_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "secret-key")
    calls = record_requests(monkeypatch, FakeResponse())

    Google().search("dune")

    assert calls[0]["params"] == {"key": "secret-key"}


def test_no_key_keeps_keyless_request(monkeypatch):
    monkeypatch.delenv("GOOGLE_BOOKS_API_KEY", raising=False)
    calls = record_requests(monkeypatch, FakeResponse())

    Google().search("dune")

    assert calls[0]["params"] is None


def test_api_key_is_not_logged_on_error(monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "secret-key")
    record_requests(monkeypatch, FakeResponse(status_code=403))

    with caplog.at_level(logging.WARNING):
        assert Google().search("dune") == []

    assert "secret-key" not in caplog.text
