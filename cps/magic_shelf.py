# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from . import db, ub, logger
from .cw_login import current_user
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta, timezone

log = logger.create()

MAGIC_SHELF_ORDER_MODES = {
    'manual',
    'name_asc',
    'name_desc',
    'book_count_desc',
    'book_count_asc',
    'created_desc',
    'created_asc',
    'modified_desc',
    'modified_asc',
}

DEFAULT_MAGIC_SHELF_ORDER_MODE = 'name_asc'


def normalize_magic_shelf_order(order_list, available_ids):
    """Normalize a magic shelf order list, appending missing IDs.

    Args:
        order_list: Iterable of shelf IDs (int/str).
        available_ids: Iterable of available shelf IDs (int).

    Returns:
        list[int]: Ordered IDs containing all available IDs exactly once.
    """
    normalized = []
    seen = set()
    available_set = set(available_ids or [])

    for item in order_list or []:
        try:
            shelf_id = int(item)
        except (TypeError, ValueError):
            continue
        if shelf_id in available_set and shelf_id not in seen:
            normalized.append(shelf_id)
            seen.add(shelf_id)

    for shelf_id in available_ids or []:
        if shelf_id not in seen:
            normalized.append(shelf_id)
            seen.add(shelf_id)

    return normalized


def sort_magic_shelves_for_user(shelves, user):
    """Sort magic shelves for a user based on view settings."""
    settings = (getattr(user, 'view_settings', None) or {}).get('magic_shelves', {})
    order_mode = settings.get('order_mode', DEFAULT_MAGIC_SHELF_ORDER_MODE)
    if order_mode not in MAGIC_SHELF_ORDER_MODES:
        order_mode = DEFAULT_MAGIC_SHELF_ORDER_MODE

    if order_mode == 'manual':
        available_ids = [s.id for s in shelves]
        order_list = settings.get('order', [])
        normalized = normalize_magic_shelf_order(order_list, available_ids)
        index = {shelf_id: idx for idx, shelf_id in enumerate(normalized)}
        shelves.sort(key=lambda s: index.get(s.id, len(index)))
        return

    if order_mode == 'name_desc':
        shelves.sort(key=lambda s: (s.name or "").casefold(), reverse=True)
        return

    if order_mode == 'book_count_desc':
        shelves.sort(key=lambda s: int(getattr(s, 'book_count', 0) or 0), reverse=True)
        return

    if order_mode == 'book_count_asc':
        shelves.sort(key=lambda s: int(getattr(s, 'book_count', 0) or 0))
        return

    if order_mode == 'created_desc':
        min_date = datetime.min.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: s.created or min_date, reverse=True)
        return

    if order_mode == 'created_asc':
        max_date = datetime.max.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: s.created or max_date)
        return

    if order_mode == 'modified_desc':
        min_date = datetime.min.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: s.last_modified or min_date, reverse=True)
        return

    if order_mode == 'modified_asc':
        max_date = datetime.max.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: s.last_modified or max_date)
        return

    # Default: name ascending
    shelves.sort(key=lambda s: (s.name or "").casefold())


def get_visible_magic_shelves_for_user(user_id):
    """Return visible magic shelves for a given user ID."""
    hidden_items = ub.session.query(
        ub.HiddenMagicShelfTemplate.template_key,
        ub.HiddenMagicShelfTemplate.shelf_id
    ).filter(
        ub.HiddenMagicShelfTemplate.user_id == user_id
    ).all()

    hidden_template_keys = {item.template_key for item in hidden_items if item.template_key}
    hidden_shelf_ids = {item.shelf_id for item in hidden_items if item.shelf_id}

    shelves = ub.session.query(ub.MagicShelf).filter(
        or_(
            ub.MagicShelf.is_public == 1,
            ub.MagicShelf.user_id == user_id
        )
    ).all()

    filtered_shelves = []
    for shelf in shelves:
        if shelf.is_system and shelf.user_id == user_id:
            template_key = None
            for key, template in SYSTEM_SHELF_TEMPLATES.items():
                if template['name'] == shelf.name:
                    template_key = key
                    break

            if template_key is not None and template_key in hidden_template_keys:
                continue

        if shelf.is_public == 1 and shelf.user_id != user_id:
            if shelf.id in hidden_shelf_ids:
                continue

        filtered_shelves.append(shelf)

    return filtered_shelves

# System Magic Shelf Templates
# These are pre-built shelves that can be created for users as examples/templates
SYSTEM_SHELF_TEMPLATES = {
    'recently_added': {
        'name': 'Recently Added',
        'icon': '⏰',
        'description': 'Books added to your library in the last 30 days',
        'rules': {
            'condition': 'AND',
            'rules': [
                {
                    'id': 'timestamp',
                    'field': 'timestamp',
                    'type': 'date',
                    'input': 'text',
                    'operator': 'greater',
                    'value': (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
                }
            ]
        }
    },
    'highly_rated': {
        'name': 'Highly Rated',
        'icon': '⭐',
        'description': 'Books with a rating of 8 or higher',
        'rules': {
            'condition': 'AND',
            'rules': [
                {
                    'id': 'rating',
                    'field': 'rating',
                    'type': 'integer',
                    'input': 'select',
                    'operator': 'greater_or_equal',
                    'value': 8
                }
            ]
        }
    },
    # 'no_cover': {
    #     'name': 'Books Without Covers',
    #     'icon': '🗒️',
    #     'description': 'Books that are missing cover images',
    #     'rules': {
    #         'condition': 'AND',
    #         'rules': [
    #             {
    #                 'id': 'has_cover',
    #                 'field': 'has_cover',
    #                 'type': 'boolean',
    #                 'input': 'radio',
    #                 'operator': 'equal',
    #                 'value': 0
    #             }
    #         ]
    #     }
    # },
    'currently_reading': {
        'name': 'Currently Reading',
        'icon': '📖',
        'description': 'Books you are currently reading (synced via KOSync/Kobo)',
        'rules': {
            'condition': 'AND',
            'rules': [{
                'id': 'read_status',
                'field': 'read_status',
                'type': 'integer',
                'input': 'radio',
                'operator': 'equal',
                'value': 2  # STATUS_IN_PROGRESS
            }]
        }
    },
    'yet_to_read': {
        'name': 'Yet to Read',
        'icon': '📚',
        'description': 'Books you haven\'t read yet',
        'rules': {
            'condition': 'AND',
            'rules': [{
                'id': 'read_status',
                'field': 'read_status',
                'type': 'integer',
                'input': 'radio',
                'operator': 'equal',
                'value': 0  # Just check for unread
            }]
        }
    },
    'recent_publications': {
        'name': 'Recent Publications',
        'icon': '🌱',
        'description': 'Books published in the last 2 years',
        'rules': {
            'condition': 'AND',
            'rules': [
                {
                    'id': 'pubdate',
                    'field': 'pubdate',
                    'type': 'date',
                    'input': 'text',
                    'operator': 'greater',
                    'value': (datetime.now(timezone.utc) - timedelta(days=730)).strftime('%Y-%m-%d')
                }
            ]
        }
    },
    # 'series_incomplete': {
    #     'name': 'Incomplete Series',
    #     'icon': '📚',
    #     'description': 'Books that are part of a series',
    #     'rules': {
    #         'condition': 'AND',
    #         'rules': [
    #             {
    #                 'id': 'series',
    #                 'field': 'series',
    #                 'type': 'string',
    #                 'input': 'text',
    #                 'operator': 'is_not_empty',
    #                 'value': None
    #             }
    #         ]
    #     }
    # }

}

# Mapping from UI field names to database models and columns
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
    'comments': (db.Comments, 'text'),  # Fixed: Points to actual text column, not relationship
    'read_status': ('custom_column', 'read_status'),  # Special handling - uses config.config_read_column
    'hardcover_id': ('identifier', 'hardcover-id'),  # Special handling - checks Identifiers table
}

# Mapping from UI operators to SQLAlchemy functions/operators
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
    'contains': lambda col, val: col.ilike(f'%{val}%') if val is not None else None,
    'not_contains': lambda col, val: ~col.ilike(f'%{val}%') if val is not None else None,
    'begins_with': lambda col, val: col.ilike(f'{val}%') if val is not None else None,
    'not_begins_with': lambda col, val: ~col.ilike(f'{val}%') if val is not None else None,
    'starts_with': lambda col, val: col.ilike(f'{val}%') if val is not None else None,  # QueryBuilder emits 'begins_with', but keep for legacy
    'ends_with': lambda col, val: col.ilike(f'%{val}') if val is not None else None,
    'not_ends_with': lambda col, val: ~col.ilike(f'%{val}') if val is not None else None,
    'is_empty': lambda col, val: col is None,
    'is_not_empty': lambda col, val: col is not None,
    'is_null': lambda col, val: col is None,
    'is_not_null': lambda col, val: col is not None,
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
    'comments': 'comments',  # For description field - requires join to Comments table
}

def build_filter_from_rule(rule, user_id=None):
    """Builds a SQLAlchemy filter condition from a single rule."""
    from . import config

    field_name = rule.get('id')
    operator_name = rule.get('operator')
    value = rule.get('value')

    if not all([field_name, operator_name]):
        return None

    # Handle dynamic custom column fields (id: 'custom_column_<N>')
    if field_name and field_name.startswith('custom_column_'):
        try:
            cc_id = int(field_name[len('custom_column_'):])
        except ValueError:
            return None

        if cc_id not in db.cc_classes:
            log.warning(f"Custom column {cc_id} not found in cc_classes")
            return None

        cc_rel_name = f'custom_column_{cc_id}'
        if not hasattr(db.Books, cc_rel_name):
            log.warning(f"Books model has no relationship '{cc_rel_name}'")
            return None

        cc_class = db.cc_classes[cc_id]
        column = cc_class.value
        rel = getattr(db.Books, cc_rel_name)

        # Coerce value to match the column's Python type before filtering
        from . import calibre_db
        cc_col = calibre_db.session.get(db.CustomColumns, cc_id)
        if cc_col:
            if cc_col.datatype == 'bool' and value is not None:
                try:
                    value = bool(int(value))
                except (ValueError, TypeError):
                    pass
            elif cc_col.datatype == 'datetime':
                if isinstance(value, str):
                    try:
                        value = datetime.strptime(value, '%Y-%m-%d')
                    except ValueError:
                        log.warning(f"Invalid date value '{value}' for custom column {cc_id}")
                        return None
                elif isinstance(value, list):
                    parsed = []
                    for v in value:
                        try:
                            parsed.append(datetime.strptime(v, '%Y-%m-%d'))
                        except (ValueError, TypeError):
                            log.warning(f"Invalid date value '{v}' for custom column {cc_id}")
                            return None
                    value = parsed
            elif cc_col.datatype == 'enumeration':
                # The empty/not-empty operators carry no value — don't let
                # enum validation reject their None and kill the filter
                # before the operator dispatch below.
                value_free_ops = ('is_empty', 'is_null', 'is_not_empty', 'is_not_null')
                if operator_name not in value_free_ops:
                    try:
                        allowed = set(cc_col.get_display_dict().get('enum_values', []))
                    except Exception:
                        allowed = set()
                    if allowed:
                        values_to_check = value if isinstance(value, list) else [value]
                        for v in values_to_check:
                            if v not in allowed:
                                log.warning(f"Invalid enum value '{v}' for custom column {cc_id}")
                                return None

        negated_ops = {
            'not_equal': 'equal',
            'not_contains': 'contains',
            'not_begins_with': 'begins_with',
            'not_ends_with': 'ends_with',
            'not_in': 'in',
            'not_between': 'between',
        }
        try:
            if operator_name in ('is_empty', 'is_null'):
                return ~rel.any()
            elif operator_name in ('is_not_empty', 'is_not_null'):
                return rel.any()
            elif operator_name in negated_ops:
                base_op = OPERATOR_MAP.get(negated_ops[operator_name])
                if not base_op:
                    return None
                filter_expr = base_op(column, value)
                return ~rel.any(filter_expr) if filter_expr is not None else None
            else:
                operator = OPERATOR_MAP.get(operator_name)
                if not operator:
                    return None
                filter_expr = operator(column, value)
                return rel.any(filter_expr) if filter_expr is not None else None
        except Exception as e:
            log.error(f"Error building filter for custom column {cc_id}: {e}", exc_info=True)
            return None

    field_info = FIELD_MAP.get(field_name)
    if not field_info:
        return None
    
    model, column_name = field_info
    
    # Special handling for hardcover_id identifier
    if model == 'identifier' and column_name == 'hardcover-id':
        # Value is 1 (has hardcover ID) or 0 (doesn't have hardcover ID)
        # Similar to has_cover boolean handling
        try:
            has_hardcover = bool(int(value)) if value is not None else True
        except (ValueError, TypeError):
            has_hardcover = True
        
        hardcover_condition = db.Books.identifiers.any(
            or_(
                db.Identifiers.type == 'hardcover-id',
                db.Identifiers.type == 'hardcover-slug',
                db.Identifiers.type == 'hardcover-edition'
            )
        )
        
        if operator_name == 'equal':
            # Equal to 1 (Yes) = has hardcover ID
            # Equal to 0 (No) = doesn't have hardcover ID
            return hardcover_condition if has_hardcover else ~hardcover_condition
        elif operator_name == 'not_equal':
            # Opposite of equal
            return ~hardcover_condition if has_hardcover else hardcover_condition
        else:
            # For any other operator (shouldn't happen with boolean type), default to equal
            return hardcover_condition if has_hardcover else ~hardcover_condition
    
    # Special handling for read_status custom column
    if model == 'custom_column' and column_name == 'read_status':
        use_custom_column = False
        if config.config_read_column and config.config_read_column != 0:
            if config.config_read_column in db.cc_classes:
                use_custom_column = True
            else:
                log.warning(f"Read status column {config.config_read_column} not found in cc_classes")

        if not use_custom_column:
            if user_id is not None:
                # Fallback to built-in read status
                # Value: 0 = Unread, 1 = Read/Finished, 2 = Currently Reading/In Progress
                try:
                    status_value = int(value)
                except (ValueError, TypeError):
                    status_value = 0

                if status_value == ub.ReadBook.STATUS_IN_PROGRESS:
                    # Currently reading: match STATUS_IN_PROGRESS
                    matching_books = ub.session.query(ub.ReadBook).filter(
                        ub.ReadBook.user_id == user_id,
                        ub.ReadBook.read_status == ub.ReadBook.STATUS_IN_PROGRESS
                    ).all()
                elif status_value == ub.ReadBook.STATUS_FINISHED:
                    # Finished reading
                    matching_books = ub.session.query(ub.ReadBook).filter(
                        ub.ReadBook.user_id == user_id,
                        ub.ReadBook.read_status == ub.ReadBook.STATUS_FINISHED
                    ).all()
                else:
                    # Unread: books with no ReadBook entry or STATUS_UNREAD
                    matching_books = ub.session.query(ub.ReadBook).filter(
                        ub.ReadBook.user_id == user_id,
                        ub.ReadBook.read_status == ub.ReadBook.STATUS_FINISHED
                    ).all()

                matching_book_ids = [rb.book_id for rb in matching_books]

                if operator_name == 'equal':
                    if status_value == ub.ReadBook.STATUS_UNREAD:
                        # Unread = NOT in finished list
                        return ~db.Books.id.in_(matching_book_ids)
                    else:
                        return db.Books.id.in_(matching_book_ids)
                elif operator_name == 'not_equal':
                    if status_value == ub.ReadBook.STATUS_UNREAD:
                        return db.Books.id.in_(matching_book_ids)
                    else:
                        return ~db.Books.id.in_(matching_book_ids)
                else:
                    return None
            else:
                log.debug("Read status column not configured and no user_id provided, skipping read_status filter")
                return None

        read_col_class = db.cc_classes[config.config_read_column]
        column = read_col_class.value
        
        # Get the operator
        operator = OPERATOR_MAP.get(operator_name)
        if not operator:
            return None
        
        # Convert integer value (0/1) to boolean (False/True) for proper comparison
        # QueryBuilder sends integers from radio buttons, but custom column expects boolean
        if isinstance(value, int):
            value = bool(value)

        # Read status custom columns are joined via relationship - get the dynamic relationship name
        cc_relationship = f'custom_column_{config.config_read_column}'
        if hasattr(db.Books, cc_relationship):
            return getattr(db.Books, cc_relationship).any(operator(column, value))
        else:
            log.error(f"Books model does not have relationship '{cc_relationship}'")
            return None
    else:
        if not model:
            return None
        column = getattr(model, column_name)
    
    operator = OPERATOR_MAP.get(operator_name)

    if not operator:
        return None

    # Handle relationships using .any()
    relationship_name = RELATIONSHIP_MAP.get(field_name)
    negated_relationship_ops = {
        'not_equal': 'equal',
        'not_contains': 'contains',
        'not_begins_with': 'begins_with',
        'not_ends_with': 'ends_with',
        'not_in': 'in',
        'not_between': 'between',
    }
    try:
        if relationship_name:
            # Special handling for is_empty/is_null on relationships:
            # These check for absence of relationships, not null values in related records
            if operator_name in ['is_empty', 'is_null']:
                return ~getattr(db.Books, relationship_name).any()
            elif operator_name in ['is_not_empty', 'is_not_null']:
                return getattr(db.Books, relationship_name).any()
            elif operator_name in negated_relationship_ops:
                base_operator_name = negated_relationship_ops[operator_name]
                base_operator = OPERATOR_MAP.get(base_operator_name)
                if not base_operator:
                    return None
                filter_expr = base_operator(column, value)
                if filter_expr is None:
                    return None
                return ~getattr(db.Books, relationship_name).any(filter_expr)
            else:
                filter_expr = operator(column, value)
                if filter_expr is None:
                    return None
                return getattr(db.Books, relationship_name).any(filter_expr)
        else:
            filter_expr = operator(column, value)
            return filter_expr
    except Exception as e:
        log.error(f"Error building filter for field '{field_name}', operator '{operator_name}', value '{value}': {str(e)}", exc_info=True)
        return None


def build_query_from_rules(rules_json, user_id=None):
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
            sub_filter = build_query_from_rules(rule, user_id)
            if sub_filter is not None:
                filters.append(sub_filter)
        # Otherwise, it's a rule
        else:
            rule_filter = build_filter_from_rule(rule, user_id)
            if rule_filter is not None:
                filters.append(rule_filter)

    if not filters:
        return None

    if condition == 'AND':
        return and_(*filters)
    elif condition == 'OR':
        return or_(*filters)
    
    return None


def get_book_ids_for_magic_shelf(shelf_id, sort_order=None, sort_param='stored', bypass_cache=False):
    """Return ordered book IDs for a magic shelf without loading book objects."""
    try:
        from . import calibre_db
        if calibre_db._desktop_compat:
            bypass_cache = True
        if not bypass_cache and current_user.is_authenticated:
            cache = ub.session.query(ub.MagicShelfCache).filter_by(
                shelf_id=shelf_id,
                user_id=current_user.id,
                sort_param=sort_param,
            ).first()
            if cache:
                created_at = cache.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                is_expired = (datetime.now(timezone.utc) - created_at) > timedelta(minutes=30)
                if not is_expired:
                    log.debug(f"Magic shelf {shelf_id} ID list served from cache ({cache.total_count} books)")
                    return cache.book_ids, cache.total_count

        query, magic_shelf = build_book_query_for_magic_shelf(shelf_id, sort_order=sort_order)
        if query is None:
            return [], 0

        all_ids = [book_id for (book_id,) in query.with_entities(db.Books.id).all()]
        total_count = len(all_ids)

        if current_user.is_authenticated and not bypass_cache:
            ub.session.query(ub.MagicShelfCache).filter_by(
                shelf_id=shelf_id,
                user_id=current_user.id,
                sort_param=sort_param,
            ).delete()
            ub.session.add(ub.MagicShelfCache(
                shelf_id=shelf_id,
                user_id=current_user.id,
                sort_param=sort_param,
                book_ids=all_ids,
                total_count=total_count,
            ))
            ub.session.commit()
            log.debug(f"Magic shelf {shelf_id} cache updated ({total_count} items)")

        return all_ids, total_count
    except SQLAlchemyError as e:
        log.error(f"Database error retrieving book IDs for magic shelf {shelf_id}: {e}")
        return [], 0


def build_book_query_for_magic_shelf(shelf_id, sort_order=None, extra_filter=None):
    """Build a Books query for a magic shelf.

    Returns:
        tuple: (query, magic_shelf) or (None, magic_shelf)
    """
    magic_shelf = ub.session.query(ub.MagicShelf).get(shelf_id)
    if not magic_shelf:
        log.warning(f"Magic shelf with ID {shelf_id} not found")
        return None, None

    rules = magic_shelf.rules
    log.debug(
        f"Loading magic shelf '{magic_shelf.name}' (ID: {shelf_id}) with "
        f"{len(rules.get('rules', [])) if rules else 0} rules"
    )
    if not rules or not rules.get('rules'):
        log.debug(f"No rules defined for magic shelf {shelf_id}")
        return None, magic_shelf

    query_filter = build_query_from_rules(rules, user_id=magic_shelf.user_id)
    if query_filter is None:
        log.warning(f"Failed to build query filter for magic shelf {shelf_id}")
        return None, magic_shelf

    cdb = db.CalibreDB(init=True)
    query = cdb.session.query(db.Books).filter(query_filter).filter(cdb.common_filters(extra_filter=extra_filter))
    # Fork-specific (#38, backport of CWA #1233): outerjoin Series when the
    # sort references Series-derived columns. Without this, ORDER BY
    # series.name produces empty results.
    if sort_order is not None:
        order_list = sort_order if isinstance(sort_order, list) else [sort_order]
        needs_series_join = any(
            'series' in str(getattr(expr, 'element', expr)).lower()
            for expr in order_list
        )
        if needs_series_join:
            query = query.outerjoin(db.books_series_link).outerjoin(db.Series)
        if isinstance(sort_order, list):
            for order_expr in sort_order:
                query = query.order_by(order_expr)
        else:
            query = query.order_by(sort_order)
    return query, magic_shelf

def get_books_for_magic_shelf(shelf_id, page=1, page_size=None, sort_order=None, sort_param='stored', bypass_cache=False):
    """
    Takes a MagicShelf ID and returns a paginated list of book objects that match its rules.
    
    Args:
        shelf_id: ID of the magic shelf
        page: Page number (1-indexed)
        page_size: Number of books per page (None = all books)
        sort_order: SQLAlchemy order_by expression
        sort_param: String identifier for the sort order (used for cache key)
        bypass_cache: If True, forces a database query and cache update
    
    Returns:
        tuple: (books, total_count)
    """
    try:
        all_ids, total_count = get_book_ids_for_magic_shelf(
            shelf_id,
            sort_order=sort_order,
            sort_param=sort_param,
            bypass_cache=bypass_cache,
        )
        
        # Apply pagination to the list of IDs we just fetched
        if page_size is not None and page_size > 0:
            start = (page - 1) * page_size
            page_ids = all_ids[start : start + page_size]
        else:
            page_ids = all_ids

        if not page_ids:
            return [], total_count

        # Fetch objects for the current page
        cdb = db.CalibreDB(init=True)
        books = cdb.session.query(db.Books).filter(db.Books.id.in_(page_ids)).all()
        book_map = {b.id: b for b in books}
        ordered_books = [book_map[bid] for bid in page_ids if bid in book_map]
        
        return ordered_books, total_count
        
    except SQLAlchemyError as e:
        log.error(f"Database error retrieving books for magic shelf {shelf_id}: {e}")
        return [], 0
    except Exception as e:
        log.error(f"Unexpected error retrieving books for magic shelf {shelf_id}: {e}")
        return [], 0


def get_book_count_for_magic_shelf(shelf_id):
    """
    Efficiently gets the total count of books for a magic shelf.
    
    Args:
        shelf_id: ID of the magic shelf
    
    Returns:
        int: Total count of matching books
    """
    try:
        query, __ = build_book_query_for_magic_shelf(shelf_id)
        if query is None:
            return 0
        return query.order_by(None).count()
        
    except Exception as e:
        log.error(f"Error counting books for magic shelf {shelf_id}: {e}")
        return 0


def create_system_magic_shelves(user_id, template_keys=None):
    """
    Create system magic shelves for a user from templates.
    
    Args:
        user_id: ID of the user to create shelves for
        template_keys: List of template keys to create (None = create all)
    
    Returns:
        int: Number of shelves created
    """
    if template_keys is None:
        template_keys = SYSTEM_SHELF_TEMPLATES.keys()
    
    created_count = 0
    
    for key in template_keys:
        if key not in SYSTEM_SHELF_TEMPLATES:
            log.warning(f"Unknown system shelf template: {key}")
            continue
        
        template = SYSTEM_SHELF_TEMPLATES[key]
        
        try:
            # Check if user already has this system shelf
            existing = ub.session.query(ub.MagicShelf).filter(
                ub.MagicShelf.user_id == user_id,
                ub.MagicShelf.name == template['name'],
                ub.MagicShelf.is_system.is_(True)
            ).first()
            
            if existing:
                log.debug(f"User {user_id} already has system shelf '{template['name']}'")
                continue
            
            # Create new system shelf
            new_shelf = ub.MagicShelf(
                user_id=user_id,
                name=template['name'],
                icon=template['icon'],
                rules=template['rules'],
                is_system=True,
                is_public=0
            )
            
            ub.session.add(new_shelf)
            created_count += 1
            log.info(f"Created system magic shelf '{template['name']}' for user {user_id}")
            
        except Exception as e:
            log.error(f"Error creating system shelf '{template.get('name')}' for user {user_id}: {e}")
            ub.session.rollback()
            continue
    
    if created_count > 0:
        try:
            ub.session.commit()
            log.info(f"Successfully created {created_count} system magic shelves for user {user_id}")
        except Exception as e:
            log.error(f"Error committing system shelves for user {user_id}: {e}")
            ub.session.rollback()
            return 0
    
    return created_count


def get_system_shelf_template(template_key):
    """
    Get a system shelf template by key.
    
    Args:
        template_key: Key of the template to retrieve
    
    Returns:
        dict: Template data or None if not found
    """
    return SYSTEM_SHELF_TEMPLATES.get(template_key)


def list_system_shelf_templates():
    """
    Get all available system shelf templates.
    
    Returns:
        dict: All system shelf templates
    """
    return SYSTEM_SHELF_TEMPLATES
