#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Partial MD5 Checksum Generation for Book Files

This module implements the same partial MD5 algorithm used by KOReader to generate
document identifiers for sync purposes. The algorithm samples data from strategic
positions in the file to create a unique hash without reading the entire file.

Based on KOReader's implementation in frontend/util.lua:partialMD5()
Reference: https://github.com/koreader/koreader/blob/master/frontend/util.lua#L1107

Version History:
- Version 'koreader': Initial implementation of KOReader partialMD5 algorithm (November 2025)
"""

import hashlib
import os
from typing import Optional

from ... import logger

log = logger.create()

# Current algorithm version - use string identifier for clarity
CHECKSUM_VERSION = 'koreader'


def calculate_koreader_partial_md5(filepath: str) -> Optional[str]:
    """
    Calculate partial MD5 hash of a file using KOReader's sampling algorithm.

    This algorithm samples 1024 bytes at exponentially spaced positions to create
    a unique identifier without reading the entire file. Positions are:
    0, 4K, 16K, 64K, 256K, 1M, 4M, 16M, 64M, 256M, 1G

    The algorithm uses larger weights at file head and smaller weights at tail,
    which reduces the probability that appended data (like PDF annotations) will
    change the digest value.

    Note: Files around these sizes may see digest changes with appended data:
    1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864,
    268435456, or 1073741824 bytes.

    Args:
        filepath: Absolute path to the file to hash

    Returns:
        32-character hexadecimal MD5 hash string, or None if file cannot be read

    Example:
        >>> calculate_koreader_partial_md5("/path/to/book.epub")
        'b3fb8f4f8448160365087d6ca05c7fa2'
    """
    if not filepath:
        return None

    if not os.path.exists(filepath):
        return None

    try:
        md5_hash = hashlib.md5()  # nosec - MD5 is used for identification, not security
        step = 1024
        sample_size = 1024

        with open(filepath, 'rb') as f:
            # Sample at positions: 0, 1K, 4K, 16K, 64K, 256K, 1M, 4M, 16M, 64M, 256M, 1G
            # Formula: lshift(step, 2*i) where i ranges from -1 to 10
            for i in range(-1, 11):
                # Calculate position using same algorithm as KOReader
                # KOReader uses: bit.lshift(step, 2*i)
                # LuaJIT's bit.lshift only uses lower 5 bits of shift count
                # So lshift(1024, -2) becomes lshift(1024, 30) = 0 (overflow)
                #
                # For i = -1: shift_count = -2, masked = 30, result = 0
                #  0: shift_count = 0, result = 1024
                #  1: shift_count = 2, result = 4096
                #  2: shift_count = 4, result = 16384
                #  3: shift_count = 6, result = 65536
                # etc.
                shift_count = 2 * i
                masked_shift = shift_count & 0x1F  # LuaJIT: only lower 5 bits used

                # Perform the shift (may overflow to 0)
                result = step << masked_shift
                # Mask to 32-bit unsigned range like LuaJIT does
                position = result & 0xFFFFFFFF

                try:
                    f.seek(position)
                    sample = f.read(sample_size)

                    if sample:
                        md5_hash.update(sample)
                    else:
                        # Reached end of file
                        break

                except (IOError, OSError):
                    # Seeking beyond file end - stop sampling
                    break

        result = md5_hash.hexdigest()
        return result

    except (IOError, OSError, PermissionError) as e:
        log.error(f"calculate_koreader_partial_md5: Error reading file {filepath}: {e}")
        return None
    except Exception as e:
        log.error(f"calculate_koreader_partial_md5: Unexpected error for {filepath}: {e}")
        return None
