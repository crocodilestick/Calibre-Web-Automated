# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
from typing import Optional, List, Dict

from cps import logger, calibre_db, db
from cps.search_metadata import cl as metadata_providers
import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()


def fetch_and_apply_metadata(book_id: int, user_enabled: bool = False) -> bool:
    """
    Fetch metadata for a newly ingested book and apply it if settings allow.
    
    Args:
        book_id: The ID of the book to fetch metadata for
        user_enabled: Deprecated parameter - metadata fetching is now admin-controlled only
        
    Returns:
        bool: True if metadata was successfully fetched and applied, False otherwise
    """
    try:
        # Check global settings (admin-controlled only)
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        
        if not cwa_settings.get('auto_metadata_fetch_enabled', False):
            log.debug("Auto metadata fetch disabled by administrator")
            return False
            
        # Get the book
        calibre_db_instance = db.CalibreDB(expire_on_commit=False, init=True)
        book = calibre_db_instance.get_book(book_id)
        if not book:
            log.error(f"Book with ID {book_id} not found")
            return False
            
        # Create search query from book title and author
        search_query = book.title
        if book.authors:
            author_names = [author.name for author in book.authors]
            search_query += " " + " ".join(author_names)
            
        log.info(f"Fetching metadata for: {search_query}")
        
        # Get provider hierarchy
        try:
            provider_hierarchy = json.loads(cwa_settings.get('metadata_provider_hierarchy', '["google","douban","dnb","ibdb","comicvine"]'))
        except (json.JSONDecodeError, TypeError):
            provider_hierarchy = ["google", "douban", "dnb", "ibdb", "comicvine"]

        # Global provider enablement map
        enabled_map_raw = cwa_settings.get('metadata_providers_enabled', '{}')
        try:
            if isinstance(enabled_map_raw, str):
                s = enabled_map_raw.strip()
                if s.startswith("'") and s.endswith("'"):
                    s = s[1:-1]
                enabled_map = json.loads(s or '{}')
            elif isinstance(enabled_map_raw, dict):
                enabled_map = enabled_map_raw
            else:
                enabled_map = {}
        except Exception:
            enabled_map = {}
            
        # Try each provider in order
        metadata_found = False
        for provider_id in provider_hierarchy:
            # Skip if globally disabled
            if not bool(enabled_map.get(provider_id, True)):
                log.debug(f"Provider {provider_id} is globally disabled")
                continue
            try:
                # Find the provider
                provider = None
                for p in metadata_providers:
                    if p.__id__ == provider_id:
                        provider = p
                        break
                        
                if not provider or not provider.active:
                    continue
                    
                log.debug(f"Trying metadata provider: {provider.__name__}")
                
                # Search for metadata
                results = provider.search(search_query, "", "en")
                if not results or len(results) == 0:
                    continue
                    
                # Use the first result
                metadata = results[0]
                
                # Apply metadata to book
                if _apply_metadata_to_book(book, metadata, calibre_db_instance):
                    log.info(f"Successfully applied metadata from {provider.__name__} for book: {book.title}")
                    metadata_found = True
                    break
                    
            except Exception as e:
                log.warning(f"Error fetching metadata from provider {provider_id}: {e}")
                continue
                
        calibre_db_instance.session.close()
        return metadata_found
        
    except Exception as e:
        log.error(f"Error in fetch_and_apply_metadata: {e}")
        return False


def _apply_metadata_to_book(book, metadata, calibre_db_instance) -> bool:
    """
    Apply fetched metadata to a book record.
    
    Args:
        book: The book database record
        metadata: The metadata record from provider
        calibre_db_instance: Database instance
        
    Returns:
        bool: True if metadata was successfully applied
    """
    try:
        # Get CWA settings to check smart application preference
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        use_smart_application = cwa_settings.get('auto_metadata_smart_application', False)
        
        updated = False
        
        # Update title - smart mode: only if longer, normal mode: always replace
        if metadata.title and metadata.title.strip():
            if use_smart_application:
                if len(metadata.title.strip()) > len(book.title.strip()):
                    book.title = metadata.title.strip()
                    updated = True
            else:
                book.title = metadata.title.strip()
                updated = True
            
        # Update authors - always update if available (both modes)
        if metadata.authors and len(metadata.authors) > 0:
            # Clear existing authors
            book.authors.clear()
            for author_name in metadata.authors:
                if author_name and author_name.strip():
                    author = calibre_db_instance.get_author_by_name(author_name.strip())
                    if not author:
                        author = db.Authors(name=author_name.strip(), sort=author_name.strip())
                        calibre_db_instance.session.add(author)
                    book.authors.append(author)
            updated = True
            
        # Update description - smart mode: only if longer, normal mode: always replace
        if metadata.description and metadata.description.strip():
            current_description = book.comments[0].text if book.comments else ""
            if use_smart_application:
                if len(metadata.description.strip()) > len(current_description):
                    if book.comments:
                        book.comments[0].text = metadata.description.strip()
                    else:
                        comment = db.Comments(text=metadata.description.strip(), book=book.id)
                        calibre_db_instance.session.add(comment)
                    updated = True
            else:
                if book.comments:
                    book.comments[0].text = metadata.description.strip()
                else:
                    comment = db.Comments(text=metadata.description.strip(), book=book.id)
                    calibre_db_instance.session.add(comment)
                updated = True
            
        # Update publisher - smart mode: only if current is empty, normal mode: always replace
        if metadata.publisher and metadata.publisher.strip():
            if use_smart_application:
                if not book.publishers or len(book.publishers) == 0:
                    publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                    if not publisher:
                        publisher = db.Publishers(name=metadata.publisher.strip())
                        calibre_db_instance.session.add(publisher)
                    book.publishers = [publisher]
                    updated = True
            else:
                # Clear existing publishers and add new one
                book.publishers.clear()
                publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                if not publisher:
                    publisher = db.Publishers(name=metadata.publisher.strip())
                    calibre_db_instance.session.add(publisher)
                book.publishers = [publisher]
                updated = True
                
        # Update tags if available (both modes)
        if hasattr(metadata, 'tags') and metadata.tags:
            for tag_name in metadata.tags:
                if tag_name and tag_name.strip():
                    tag = calibre_db_instance.get_tag_by_name(tag_name.strip())
                    if not tag:
                        tag = db.Tags(name=tag_name.strip())
                        calibre_db_instance.session.add(tag)
                    if tag not in book.tags:
                        book.tags.append(tag)
            updated = True
            
        # Update series if available (both modes)
        if hasattr(metadata, 'series') and metadata.series and metadata.series.strip():
            series = calibre_db_instance.get_series_by_name(metadata.series.strip())
            if not series:
                series = db.Series(name=metadata.series.strip(), sort=metadata.series.strip())
                calibre_db_instance.session.add(series)
            book.series.clear()
            book.series.append(series)
            
            # Set series index if available
            if hasattr(metadata, 'series_index') and metadata.series_index:
                try:
                    book.series_index = float(metadata.series_index)
                except (ValueError, TypeError):
                    book.series_index = 1.0
            updated = True
            
        # Update published date if available (both modes)
        if hasattr(metadata, 'publishedDate') and metadata.publishedDate:
            try:
                from datetime import datetime
                if isinstance(metadata.publishedDate, str):
                    # Try to parse various date formats
                    for fmt in ['%Y-%m-%d', '%Y-%m', '%Y']:
                        try:
                            book.pubdate = datetime.strptime(metadata.publishedDate, fmt).date()
                            updated = True
                            break
                        except ValueError:
                            continue
                elif hasattr(metadata.publishedDate, 'date'):
                    book.pubdate = metadata.publishedDate.date()
                    updated = True
            except Exception as e:
                log.warning(f"Error parsing published date: {e}")
                
        # Update rating if available (both modes)
        if hasattr(metadata, 'rating') and metadata.rating:
            try:
                rating_value = float(metadata.rating)
                if 0 <= rating_value <= 10:  # Calibre uses 0-10 scale
                    if book.ratings:
                        book.ratings[0].rating = int(rating_value * 2)  # Convert to Calibre's 0-10 scale
                    else:
                        rating = db.Ratings(rating=int(rating_value * 2))
                        calibre_db_instance.session.add(rating)
                        book.ratings = [rating]
                    updated = True
            except (ValueError, TypeError):
                pass
                
        # Update identifiers if available (both modes)
        if hasattr(metadata, 'identifiers') and metadata.identifiers:
            for identifier_type, identifier_value in metadata.identifiers.items():
                if identifier_type and identifier_value:
                    # Check if identifier already exists
                    existing = False
                    for identifier in book.identifiers:
                        if identifier.type == identifier_type:
                            identifier.val = identifier_value
                            existing = True
                            break
                    if not existing:
                        new_identifier = db.Identifiers(type=identifier_type, val=identifier_value, book=book.id)
                        calibre_db_instance.session.add(new_identifier)
                        book.identifiers.append(new_identifier)
                    updated = True
        
        # Handle cover image - this will be enhanced with resolution checking
        if hasattr(metadata, 'cover') and metadata.cover:
            # TODO: Implement cover resolution checking for smart mode
            # For now, just apply the cover in normal mode
            if not use_smart_application:
                # Apply cover (implementation depends on how covers are handled in Calibre-Web)
                pass
        
        if updated:
            calibre_db_instance.session.commit()
            
        return updated
        
    except Exception as e:
        log.error(f"Error applying metadata to book: {e}")
        return False
        if metadata.publisher and metadata.publisher.strip():
            publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
            if not publisher:
                publisher = db.Publishers(name=metadata.publisher.strip())
                calibre_db_instance.session.add(publisher)
            book.publishers.clear()
            book.publishers.append(publisher)
            updated = True
            
        # Update publication date if available
        if metadata.publishedDate and metadata.publishedDate.strip():
            try:
                from datetime import datetime
                pub_date = datetime.strptime(metadata.publishedDate.strip(), "%Y-%m-%d")
                book.pubdate = pub_date
                updated = True
            except ValueError:
                pass  # Invalid date format
                
        # Update series if available
        if metadata.series and metadata.series.strip():
            series = calibre_db_instance.get_series_by_name(metadata.series.strip())
            if not series:
                series = db.Series(name=metadata.series.strip())
                calibre_db_instance.session.add(series)
            book.series.clear()
            book.series.append(series)
            if metadata.series_index:
                try:
                    book.series_index = float(metadata.series_index)
                except (ValueError, TypeError):
                    book.series_index = 1.0
            updated = True
            
        # Update tags if available
        if metadata.tags and len(metadata.tags) > 0:
            book.tags.clear()
            for tag_name in metadata.tags:
                if tag_name and tag_name.strip():
                    tag = calibre_db_instance.get_tag_by_name(tag_name.strip())
                    if not tag:
                        tag = db.Tags(name=tag_name.strip())
                        calibre_db_instance.session.add(tag)
                    book.tags.append(tag)
            updated = True
            
        # Update rating if available
        if metadata.rating and float(metadata.rating) > 0:
            rating = calibre_db_instance.get_rating_by_name(int(float(metadata.rating) * 2))  # Convert to 10-point scale
            if rating:
                book.ratings.clear()
                book.ratings.append(rating)
                updated = True
                
        # TODO: Handle cover image download and update
        # This would require downloading the cover from metadata.cover URL
        # and saving it to the book's directory
        
        if updated:
            calibre_db_instance.session.commit()
            log.info(f"Metadata successfully applied to book: {book.title}")
            return True
        else:
            log.debug(f"No metadata improvements found for book: {book.title}")
            return False
            
    except Exception as e:
        log.error(f"Error applying metadata to book {book.id}: {e}")
        calibre_db_instance.session.rollback()
        return False
