#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Sync Protocols Module

Implementations of various reading progress sync protocols.
Currently supports KOSync for KOReader devices.
"""

from .kosync import kosync, get_book_by_checksum

__all__ = [
    'kosync',
    'get_book_by_checksum',
]
