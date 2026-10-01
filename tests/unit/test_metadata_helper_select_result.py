# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace

import pytest

from cps.metadata_helper import _select_result
from cps.metadata_provider.hardcover import Hardcover
from cps.services.Metadata import MetaRecord, MetaSourceInfo

pytestmark = pytest.mark.unit

SCORING_PROVIDER = SimpleNamespace(calculate_confidence_score=Hardcover.calculate_confidence_score)


def _record(title, authors):
    return MetaRecord(
        id=title,
        title=title,
        authors=authors,
        url="",
        source=MetaSourceInfo(id="hardcover", description="Hardcover", link=""),
    )


def _book(title, author):
    return SimpleNamespace(
        title=title,
        authors=[SimpleNamespace(name=author)],
        identifiers=[],
        series=[],
        series_index=None,
        publishers=[],
        pubdate=None,
    )


def test_prefers_the_matching_title_over_the_first_result():
    results = [
        _record("The Great Dune Trilogy", ["Frank Herbert"]),
        _record("Children of Dune", ["Frank Herbert"]),
    ]

    selected = _select_result(SCORING_PROVIDER, results, _book("Children of Dune", "Frank Herbert"), 0.85)

    assert selected.title == "Children of Dune"


def test_finds_a_match_ranked_far_down_the_results():
    results = [_record(f"Dune Study Guide {n}", ["Someone Else"]) for n in range(15)]
    results.append(_record("Dune", ["Frank Herbert"]))

    selected = _select_result(SCORING_PROVIDER, results, _book("Dune", "Frank Herbert"), 0.85)

    assert selected.title == "Dune"


def test_returns_none_when_no_result_is_confident():
    results = [_record("Harry Potter and the Chamber of Secrets", ["J.K. Rowling"])]

    selected = _select_result(SCORING_PROVIDER, results, _book("Secrets of Harry Bright", "Joseph Wambaugh"), 0.85)

    assert selected is None


def test_uses_the_first_result_for_providers_without_scoring():
    results = [_record("First", ["Someone"]), _record("Second", ["Someone"])]

    selected = _select_result(SimpleNamespace(), results, _book("Second", "Someone"), 0.85)

    assert selected.title == "First"
