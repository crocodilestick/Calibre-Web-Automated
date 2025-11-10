#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Checksum Module

Provides checksum calculation and management for book files.
Supports KOReader's partial MD5 algorithm for efficient file identification.
"""

from .koreader import calculate_koreader_partial_md5, CHECKSUM_VERSION
from .manager import (
    store_checksum,
    calculate_and_store_checksum,
    get_latest_checksum,
    get_checksum_history
)

__all__ = [
    'calculate_koreader_partial_md5',
    'CHECKSUM_VERSION',
    'store_checksum',
    'calculate_and_store_checksum',
    'get_latest_checksum',
    'get_checksum_history',
]
