# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from cps.metadata_provider import amazon
from cps.metadata_provider.amazon import Amazon, SERIES_RE, normalize_amazon_domain


@pytest.mark.parametrize(
    "value, expected",
    [
        ("it", "it"),
        ("co.uk", "co.uk"),
        (" DE ", "de"),
        ("amazon.fr", "fr"),
        ("https://www.amazon.es/", "es"),
        ("", "com"),
        (None, "com"),
        ("co.jp", "com"),  # Japan has its own provider
        ("evil.example", "com"),
    ],
)
def test_normalize_amazon_domain(value, expected):
    assert normalize_amazon_domain(value) == expected


@pytest.mark.parametrize(
    "text, index, series",
    [
        ("Book 2 of 5: Dungeon Crawler Carl", "2", "Dungeon Crawler Carl"),
        ("Book 3: The Stormlight Archive", "3", "The Stormlight Archive"),
        ("Libro 3 di 7: Dungeon Crawler Carl", "3", "Dungeon Crawler Carl"),
        ("Buch 1 von 4: Die Tribute von Panem", "1", "Die Tribute von Panem"),
        ("Band 2 aus 3: Reihe", "2", "Reihe"),
        ("Tome 2 sur 5 : Le Trône de verre", "2", "Le Trône de verre"),
        ("Libro 4 de 6: Trono de cristal", "4", "Trono de cristal"),
    ],
)
def test_series_regex_handles_store_languages(text, index, series):
    match = SERIES_RE.search(text)
    assert match is not None
    assert match.group(1) == index
    assert match.group(2).strip() == series


class _FakeResponse:
    text = "<html><body></body></html>"

    def raise_for_status(self):
        return None


def test_search_uses_configured_store(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("headers") or {}))
        return _FakeResponse()

    monkeypatch.setattr(amazon, "get_amazon_domain", lambda: "it")
    provider = Amazon()
    monkeypatch.setattr(provider, "session", type("S", (), {"get": staticmethod(fake_get)})())
    provider.active = True

    assert provider.search("Il ricettario dell'anarchico") == []
    assert calls, "search request was not sent"
    url, headers = calls[0]
    assert url == "https://www.amazon.it/s"
    assert headers.get("Accept-Language", "").startswith("it-IT")


def test_get_amazon_domain_falls_back_to_com(monkeypatch):
    import scripts.cwa_db as cwa_db

    def broken_db():
        raise RuntimeError("no database")

    monkeypatch.setattr(cwa_db, "CWA_DB", broken_db)
    assert amazon.get_amazon_domain() == "com"
