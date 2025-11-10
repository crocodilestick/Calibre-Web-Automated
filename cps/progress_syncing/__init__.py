#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Progress Syncing Module for Calibre-Web-Automated

This package provides reading progress synchronization functionality for various
e-reader devices and applications. It includes:

- Checksum generation and management (partial MD5 for file identification)
- Sync protocol implementations (KOSync for KOReader, extensible for others)
- Database models for tracking checksums and sync data

The module is designed to be modular and extensible, allowing for easy addition
of new sync protocols and checksum algorithms.

Architecture:
    models.py           - Database models (BookFormatChecksum)
    checksums/          - Checksum calculation and storage
        koreader.py     - KOReader partialMD5 algorithm implementation
        manager.py      - Checksum storage, retrieval, and history management
    protocols/          - Sync protocol implementations
        kosync.py       - KOSync protocol for KOReader devices
"""

# Export commonly used components
# NOTE: kosync blueprint is NOT imported here to avoid circular imports
# Import it directly from .protocols.kosync where needed
from .checksums.koreader import calculate_koreader_partial_md5, CHECKSUM_VERSION
from .checksums.manager import (
    store_checksum,
    calculate_and_store_checksum,
    get_latest_checksum,
    get_checksum_history
)
from .models import (
    ensure_calibre_db_tables,
    ensure_app_db_tables,
    ensure_checksum_table,
    BookFormatChecksum,
    KOSyncProgress
)

__all__ = [
    # Checksum functions
    'calculate_koreader_partial_md5',
    'CHECKSUM_VERSION',
    'store_checksum',
    'calculate_and_store_checksum',
    'get_latest_checksum',
    'get_checksum_history',
    # Database models and migrations
    'ensure_calibre_db_tables',
    'ensure_app_db_tables',
    'ensure_checksum_table',
    'BookFormatChecksum',
    'KOSyncProgress',
]

