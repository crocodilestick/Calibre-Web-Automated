#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Reading Services API for Kobo Annotations/Highlights
Handles annotation sync from Kobo devices

These routes are at the root level: /api/v3/..., /api/UserStorage/...
"""

import json
from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, request, make_response, jsonify, abort
from werkzeug.datastructures import Headers
import requests

from . import logger, calibre_db, db, config, ub, csrf
from .cw_login import current_user, login_required
from .services import hardcover

log = logger.create()

# Create blueprint at root level (no prefix)
readingservices = Blueprint("readingservices", __name__)

KOBO_READING_SERVICES_URL = "https://readingservices.kobo.com"


def requires_reading_services_auth(f):
    """
    Auth decorator for reading services endpoints.
    Checks if annotation sync is enabled and user is authenticated.
    If not enabled or not authenticated, proxies the request to Kobo without processing.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if annotation sync is enabled
        if not config.config_kobo_annotation_sync:
            log.debug("Kobo annotation sync disabled, proxying to Kobo")
            return proxy_to_kobo_reading_services()
        
        # Check if Kobo sync is enabled (annotation sync depends on it)
        if not config.config_kobo_sync:
            log.debug("Kobo sync disabled, proxying to Kobo")
            return proxy_to_kobo_reading_services()
        
        # Check if user is authenticated (cookie from Kobo sync)
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        else:
            # User not authenticated - just proxy to Kobo
            log.debug("Reading services request without auth, proxying to Kobo")
            return proxy_to_kobo_reading_services()
    return decorated_function


def get_book_identifiers(book):
    """Extract relevant identifiers from book."""
    identifiers = {}
    if book and book.identifiers:
        for identifier in book.identifiers:
            id_type = identifier.type.lower()
            if id_type in ['hardcover-id', 'hardcover-edition', 'hardcover-slug', 'isbn']:
                identifiers[id_type] = identifier.val
    return identifiers


CONNECTION_SPECIFIC_HEADERS = [
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
]


def make_request_to_kobo_reading_services():
    """Make a request to Kobo's reading services API, similar to make_request_to_kobo_store."""
    # Build the URL for Kobo's reading services
    kobo_url = KOBO_READING_SERVICES_URL + request.path
    if request.query_string:
        kobo_url += "?" + request.query_string.decode('utf-8')
    
    log.debug(f"Proxying to Kobo Reading Services: {kobo_url}")
    log.debug(f"Method: {request.method}")
    
    # Forward headers (including Authorization, x-kobo-userkey, etc.)
    outgoing_headers = Headers(request.headers)
    outgoing_headers.remove("Host")
    # Remove CWA session cookie - Kobo doesn't need it and it might cause issues
    outgoing_headers.pop("Cookie", None)
    
    log.debug(f"Outgoing headers: {dict(outgoing_headers)}")
    
    request_data = request.get_data()
    if request_data:
        log.debug(f"Request body length: {len(request_data)}")
        try:
            log.debug(f"Request body (JSON): {json.loads(request_data)}")
        except:
            log.debug(f"Request body (raw): {request_data[:500]}")
    
    store_response = requests.request(
        method=request.method,
        url=kobo_url,
        headers=outgoing_headers,
        data=request_data,
        allow_redirects=False,
        timeout=(2, 10)
    )
    
    log.debug(f"Kobo Reading Services response status code: {store_response.status_code}")
    log.debug(f"Kobo Reading Services response headers: {dict(store_response.headers)}")
    log.debug(f"Kobo Reading Services response body: {store_response.text[:1000]}")
    
    if store_response.status_code >= 400:
        log.warning(f"Kobo Reading Services error {store_response.status_code}")
        log.warning(f"Response body: {store_response.text[:1000]}")
        log.warning(f"Response headers: {dict(store_response.headers)}")
    
    return store_response


def proxy_to_kobo_reading_services():
    """Proxy the request to Kobo's reading services API."""
    try:
        store_response = make_request_to_kobo_reading_services()
        
        response_headers = store_response.headers
        for header_key in CONNECTION_SPECIFIC_HEADERS:
            response_headers.pop(header_key, default=None)
        
        return make_response(
            store_response.content, store_response.status_code, response_headers.items()
        )
    except Exception as e:
        log.error(f"Failed to proxy to Kobo Reading Services: {e}")
        import traceback
        log.error(traceback.format_exc())
        return make_response(jsonify({"error": "Failed to proxy request"}), 502)


def get_book_by_entitlement_id(entitlement_id):
    """Get book from database by UUID (entitlement_id)."""
    try:
        book = calibre_db.get_book_by_uuid(entitlement_id)
        return book
    except Exception as e:
        log.error(f"Error getting book by entitlement ID {entitlement_id}: {e}")
        return None


def log_annotation_data(entitlement_id, method, data=None):
    """Log annotation data and link to book identifiers."""
    log.info("=" * 80)
    log.info(f"ANNOTATION {method}")
    log.info("=" * 80)
    log.info(f"Entitlement ID: {entitlement_id}")
    log.info(f"User: {current_user.name}")
    
    # Try to link to book
    book = get_book_by_entitlement_id(entitlement_id)
    if book:
        log.info(f"Book: {book.title}")
        log.info(f"Book ID: {book.id}")
        
        # Log identifiers
        if book.identifiers:
            log.info("Identifiers:")
            for identifier in book.identifiers:
                log.info(f"  {identifier.type}: {identifier.val}")
    else:
        log.warning(f"Could not find book for entitlement ID: {entitlement_id}")
    
    if data:
        log.info("Annotation Data:")
        log.info(json.dumps(data, indent=2))
    
    log.info("=" * 80)


def process_annotation_for_sync(annotation, book, identifiers, progress_percent=None):
    """
    Process a single annotation and sync to Hardcover if needed.
    
    Args:
        annotation: Annotation dict from Kobo
        book: Calibre book object
        identifiers: Book identifiers dict
        progress_percent: Optional overall book progress
    
    Returns:
        True if synced successfully, False otherwise
    """
    annotation_id = annotation.get('id')
    highlighted_text = annotation.get('highlightedText')
    note_text = annotation.get('noteText')
    
    log.info("---")
    log.info(f"Processing Annotation ID: {annotation_id}")
    log.info(f"Type: {annotation.get('type')}")
    log.info(f"Highlighted Text: {highlighted_text}")
    log.info(f"Note Text: {note_text}")
    log.info(f"Highlight Color: {annotation.get('highlightColor')}")
    
    # Skip if no text content
    if not highlighted_text and not note_text:
        log.info("Skipping annotation with no text content")
        return False
    
    # Check if already synced
    if annotation_id:
        existing_sync = ub.session.query(ub.KoboAnnotationSync).filter(
            ub.KoboAnnotationSync.annotation_id == annotation_id,
            ub.KoboAnnotationSync.user_id == current_user.id
        ).first()
        
        if existing_sync and existing_sync.synced_to_hardcover:
            log.info(f"Annotation {annotation_id} already synced to Hardcover, skipping")
            return False
        
        # Check for duplicate content (same highlight+note combination)
        # Create a unique key from the content
        content_key = f"{highlighted_text or ''}:{note_text or ''}"
        duplicate_sync = ub.session.query(ub.KoboAnnotationSync).filter(
            ub.KoboAnnotationSync.user_id == current_user.id,
            ub.KoboAnnotationSync.book_id == book.id,
            ub.KoboAnnotationSync.synced_to_hardcover == True
        ).all()
        
        for sync_record in duplicate_sync:
            # We don't store the content in the sync table, so we can't check for exact duplicates
            # This is a limitation - we'll rely on annotation_id being unique
            pass
    
    # Get progress if not provided
    if progress_percent is None:
        location = annotation.get('location', {})
        if location and 'span' in location:
            span = location['span']
            chapter_progress = span.get('chapterProgress', 0)
            log.info(f"Chapter: {span.get('chapterTitle')}")
            log.info(f"Chapter Progress: {chapter_progress * 100:.1f}%")
        
        # Try to get the actual book progress from KoboReadingState
        kobo_reading_state = ub.session.query(ub.KoboReadingState).filter(
            ub.KoboReadingState.book_id == book.id,
            ub.KoboReadingState.user_id == current_user.id
        ).first()
        
        if kobo_reading_state and kobo_reading_state.current_bookmark:
            if kobo_reading_state.current_bookmark.progress_percent:
                progress_percent = kobo_reading_state.current_bookmark.progress_percent
                log.info(f"Overall Book Progress: {progress_percent:.1f}%")
            else:
                # Fallback to chapter progress if no overall progress available
                if location and 'span' in location:
                    progress_percent = chapter_progress * 100
        else:
            # Fallback to chapter progress if no reading state found
            if location and 'span' in location:
                progress_percent = chapter_progress * 100
    
    # Sync to Hardcover if enabled and user has token
    if config.config_hardcover_sync and current_user.hardcover_token and bool(hardcover):
        if identifiers:
            log.info(f"Syncing annotation to Hardcover with identifiers: {identifiers}")
            try:
                hardcover_client = hardcover.HardcoverClient(current_user.hardcover_token)
                result = hardcover_client.add_journal_entry(
                    identifiers=identifiers,
                    note_text=note_text,
                    progress_percent=progress_percent,
                    highlighted_text=highlighted_text
                )
                
                if result:
                    # Track sync in database
                    if annotation_id:
                        if existing_sync:
                            existing_sync.synced_to_hardcover = True
                            existing_sync.hardcover_journal_id = result.get('id')
                            existing_sync.last_synced = datetime.now(timezone.utc)
                        else:
                            sync_record = ub.KoboAnnotationSync(
                                user_id=current_user.id,
                                annotation_id=annotation_id,
                                book_id=book.id,
                                synced_to_hardcover=True,
                                hardcover_journal_id=result.get('id')
                            )
                            ub.session.add(sync_record)
                        ub.session_commit()
                        log.info(f"Successfully synced annotation {annotation_id} to Hardcover")
                    return True
                else:
                    log.warning(f"Failed to sync annotation {annotation_id} to Hardcover")
                    return False
            except Exception as e:
                log.error(f"Error syncing annotation to Hardcover: {e}")
                import traceback
                log.error(traceback.format_exc())
                return False
        else:
            log.info("No Hardcover identifiers found, skipping sync")
            return False
    else:
        if not config.config_hardcover_sync:
            log.debug("Hardcover sync disabled")
        elif not current_user.hardcover_token:
            log.debug("User has no Hardcover token")
        return False


@csrf.exempt
@readingservices.route("/api/v3/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth
def handle_annotations(entitlement_id):
    """
    Handle annotation requests for a specific book.
    GET: Retrieve all annotations for a book
    PATCH: Update/create annotations
    """
    if request.method == "GET":
        log.info(f"GET annotations for entitlement: {entitlement_id}")
        log_annotation_data(entitlement_id, "GET")
        
        # Get the response from Kobo first
        try:
            store_response = make_request_to_kobo_reading_services()
            
            # Try to parse and process annotations from the response
            if store_response.status_code == 200:
                try:
                    response_data = store_response.json()
                    annotations = response_data.get('annotations', [])
                    
                    if annotations:
                        log.info(f"Found {len(annotations)} existing annotations from Kobo")
                        
                        # Get book from database
                        book = get_book_by_entitlement_id(entitlement_id)
                        if book:
                            identifiers = get_book_identifiers(book)
                            
                            # Process each annotation
                            synced_count = 0
                            for annotation in annotations:
                                if process_annotation_for_sync(annotation, book, identifiers):
                                    synced_count += 1
                            
                            log.info(f"Synced {synced_count} of {len(annotations)} annotations to Hardcover")
                        else:
                            log.warning(f"Book not found for entitlement {entitlement_id}, skipping sync")
                except Exception as e:
                    log.error(f"Error processing GET annotations response: {e}")
                    import traceback
                    log.error(traceback.format_exc())
            
            # Return the original response from Kobo
            response_headers = store_response.headers
            for header_key in CONNECTION_SPECIFIC_HEADERS:
                response_headers.pop(header_key, default=None)
            return make_response(
                store_response.content, store_response.status_code, response_headers.items()
            )
        except requests.exceptions.RequestException as e:
            log.error(f"Failed to proxy GET annotations to Kobo Reading Services: {e}")
            return make_response(jsonify({"error": "Failed to proxy request"}), 502)
        except Exception as e:
            log.error(f"Unexpected error proxying GET annotations: {e}")
            import traceback
            log.error(traceback.format_exc())
            return make_response(jsonify({"error": "Internal server error"}), 500)
        
    elif request.method == "PATCH":
        try:
            data = request.get_json()
            log_annotation_data(entitlement_id, "PATCH", data)
            
            # Handle deleted annotations
            if data and "deletedAnnotationIds" in data:
                deleted_ids = data["deletedAnnotationIds"]
                log.info(f"Deleted annotation IDs: {deleted_ids}")
                # TODO: Handle deletion (remove from sync tracking, delete from Hardcover if needed)
            
            # Get book from database
            book = get_book_by_entitlement_id(entitlement_id)
            if not book:
                log.warning(f"Book not found for entitlement {entitlement_id}, skipping Hardcover sync")
            else:
                identifiers = get_book_identifiers(book)
                
                # Extract updated annotations
                if data and "updatedAnnotations" in data:
                    log.info(f"Processing {len(data['updatedAnnotations'])} updated annotations")
                    for annotation in data["updatedAnnotations"]:
                        process_annotation_for_sync(annotation, book, identifiers)
                    
        except Exception as e:
            log.error(f"Error processing PATCH annotations: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices.route("/api/v3/content/checkforchanges", methods=["POST"])
@requires_reading_services_auth
def handle_check_for_changes():
    """
    Handle check for changes request.
    Proxies to Kobo's reading services.
    """
    try:
        data = request.get_json()
        log.debug(f"Check for changes request: {data}")
    except:
        pass
    
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices.route("/api/UserStorage/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_user_storage(subpath):
    """
    Handle UserStorage API requests (e.g., /api/UserStorage/Metadata).
    Proxies to Kobo's reading services.
    """
    log.debug(f"UserStorage request: {request.method} /api/UserStorage/{subpath}")
    log.debug(f"Full path: {request.full_path}")
    
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices.route("/api/v3/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_unknown_reading_service_request(subpath):
    """
    Catch-all handler for any reading services requests not explicitly handled.
    Logs the request and proxies to Kobo's reading services.
    """
    log.debug(f"Unknown reading services request: {request.method} /api/v3/{subpath}")
    log.debug(f"Full path: {request.full_path}")
    log.debug(f"Headers: {request.headers}")
    try:
        log.debug(f"JSON: {request.get_json()}")
    except:
        log.debug(f"Could not get JSON")
    try:
        log.debug(f"Data: {request.get_data()}")
    except:
        log.debug(f"Could not get data")
    
    # Proxy to Kobo
    return proxy_to_kobo_reading_services()

