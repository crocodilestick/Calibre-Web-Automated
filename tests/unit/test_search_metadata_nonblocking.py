# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import time

import gevent

from cps import search_metadata
from cps.services.Metadata import MetaRecord, MetaSourceInfo


def make_record(title):
    return MetaRecord(
        id=title,
        title=title,
        authors=[],
        url="",
        source=MetaSourceInfo(id="test", description="Test", link=""),
    )


class FakeProvider:
    def __init__(self, titles, error=None):
        self.titles = titles
        self.error = error

    def search(self, query, generic_cover="", locale="en"):
        if self.error:
            raise self.error
        return [make_record(title) for title in self.titles]


def test_collect_search_results_merges_providers_and_skips_failures():
    providers = [FakeProvider(["a", "b"]), FakeProvider([], RuntimeError("down")), FakeProvider(["c"])]
    searches = [(provider, provider.search) for provider in providers]

    data = search_metadata._collect_search_results(searches, "query", "", "en")

    assert sorted(item["title"] for item in data) == ["a", "b", "c"]


def test_run_without_blocking_server_returns_result(monkeypatch):
    monkeypatch.setattr(search_metadata, "_GEVENT", False)

    assert search_metadata._run_without_blocking_server(lambda value: value * 2, 21) == 42


def test_gevent_server_keeps_serving_during_search(monkeypatch):
    monkeypatch.setattr(search_metadata, "_GEVENT", True)
    monkeypatch.setattr(search_metadata, "get_hub", gevent.get_hub, raising=False)
    release = threading.Event()
    ticks = []

    def slow_search():
        return "done" if release.wait(5) else "blocked"

    def other_request():
        ticks.append(time.monotonic())
        release.set()

    search = gevent.spawn(search_metadata._run_without_blocking_server, slow_search)
    gevent.spawn_later(0.1, other_request)

    assert search.get(timeout=10) == "done"
    assert len(ticks) == 1
