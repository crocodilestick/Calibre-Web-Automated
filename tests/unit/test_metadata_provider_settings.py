# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for metadata provider region helpers and config loading."""

from types import SimpleNamespace

import pytest

from cps import constants
from cps.metadata_provider_settings import (
    apply_config_metadata_provider_regions,
    apply_user_metadata_provider_regions,
    get_effective_amazon_region,
    get_metadata_provider_context,
    validate_amazon_region,
)


@pytest.mark.unit
class TestMetadataProviderSettings:
    def test_validate_provider_regions(self) -> None:
        assert validate_amazon_region("de") == "de"
        assert validate_amazon_region("DE") == "de"
        assert validate_amazon_region("invalid") == ""

    def test_apply_user_metadata_provider_regions(self) -> None:
        user = SimpleNamespace(amazon_region=None)

        apply_user_metadata_provider_regions(
            user,
            {"amazon_region": "ca"},
        )
        assert user.amazon_region == "ca"

        apply_user_metadata_provider_regions(
            user,
            {"amazon_region": "not-real"},
        )
        assert user.amazon_region == ""

    def test_apply_config_metadata_provider_regions(self) -> None:
        config = SimpleNamespace(config_amazon_region="")

        apply_config_metadata_provider_regions(
            config,
            {"amazon_region": "co.uk"},
        )
        assert config.config_amazon_region == "co.uk"

        apply_config_metadata_provider_regions(
            config,
            {"amazon_region": "not-real"},
        )
        assert config.config_amazon_region == ""

    def test_get_metadata_provider_context(self) -> None:
        user = SimpleNamespace(amazon_region="ca")

        context = get_metadata_provider_context(user)

        assert context["amazon_regions"] == constants.AMAZON_REGIONS
        assert context["amazon_region"] == "ca"

    def test_get_metadata_provider_context_with_explicit_values(self) -> None:
        context = get_metadata_provider_context(amazon_region="de")

        assert context["amazon_region"] == "de"

    def test_get_effective_amazon_region_prefers_user_over_config(self) -> None:
        user = SimpleNamespace(amazon_region="fr")

        assert get_effective_amazon_region(user, config_amazon_region="de") == "fr"

    def test_get_effective_amazon_region_uses_config_when_user_missing(self) -> None:
        user = SimpleNamespace(amazon_region="")

        assert get_effective_amazon_region(user, config_amazon_region="de") == "de"

    def test_get_effective_amazon_region_falls_back_to_default(self) -> None:
        user = SimpleNamespace(amazon_region="")

        assert get_effective_amazon_region(user, config_amazon_region="not-real") == constants.AMAZON_REGIONS[0]
