# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/opds.py

Tests cover the OPDS cover-image route contract:
- feed_get_cover() must request a cacheable (non-original) thumbnail
  resolution. feed.xml/json.txt reuse this single route for every book's
  "image" and "image/thumbnail" rel on every catalog page, so if it ever
  regresses to requesting no resolution (or COVER_THUMBNAIL_ORIGINAL, which
  is falsy), get_book_cover_internal()'s `if resolution:` check silently
  skips the thumbnail cache/on-demand generation and every OPDS cover
  request falls back to reading the raw cover.jpg from disk every time.

Note: calls feed_get_cover.__wrapped__ directly to bypass the
@requires_basic_auth_if_no_ano decorator, which needs a live Flask request
context. This is a unit test of the routing contract, not an auth test.
"""

import pytest
from unittest.mock import patch

from cps import constants
from cps.opds import feed_get_cover


class TestFeedGetCover:
    """Test that OPDS cover requests use a cacheable resolution"""

    @patch('cps.opds.get_book_cover')
    def test_requests_medium_resolution(self, mock_get_book_cover):
        """feed_get_cover must pass COVER_THUMBNAIL_MEDIUM through to
        get_book_cover so the request actually reaches the thumbnail
        cache/on-demand generation path instead of always serving the
        uncached original file."""
        mock_get_book_cover.return_value = "sentinel-response"

        result = feed_get_cover.__wrapped__("42")

        mock_get_book_cover.assert_called_once_with("42", constants.COVER_THUMBNAIL_MEDIUM)
        assert result == "sentinel-response"

    @patch('cps.opds.get_book_cover')
    def test_resolution_argument_is_truthy(self, mock_get_book_cover):
        """Regression guard: COVER_THUMBNAIL_ORIGINAL is 0, which is falsy
        and is silently treated as "no resolution requested" by
        get_book_cover_internal()'s `if resolution:` check. Whatever
        resolution feed_get_cover passes must stay nonzero, or OPDS covers
        silently go back to being served uncached on every request."""
        feed_get_cover.__wrapped__("1")

        called_resolution = mock_get_book_cover.call_args.args[1]
        assert called_resolution, "resolution passed to get_book_cover must be truthy"
        assert called_resolution != constants.COVER_THUMBNAIL_ORIGINAL
