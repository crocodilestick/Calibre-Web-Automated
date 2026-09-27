# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for how db.Books loads its relationships.

The relationships must be eager (templates read them after the session has
closed, see #1067), but not lazy='subquery': that strategy re-runs the parent
query to find the related rows, so with ORDER BY random() and a LIMIT (the
Discover page, the random books strip, OPDS "discover") the second run picks
different books and most results come back with missing or wrong authors,
tags, series and formats. lazy='selectin' loads by the parent ids instead.
"""

import pytest
from sqlalchemy import inspect

from cps import db

pytestmark = pytest.mark.unit

RELATIONSHIPS = ("authors", "tags", "comments", "data", "series",
                 "ratings", "languages", "publishers", "identifiers")


@pytest.mark.parametrize("name", RELATIONSHIPS)
def test_books_relationship_uses_selectin(name):
    rel = inspect(db.Books).relationships[name]
    assert rel.lazy == "selectin"
