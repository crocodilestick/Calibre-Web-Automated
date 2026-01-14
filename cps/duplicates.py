# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint, jsonify, request, abort
from flask_babel import gettext as _
from sqlalchemy import func, and_
from datetime import datetime
from functools import wraps
import hashlib

from . import db, calibre_db, logger, ub, csrf
from .admin import admin_required  
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .cw_login import current_user

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

duplicates = Blueprint('duplicates', __name__)
log = logger.create()


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


def validate_resolution_strategy(strategy):
    """Validate that strategy is one of the allowed values"""
    valid_strategies = ['newest', 'highest_quality_format', 'most_metadata', 'largest_file_size']
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
        return max(books, key=lambda b: b.timestamp if b.timestamp else datetime.min)
    
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
        return max(books, key=lambda b: (get_best_format_score(b), b.timestamp if b.timestamp else datetime.min))
    
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
        return max(books, key=lambda b: (metadata_score(b), b.timestamp if b.timestamp else datetime.min))
    
    elif strategy == 'largest_file_size':
        # Sum all format file sizes
        def total_file_size(book):
            if not book.data:
                return 0
            return sum(data.uncompressed_size for data in book.data if hasattr(data, 'uncompressed_size') and data.uncompressed_size)
        
        # Keep book with largest total file size, fallback to newest if tie
        return max(books, key=lambda b: (total_file_size(b), b.timestamp if b.timestamp else datetime.min))
    
    else:
        # Default fallback: keep newest
        return max(books, key=lambda b: b.timestamp if b.timestamp else datetime.min)


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


@duplicates.route("/duplicates")
@login_required_if_no_ano
@admin_or_edit_required
def show_duplicates():
    """Display books with duplicate titles and authors"""
    print("[cwa-duplicates] Loading duplicates page...", flush=True)
    log.info("[cwa-duplicates] Loading duplicates page for user: %s", current_user.name)
    
    try:
        # Use SQL to efficiently find duplicates with proper user filtering
        duplicate_groups = find_duplicate_books()
        
        print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
        log.info("[cwa-duplicates] Found %s duplicate groups total", len(duplicate_groups))
        
        return render_title_template('duplicates.html', 
                                     duplicate_groups=duplicate_groups,
                                     title=_("Duplicate Books"), 
                                     page="duplicates")
                                     
    except Exception as e:
        print(f"[cwa-duplicates] Critical error loading duplicates page: {str(e)}", flush=True)
        log.error("[cwa-duplicates] Critical error loading duplicates page: %s", str(e))
        # Return empty page on error
        return render_title_template('duplicates.html', 
                                     duplicate_groups=[],
                                     title=_("Duplicate Books"), 
                                     page="duplicates")


def find_duplicate_books(include_dismissed=False, user_id=None):
    """Find books with duplicate combinations based on configurable criteria
    
    Args:
        include_dismissed: If False, filter out dismissed groups for the user
        user_id: User ID for dismissed filtering (defaults to current_user.id)
    
    Returns:
        List of duplicate group dictionaries
    """
    
    if user_id is None and hasattr(current_user, 'id'):
        user_id = current_user.id
    
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
            'duplicate_detection_format': 0
        }
    
    # Extract duplicate detection criteria
    use_title = settings.get('duplicate_detection_title', 1)
    use_author = settings.get('duplicate_detection_author', 1) 
    use_language = settings.get('duplicate_detection_language', 1)
    use_series = settings.get('duplicate_detection_series', 0)
    use_publisher = settings.get('duplicate_detection_publisher', 0)
    use_format = settings.get('duplicate_detection_format', 0)
    
    # Ensure at least one criterion is selected (fallback to title+author if none selected)
    if not any([use_title, use_author, use_language, use_series, use_publisher, use_format]):
        print("[cwa-duplicates] Warning: No duplicate detection criteria selected, falling back to title+author", flush=True)
        log.warning("[cwa-duplicates] No duplicate detection criteria selected, falling back to title+author")
        use_title = 1
        use_author = 1
    
    print(f"[cwa-duplicates] Using duplicate detection criteria: title={use_title}, author={use_author}, language={use_language}, series={use_series}, publisher={use_publisher}, format={use_format}", flush=True)
    
    # Get all books with proper user filtering - this is much simpler and more reliable
    # than trying to do complex joins for duplicate detection
    books_query = (calibre_db.session.query(db.Books)
                   .filter(calibre_db.common_filters())  # Respect user permissions and library filtering
                   .order_by(db.Books.title, db.Books.timestamp.desc()))
    
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
        
        if use_title:
            # Handle potential None title
            title = book.title if book.title else "untitled"
            key_parts.append(title.lower().strip())
        
        if use_author:
            # Ensure authors are loaded and not empty
            if book.authors and len(book.authors) > 0:
                # Get primary author (use Calibre-Web's standard approach)
                book.ordered_authors = calibre_db.order_authors([book])
                primary_author = book.ordered_authors[0].name if book.ordered_authors and len(book.ordered_authors) > 0 else "unknown"
                key_parts.append(primary_author.lower().strip())
            else:
                key_parts.append("unknown")
        
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
            books.sort(key=lambda x: x.timestamp if x.timestamp else datetime.min, reverse=True)
            
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
        
        if cache_data and not cache_data['scan_pending']:
            # Cache is valid, use it
            duplicate_groups = cache_data['duplicate_groups']
            
            # Filter out dismissed groups for this user
            if current_user and current_user.id:
                try:
                    dismissed_hashes = set()
                    dismissed_groups = ub.session.query(ub.DismissedDuplicateGroup.group_hash)\
                        .filter(ub.DismissedDuplicateGroup.user_id == current_user.id)\
                        .all()
                    dismissed_hashes = {row[0] for row in dismissed_groups}
                    
                    if dismissed_hashes:
                        duplicate_groups = [group for group in duplicate_groups 
                                          if group['group_hash'] not in dismissed_hashes]
                except Exception as e:
                    log.error("[cwa-duplicates] Error filtering dismissed groups: %s", str(e))
            
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
                'cached': True
            })
        
        # Cache is invalid or pending, run fresh scan
        duplicate_groups = find_duplicate_books(include_dismissed=False)
        count = len(duplicate_groups)
        
        # Update cache with full results (before filtering dismissed)
        all_groups = find_duplicate_books(include_dismissed=True)
        cwa_db.update_duplicate_cache(all_groups, len(all_groups))
        
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
            'cached': False
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
        
        # Run scan
        duplicate_groups = find_duplicate_books(include_dismissed=False)
        
        # Update cache
        all_groups = find_duplicate_books(include_dismissed=True)
        cwa_db.update_duplicate_cache(all_groups, len(all_groups))
        
        log.info("[cwa-duplicates] Manual scan triggered by user %s, found %s groups", 
                current_user.name, len(duplicate_groups))
        
        return jsonify({
            'success': True,
            'message': _('Duplicate scan completed'),
            'count': len(duplicate_groups)
        })
        
    except Exception as e:
        log.error("[cwa-duplicates] Error triggering scan: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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


def auto_resolve_duplicates(strategy='newest', dry_run=False, user_id=None, trigger_type='manual'):
    """
    Automatically resolve duplicate books by keeping one and deleting others.
    
    Args:
        strategy: Resolution strategy ('newest', 'highest_quality_format', 'most_metadata', 'largest_file_size')
        dry_run: If True, return preview without actually deleting
        user_id: User ID triggering the resolution (for audit)
        trigger_type: 'manual', 'scheduled', or 'automatic'
    
    Returns:
        dict with keys:
            'success': bool
            'resolved_count': int (number of groups resolved)
            'deleted_count': int (total books deleted)
            'kept_count': int (total books kept)
            'errors': list of error messages
            'preview': list of dicts (if dry_run=True) with 'group', 'kept_book', 'deleted_books'
    """
    from cps.editbooks import delete_book_from_table
    from cps import config
    import os
    import shutil
    
    # Validate strategy
    if not validate_resolution_strategy(strategy):
        return {'success': False, 'errors': [f'Invalid strategy: {strategy}']}
    
    # Get duplicate groups (exclude dismissed)
    duplicate_groups = find_duplicate_books(include_dismissed=False)
    
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
                # Preview mode: just collect info
                result['preview'].append({
                    'group_hash': group['group_hash'],
                    'title': group['title'],
                    'author': group['author'],
                    'kept_book_id': book_to_keep.id,
                    'kept_book_timestamp': book_to_keep.timestamp.strftime('%Y-%m-%d %H:%M') if book_to_keep.timestamp else 'Unknown',
                    'kept_book_formats': [d.format for d in book_to_keep.data] if book_to_keep.data else [],
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
            deleted_ids = []
            backup_dir = f"/config/processed_books/duplicate_resolutions/{datetime.now().strftime('%Y%m%d_%H%M%S')}_group_{group['group_hash'][:8]}"
            os.makedirs(backup_dir, exist_ok=True)
            
            # Backup and delete each duplicate
            for book in books_to_delete:
                try:
                    # Backup book files
                    book_path = os.path.join(config.config_calibre_dir, book.path)
                    if os.path.exists(book_path):
                        backup_path = os.path.join(backup_dir, f"book_{book.id}")
                        shutil.copytree(book_path, backup_path)
                        log.info("[cwa-duplicates] Backed up book %s to %s", book.id, backup_path)
                    
                    # Delete from Calibre library
                    delete_book_from_table(book.id, "", True)  # True = delete from disk
                    deleted_ids.append(book.id)
                    log.info("[cwa-duplicates] Deleted duplicate book %s: %s", book.id, book.title)
                    
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
        
        except Exception as e:
            log.error("[cwa-duplicates] Error resolving duplicate group '%s': %s", group.get('title', 'unknown'), e)
            result['errors'].append(f"Group '{group.get('title', 'unknown')}': {str(e)}")
    

    if result['errors']:
        result['success'] = False
    
    return result
