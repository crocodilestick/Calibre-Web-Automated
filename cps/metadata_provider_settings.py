# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for metadata provider region settings."""

from collections.abc import Sequence
from typing import Any

from . import constants


def validate_provider_region(value: Any, allowed_regions: Sequence[str]) -> str:
    """Return a normalized region value or an empty string when invalid."""
    if value is None:
        return ""

    region = str(value).strip().lower()
    return region if region in allowed_regions else ""


def validate_amazon_region(value: Any) -> str:
    """Return a validated Amazon region."""
    return validate_provider_region(value, constants.AMAZON_REGIONS)


def get_effective_amazon_region(
    user: Any | None = None,
    *,
    config_amazon_region: Any | None = None,
) -> str:
    """Return the effective Amazon region using user, config, then default fallback."""
    user_region = validate_amazon_region(getattr(user, "amazon_region", None)) if user is not None else ""
    if user_region:
        return user_region

    config_region = validate_amazon_region(config_amazon_region)
    if config_region:
        return config_region

    return constants.AMAZON_REGIONS[0]


def apply_config_metadata_provider_regions(config_obj: Any, form_data: dict[str, Any]) -> None:
    """Apply validated metadata provider regions to a config-like object."""
    config_obj.config_amazon_region = validate_amazon_region(form_data.get("amazon_region"))


def apply_user_metadata_provider_regions(user: Any, form_data: dict[str, Any]) -> None:
    """Apply validated metadata provider regions to a user-like object."""
    user.amazon_region = validate_amazon_region(form_data.get("amazon_region"))


def get_metadata_provider_context(
    user: Any | None = None,
    *,
    amazon_region: str | None = None,
) -> dict[str, Any]:
    """Return shared template context for metadata provider region settings."""
    return {
        "amazon_regions": constants.AMAZON_REGIONS,
        "amazon_region": amazon_region
        if amazon_region is not None
        else getattr(user, "amazon_region", "")
        if user is not None
        else "",
    }
