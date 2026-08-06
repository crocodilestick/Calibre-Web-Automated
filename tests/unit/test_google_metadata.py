# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/metadata_provider/google.py

Loads google.py directly by file path to avoid the heavy cps app stack.
Verifies:
- Searches work without an API key (no key= param in URL)
- The API key is appended when configured
- Empty string key is treated as no key
- HTTP errors return an empty list rather than raising
"""

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union
from unittest.mock import MagicMock, Mock, patch

# ---------------------------------------------------------------------------
# Minimal stubs for the cps classes google.py depends on
# ---------------------------------------------------------------------------

@dataclass
class _MetaSourceInfo:
    id: str
    description: str
    link: str


@dataclass
class _MetaRecord:
    id: Union[str, int]
    title: str
    authors: List[str]
    url: str
    source: _MetaSourceInfo
    cover: str = ""
    description: Optional[str] = ""
    series: Optional[str] = None
    series_index: Optional[Union[int, float]] = 0
    identifiers: Dict = field(default_factory=dict)
    publisher: Optional[str] = None
    publishedDate: Optional[str] = None
    rating: Optional[int] = 0
    languages: Optional[List[str]] = field(default_factory=list)
    tags: Optional[List[str]] = field(default_factory=list)


class _Metadata:
    def __init__(self):
        self.active = True

    def get_title_tokens(self, query, strip_joiners=False):
        return query.split()


# ---------------------------------------------------------------------------
# Build mock modules and inject into sys.modules before loading google.py
# ---------------------------------------------------------------------------

_mock_log = MagicMock()
_mock_logger = MagicMock()
_mock_logger.create.return_value = _mock_log

_mock_config = MagicMock()
_mock_config.config_google_api_key = None

_mock_cps = MagicMock()
_mock_cps.logger = _mock_logger
_mock_cps.config = _mock_config

_mock_services_metadata = MagicMock()
_mock_services_metadata.MetaRecord = _MetaRecord
_mock_services_metadata.MetaSourceInfo = _MetaSourceInfo
_mock_services_metadata.Metadata = _Metadata

_mock_iso = MagicMock()
_mock_iso.get_lang3 = lambda code: code
_mock_iso.get_language_name = lambda locale, code: code

sys.modules["cps"] = _mock_cps
sys.modules["cps.isoLanguages"] = _mock_iso
sys.modules["cps.services"] = MagicMock()
sys.modules["cps.services.Metadata"] = _mock_services_metadata

# Load google.py directly by file path, bypassing the package hierarchy
_google_path = Path(__file__).parent.parent.parent / "cps" / "metadata_provider" / "google.py"
_spec = importlib.util.spec_from_file_location("cps.metadata_provider.google", _google_path)
_google_module = importlib.util.module_from_spec(_spec)
sys.modules["cps.metadata_provider.google"] = _google_module
_spec.loader.exec_module(_google_module)

Google = _google_module.Google

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE = {
    "items": [
        {
            "id": "abc123",
            "volumeInfo": {
                "title": "Looking for Alaska",
                "authors": ["John Green"],
                "description": "A great book.",
                "publisher": "Dutton Books",
                "publishedDate": "2005-03-03",
                "averageRating": 4,
                "categories": ["Young Adult"],
                "language": "en",
                "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"},
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9780525475361"}
                ],
            },
        }
    ]
}


def _make_mock_response(json_data):
    resp = Mock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch.object(_google_module, "requests")
def test_search_without_api_key(mock_requests):
    """No API key configured → key= must not appear in the request URL."""
    _mock_config.config_google_api_key = None
    mock_requests.get.return_value = _make_mock_response(SAMPLE_RESPONSE)

    results = Google().search("Looking for Alaska")

    called_url = mock_requests.get.call_args[0][0]
    assert "key=" not in called_url
    assert len(results) == 1
    assert results[0].title == "Looking for Alaska"


@patch.object(_google_module, "requests")
def test_search_with_api_key(mock_requests):
    """API key configured → key=<value> must be appended to the request URL."""
    _mock_config.config_google_api_key = "MY_TEST_KEY"
    mock_requests.get.return_value = _make_mock_response(SAMPLE_RESPONSE)

    results = Google().search("Looking for Alaska")

    called_url = mock_requests.get.call_args[0][0]
    assert "key=MY_TEST_KEY" in called_url
    assert len(results) == 1


@patch.object(_google_module, "requests")
def test_search_with_empty_api_key(mock_requests):
    """Empty string API key → treated as no key, key= must not appear."""
    _mock_config.config_google_api_key = ""
    mock_requests.get.return_value = _make_mock_response(SAMPLE_RESPONSE)

    results = Google().search("Looking for Alaska")

    called_url = mock_requests.get.call_args[0][0]
    assert "key=" not in called_url


@patch.object(_google_module, "requests")
def test_search_returns_empty_on_http_error(mock_requests):
    """HTTP errors must return an empty list, not raise."""
    _mock_config.config_google_api_key = None
    import requests as req
    mock_requests.get.side_effect = req.exceptions.HTTPError("429 Too Many Requests")

    results = Google().search("Looking for Alaska")

    assert results == []
