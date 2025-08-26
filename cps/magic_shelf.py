# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from . import db, ub
from sqlalchemy import and_, or_, not_
from sqlalchemy.sql.expression import func

# Mapping from UI field names to database models and columns
# This will need to be expanded to cover all filterable fields
FIELD_MAP = {
    'title': (db.Books, 'title'),
    'author': (db.Authors, 'name'),
    'tag': (db.Tags, 'name'),
    'series': (db.Series, 'name'),
    'publisher': (db.Publishers, 'name'),
    'rating': (db.Ratings, 'rating'),
    'language': (db.Languages, 'lang_code'),
    'pubdate': (db.Books, 'pubdate'),
    'timestamp': (db.Books, 'timestamp'),
    'has_cover': (db.Books, 'has_cover'),
    'series_index': (db.Books, 'series_index'),
}

# Mapping from UI operators to SQLAlchemy functions/operators
# This will also need to be expanded
OPERATOR_MAP = {
    # 'equals': lambda col, val: col == val,  # Not used by QueryBuilder
    'equal': lambda col, val: col == val,
    # 'not_equals': lambda col, val: col != val,  # Not used by QueryBuilder
    'not_equal': lambda col, val: col != val,
    'less': lambda col, val: col < val,
    # 'less_than': lambda col, val: col < val,  # Not used by QueryBuilder
    'less_or_equal': lambda col, val: col <= val,
    # 'less_than_equal_to': lambda col, val: col <= val,  # Not used by QueryBuilder
    'greater': lambda col, val: col > val,
    # 'greater_than': lambda col, val: col > val,  # Not used by QueryBuilder
    'greater_or_equal': lambda col, val: col >= val,
    # 'greater_than_equal_to': lambda col, val: col >= val,  # Not used by QueryBuilder
    'between': lambda col, val: col.between(*val) if isinstance(val, (list, tuple)) and len(val) == 2 else None,
    'not_between': lambda col, val: ~col.between(*val) if isinstance(val, (list, tuple)) and len(val) == 2 else None,
    'contains': lambda col, val: col.ilike(f'%{val}%'),
    'not_contains': lambda col, val: ~col.ilike(f'%{val}%'),
    'begins_with': lambda col, val: col.ilike(f'{val}%'),
    'not_begins_with': lambda col, val: ~col.ilike(f'{val}%'),
    'starts_with': lambda col, val: col.ilike(f'{val}%'),  # QueryBuilder emits 'begins_with', but keep for legacy
    'ends_with': lambda col, val: col.ilike(f'%{val}'),
    'not_ends_with': lambda col, val: ~col.ilike(f'%{val}'),
    'is_empty': lambda col, val: col == None,
    'is_not_empty': lambda col, val: col != None,
    'in': lambda col, val: col.in_(val if isinstance(val, list) else [val]),
    'not_in': lambda col, val: ~col.in_(val if isinstance(val, list) else [val]),
}

RELATIONSHIP_MAP = {
    'author': 'authors',
    'tag': 'tags',
    'series': 'series',
    'publisher': 'publishers',
    'rating': 'ratings',
    'language': 'languages',
}

def build_filter_from_rule(rule):
    """Builds a SQLAlchemy filter condition from a single rule."""
    field_name = rule.get('id')
    operator_name = rule.get('operator')
    value = rule.get('value')

    if not all([field_name, operator_name]):
        return None

    model, column_name = FIELD_MAP.get(field_name)
    if not model:
        return None

    column = getattr(model, column_name)
    operator = OPERATOR_MAP.get(operator_name)

    if not operator:
        return None

    # Handle relationships using .any()
    relationship_name = RELATIONSHIP_MAP.get(field_name)
    if relationship_name:
        return getattr(db.Books, relationship_name).any(operator(column, value))
    else:
        return operator(column, value)


def build_query_from_rules(rules_json):
    """
    Recursively builds a SQLAlchemy query filter from a JSON rule structure.
    """
    if not rules_json or not rules_json.get('rules'):
        return None

    condition = rules_json.get('condition', 'AND').upper()
    rules = rules_json.get('rules', [])
    
    filters = []
    for rule in rules:
        # If 'condition' is present, it's a group, recurse
        if 'condition' in rule:
            sub_filter = build_query_from_rules(rule)
            if sub_filter is not None:
                filters.append(sub_filter)
        # Otherwise, it's a rule
        else:
            rule_filter = build_filter_from_rule(rule)
            if rule_filter is not None:
                filters.append(rule_filter)

    if not filters:
        return None

    if condition == 'AND':
        return and_(*filters)
    elif condition == 'OR':
        return or_(*filters)
    
    return None

def get_books_for_magic_shelf(shelf_id):
    """
    Takes a MagicShelf ID and returns a list of book objects that match its rules.
    """
    magic_shelf = ub.session.query(ub.MagicShelf).get(shelf_id)
    if not magic_shelf:
        return []

    rules = magic_shelf.rules
    print(f"[MagicShelf Debug] Shelf ID: {shelf_id} | Rules: {rules}", flush=True)
    if not rules:
        print(f"[MagicShelf Debug] No rules found for shelf {shelf_id}", flush=True)
        return []

    cdb = db.CalibreDB(init=True)
    query_filter = build_query_from_rules(rules)
    print(f"[MagicShelf Debug] Built query filter: {query_filter}", flush=True)
    if query_filter is None:
        print(f"[MagicShelf Debug] Query filter is None, returning empty list for shelf {shelf_id}", flush=True)
        return []
    query = cdb.session.query(db.Books)
    query = query.filter(query_filter)
    # Apply standard user permissions filters
    query = query.filter(cdb.common_filters())
    return query.all()
