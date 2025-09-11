# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
import concurrent.futures
from typing import List, Optional, Dict, Any

from cps import logger, ub
from cps.search_metadata import cl
from cps.string_helper import strip_whitespaces

log = logger.create()


def get_metadata_provider_hierarchy(cwa_settings: Dict[str, Any]) -> List[str]:
    """Get the configured metadata provider hierarchy"""
    try:
        hierarchy_json = cwa_settings.get('metadata_provider_hierarchy', '["google","douban","dnb"]')
        if isinstance(hierarchy_json, str):
            hierarchy = json.loads(hierarchy_json)
        else:
            hierarchy = hierarchy_json
        return hierarchy if isinstance(hierarchy, list) else ["google", "douban", "dnb"]
    except (json.JSONDecodeError, TypeError):
        log.warning("Invalid metadata provider hierarchy config, using default")
        return ["google", "douban", "dnb"]


def fetch_metadata_for_book(book_title: str, book_authors: str = "", user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch metadata for a book using the configured provider hierarchy
    
    Args:
        book_title: Title of the book
        book_authors: Authors of the book (comma-separated)
        user_id: User ID for checking user preferences
        
    Returns:
        Dict with metadata if found, None otherwise
    """
    try:
        # Import here to avoid circular imports
        from scripts.cwa_db import CWA_DB
        
        # Get CWA settings
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.cwa_settings
        
        # Check if auto metadata fetch is globally enabled
        if not cwa_settings.get('auto_metadata_fetch_enabled', False):
            log.debug("Auto metadata fetch is globally disabled")
            return None
            
        # Check user preference if user_id provided
        if user_id:
            user = ub.session.query(ub.User).filter(ub.User.id == user_id).first()
            if user and not user.auto_metadata_fetch:
                log.debug(f"User {user_id} has auto metadata fetch disabled")
                return None
        
        # Build search query
        query_parts = [strip_whitespaces(book_title)]
        if book_authors:
            # Add first author to search query for better results
            first_author = book_authors.split(',')[0].strip()
            if first_author:
                query_parts.append(strip_whitespaces(first_author))
        
        query = " ".join(query_parts)
        if not query:
            log.warning("Empty query for metadata search")
            return None
            
        log.info(f"Fetching metadata for: {query}")
        
        # Get provider hierarchy
        provider_hierarchy = get_metadata_provider_hierarchy(cwa_settings)

        # Get global enabled map for providers
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
        
        # Get available metadata providers
        available_providers = {provider.__id__: provider for provider in cl if provider.active}
        
        # Try providers in order of preference
        for provider_id in provider_hierarchy:
            # Skip if globally disabled
            if not bool(enabled_map.get(provider_id, True)):
                log.debug(f"Provider {provider_id} is globally disabled")
                continue
            if provider_id not in available_providers:
                log.debug(f"Provider {provider_id} not available or inactive")
                continue
                
            provider = available_providers[provider_id]
            log.debug(f"Trying metadata provider: {provider.__name__}")
            
            try:
                # Use ThreadPoolExecutor for timeout control
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(provider.search, query, "", "en")
                    results = future.result(timeout=30)  # 30 second timeout
                    
                if results and len(results) > 0:
                    # Return the first (best) result
                    metadata = results[0]
                    log.info(f"Found metadata using provider {provider.__name__}: {metadata.title}")
                    
                    return {
                        'title': metadata.title,
                        'authors': metadata.authors,
                        'description': getattr(metadata, 'description', ''),
                        'publisher': getattr(metadata, 'publisher', ''),
                        'publishedDate': getattr(metadata, 'publishedDate', ''),
                        'tags': getattr(metadata, 'tags', []),
                        'rating': getattr(metadata, 'rating', 0),
                        'series': getattr(metadata, 'series', ''),
                        'series_index': getattr(metadata, 'series_index', 1),
                        'cover': getattr(metadata, 'cover', ''),
                        'identifiers': getattr(metadata, 'identifiers', {}),
                        'languages': getattr(metadata, 'languages', []),
                        'source': f"{provider.__name__}"
                    }
                    
            except concurrent.futures.TimeoutError:
                log.warning(f"Metadata provider {provider.__name__} timed out")
                continue
            except Exception as e:
                log.warning(f"Error fetching metadata from {provider.__name__}: {str(e)}")
                continue
                
        log.info(f"No metadata found for: {query}")
        return None
        
    except Exception as e:
        log.error(f"Error in fetch_metadata_for_book: {str(e)}")
        return None
