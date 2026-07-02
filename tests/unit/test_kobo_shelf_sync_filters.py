# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo shelf sync filters."""

import pytest

from kobo_sync_utils import kobo_sync_disabled_filter


class _FakeColumn:
    def __eq__(self, other):
        return ("eq", other)

    def is_(self, other):
        return ("is", other)


@pytest.mark.unit
class TestKoboShelfSyncFilters:
    def test_disabled_filter_matches_false_or_null(self):
        conditions = kobo_sync_disabled_filter(_FakeColumn(), combine=lambda *items: items)

        assert conditions == (
            ("eq", False),
            ("is", None),
        )
