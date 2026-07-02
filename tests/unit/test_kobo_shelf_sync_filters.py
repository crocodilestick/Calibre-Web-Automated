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

    def test_disabled_filter_compiles_with_sqlite(self):
        from sqlalchemy import Column, Boolean
        from sqlalchemy.dialects import sqlite

        col = Column("kobo_sync", Boolean)
        expr = kobo_sync_disabled_filter(col)

        # Compile the expression for SQLite
        compiled = expr.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True}
        )
        sql_str = str(compiled)

        # Verify that both check clauses are in the generated SQL statement
        assert "kobo_sync = 0" in sql_str or "kobo_sync = false" in sql_str
        assert "kobo_sync IS NULL" in sql_str

