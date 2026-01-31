# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Base class for metadata provider unit tests
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Type

from bs4 import BeautifulSoup as BS

from cps.services.Metadata import Metadata, MetaRecord


@dataclass
class ExpectedMetadata:
    provider: Type[Metadata]
    region: str
    md: MetaRecord
    lang_header: str
    test_file: str


class MetadataProviderTestBase:
    """Base class for metadata provider unit tests"""

    base_fixtures_path = Path(__file__).parent.parent / "fixtures"
    base_html_fixtures_path = Path(__file__).parent.parent / "fixtures" / "html"
    base_json_fixtures_path = Path(__file__).parent.parent / "fixtures" / "json"

    def fixture_path(self, provider: Metadata, case: str, ext: str) -> Path:
        """Get the path to the fixture file for a given provider, test case, and extension"""
        return self.base_fixtures_path / ext / f"{provider.__id__}_{case}.{ext}"

    def html_fixture_path(self, provider: Metadata, case: str) -> Path:
        """Get the path to the HTML fixture file for a given provider and test case"""
        return self.fixture_path(provider, case, "html")

    def json_fixture_path(self, provider: Metadata, case: str) -> Path:
        """Get the path to the JSON fixture file for a given provider and test case"""
        return self.fixture_path(provider, case, "json")

    def xml_fixture_path(self, provider: Metadata, case: str) -> Path:
        """Get the path to the XML fixture file for a given provider and test case"""
        return self.fixture_path(provider, case, "xml")

    def html_fixture_soup(self, provider: Metadata, case: str) -> BS:
        """Load and parse the fixture HTML file for a given provider and test case"""
        fixture_file = self.html_fixture_path(provider, case)
        with open(fixture_file, "r", encoding="utf-8") as f:
            html_content = f.read()

        return BS(html_content, "lxml")

    pass
