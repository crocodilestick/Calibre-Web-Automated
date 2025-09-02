# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint
from flask_babel import gettext as _
from sqlalchemy import func, and_

from . import db, calibre_db, logger
from .admin import admin_required  
from .usermanagement import login_required_if_no_ano
from .render_template import render_title_template
from .cw_login import current_user

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
    """Find books with duplicate title + primary author combinations using efficient SQL"""
    
    # Get all books with proper user filtering - this is much simpler and more reliable
    # than trying to do complex joins for duplicate detection
    books_query = (calibre_db.session.query(db.Books)
                   .filter(calibre_db.common_filters())  # Respect user permissions and library filtering
                   .order_by(db.Books.title, db.Books.timestamp.desc()))
    
    all_books = books_query.all()
    print(f"[cwa-duplicates] Retrieved {len(all_books)} books with user filtering applied", flush=True)
    
    # Group books by title + primary author combination (case-insensitive)
    title_author_groups = {}
    
    for book in all_books:
        # Ensure authors are loaded (lazy loading)
        if not book.authors:
            continue
            
        # Get primary author (use Calibre-Web's standard approach)
        book.ordered_authors = calibre_db.order_authors([book])
        primary_author = book.ordered_authors[0].name if book.ordered_authors else "Unknown"
        
        # Create case-insensitive key
        key = (book.title.lower().strip(), primary_author.lower().strip())
        
        if key not in title_author_groups:
            title_author_groups[key] = []
        title_author_groups[key].append(book)
    
    print(f"[cwa-duplicates] Grouped books into {len(title_author_groups)} unique title+author combinations", flush=True)
    
    # Filter to only groups with duplicates and prepare display data
    duplicate_groups = []
    for (lower_title, lower_author), books in title_author_groups.items():
        if len(books) > 1:
            # Sort books by timestamp (newest first)
            books.sort(key=lambda x: x.timestamp, reverse=True)
            
            # Add additional information for display
            for book in books:
                # Ensure we have ordered authors
                if not hasattr(book, 'ordered_authors') or not book.ordered_authors:
                    book.ordered_authors = calibre_db.order_authors([book])
                
                book.author_names = ', '.join([author.name.replace('|', ',') for author in book.ordered_authors])
                
                # Add cover URL
                if book.has_cover:
                    book.cover_url = f"/cover/{book.id}"
                else:
                    book.cover_url = "/static/generic_cover.jpg"
            
            duplicate_groups.append({
                'title': books[0].title,
                'author': books[0].author_names.split(',')[0].strip(),  # Primary author
                'count': len(books),
                'books': books
            })
            
            book_ids = [book.id for book in books]
            print(f"[cwa-duplicates] Found duplicate group: '{books[0].title}' by {books[0].author_names.split(',')[0].strip()} ({len(books)} copies) - IDs: {book_ids}", flush=True)
            log.info("[cwa-duplicates] Found duplicate group: '%s' by %s (%s copies) - IDs: %s", 
                    books[0].title, books[0].author_names.split(',')[0].strip(), len(books), book_ids)
    
    # Sort by title, then author for consistent display
    duplicate_groups.sort(key=lambda x: (x['title'].lower(), x['author'].lower()))
    
    print(f"[cwa-duplicates] Found {len(duplicate_groups)} duplicate groups total", flush=True)
    
    return duplicate_groups
