# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Magic Shelf normal_shelf rule source and parsing engine."""

import pytest
from unittest.mock import patch, MagicMock
import sqlalchemy
from sqlalchemy.dialects import sqlite

from cps.magic_shelf import build_filter_from_rule, build_query_from_rules, invalidate_magic_shelf_cache
from cps import db, ub


@pytest.mark.unit
class TestMagicShelfRulesNormalShelf:

    @patch('cps.ub.session')
    def test_normal_shelf_equal_private_magic_shelf_success(self, mock_session):
        """Test that a private Magic Shelf can reference own private normal shelf."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0  # Private shelf
        fake_shelf.name = "My Private Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        fake_book_ids = [MagicMock(book_id=10), MagicMock(book_id=20)]
        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter.return_value.all.return_value = fake_book_ids

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            elif model_or_column is ub.BookShelf.book_id:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': '42'
        }

        expr = build_filter_from_rule(rule, user_id=1, is_public=False)

        assert expr is not None

        # Compile to SQLite and assert the generated SQL
        sql_str = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "books.id IN (10, 20)" in sql_str

    @patch('cps.ub.session')
    def test_normal_shelf_equal_public_magic_shelf_denied(self, mock_session):
        """Test that a public Magic Shelf cannot reference a private normal shelf."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0  # Private shelf
        fake_shelf.name = "My Private Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': '42'
        }

        # When is_public=True (public magic shelf), referencing a private shelf must return false()
        expr = build_filter_from_rule(rule, user_id=1, is_public=True)

        assert isinstance(expr, sqlalchemy.sql.elements.False_)

    @patch('cps.ub.session')
    def test_normal_shelf_equal_public_magic_shelf_success(self, mock_session):
        """Test that a public Magic Shelf can reference a public normal shelf."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 1  # Public shelf
        fake_shelf.name = "Public Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        fake_book_ids = [MagicMock(book_id=10), MagicMock(book_id=20)]
        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter.return_value.all.return_value = fake_book_ids

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            elif model_or_column is ub.BookShelf.book_id:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': '42'
        }

        expr = build_filter_from_rule(rule, user_id=1, is_public=True)

        assert expr is not None
        sql_str = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "books.id IN (10, 20)" in sql_str

    @patch('cps.ub.session')
    def test_normal_shelf_not_equal_success(self, mock_session):
        """Test that not_equal operator negates the IN clause."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0
        fake_shelf.name = "My Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        fake_book_ids = [MagicMock(book_id=10)]
        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter.return_value.all.return_value = fake_book_ids

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            elif model_or_column is ub.BookShelf.book_id:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'not_equal',
            'value': '42'
        }

        expr = build_filter_from_rule(rule, user_id=1, is_public=False)

        assert expr is not None
        sql_str = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "books.id NOT IN (10)" in sql_str

    @patch('cps.ub.session')
    def test_normal_shelf_empty(self, mock_session):
        """Test that referencing an empty shelf returns empty IN condition."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0
        fake_shelf.name = "Empty Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        mock_bookshelf_query = MagicMock()
        mock_bookshelf_query.filter.return_value.all.return_value = []

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            elif model_or_column is ub.BookShelf.book_id:
                return mock_bookshelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': '42'
        }

        expr = build_filter_from_rule(rule, user_id=1, is_public=False)

        assert expr is not None
        sql_str = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        # In SQLAlchemy 2.0, an empty IN list compiles to "books.id IN (SELECT 1 FROM (SELECT 1) WHERE 1!=1)".
        assert "books.id IN (SELECT 1 FROM (SELECT 1) WHERE 1!=1)" in sql_str or "books.id IN (SELECT 1 FROM (SELECT 1) WHERE 1 != 1)" in sql_str

    @patch('cps.ub.session')
    def test_normal_shelf_invalid_id(self, mock_session):
        """Test that invalid string shelf ID yields false()."""
        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': 'abc'
        }
        expr = build_filter_from_rule(rule, user_id=1, is_public=False)
        assert isinstance(expr, sqlalchemy.sql.elements.False_)

    @patch('cps.ub.session')
    def test_normal_shelf_access_denied(self, mock_session):
        """Test that referencing a private shelf of another user yields false()."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 999  # owned by other user
        fake_shelf.is_public = 0  # private
        fake_shelf.name = "Foreign Private Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'equal',
            'value': '42'
        }

        expr = build_filter_from_rule(rule, user_id=1, is_public=False)
        assert isinstance(expr, sqlalchemy.sql.elements.False_)

    @patch('cps.ub.session')
    def test_normal_shelf_unsupported_operator(self, mock_session):
        """Test that unsupported operators (e.g. contains) on normal_shelf yield false()."""
        fake_shelf = MagicMock()
        fake_shelf.id = 42
        fake_shelf.user_id = 1
        fake_shelf.is_public = 0
        fake_shelf.name = "My Shelf"

        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.first.return_value = fake_shelf

        def query_side_effect(model_or_column):
            if model_or_column is ub.Shelf:
                return mock_shelf_query
            return MagicMock()

        mock_session.query.side_effect = query_side_effect

        rule = {
            'id': 'normal_shelf',
            'operator': 'contains',  # forbidden operator
            'value': '42'
        }
        expr = build_filter_from_rule(rule, user_id=1, is_public=False)
        assert isinstance(expr, sqlalchemy.sql.elements.False_)

    @patch('cps.ub.session')
    def test_cache_invalidation(self, mock_session):
        """Test that invalidate_magic_shelf_cache flushes MagicShelfCache table."""
        invalidate_magic_shelf_cache()
        mock_session.query.assert_called_with(ub.MagicShelfCache)
        mock_session.query().delete.assert_called_once()

    def test_regression_existing_rule(self):
        """Test that standard rules (like title matching) remain unaffected."""
        rule = {
            'id': 'title',
            'operator': 'contains',
            'value': 'Harry Potter'
        }
        expr = build_filter_from_rule(rule, user_id=1, is_public=False)
        assert expr is not None
        sql_str = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "lower(books.title) LIKE lower('%Harry Potter%')" in sql_str
