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

from . import db, calibre_db, logger, ub
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
    except Exception as e:
        print(f"[cwa-duplicates] Error loading CWA settings: {str(e)}, falling back to defaults", flush=True)
        log.error("[cwa-duplicates] Error loading CWA settings: %s, falling back to defaults", str(e))
        # Fallback to safe defaults
        settings = {
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
        # Check if notifications are enabled
        cwa_db = CWA_DB()
        notifications_enabled = cwa_db.cwa_settings.get('duplicate_notifications_enabled', 1)
        
        # Get unresolved duplicate groups
        duplicate_groups = find_duplicate_books(include_dismissed=False)
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
            'preview': preview
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
