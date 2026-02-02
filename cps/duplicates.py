# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint, jsonify, request, abort
from flask_babel import gettext as _
from sqlalchemy import func, and_, case
from sqlalchemy.sql.expression import true, false
from sqlalchemy.orm import joinedload
from datetime import datetime, timezone
from functools import wraps
import hashlib
import os
import time
from shutil import copyfile

from . import db, calibre_db, logger, ub, csrf, config, helper
from .services.worker import WorkerThread, STAT_FINISH_SUCCESS, STAT_FAIL, STAT_ENDED, STAT_CANCELLED
from .admin import admin_required  
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .cw_login import current_user

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

duplicates = Blueprint('duplicates', __name__)
log = logger.create()


def _normalize_timestamp(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _timestamp_or_default(ts, default):
    normalized = _normalize_timestamp(ts)
    return normalized if normalized is not None else default


_AWARE_MIN = datetime.min.replace(tzinfo=timezone.utc)
_AWARE_MAX = datetime.max.replace(tzinfo=timezone.utc)


def admin_or_edit_required(f):
    """Decorator that allows access to admins or users with edit role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not (current_user.role_admin() or current_user.role_edit()):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def generate_group_hash(title, author):
    """Generate MD5 hash for a duplicate group based on title and author
    
    Args:
        title: Book title (will be normalized)
        author: Primary author name (will be normalized)
        
    Returns:
        32-character MD5 hash string
    """
    # Normalize inputs - lowercase, strip whitespace
    normalized_title = (title or "untitled").lower().strip()
    normalized_author = (author or "unknown").lower().strip()
    
    # Create composite key
    composite = f"{normalized_title}|{normalized_author}"
    
    # Generate MD5 hash
    return hashlib.md5(composite.encode('utf-8')).hexdigest()


def normalize_title_for_duplicates(title, primary_author=None):
    """Normalize title for duplicate detection.

    If the title starts with the primary author (e.g., "Homer, the Iliad"),
    strip the leading author prefix to avoid false negatives.
    """
    normalized = (title or "untitled").lower().strip()
    if primary_author:
        author_norm = str(primary_author).lower().strip()
        author_prefix = f"{author_norm}, "
        if normalized.startswith(author_prefix):
            normalized = normalized[len(author_prefix):].strip()
    return normalized


def validate_resolution_strategy(strategy):
    """Validate that strategy is one of the allowed values"""
    valid_strategies = ['newest', 'oldest', 'merge', 'highest_quality_format', 'most_metadata', 'largest_file_size']
    return strategy in valid_strategies


def select_book_to_keep(books, strategy):
    """
    Select which book to keep from a duplicate group based on strategy.
    
    Args:
        books: List of book objects from find_duplicate_books()
        strategy: One of 'newest', 'highest_quality_format', 'most_metadata', 'largest_file_size'
    
    Returns:
        The book object to keep
    """
    if not books:
        return None
    
    if strategy == 'newest':
        # Keep the most recently added book
        return max(books, key=lambda b: _timestamp_or_default(b.timestamp, _AWARE_MIN))

    elif strategy == 'oldest':
        # Keep the earliest added book
        return min(books, key=lambda b: _timestamp_or_default(b.timestamp, _AWARE_MAX))

    elif strategy == 'merge':
        # Merge into the newest book by default
        return max(books, key=lambda b: _timestamp_or_default(b.timestamp, _AWARE_MIN))
    
    elif strategy == 'highest_quality_format':
        # Get format priority from settings
        try:
            import json
            cwa_db = CWA_DB()
            format_priority_json = cwa_db.cwa_settings.get('duplicate_format_priority', '{}')
            format_priority = json.loads(format_priority_json)
        except Exception as e:
            log.warning("[cwa-duplicates] Error loading format priority from settings, using defaults: %s", str(e))
            # Fallback to default priority
            format_priority = {
                'EPUB': 100,
                'KEPUB': 95,
                'AZW3': 90,
                'MOBI': 80,
                'AZW': 75,
                'PDF': 60,
                'TXT': 40,
                'CBZ': 35,
                'CBR': 35,
                'FB2': 30,
                'DJVU': 25,
                'HTML': 20,
                'RTF': 15,
                'DOC': 10,
                'DOCX': 10,
            }
        
        def get_best_format_score(book):
            """Calculate best format score for a book"""
            if not book.data:
                return 0
            scores = [format_priority.get(data.format.upper(), 0) for data in book.data if data.format]
            return max(scores) if scores else 0
        
        # Keep book with highest quality format, fallback to newest if tie
        return max(books, key=lambda b: (get_best_format_score(b), _timestamp_or_default(b.timestamp, _AWARE_MIN)))
    
    elif strategy == 'most_metadata':
        # Count metadata completeness
        def metadata_score(book):
            score = 0
            
            # Tags
            if hasattr(book, 'tags') and book.tags:
                score += len(book.tags) * 2
            
            # Series
            if hasattr(book, 'series') and book.series:
                score += 5
            
            # Rating
            if hasattr(book, 'ratings') and book.ratings:
                for rating in book.ratings:
                    if rating.rating and rating.rating > 0:
                        score += 3
            
            # Description/comments
            if hasattr(book, 'comments') and book.comments:
                for comment in book.comments:
                    if comment.text and len(comment.text.strip()) > 50:
                        score += 10
            
            # Publisher
            if hasattr(book, 'publishers') and book.publishers:
                score += 2
            
            # Published date
            if hasattr(book, 'pubdate') and book.pubdate:
                score += 2
            
            # Identifiers (ISBN, etc.)
            if hasattr(book, 'identifiers') and book.identifiers:
                score += len(book.identifiers) * 3
            
            # Number of formats
            if hasattr(book, 'data') and book.data:
                score += len(book.data)
            
            return score
        
        # Keep book with most complete metadata, fallback to newest if tie
        return max(books, key=lambda b: (metadata_score(b), _timestamp_or_default(b.timestamp, _AWARE_MIN)))
    
    elif strategy == 'largest_file_size':
        # Sum all format file sizes
        def total_file_size(book):
            if not book.data:
                return 0
            return sum(data.uncompressed_size for data in book.data if hasattr(data, 'uncompressed_size') and data.uncompressed_size)
        
        # Keep book with largest total file size, fallback to newest if tie
        return max(books, key=lambda b: (total_file_size(b), _timestamp_or_default(b.timestamp, _AWARE_MIN)))
    
    else:
        # Default fallback: keep newest
        return max(books, key=lambda b: _timestamp_or_default(b.timestamp, _AWARE_MIN))


def get_unresolved_duplicate_count(user_id=None):
    """Get count of unresolved duplicate groups for a user
    
    Args:
        user_id: User ID (defaults to current_user.id)
        
    Returns:
        Integer count of unresolved duplicate groups
    """
    if user_id is None:
        user_id = current_user.id
    
    try:
        # Get all duplicate groups
        duplicate_groups = find_duplicate_books(include_dismissed=False, user_id=user_id)
        return len(duplicate_groups)
    except Exception as e:
        log.error("[cwa-duplicates] Error counting unresolved duplicates: %s", str(e))
        return 0


def filter_dismissed_groups(duplicate_groups, user_id=None):
    """Filter dismissed duplicate groups for a given user."""
    if not duplicate_groups:
        return []
    if user_id is None:
        try:
            user_id = current_user.id
        except Exception:
            user_id = None
    if not user_id:
        return duplicate_groups

    try:
        dismissed_groups = ub.session.query(ub.DismissedDuplicateGroup.group_hash)\
            .filter(ub.DismissedDuplicateGroup.user_id == user_id)\
            .all()
        dismissed_hashes = {row[0] for row in dismissed_groups}
        if not dismissed_hashes:
            return duplicate_groups
        return [group for group in duplicate_groups if group.get('group_hash') not in dismissed_hashes]
    except Exception as e:
        log.error("[cwa-duplicates] Error filtering dismissed groups: %s", str(e))
        return duplicate_groups


@duplicates.route("/duplicates")
@login_required_if_no_ano
@admin_or_edit_required
def show_duplicates():
    """Display books with duplicate titles and authors"""
    print("[cwa-duplicates] Loading duplicates page...", flush=True)
    log.info("[cwa-duplicates] Loading duplicates page for user: %s", current_user.name)
    
    try:
        # Use SQL/Python detection to find all duplicates once, then filter for current user
        all_groups = find_duplicate_books(include_dismissed=True)
        duplicate_groups = filter_dismissed_groups(all_groups, current_user.id if current_user else None)

        # Update cache so notifications reflect the latest scan
        try:
            max_book_id = 0
            try:
                max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                max_book_id = max_id_result if max_id_result is not None else 0
            except Exception as max_ex:
                log.warning("[cwa-duplicates] Could not get max book ID for cache update: %s", str(max_ex))

            cwa_db_cache = CWA_DB()
            cwa_db_cache.update_duplicate_cache(all_groups, len(all_groups), max_book_id)
            log.debug("[cwa-duplicates] Cache updated from /duplicates page load")
        except Exception as cache_ex:
            log.warning("[cwa-duplicates] Failed to update cache from /duplicates page: %s", str(cache_ex))

        # Compute next scheduled scan run
        cwa_db = CWA_DB()
        next_scan_run = get_next_duplicate_scan_run(cwa_db.cwa_settings)
        
        print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
        log.info("[cwa-duplicates] Found %s duplicate groups total", len(duplicate_groups))
        
        return render_title_template('duplicates.html', 
                                     duplicate_groups=duplicate_groups,
                                     next_scan_run=next_scan_run,
                                     title=_("Duplicate Books"), 
                                     page="duplicates")
                                     
    except Exception as e:
        print(f"[cwa-duplicates] Critical error loading duplicates page: {str(e)}", flush=True)
        log.error("[cwa-duplicates] Critical error loading duplicates page: %s", str(e))
        # Return empty page on error
        return render_title_template('duplicates.html', 
                                     duplicate_groups=[],
                                     next_scan_run=None,
                                     title=_("Duplicate Books"), 
                                     page="duplicates")


def get_next_duplicate_scan_run(settings):
    """Compute next scheduled duplicate scan run time based on settings."""
    try:
        enabled = bool(settings.get('duplicate_scan_enabled', 0))
        cron_expr = (settings.get('duplicate_scan_cron') or '').strip()

        if not enabled:
            return None

        if not cron_expr:
            return None

        from apscheduler.triggers.cron import CronTrigger
        now = datetime.now().astimezone()
        trigger = CronTrigger.from_crontab(cron_expr, timezone=now.tzinfo)
        next_run = trigger.get_next_fire_time(None, now)
        return next_run.isoformat() if next_run else None
    except Exception:
        return None


def find_duplicate_books(include_dismissed=False, user_id=None):
    """Find books with duplicate combinations based on configurable criteria
    
    Args:
        include_dismissed: If False, filter out dismissed groups for the user
        user_id: User ID for dismissed filtering (defaults to current_user.id)
    
    Returns:
        List of duplicate group dictionaries
    """
    import time
    start_time = time.perf_counter()
    
    if user_id is None:
        try:
            if hasattr(current_user, 'id'):
                user_id = current_user.id
        except Exception:
            # current_user may be unavailable outside a request context
            user_id = None
    
    try:
        # Get CWA settings for duplicate detection
        cwa_db = CWA_DB()
        settings = cwa_db.cwa_settings
        
        # Check if duplicate detection is enabled
        detection_enabled = settings.get('duplicate_detection_enabled', 1)
        if not detection_enabled:
            print("[cwa-duplicates] Duplicate detection is disabled in settings", flush=True)
            return []
            
    except Exception as e:
        print(f"[cwa-duplicates] Error loading CWA settings: {str(e)}, falling back to defaults", flush=True)
        log.error("[cwa-duplicates] Error loading CWA settings: %s, falling back to defaults", str(e))
        # Fallback to safe defaults
        settings = {
            'duplicate_detection_enabled': 1,
            'duplicate_detection_title': 1,
            'duplicate_detection_author': 1,
            'duplicate_detection_language': 1,
            'duplicate_detection_series': 0,
            'duplicate_detection_publisher': 0,
            'duplicate_detection_format': 0,
            'duplicate_detection_use_sql': 1,
            'duplicate_scan_method': 'hybrid'
        }
    
    # Extract duplicate detection criteria
    use_title = settings.get('duplicate_detection_title', 1)
    use_author = settings.get('duplicate_detection_author', 1) 
    use_language = settings.get('duplicate_detection_language', 1)
    use_series = settings.get('duplicate_detection_series', 0)
    use_publisher = settings.get('duplicate_detection_publisher', 0)
    use_format = settings.get('duplicate_detection_format', 0)
    
    # Check SQL method preference
    use_sql = settings.get('duplicate_detection_use_sql', 1)
    scan_method = settings.get('duplicate_scan_method', 'auto')
    
    # Ensure at least one criterion is selected (fallback to title+author if none selected)
    if not any([use_title, use_author, use_language, use_series, use_publisher, use_format]):
        print("[cwa-duplicates] Warning: No duplicate detection criteria selected, falling back to title+author", flush=True)
        log.warning("[cwa-duplicates] No duplicate detection criteria selected, falling back to title+author")
        use_title = 1
        use_author = 1
    
    # Determine which method to use
    method_to_use = 'python'  # Default fallback

    if scan_method == 'python':
        method_to_use = 'python'
    elif scan_method == 'sql':
        # SQL-only is available but still experimental
        method_to_use = 'sql' if not use_format else 'hybrid'
    elif scan_method == 'hybrid':
        method_to_use = 'hybrid'
    else:  # 'auto'
        if use_sql:
            # Prefer hybrid prefilter for safety unless SQL-only is explicitly chosen
            method_to_use = 'hybrid'
        else:
            method_to_use = 'python'
    
    print(f"[cwa-duplicates] Using detection method: {method_to_use}", flush=True)
    print(f"[cwa-duplicates] Using duplicate detection criteria: title={use_title}, author={use_author}, language={use_language}, series={use_series}, publisher={use_publisher}, format={use_format}", flush=True)
    
    # Call appropriate method
    if method_to_use == 'sql':
        duplicate_groups = find_duplicate_books_sql(
            use_title, use_author, use_language, use_series, use_publisher,
            include_dismissed, user_id
        )
    elif method_to_use == 'hybrid':
        # Use SQL as a prefilter to get candidate book IDs, then Python for robust grouping
        candidate_ids = find_duplicate_candidate_ids_sql(use_title, use_author, user_id=user_id)
        if candidate_ids is None:
            print("[cwa-duplicates] Hybrid prefilter unavailable, falling back to full Python scan", flush=True)
            duplicate_groups = find_duplicate_books_python(
                use_title, use_author, use_language, use_series, use_publisher, use_format,
                include_dismissed, user_id
            )
        elif not candidate_ids:
            duplicate_groups = []
        else:
            duplicate_groups = find_duplicate_books_python(
                use_title, use_author, use_language, use_series, use_publisher, use_format,
                include_dismissed, user_id, candidate_ids=candidate_ids
            )
        print("[cwa-duplicates] Hybrid prefilter applied (SQL candidates + Python validation)", flush=True)
    else:
        duplicate_groups = find_duplicate_books_python(
            use_title, use_author, use_language, use_series, use_publisher, use_format,
            include_dismissed, user_id
        )
    
    duration = time.perf_counter() - start_time
    print(f"[cwa-duplicates] Scan completed in {duration:.2f}s using {method_to_use} method", flush=True)
    log.info("[cwa-duplicates] Scan completed in %.2fs using %s method", duration, method_to_use)
    
    # Get max book ID for incremental scanning (from calibre database, not cwa.db)
    max_book_id = 0
    try:
        max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
        max_book_id = max_id_result if max_id_result is not None else 0
    except Exception as e:
        log.warning("[cwa-duplicates] Could not get max book ID: %s", str(e))
    
    # Update cache with performance metrics
    try:
        cwa_db_update = CWA_DB()
        cwa_db_update.cur.execute("""
            UPDATE cwa_duplicate_cache 
            SET scan_duration_seconds = ?, scan_method_used = ?, last_scanned_book_id = ?
            WHERE id = 1
        """, (duration, method_to_use, max_book_id))
        cwa_db_update.con.commit()
    except Exception as e:
        log.warning("[cwa-duplicates] Failed to update performance metrics: %s", str(e))
    
    return duplicate_groups


def find_duplicate_candidate_ids_sql(use_title, use_author, user_id=None, min_book_id=None):
    """SQL-based candidate prefilter for hybrid mode.

    Returns a set of book IDs that are likely part of duplicate groups.
    Uses only title/author prefiltering to remain a safe superset.

    Args:
        use_title: Whether title criteria is enabled
        use_author: Whether author criteria is enabled

    Returns:
        set of int book IDs, empty set if none, or None if prefilter should be skipped
    """
    # If neither title nor author is enabled, prefilter is too risky -> skip
    if not use_title and not use_author:
        return None

    print("[cwa-duplicates] Using SQL hybrid prefilter (candidate IDs)", flush=True)

    # Note: these GROUP BY fields are evaluated by SQLite at query time; they are not cached
    # groupings in memory. We only use this query to prefilter candidate IDs.
    group_by_fields = []

    norm_title = None
    primary_author = None

    if use_author:
        norm_author_sort = func.lower(func.trim(func.coalesce(db.Books.author_sort, 'unknown')))
        primary_author = case(
            (func.instr(norm_author_sort, '&') > 0,
             func.substr(norm_author_sort, 1, func.instr(norm_author_sort, '&') - 1)),
            else_=norm_author_sort
        )
        group_by_fields.append(primary_author)

    if use_title:
        norm_title = func.lower(func.trim(func.coalesce(db.Books.title, 'untitled')))
        if primary_author is not None:
            author_prefix = primary_author + ', '
            norm_title = case(
                (norm_title.like(author_prefix + '%'),
                 func.trim(func.substr(norm_title, func.length(primary_author) + 3))),
                else_=norm_title
            )
        group_by_fields.append(norm_title)

    max_id_field = func.max(db.Books.id).label('max_book_id')

    query = (calibre_db.session.query(
                func.count(func.distinct(db.Books.id)).label('book_count'),
                func.group_concat(func.distinct(db.Books.id)).label('book_ids_str'),
                max_id_field
            )
            .select_from(db.Books)
            .filter(get_common_filters(user_id=user_id))
            .group_by(*group_by_fields)
            .having(func.count(func.distinct(db.Books.id)) > 1))

    if min_book_id is not None:
        query = query.having(max_id_field >= int(min_book_id))

    # Debug: print the actual SQL being executed
    try:
        from sqlalchemy.dialects import sqlite
        compiled = query.statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
        print(f"[cwa-duplicates] SQL prefilter query:\n{compiled}", flush=True)
    except Exception as debug_ex:
        print(f"[cwa-duplicates] Could not compile SQL for debug: {debug_ex}", flush=True)

    try:
        print(f"[cwa-duplicates] Executing SQL prefilter query (min_book_id={min_book_id})...", flush=True)
        results = query.all()
        print(f"[cwa-duplicates] SQL prefilter query completed, got {len(results)} result rows", flush=True)
    except Exception as e:
        log.error("[cwa-duplicates] Hybrid prefilter SQL failed: %s", str(e))
        print(f"[cwa-duplicates] Hybrid prefilter SQL failed: {str(e)}", flush=True)
        return None

    candidate_ids = set()
    for row in results:
        if not row.book_ids_str:
            continue
        candidate_ids.update(int(bid) for bid in row.book_ids_str.split(',') if bid)

    print(f"[cwa-duplicates] Hybrid prefilter returned {len(candidate_ids)} candidate books", flush=True)
    return candidate_ids


def find_duplicate_books_sql(use_title, use_author, use_language, use_series, use_publisher,
                              include_dismissed=False, user_id=None):
    """SQL-based duplicate detection using GROUP BY - experimental/WIP
    
    NOTE: This is experimental code, disabled by default. Needs refinement:
    - Multi-author books create duplicate rows (handled by DISTINCT but not ideal)
    - Relies on COALESCE for NULL handling which may not match Python behavior exactly
    - Not thoroughly tested across all criteria combinations
    
    Use Python method (default) for production until this is properly tested.
    
    Args:
        use_title, use_author, use_language, use_series, use_publisher: Boolean flags for criteria
        include_dismissed: If False, filter out dismissed groups
        user_id: User ID for dismissed filtering
    
    Returns:
        List of duplicate group dictionaries
    """
    print("[cwa-duplicates] Using SQL-based duplicate detection", flush=True)
    
    # Build dynamic GROUP BY clause based on criteria
    group_by_fields = []
    select_fields = []
    
    if use_title:
        group_by_fields.append(func.lower(db.Books.title))
        select_fields.append(func.lower(db.Books.title).label('norm_title'))
    
    if use_author:
        group_by_fields.append(func.lower(db.Authors.name))
        select_fields.append(func.lower(db.Authors.name).label('norm_author'))
    
    if use_language:
        # Use COALESCE to handle NULL languages (books without language)
        group_by_fields.append(func.coalesce(func.lower(db.Languages.lang_code), 'unknown'))
        select_fields.append(func.coalesce(func.lower(db.Languages.lang_code), 'unknown').label('norm_language'))
    
    if use_series:
        # Use COALESCE to handle NULL series (books without series)
        group_by_fields.append(func.coalesce(func.lower(db.Series.name), 'no_series'))
        select_fields.append(func.coalesce(func.lower(db.Series.name), 'no_series').label('norm_series'))
    
    if use_publisher:
        # Use COALESCE to handle NULL publishers (books without publisher)
        group_by_fields.append(func.coalesce(func.lower(db.Publishers.name), 'unknown_publisher'))
        select_fields.append(func.coalesce(func.lower(db.Publishers.name), 'unknown_publisher').label('norm_publisher'))
    
    # Add count and aggregated book IDs
    # Use DISTINCT because LEFT JOINs can create duplicate rows for books with multiple languages/series/publishers
    select_fields.extend([
        func.count(func.distinct(db.Books.id)).label('book_count'),
        func.group_concat(func.distinct(db.Books.id)).label('book_ids_str')
    ])
    
    # Build query starting from Books table with explicit joins
    query = calibre_db.session.query(*select_fields).select_from(db.Books)
    
    # Join required tables based on criteria
    # Note: Books with multiple authors/languages/etc will create multiple rows - handled by DISTINCT in count
    if use_author:
        # Join to get author (books_authors_link has no ordering column, Python uses first from relationship)
        query = query.join(db.books_authors_link, db.Books.id == db.books_authors_link.c.book)\
                     .join(db.Authors, db.books_authors_link.c.author == db.Authors.id)
    
    if use_language:
        # LEFT JOIN to include books without languages (handled by COALESCE)
        query = query.outerjoin(db.books_languages_link, db.Books.id == db.books_languages_link.c.book)\
                     .outerjoin(db.Languages, db.books_languages_link.c.lang_code == db.Languages.id)
    
    if use_series:
        # LEFT JOIN to include books without series (handled by COALESCE)
        query = query.outerjoin(db.books_series_link, db.Books.id == db.books_series_link.c.book)\
                     .outerjoin(db.Series, db.books_series_link.c.series == db.Series.id)
    
    if use_publisher:
        # LEFT JOIN to include books without publishers (handled by COALESCE)
        query = query.outerjoin(db.books_publishers_link, db.Books.id == db.books_publishers_link.c.book)\
                     .outerjoin(db.Publishers, db.books_publishers_link.c.publisher == db.Publishers.id)
    
    # Apply common filters for user permissions
    query = query.filter(get_common_filters(user_id=user_id))
    
    # Group by selected criteria
    query = query.group_by(*group_by_fields)
    
    # Only get groups with 2+ books (duplicates)
    query = query.having(func.count(func.distinct(db.Books.id)) > 1)
    
    # Execute query
    try:
        results = query.all()
        print(f"[cwa-duplicates] SQL query returned {len(results)} duplicate groups", flush=True)
    except Exception as e:
        log.error("[cwa-duplicates] SQL query failed: %s, falling back to Python method", str(e))
        print(f"[cwa-duplicates] SQL query failed: {str(e)}, falling back to Python method", flush=True)
        return find_duplicate_books_python(
            use_title, use_author, use_language, use_series, use_publisher, False,
            include_dismissed, user_id
        )
    
    # Process results into duplicate groups
    duplicate_groups = []
    
    for result in results:
        # Parse book IDs from group_concat result
        book_ids_str = result.book_ids_str
        book_ids = [int(bid) for bid in book_ids_str.split(',')]
        
        # Load full book objects for these IDs with eager loading
        books = (calibre_db.session.query(db.Books)
                .options(joinedload(db.Books.data))
                .options(joinedload(db.Books.authors))
                .filter(db.Books.id.in_(book_ids))
                .filter(get_common_filters(user_id=user_id))
                .order_by(db.Books.timestamp.desc())
                .all())
        
        if len(books) < 2:
            continue  # Safety check
        
        # Prepare display data
        for book in books:
            # Ensure we have ordered authors
            if not hasattr(book, 'ordered_authors') or not book.ordered_authors:
                book.ordered_authors = calibre_db.order_authors([book])
            
            # Handle potential missing authors
            if book.ordered_authors and len(book.ordered_authors) > 0:
                book.author_names = ', '.join([author.name.replace('|', ',') for author in book.ordered_authors if author.name])
            else:
                book.author_names = 'Unknown'
            
            # Add cover URL
            if hasattr(book, 'has_cover') and book.has_cover:
                book.cover_url = f"/cover/{book.id}"
            else:
                book.cover_url = "/static/generic_cover.svg"
        
        # Get safe title and author for display
        display_title = books[0].title if books[0].title else 'Untitled'
        display_author = 'Unknown'
        if hasattr(books[0], 'author_names') and books[0].author_names:
            display_author = books[0].author_names.split(',')[0].strip()
        
        # Generate group hash for dismiss tracking
        group_hash = generate_group_hash(display_title, display_author)
        
        duplicate_groups.append({
            'title': display_title,
            'author': display_author,
            'count': len(books),
            'books': books,
            'group_hash': group_hash
        })
        
        print(f"[cwa-duplicates] Found duplicate group: '{display_title}' by {display_author} ({len(books)} copies) - IDs: {book_ids}", flush=True)
        log.info("[cwa-duplicates] Found duplicate group: '%s' by %s (%s copies) - IDs: %s", 
                display_title, display_author, len(books), book_ids)
    
    # Filter out dismissed groups if requested
    if not include_dismissed and user_id:
        try:
            dismissed_hashes = set()
            dismissed_groups = ub.session.query(ub.DismissedDuplicateGroup.group_hash)\
                .filter(ub.DismissedDuplicateGroup.user_id == user_id)\
                .all()
            dismissed_hashes = {row[0] for row in dismissed_groups}
            
            if dismissed_hashes:
                original_count = len(duplicate_groups)
                duplicate_groups = [group for group in duplicate_groups 
                                  if group['group_hash'] not in dismissed_hashes]
                filtered_count = original_count - len(duplicate_groups)
                if filtered_count > 0:
                    print(f"[cwa-duplicates] Filtered out {filtered_count} dismissed groups for user {user_id}", flush=True)
                    log.info("[cwa-duplicates] Filtered out %s dismissed groups for user %s", 
                            filtered_count, user_id)
        except Exception as e:
            log.error("[cwa-duplicates] Error filtering dismissed groups: %s", str(e))
    
    # Sort by title, then author for consistent display
    duplicate_groups.sort(key=lambda x: (x['title'].lower(), x['author'].lower()))
    
    print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
    
    return duplicate_groups


def find_duplicate_books_python(use_title, use_author, use_language, use_series, use_publisher, use_format,
                                 include_dismissed=False, user_id=None, candidate_ids=None):
    """Original Python-based duplicate detection - fallback for complex scenarios
    
    Args:
        use_title, use_author, use_language, use_series, use_publisher, use_format: Boolean flags
        include_dismissed: If False, filter out dismissed groups
        user_id: User ID for dismissed filtering
    
    Returns:
        List of duplicate group dictionaries
    """
    print("[cwa-duplicates] Using Python-based duplicate detection", flush=True)
    
    # Get all books with proper user filtering - this is much simpler and more reliable
    # than trying to do complex joins for duplicate detection
    books_query = (calibre_db.session.query(db.Books)
                   .filter(get_common_filters(user_id=user_id))  # Respect user permissions and library filtering
                   .order_by(db.Books.title, db.Books.timestamp.desc()))

    if candidate_ids is not None:
        if not candidate_ids:
            print("[cwa-duplicates] No candidate IDs provided, returning empty duplicate set", flush=True)
            return []
        books_query = books_query.filter(db.Books.id.in_(list(candidate_ids)))
    
    all_books = books_query.all()
    print(f"[cwa-duplicates] Retrieved {len(all_books)} books with user filtering applied", flush=True)
    
    # Safety check for very large libraries (optional performance warning)
    if len(all_books) > 50000:
        print(f"[cwa-duplicates] Warning: Processing {len(all_books)} books may take some time", flush=True)
        log.warning("[cwa-duplicates] Processing large library: %s books", len(all_books))
    
    # Group books by configurable criteria combination (case-insensitive)
    grouped_books = {}
    
    for book in all_books:
        # Build key based on selected criteria
        key_parts = []

        primary_author = None
        if use_author:
            # Ensure authors are loaded and not empty
            if book.authors and len(book.authors) > 0:
                # Get primary author (use Calibre-Web's standard approach)
                book.ordered_authors = calibre_db.order_authors([book])
                primary_author = book.ordered_authors[0].name if book.ordered_authors and len(book.ordered_authors) > 0 else "unknown"
            else:
                primary_author = "unknown"
        
        if use_title:
            # Handle potential None title
            title = book.title if book.title else "untitled"
            key_parts.append(normalize_title_for_duplicates(title, primary_author))

        if use_author:
            key_parts.append(primary_author.lower().strip() if primary_author else "unknown")
        
        if use_language:
            # Get primary language code
            if book.languages and len(book.languages) > 0:
                primary_language = book.languages[0].lang_code if book.languages[0].lang_code else "unknown"
                key_parts.append(primary_language.lower().strip())
            else:
                key_parts.append("unknown")
        
        if use_series:
            # Get series name
            if book.series and len(book.series) > 0:
                series_name = book.series[0].name if book.series[0].name else "no_series"
                key_parts.append(series_name.lower().strip())
            else:
                key_parts.append("no_series")
        
        if use_publisher:
            # Get publisher name
            if book.publishers and len(book.publishers) > 0:
                publisher_name = book.publishers[0].name if book.publishers[0].name else "unknown_publisher"
                key_parts.append(publisher_name.lower().strip())
            else:
                key_parts.append("unknown_publisher")
        
        if use_format:
            # Get file formats (consider books with same formats as potentially duplicate)
            if book.data and len(book.data) > 0:
                formats = sorted([data.format.lower() for data in book.data if data.format])
                format_str = ",".join(formats) if formats else "no_format"
                key_parts.append(format_str)
            else:
                key_parts.append("no_format")
        
        # Create composite key
        key = tuple(key_parts)
        
        if key not in grouped_books:
            grouped_books[key] = []
        grouped_books[key].append(book)
    
    print(f"[cwa-duplicates] Grouped books into {len(grouped_books)} unique combinations based on selected criteria", flush=True)
    
    # Filter to only groups with duplicates and prepare display data
    duplicate_groups = []
    for key, books in grouped_books.items():
        if len(books) > 1:
            # Sort books by timestamp (newest first)
            books.sort(key=lambda x: _timestamp_or_default(x.timestamp, _AWARE_MIN), reverse=True)
            
            # Add additional information for display
            for book in books:
                # Ensure we have ordered authors
                if not hasattr(book, 'ordered_authors') or not book.ordered_authors:
                    book.ordered_authors = calibre_db.order_authors([book])
                
                # Handle potential missing authors
                if book.ordered_authors and len(book.ordered_authors) > 0:
                    book.author_names = ', '.join([author.name.replace('|', ',') for author in book.ordered_authors if author.name])
                else:
                    book.author_names = 'Unknown'
                
                # Add cover URL
                if hasattr(book, 'has_cover') and book.has_cover:
                    book.cover_url = f"/cover/{book.id}"
                else:
                    book.cover_url = "/static/generic_cover.svg"
            
            # Get safe title and author for display
            display_title = books[0].title if books[0].title else 'Untitled'
            display_author = 'Unknown'
            if hasattr(books[0], 'author_names') and books[0].author_names:
                display_author = books[0].author_names.split(',')[0].strip()
            
            # Generate group hash for dismiss tracking
            group_hash = generate_group_hash(display_title, display_author)
            
            duplicate_groups.append({
                'title': display_title,
                'author': display_author,
                'count': len(books),
                'books': books,
                'group_hash': group_hash
            })
            
            book_ids = [book.id for book in books]
            print(f"[cwa-duplicates] Found duplicate group: '{display_title}' by {display_author} ({len(books)} copies) - IDs: {book_ids}", flush=True)
            log.info("[cwa-duplicates] Found duplicate group: '%s' by %s (%s copies) - IDs: %s", 
                    display_title, display_author, len(books), book_ids)
    
    # Filter out dismissed groups if requested
    if not include_dismissed and user_id:
        try:
            dismissed_hashes = set()
            dismissed_groups = ub.session.query(ub.DismissedDuplicateGroup.group_hash)\
                .filter(ub.DismissedDuplicateGroup.user_id == user_id)\
                .all()
            dismissed_hashes = {row[0] for row in dismissed_groups}
            
            if dismissed_hashes:
                original_count = len(duplicate_groups)
                duplicate_groups = [group for group in duplicate_groups 
                                  if group['group_hash'] not in dismissed_hashes]
                filtered_count = original_count - len(duplicate_groups)
                if filtered_count > 0:
                    print(f"[cwa-duplicates] Filtered out {filtered_count} dismissed groups for user {user_id}", flush=True)
                    log.info("[cwa-duplicates] Filtered out %s dismissed groups for user %s", 
                            filtered_count, user_id)
        except Exception as e:
            log.error("[cwa-duplicates] Error filtering dismissed groups: %s", str(e))
    
    # Sort by title, then author for consistent display
    duplicate_groups.sort(key=lambda x: (x['title'].lower(), x['author'].lower()))
    
    print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
    
    return duplicate_groups


def get_common_filters(user_id=None, allow_show_archived=False, return_all_languages=False):
    """Build common filters using either current_user or a specific user_id.

    Falls back to no-op filters if user context is unavailable.
    """
    try:
        if user_id is None:
            return calibre_db.common_filters(allow_show_archived=allow_show_archived,
                                             return_all_languages=return_all_languages)
    except Exception:
        # No request context; fall back to permissive filter
        return true()

    try:
        user = ub.session.query(ub.User).filter(ub.User.id == int(user_id)).first()
        if not user:
            return true()

        if not allow_show_archived:
            archived_books = (ub.session.query(ub.ArchivedBook)
                              .filter(ub.ArchivedBook.user_id == int(user.id))
                              .filter(ub.ArchivedBook.is_archived == True)
                              .all())
            archived_book_ids = [archived_book.book_id for archived_book in archived_books]
            archived_filter = db.Books.id.notin_(archived_book_ids)
        else:
            archived_filter = true()

        if user.filter_language() == "all" or return_all_languages:
            lang_filter = true()
        else:
            lang_filter = db.Books.languages.any(db.Languages.lang_code == user.filter_language())

        negtags_list = user.list_denied_tags()
        postags_list = user.list_allowed_tags()
        neg_content_tags_filter = false() if negtags_list == [''] else db.Books.tags.any(db.Tags.name.in_(negtags_list))
        pos_content_tags_filter = true() if postags_list == [''] else db.Books.tags.any(db.Tags.name.in_(postags_list))

        if config.config_restricted_column:
            try:
                pos_cc_list = (user.allowed_column_value or '').split(',')
                pos_content_cc_filter = true() if pos_cc_list == [''] else \
                    getattr(db.Books, 'custom_column_' + str(config.config_restricted_column)). \
                    any(db.cc_classes[config.config_restricted_column].value.in_(pos_cc_list))
                neg_cc_list = (user.denied_column_value or '').split(',')
                neg_content_cc_filter = false() if neg_cc_list == [''] else \
                    getattr(db.Books, 'custom_column_' + str(config.config_restricted_column)). \
                    any(db.cc_classes[config.config_restricted_column].value.in_(neg_cc_list))
            except Exception:
                pos_content_cc_filter = false()
                neg_content_cc_filter = true()
        else:
            pos_content_cc_filter = true()
            neg_content_cc_filter = false()

        return and_(lang_filter, pos_content_tags_filter, ~neg_content_tags_filter,
                    pos_content_cc_filter, ~neg_content_cc_filter, archived_filter)
    except Exception:
        return true()


@duplicates.route("/duplicates/status")
@login_required_if_no_ano
@admin_or_edit_required
def get_duplicate_status():
    """API endpoint to get unresolved duplicate count and sample groups
    
    Returns JSON with:
        - enabled: Whether notifications are enabled
        - count: Number of unresolved duplicate groups
        - preview: List of up to 3 sample duplicate groups
    """
    try:
        # Check if duplicate detection is enabled
        cwa_db = CWA_DB()
        detection_enabled = cwa_db.cwa_settings.get('duplicate_detection_enabled', 1)
        
        if not detection_enabled:
            return jsonify({
                'success': True,
                'enabled': False,
                'count': 0,
                'preview': []
            })
        
        # Check if notifications are enabled
        notifications_enabled = cwa_db.cwa_settings.get('duplicate_notifications_enabled', 1)
        
        # Try to get cached results first
        cache_data = cwa_db.get_duplicate_cache()
        
        if cache_data and cache_data.get('duplicate_groups') is not None:
            # Cache is available; use it even if scan is pending
            duplicate_groups = cache_data['duplicate_groups']
            
            # Filter out dismissed groups for this user
            duplicate_groups = filter_dismissed_groups(
                duplicate_groups,
                current_user.id if current_user and current_user.id else None
            )
            
            count = len(duplicate_groups)
            
            # Get preview of first 3 groups
            preview = []
            for group in duplicate_groups[:3]:
                preview.append({
                    'title': group['title'],
                    'author': group['author'],
                    'count': group['count'],
                    'hash': group['group_hash']
                })

            return jsonify({
                'success': True,
                'enabled': bool(notifications_enabled),
                'count': count,
                'preview': preview,
                'cached': True,
                'stale': bool(cache_data.get('scan_pending')),
                'needs_scan': bool(cache_data.get('scan_pending'))
            })
        
        # Cache is missing - DO NOT trigger scan here!
        # This endpoint is called on every page load via duplicate-notifier.js
        # Scans should ONLY be triggered by:
        # 1. Manual "Trigger Scan" button on /duplicates page (via /duplicates/trigger-scan)
        # 2. After ingest operations (via cache invalidation + manual trigger)
        # 3. Scheduled background scans (Phase 2 - not yet implemented)
        log.debug("[cwa-duplicates] Cache invalid/pending in status check, returning empty (no auto-scan)")
        
        return jsonify({
            'success': True,
            'enabled': bool(notifications_enabled),
            'count': 0,
            'preview': [],
            'cached': False,
            'needs_scan': True  # Frontend can optionally show "scan needed" message
        })
    except Exception as e:
        log.error("[cwa-duplicates] Error getting duplicate status: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e),
            'count': 0,
            'preview': []
        }), 500


@duplicates.route("/duplicates/dismiss/<group_hash>", methods=['POST'])
@login_required_if_no_ano
@admin_or_edit_required
def dismiss_duplicate_group(group_hash):
    """API endpoint to dismiss a duplicate group
    
    Args:
        group_hash: MD5 hash of the duplicate group
        
    Returns:
        JSON response with success status and new count
    """
    try:
        # Check if already dismissed
        existing = ub.session.query(ub.DismissedDuplicateGroup)\
            .filter(ub.DismissedDuplicateGroup.user_id == current_user.id)\
            .filter(ub.DismissedDuplicateGroup.group_hash == group_hash)\
            .first()
        
        if existing:
            return jsonify({
                'success': True,
                'message': _('Duplicate group already dismissed'),
                'count': get_unresolved_duplicate_count()
            })
        
        # Create dismissal record
        dismissal = ub.DismissedDuplicateGroup(
            user_id=current_user.id,
            group_hash=group_hash
        )
        ub.session.add(dismissal)
        ub.session.commit()
        
        log.info("[cwa-duplicates] User %s dismissed duplicate group %s", 
                current_user.name, group_hash)
        
        # Get new count
        new_count = get_unresolved_duplicate_count()
        
        return jsonify({
            'success': True,
            'message': _('Duplicate group dismissed'),
            'count': new_count
        })
        
    except Exception as e:
        ub.session.rollback()
        log.error("[cwa-duplicates] Error dismissing duplicate group: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@duplicates.route("/duplicates/undismiss/<group_hash>", methods=['POST'])
@login_required_if_no_ano
@admin_or_edit_required
def undismiss_duplicate_group(group_hash):
    """API endpoint to un-dismiss a duplicate group
    
    Args:
        group_hash: MD5 hash of the duplicate group
        
    Returns:
        JSON response with success status and new count
    """
    try:
        # Find and delete dismissal record
        deleted = ub.session.query(ub.DismissedDuplicateGroup)\
            .filter(ub.DismissedDuplicateGroup.user_id == current_user.id)\
            .filter(ub.DismissedDuplicateGroup.group_hash == group_hash)\
            .delete()
        
        ub.session.commit()
        
        if deleted:
            log.info("[cwa-duplicates] User %s un-dismissed duplicate group %s", 
                    current_user.name, group_hash)
            message = _('Duplicate group restored')
        else:
            message = _('Duplicate group was not dismissed')
        
        # Get new count
        new_count = get_unresolved_duplicate_count()
        
        return jsonify({
            'success': True,
            'message': message,
            'count': new_count
        })
        
    except Exception as e:
        ub.session.rollback()
        log.error("[cwa-duplicates] Error un-dismissing duplicate group: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@duplicates.route("/duplicates/invalidate-cache", methods=['POST'])
@csrf.exempt
def invalidate_cache():
    """Internal endpoint to invalidate duplicate cache (called after ingest)"""
    try:
        cwa_db = CWA_DB()
        success = cwa_db.invalidate_duplicate_cache()
        
        if success:
            log.info("[cwa-duplicates] Cache invalidated - will refresh on next status check")
            return jsonify({'success': True, 'message': 'Cache invalidated'})
        else:
            return jsonify({'success': False, 'error': 'Failed to invalidate cache'}), 500
            
    except Exception as e:
        log.error("[cwa-duplicates] Error invalidating cache: %s", str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@duplicates.route("/duplicates/trigger-scan", methods=['POST'])
@csrf.exempt
@login_required_if_no_ano
@admin_or_edit_required
def trigger_scan():
    """Manually trigger a duplicate scan"""
    try:
        # Invalidate cache and run fresh scan
        cwa_db = CWA_DB()
        cwa_db.invalidate_duplicate_cache()

        # Queue background task
        try:
            from cps.tasks.duplicate_scan import TaskDuplicateScan
            task = TaskDuplicateScan(full_scan=True, trigger_type='manual', user_id=current_user.id)
            WorkerThread.add(current_user.name, task, hidden=False)

            log.info("[cwa-duplicates] Manual scan queued by user %s (task_id=%s)", 
                    current_user.name, task.id)
            print(f"[cwa-duplicates] Manual scan queued for user {current_user.name}, task_id={task.id}", flush=True)

            return jsonify({
                'success': True,
                'message': _('Duplicate scan queued'),
                'task_id': str(task.id),
                'queued': True
            })
        except Exception as e:
            log.error("[cwa-duplicates] Failed to queue scan task, falling back to sync scan: %s", str(e))
            print(f"[cwa-duplicates] Failed to queue task, using fallback: {str(e)}", flush=True)

            # Fallback to synchronous scan to avoid hard failures
            duplicate_groups = find_duplicate_books(include_dismissed=False)
            max_book_id = 0
            try:
                max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                max_book_id = max_id_result if max_id_result is not None else 0
            except Exception as ex:
                log.warning("[cwa-duplicates] Could not get max book ID in trigger_scan fallback: %s", str(ex))

            all_groups = find_duplicate_books(include_dismissed=True)
            cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)

            # Check if auto-resolution is enabled for fallback sync scan
            if len(duplicate_groups) > 0:
                try:
                    auto_resolve_enabled = cwa_db.cwa_settings.get('duplicate_auto_resolve_enabled', 0)
                    auto_resolve_strategy = cwa_db.cwa_settings.get('duplicate_auto_resolve_strategy', 'newest')
                    
                    if auto_resolve_enabled:
                        log.info("[cwa-duplicates] Auto-resolution enabled in fallback, triggering with strategy: %s", 
                                auto_resolve_strategy)
                        print(f"[cwa-duplicates] Fallback scan complete, triggering auto-resolution (strategy: {auto_resolve_strategy})", 
                              flush=True)
                        
                        # Pass the pre-scanned duplicate groups to avoid re-scanning
                        result = auto_resolve_duplicates(
                            strategy=auto_resolve_strategy,
                            dry_run=False,
                            user_id=current_user.id if current_user else None,
                            trigger_type='manual',
                            duplicate_groups=duplicate_groups
                        )
                        
                        if result['success'] and result['resolved_count'] > 0:
                            log.info("[cwa-duplicates] Fallback auto-resolution completed: resolved=%s, kept=%s, deleted=%s",
                                    result['resolved_count'], result['kept_count'], result['deleted_count'])
                            print(f"[cwa-duplicates] Fallback auto-resolution completed: {result['resolved_count']} groups resolved", 
                                  flush=True)
                            
                            # Re-scan to get updated counts after resolution
                            duplicate_groups = find_duplicate_books(include_dismissed=False)
                            all_groups = find_duplicate_books(include_dismissed=True)
                            cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)
                            log.debug("[cwa-duplicates] Cache refreshed after fallback auto-resolution")
                except Exception as ex:
                    log.error("[cwa-duplicates] Error during fallback auto-resolution: %s", str(ex))
                    print(f"[cwa-duplicates] Fallback auto-resolution error: {str(ex)}", flush=True)

            return jsonify({
                'success': True,
                'message': _('Duplicate scan completed (fallback)'),
                'count': len(duplicate_groups),
                'fallback': True,
                'queued': False,
                'fallback_reason': str(e)
            })
        
    except Exception as e:
        log.error("[cwa-duplicates] Error triggering scan: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@duplicates.route("/duplicates/scan-progress/<task_id>", methods=['GET'])
@login_required_if_no_ano
@admin_or_edit_required
def scan_progress(task_id):
    """Get progress for a queued duplicate scan task"""
    try:
        worker = WorkerThread.get_instance()
        task = None
        for __, __, __, queued_task, __ in worker.tasks:
            if str(queued_task.id) == str(task_id):
                task = queued_task
                break

        if task is None:
            return jsonify({'success': False, 'error': 'Task not found'}), 404

        status = 'running'
        if task.stat in (STAT_FINISH_SUCCESS,):
            status = 'completed'
        elif task.stat in (STAT_FAIL,):
            status = 'failed'
        elif task.stat in (STAT_CANCELLED, STAT_ENDED):
            status = 'cancelled'

        message = getattr(task, 'message', '')
        if status == 'failed' and getattr(task, 'error', None):
            message = task.error

        return jsonify({
            'success': True,
            'task_id': str(task.id),
            'progress': task.progress,
            'status': status,
            'message': message,
            'result_count': getattr(task, 'result_count', None)
        })
    except Exception as e:
        log.error("[cwa-duplicates] Error fetching scan progress: %s", str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@duplicates.route("/duplicates/cancel-scan/<task_id>", methods=['POST'])
@csrf.exempt
@login_required_if_no_ano
@admin_or_edit_required
def cancel_scan(task_id):
    """Cancel a running or queued duplicate scan task."""
    try:
        worker = WorkerThread.get_instance()
        worker.end_task(task_id)
        return jsonify({'success': True, 'message': 'Scan cancelled'})
    except Exception as e:
        log.error("[cwa-duplicates] Error cancelling scan: %s", str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@duplicates.route("/duplicates/preview-resolution", methods=["POST"])
@login_required_if_no_ano
@admin_required
def preview_resolution():
    """Preview auto-resolution without executing"""
    print("[cwa-duplicates] Preview resolution endpoint called", flush=True)
    log.info("[cwa-duplicates] Preview resolution endpoint called")
    try:
        from flask import request
        strategy = request.json.get('strategy', 'newest')
        print(f"[cwa-duplicates] Preview strategy: {strategy}", flush=True)
        log.info("[cwa-duplicates] Preview strategy: %s", strategy)
        
        if not validate_resolution_strategy(strategy):
            error_msg = f'Invalid resolution strategy: {strategy}'
            print(f"[cwa-duplicates] {error_msg}", flush=True)
            log.error("[cwa-duplicates] %s", error_msg)
            return jsonify({
                'success': False,
                'error': _(error_msg)
            }), 400
        
        print("[cwa-duplicates] Calling auto_resolve_duplicates in dry_run mode...", flush=True)
        # Note: No duplicate_groups passed - will scan to get fresh data for preview
        result = auto_resolve_duplicates(
            strategy=strategy,
            dry_run=True,
            user_id=current_user.id,
            trigger_type='manual'
        )
        
        print(f"[cwa-duplicates] Preview result: {result.get('success', False)}, resolved_count={result.get('resolved_count', 0)}", flush=True)
        return jsonify(result)
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[cwa-duplicates] Error previewing resolution: {e}\n{error_trace}", flush=True)
        log.error("[cwa-duplicates] Error previewing resolution: %s\n%s", str(e), error_trace)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@duplicates.route("/duplicates/execute-resolution", methods=["POST"])
@login_required_if_no_ano
@admin_required
def execute_resolution():
    """Execute auto-resolution"""
    try:
        from flask import request
        strategy = request.json.get('strategy', 'newest')
        
        if not validate_resolution_strategy(strategy):
            return jsonify({
                'success': False,
                'error': _('Invalid resolution strategy')
            }), 400
        
        # Note: No duplicate_groups passed - will scan to get fresh data for execution
        result = auto_resolve_duplicates(
            strategy=strategy,
            dry_run=False,
            user_id=current_user.id,
            trigger_type='manual'
        )
        
        # Invalidate cache after resolution
        if result['success'] and result['deleted_count'] > 0:
            cwa_db = CWA_DB()
            cwa_db.invalidate_duplicate_cache()
        
        return jsonify(result)
        
    except Exception as e:
        log.error("[cwa-duplicates] Error executing resolution: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def auto_resolve_duplicates(strategy='newest', dry_run=False, user_id=None, trigger_type='manual', duplicate_groups=None):
    """
    Automatically resolve duplicate books by keeping one and deleting others.
    
    Args:
        strategy: Resolution strategy ('newest', 'highest_quality_format', 'most_metadata', 'largest_file_size')
        dry_run: If True, return preview without actually deleting
        user_id: User ID triggering the resolution (for audit), None for system-initiated
        trigger_type: 'manual', 'scheduled', or 'automatic'
        duplicate_groups: Pre-scanned duplicate groups (avoids re-scanning). If None, will scan.
    
    Returns:
        dict with keys:
            'success': bool
            'resolved_count': int (number of groups resolved)
            'deleted_count': int (total books deleted)
            'kept_count': int (total books kept)
            'errors': list of error messages
            'preview': list of dicts (if dry_run=True) with 'group', 'kept_book', 'deleted_books'
    """
    try:
        import time
        start_time = time.time()
        
        log.info("[cwa-duplicates] Starting auto-resolution (strategy=%s, dry_run=%s, trigger=%s, pre_scanned=%s)", 
                 strategy, dry_run, trigger_type, duplicate_groups is not None)
        print(f"[cwa-duplicates] Auto-resolve starting: strategy={strategy}, dry_run={dry_run}, trigger={trigger_type}, " 
              f"pre_scanned={duplicate_groups is not None}", flush=True)
        
        # Initialize database sessions for thread safety
        from cps.ub import init_db_thread
        try:
            init_db_thread()
        except Exception:
            pass
        
        calibre_db.ensure_session()
        
        # Disk space check (strategy-dependent thresholds)
        try:
            import shutil as shutil_disk
            stat = shutil_disk.disk_usage('/config')
            available_gb = stat.free / (1024**3)
            
            # Merge strategy needs more space (copies formats before deletion)
            min_space_gb = 2.0 if strategy == 'merge' else 0.5
            
            if available_gb < min_space_gb:
                log.warning("[cwa-duplicates] Low disk space (%.2f GB available, %.2f GB recommended for %s strategy)", 
                           available_gb, min_space_gb, strategy)
                print(f"[cwa-duplicates] WARNING: Low disk space ({available_gb:.2f} GB available, "
                      f"{min_space_gb:.2f} GB recommended for {strategy} strategy)", flush=True)
                
                if trigger_type == 'automatic' and available_gb < min_space_gb * 0.5:
                    # For automatic triggers, abort if critically low
                    return {
                        'success': False,
                        'resolved_count': 0,
                        'deleted_count': 0,
                        'kept_count': 0,
                        'errors': [f'Insufficient disk space: {available_gb:.2f} GB available, {min_space_gb} GB required']
                    }
        except Exception as e:
            log.debug("[cwa-duplicates] Disk space check failed: %s", str(e))
        
        import shutil
        
        # Validate strategy
        if not validate_resolution_strategy(strategy):
            return {'success': False, 'errors': [f'Invalid strategy: {strategy}']}
        
        # Get duplicate groups (exclude dismissed)
        # If groups were passed in, use them (avoids expensive re-scan)
        if duplicate_groups is None:
            log.debug("[cwa-duplicates] No groups provided, scanning for duplicates...")
            print("[cwa-duplicates] auto_resolve received None groups - will scan", flush=True)
            duplicate_groups = find_duplicate_books(include_dismissed=False)
        else:
            log.debug("[cwa-duplicates] Using %d pre-scanned duplicate groups", len(duplicate_groups))
            print(f"[cwa-duplicates] auto_resolve using {len(duplicate_groups)} pre-scanned groups (type: {type(duplicate_groups).__name__})", 
                  flush=True)
        
        if not duplicate_groups:
            return {
                'success': True,
                'resolved_count': 0,
                'deleted_count': 0,
                'kept_count': 0,
                'errors': [],
                'message': 'No unresolved duplicates found'
            }
        
        result = {
            'success': True,
            'resolved_count': 0,
            'deleted_count': 0,
            'kept_count': 0,
            'errors': [],
            'preview': [] if dry_run else None
        }
        
        cwa_db = CWA_DB()
        
        for group in duplicate_groups:
            try:
                # Select book to keep
                book_to_keep = select_book_to_keep(group['books'], strategy)
                
                if not book_to_keep:
                    result['errors'].append(f"Could not select book to keep for group: {group['title']}")
                    continue
                
                # Get books to delete
                books_to_delete = [b for b in group['books'] if b.id != book_to_keep.id]
                
                if not books_to_delete:
                    continue  # Only one book in group, nothing to resolve
                
                if dry_run:
                    kept_formats = []
                    if book_to_keep.data:
                        for data in book_to_keep.data:
                            if data.format and data.format not in kept_formats:
                                kept_formats.append(data.format)
                    if strategy == 'merge':
                        for book in books_to_delete:
                            if book.data:
                                for data in book.data:
                                    if data.format and data.format not in kept_formats:
                                        kept_formats.append(data.format)
                    # Preview mode: just collect info
                    result['preview'].append({
                        'group_hash': group['group_hash'],
                        'title': group['title'],
                        'author': group['author'],
                        'kept_book_id': book_to_keep.id,
                        'kept_book_timestamp': book_to_keep.timestamp.strftime('%Y-%m-%d %H:%M') if book_to_keep.timestamp else 'Unknown',
                        'kept_book_formats': kept_formats,
                        'deleted_book_ids': [b.id for b in books_to_delete],
                        'deleted_books_info': [{
                            'id': b.id,
                            'timestamp': b.timestamp.strftime('%Y-%m-%d %H:%M') if b.timestamp else 'Unknown',
                            'formats': [d.format for d in b.data] if b.data else []
                        } for b in books_to_delete]
                    })
                    result['kept_count'] += 1
                    result['deleted_count'] += len(books_to_delete)
                    result['resolved_count'] += 1
                    continue
                
                # Actual resolution mode
                # Re-fetch books in the active session to avoid detached object issues
                book_to_keep_id = book_to_keep.id
                books_to_delete_ids = [b.id for b in books_to_delete]
                book_to_keep_ref = calibre_db.get_book(book_to_keep_id)
                if not book_to_keep_ref:
                    result['errors'].append(f"Book to keep (ID {book_to_keep_id}) no longer exists")
                    continue
                books_to_delete = [calibre_db.get_book(book_id) for book_id in books_to_delete_ids]
                books_to_delete = [b for b in books_to_delete if b]
                if not books_to_delete:
                    continue
                book_to_keep = book_to_keep_ref

                deleted_ids = []
                backup_dir = f"/config/processed_books/duplicate_resolutions/{datetime.now().strftime('%Y%m%d_%H%M%S')}_group_{group['group_hash'][:8]}"
                os.makedirs(backup_dir, exist_ok=True)

                if strategy == 'merge':
                    try:
                        merge_duplicate_group(book_to_keep, books_to_delete)
                    except Exception as e:
                        log.error("[cwa-duplicates] Error merging books for group '%s': %s", group.get('title', 'unknown'), e)
                        result['errors'].append(f"Group '{group.get('title', 'unknown')}': merge failed: {str(e)}")
                        continue
                
                # Backup and delete each duplicate
                for book in books_to_delete:
                    try:
                        print(f"[cwa-duplicates-auto] Starting deletion of book {book.id}...", flush=True)
                        
                        # Backup book files
                        book_path = os.path.join(config.config_calibre_dir, book.path)
                        if os.path.exists(book_path):
                            backup_path = os.path.join(backup_dir, f"book_{book.id}")
                            print(f"[cwa-duplicates-auto] Backing up book {book.id} to {backup_path}...", flush=True)
                            shutil.copytree(book_path, backup_path)
                            log.info("[cwa-duplicates] Backed up book %s to %s", book.id, backup_path)
                        
                        print(f"[cwa-duplicates-auto] Deleting book {book.id} from library...", flush=True)
                        # Delete from Calibre library (bypass user permission check for automatic resolution)
                        from cps import helper
                        delete_result, delete_error = helper.delete_book(book, config.get_book_path(), book_format="")
                        
                        if not delete_result:
                            raise Exception(f"Delete failed: {delete_error}")
                        
                        print(f"[cwa-duplicates-auto] Cleaning up database for book {book.id}...", flush=True)
                        # Clean up database references
                        from cps.editbooks import delete_whole_book
                        delete_whole_book(book.id, book)
                        
                        calibre_db.session.commit()
                        deleted_ids.append(book.id)
                        log.info("[cwa-duplicates] Deleted duplicate book %s: %s", book.id, book.title)
                        
                        print(f"[cwa-duplicates-auto] Cancelling tasks for book {book.id}...", flush=True)
                        # Cancel any pending tasks for this book
                        try:
                            from cps.services.worker import WorkerThread
                            worker = WorkerThread.get_instance()
                            if worker:
                                cancelled_count = worker.cancel_tasks_for_book(book.id)
                                if cancelled_count > 0:
                                    log.info("[cwa-duplicates] Cancelled %d pending task(s) for deleted book %s", 
                                            cancelled_count, book.id)
                                    print(f"[cwa-duplicates-auto] Cancelled {cancelled_count} pending task(s) for book {book.id}", 
                                          flush=True)
                        except Exception as cancel_ex:
                            log.warning("[cwa-duplicates] Failed to cancel tasks for book %s: %s", book.id, cancel_ex)
                        
                        print(f"[cwa-duplicates-auto] Cancelling scheduled jobs for book {book.id}...", flush=True)
                        # Cancel any scheduled jobs (auto-send, etc.) for this book
                        try:
                            cancelled_scheduled = cwa_db.scheduled_cancel_for_book(book.id)
                            if cancelled_scheduled > 0:
                                log.info("[cwa-duplicates] Cancelled %d scheduled job(s) for deleted book %s", 
                                        cancelled_scheduled, book.id)
                        except Exception as schedule_ex:
                            log.warning("[cwa-duplicates] Failed to cancel scheduled jobs for book %s: %s", book.id, schedule_ex)
                        
                        print(f"[cwa-duplicates-auto] Book {book.id} deletion complete", flush=True)
                        
                    except Exception as e:
                        log.error("[cwa-duplicates] Error deleting book %s: %s", book.id, e)
                        result['errors'].append(f"Failed to delete book {book.id}: {str(e)}")
                
                if deleted_ids:
                    # Log to audit table
                    cwa_db.log_duplicate_resolution(
                        group_hash=group['group_hash'],
                        group_title=group['title'],
                        group_author=group['author'],
                        kept_book_id=book_to_keep.id,
                        deleted_book_ids=deleted_ids,
                        strategy=strategy,
                        trigger_type=trigger_type,
                        user_id=user_id,
                        notes=f"Resolved {len(deleted_ids)} duplicate(s) using {strategy} strategy"
                    )
                    
                    result['resolved_count'] += 1
                    result['kept_count'] += 1
                    result['deleted_count'] += len(deleted_ids)
                    
                    log.info("[cwa-duplicates] Resolved duplicate group '%s' by %s: kept book %s, deleted %s duplicates", 
                            group['title'], group['author'], book_to_keep.id, len(deleted_ids))
                    
                    # Docker log for automatic triggers
                    if trigger_type == 'automatic':
                        print(f"[cwa-duplicates-auto] ✓ Resolved '{group['title']}' by {group['author']}: "
                              f"kept book {book_to_keep.id}, deleted {len(deleted_ids)} duplicate(s) [{strategy} strategy]", 
                              flush=True)
            
            except Exception as e:
                log.error("[cwa-duplicates] Error resolving duplicate group '%s': %s", group.get('title', 'unknown'), e)
                result['errors'].append(f"Group '{group.get('title', 'unknown')}': {str(e)}")
        

        if result['errors']:
            result['success'] = False
        
        # Invalidate cache if any books were deleted
        if result['deleted_count'] > 0:
            try:
                cwa_db.invalidate_duplicate_cache()
                log.debug("[cwa-duplicates] Duplicate cache invalidated after auto-resolution")
            except Exception as ex:
                log.warning("[cwa-duplicates] Failed to invalidate cache after resolution: %s", str(ex))
        
        # Log timing information
        elapsed_time = time.time() - start_time
        log.info("[cwa-duplicates] Auto-resolution completed in %.2f seconds: resolved=%d, kept=%d, deleted=%d, errors=%d",
                 elapsed_time, result['resolved_count'], result['kept_count'], result['deleted_count'], len(result['errors']))
        print(f"[cwa-duplicates] Auto-resolution completed in {elapsed_time:.2f}s: "
              f"resolved={result['resolved_count']}, kept={result['kept_count']}, deleted={result['deleted_count']}, "
              f"errors={len(result['errors'])}", flush=True)
        
        return result
        
    finally:
        # Always cleanup sessions
        try:
            if calibre_db.session is not None:
                calibre_db.session.close()
        except Exception:
            pass


def merge_duplicate_group(book_to_keep, books_to_merge):
    """Merge formats from duplicate books into the target book."""
    if not book_to_keep or not books_to_merge:
        return

    to_book = calibre_db.get_book(book_to_keep.id)
    if not to_book:
        raise ValueError("Target book not found for merge")

    existing_formats = [file.format for file in to_book.data] if to_book.data else []
    author_name = "unknown"
    if to_book.authors:
        author_name = to_book.authors[0].name
    to_name = helper.get_valid_filename(to_book.title, chars=96) + ' - ' + helper.get_valid_filename(author_name, chars=96)

    for source in books_to_merge:
        from_book = calibre_db.get_book(source.id)
        if not from_book:
            continue
        for element in from_book.data:
            if element.format not in existing_formats:
                filepath_new = os.path.normpath(os.path.join(config.get_book_path(),
                                                             to_book.path,
                                                             to_name + "." + element.format.lower()))
                filepath_old = os.path.normpath(os.path.join(config.get_book_path(),
                                                             from_book.path,
                                                             element.name + "." + element.format.lower()))
                copyfile(filepath_old, filepath_new)
                to_book.data.append(db.Data(to_book.id,
                                            element.format,
                                            element.uncompressed_size,
                                            to_name))
                existing_formats.append(element.format)
    calibre_db.session.commit()
