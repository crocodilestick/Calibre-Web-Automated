# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the Amazon metadata providers
"""

import pytest
from unittest.mock import MagicMock, patch

from cps.metadata_provider.amazon import Amazon
from cps.services.Metadata import MetaRecord, MetaSourceInfo
from tests.unit.metadata_base import ExpectedMetadata, MetadataProviderTestBase


@pytest.mark.unit
class TestAmazonMetadataProviders(MetadataProviderTestBase):
    """Tests for Amazon metadata providers"""

    def test_amazon_region_precedence(self) -> None:
        """Test that the Amazon provider region prefers user settings over global settings."""
        provider = Amazon()

        # Default case: com
        assert provider.amazon_region() == "com"
        assert provider.language_codes() == ["en-US", "en"]

        # Global setting
        with patch('cps.metadata_provider.amazon.config') as mock_config:
            mock_config.amazon_region = "de"
            assert provider.amazon_region() == "de"
            assert provider.language_codes() == ["de-DE", "de"]

            with patch('cps.metadata_provider.amazon.current_user') as mock_user:
                # User setting
                mock_user.amazon_region = "fr"
                assert provider.amazon_region() == "fr"
                assert provider.language_codes() == ["fr-FR", "fr"]

    def test_amazon_search_results(self) -> None:
        """Test the Amazon search results parsing"""
        provider = Amazon()
        search_page = self.html_fixture_soup(provider, "search_results")

        # Fetch and parse search results
        results = provider.parse_search_results(search_page)
        assert len(results) == 3

        expected_links = set(
            [
                "/dp/ABCDEF",
                "/ssdp/ABCDEF",
                "/dp/GHIJKL",
            ]
        )

        for link in expected_links:
            assert link in results

    def test_amazon_parser(self) -> None:
        """Test the Amazon metadata parsers"""
        expected_metadata = [
            ExpectedMetadata(
                provider=Amazon,
                region="com",
                lang_header="en-US,en;q=0.9",
                md=MetaRecord(
                    id="B0DL524V1M",
                    title="An Elemental Title",
                    series_index=3,
                    series="True Sol Planets",
                    authors=["Gaia Earth"],
                    url="https://www.amazon.com/dummy-url",
                    rating=4,
                    identifiers={"mobi-asin": "B0DL524V1M", "amazon": "B0DL524V1M"},
                    cover="https://m.media-amazon.com/images/I/914f54v5PuL._SL1500_.jpg",
                    description="<div>\n\n<span> In a world with elements, there are elements! </span>\n\n</div>",
                    publisher="Sol Publishing Co",
                    publishedDate="1970-01-02",
                    source=MetaSourceInfo(
                        id="amazon", description="Amazon", link="https://www.amazon.com"
                    ),
                ),
                test_file="all_fields",
            ),
            ExpectedMetadata(
                provider=Amazon,
                region="ca",
                lang_header="en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
                md=MetaRecord(
                    id="B0DL524V1M",
                    title="An Elemental Title",
                    series_index=3,
                    series="True Sol Planets",
                    authors=["Gaia Earth"],
                    url="https://www.amazon.ca/dummy-url",
                    rating=4,
                    identifiers={"mobi-asin": "B0DL524V1M", "amazon_ca": "B0DL524V1M"},
                    cover="https://m.media-amazon.com/images/I/914f54v5PuL._SL1500_.jpg",
                    description="<div>\n\n<span> In a world with elements, there are elements! </span>\n\n</div>",
                    publisher="Sol Publishing Co",
                    publishedDate="1970-01-02",
                    source=MetaSourceInfo(
                        id="amazon_ca", description="AmazonCa", link="https://www.amazon.ca"
                    ),
                ),
                test_file="all_fields",
            ),
            ExpectedMetadata(
                provider=Amazon,
                region="co.jp",
                lang_header="ja-JP,ja;q=0.9",
                md=MetaRecord(
                    id="B0DL524V1M",
                    title="祝福のチェスカ: 1【電子限定描き下ろし付き】 (ZERO-SUMコミックス)",
                    series_index=1,
                    series="祝福のチェスカ",
                    authors=["乃原 美隆"],
                    url="https://www.amazon.co.jp/dummy-url",
                    rating=3,
                    identifiers={"amazon_jp": "B0DL524V1M", "mobi-asin": "B0DL524V1M"},
                    cover="https://m.media-amazon.com/images/I/914f54v5PuL._SL1500_.jpg",
                    description="<div>\n\n<span>\n 神より与えられた超能力（ルア）を使役する人々に支配されている世界で、その力を持たない人々は『ヤグー』と呼ばれ過酷な差別に晒されていた。そんなある日、世界中の王族・為政者の子供たちが通うナンカン共和国のマカリ学園にヤグーの王子が入学することになる。それをきっかけに世界は一変し――…!?言語学の天才である少女・チェスカと虐げられし民も美しき王子・シキが出会う時、世界のルールは覆される!!壮大なる本格ファンタジーが今、幕を開ける――…!!\n </span>\n\n</div>",
                    publisher="一迅社",
                    publishedDate="2024-10-31",
                    source=MetaSourceInfo(
                        id="amazon_jp",
                        description="AmazonJp",
                        link="https://www.amazon.co.jp",
                    ),
                ),
                test_file="all_fields",
            ),
        ]

        for expected in expected_metadata:
            with patch('cps.metadata_provider.amazon.config') as mock_config:
                mock_config.amazon_region = expected.region
                provider = expected.provider()
                page = self.html_fixture_soup(provider, expected.test_file)

                # Mock the HTTP request to return the fixture content
                provider.get = MagicMock(return_value=page)

                # Fetch and parse metadata
                metadata = provider.parse_detail_page("/dummy-url", "/generic.jpg", 1)
                assert metadata is not None

                # Validate headers
                assert provider.headers["Accept-Language"] == expected.lang_header
                assert provider.session.headers["Accept-Language"] == expected.lang_header

                # Validate parsed metadata (this is a placeholder; actual fields should be checked)
                assert isinstance(metadata[0], MetaRecord)
                assert metadata[0] == expected.md
