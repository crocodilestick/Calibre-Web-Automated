# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint
from flask_babel import gettext as _
from sqlalchemy import func, and_
from datetime import datetime

from . import db, calibre_db, logger
from .admin import admin_required  
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .cw_login import current_user

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

duplicates = Blueprint('duplicates', __name__)
log = logger.create()


@duplicates.route("/duplicates")
@login_required_if_no_ano
@admin_required
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


def find_duplicate_books():
    """Find books with duplicate combinations based on configurable criteria"""
    
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
            
            duplicate_groups.append({
                'title': display_title,
                'author': display_author,
                'count': len(books),
                'books': books
            })
            
            book_ids = [book.id for book in books]
            print(f"[cwa-duplicates] Found duplicate group: '{display_title}' by {display_author} ({len(books)} copies) - IDs: {book_ids}", flush=True)
            log.info("[cwa-duplicates] Found duplicate group: '%s' by %s (%s copies) - IDs: %s", 
                    display_title, display_author, len(books), book_ids)
    
    # Sort by title, then author for consistent display
    duplicate_groups.sort(key=lambda x: (x['title'].lower(), x['author'].lower()))
    
    print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
    
    return duplicate_groups
