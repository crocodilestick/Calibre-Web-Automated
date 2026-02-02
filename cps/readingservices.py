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
import os
import zipfile
import re
from datetime import datetime, timezone
from functools import wraps
from typing import TypedDict, NotRequired
from flask import Blueprint, request, make_response, jsonify, abort
from werkzeug.datastructures import Headers
import requests
from lxml import etree

from . import logger, calibre_db, db, config, ub, csrf
from .cw_login import current_user, login_required
from .services import hardcover

log = logger.create()

# Create blueprints to handle the relevant reading services API routes
readingservices_api_v3 = Blueprint("readingservices_api_v3", __name__, url_prefix="/api/v3")
readingservices_userstorage = Blueprint("readingservices_userstorage", __name__, url_prefix="/api/UserStorage")

KOBO_READING_SERVICES_URL = "https://readingservices.kobo.com"

# Constants for annotation processing
MAX_PROGRESS_PERCENTAGE = 100  # Cap progress at 100%
SYNC_CHECK_BATCH_SIZE = 50  # Batch size for checking existing syncs
REQUEST_TIMEOUT = (2, 10)  # (connect, read) timeouts in seconds

CONNECTION_SPECIFIC_HEADERS = [
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
]

def redact_headers(headers):
    """Redact sensitive headers from the headers dictionary.
    
    Returns a new dictionary with sensitive headers redacted to avoid
    mutating the original headers object.
    """
    redacted = dict(headers)
    for sensitive_header in ['Authorization', 'x-kobo-userkey', 'Cookie', 'Set-Cookie']:
        if sensitive_header in redacted:
            redacted[sensitive_header] = '***REDACTED***'
    return redacted


def proxy_to_kobo_reading_services():
    """Proxy the request to Kobo's reading services API."""
    try:
        kobo_url = KOBO_READING_SERVICES_URL + request.path
        if request.query_string:
            kobo_url += "?" + request.query_string.decode('utf-8')
        
        log.debug(f"Proxying {request.method} to Kobo Reading Services: {kobo_url}")
        
        # Forward headers (including Authorization, x-kobo-userkey, etc.)
        outgoing_headers = Headers(request.headers)
        outgoing_headers.remove("Host")
        # Remove CWA session cookie - Kobo doesn't need it and it causes issues
        outgoing_headers.pop("Cookie", None)
        
        readingservices_response = requests.request(
            method=request.method,
            url=kobo_url,
            headers=outgoing_headers,
            data=request.get_data(),
            allow_redirects=False,
            timeout=(2, 10)
        )
        
        if readingservices_response.status_code >= 400:
            log.warning(f"Kobo Reading Services error {readingservices_response.status_code}")
            log.warning(f"Response body: {readingservices_response.text[:5000]}")
            log.warning(f"Response headers: {redact_headers(dict(readingservices_response.headers))}")
        
        response_headers = readingservices_response.headers
        for header_key in CONNECTION_SPECIFIC_HEADERS:
            response_headers.pop(header_key, default=None)
        
        return make_response(
            readingservices_response.content, readingservices_response.status_code, response_headers.items()
        )
    except requests.exceptions.Timeout:
        log.error("Timeout connecting to Kobo Reading Services")
        return make_response(jsonify({"error": "Gateway timeout"}), 504)
    except requests.exceptions.ConnectionError as e:
        log.error(f"Connection error to Kobo Reading Services: {e}")
        return make_response(jsonify({"error": "Bad gateway"}), 502)
    except requests.exceptions.RequestException as e:
        log.error(f"Request failed to Kobo Reading Services: {e}")
        return make_response(jsonify({"error": "Bad gateway"}), 502)
    except Exception as e:
        log.error(f"Unexpected error proxying to Kobo Reading Services: {e}")
        import traceback
        log.error(traceback.format_exc())
        return make_response(jsonify({"error": "Internal server error"}), 500)


def requires_reading_services_auth_and_config(f):
    """
    Auth decorator for Reading Services endpoints.
    Checks if annotation sync is enabled and user is authenticated.
    If not enabled or not authenticated, proxies the request to Kobo without processing.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if annotation sync is enabled
        if not config.config_hardcover_annotations_sync:
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


def get_book_by_entitlement_id(entitlement_id):
    """Get book from database by UUID (entitlement_id)."""
    try:
        book = calibre_db.get_book_by_uuid(entitlement_id)
        return book
    except Exception as e:
        log.error(f"Error getting book by entitlement ID {entitlement_id}: {e}")
        return None


def get_book_identifiers(book):
    """Extract relevant identifiers from book."""
    identifiers = {}
    if book and book.identifiers:
        for identifier in book.identifiers:
            id_type = identifier.type.lower()
            if id_type in ['hardcover-id', 'hardcover-edition', 'hardcover-slug', 'isbn']:
                identifiers[id_type] = identifier.val
    return identifiers


def log_annotation_data(entitlement_id, method, data=None):
    """Log annotation data and link to book identifiers."""
    log.debug(f"ANNOTATION {method}")
    log.debug(f"Entitlement ID: {entitlement_id}")
    log.debug(f"User: {current_user.name}")
    
    # Try to link to book
    book = get_book_by_entitlement_id(entitlement_id)
    if book:
        log.debug(f"Book: {book.title}")
        log.debug(f"Book ID: {book.id}")
        
        # Log identifiers
        if book.identifiers:
            log.debug("Identifiers:")
            for identifier in book.identifiers:
                log.debug(f"  {identifier.type}: {identifier.val}")
    else:
        log.warning(f"Could not find book for entitlement ID: {entitlement_id}")
    
    if data:
        log.debug("Annotation Data:")
        log.debug(json.dumps(data, indent=2))


class EpubProgressCalculator:
    """
    Helper class to calculate progress from EPUB/KEPUB files efficiently.
    Parses the book structure once and reuses it for multiple calculations.
    """
    def __init__(self, book: db.Books):
        self.book = book
        self.spine_items: list[str] = []
        self.chapter_lengths: list[int] = []
        self.total_chars = 0
        self.initialized = False
        self.error = False

    def _initialize(self):
        if self.initialized:
            return

        if not self.book or not self.book.path:
            self.error = True
            return

        book_data = None
        kepub_datas = [data for data in self.book.data if data.format.lower() == 'kepub']
        if len(kepub_datas) >= 1:
            book_data = kepub_datas[0]
        else:
            epub_datas = [data for data in self.book.data if data.format.lower() == 'epub']
            if len(epub_datas) >= 1:
                book_data = epub_datas[0]
        
        if not book_data:
            self.error = True
            return

        try:
            file_path = os.path.normpath(os.path.join(
                config.get_book_path(),
                self.book.path,
                book_data.name + "." + book_data.format.lower()
            ))
            
            if not os.path.exists(file_path):
                self.error = True
                return
            
            with zipfile.ZipFile(file_path, 'r') as epub_zip:
                # Find OPF
                container_data = epub_zip.read('META-INF/container.xml')
                container_tree = etree.fromstring(container_data)
                ns = {
                    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
                    'opf': 'http://www.idpf.org/2007/opf'
                }
                opf_path = container_tree.xpath(
                    '//container:rootfile/@full-path',
                    namespaces={'container': ns['container']}
                )[0]
                
                # Parse OPF
                opf_data = epub_zip.read(opf_path)
                opf_tree = etree.fromstring(opf_data)
                opf_dir = os.path.dirname(opf_path)
                
                # Get manifest
                manifest = {}
                for item in opf_tree.xpath('//opf:manifest/opf:item', namespaces={'opf': ns['opf']}):
                    item_id = item.get('id')
                    href = item.get('href')
                    if item_id and href:
                        full_href = os.path.normpath(os.path.join(opf_dir, href)).replace('\\', '/')
                        manifest[item_id] = full_href
                
                # Get spine
                for itemref in opf_tree.xpath('//opf:spine/opf:itemref', namespaces={'opf': ns['opf']}):
                    idref = itemref.get('idref')
                    if idref and idref in manifest:
                        self.spine_items.append(manifest[idref])
                
                if not self.spine_items:
                    self.error = True
                    return

                # Calculate lengths
                for spine_item in self.spine_items:
                    try:
                        content = epub_zip.read(spine_item).decode('utf-8', errors='ignore')
                        try:
                            html_tree = etree.fromstring(content.encode('utf-8'))
                            text_content = ''.join(html_tree.itertext())
                            char_count = len(text_content.strip())
                        except etree.XMLSyntaxError:
                            text_content = re.sub(r'<[^>]+>', '', content)
                            char_count = len(text_content.strip())
                        self.chapter_lengths.append(char_count)
                    except Exception:
                        self.chapter_lengths.append(0)
                
                self.total_chars = sum(self.chapter_lengths)
                self.initialized = True

        except Exception as e:
            log.error(f"Error initializing EPUB calculator: {e}")
            self.error = True

    def calculate(self, chapter_filename: str, chapter_progress: float):
        if not self.initialized:
            self._initialize()
        
        if self.error or self.total_chars == 0:
            return None

        normalized_chapter = chapter_filename.replace('\\', '/')
        target_chapter_index = None
        
        for idx, spine_item in enumerate(self.spine_items):
            if normalized_chapter in spine_item or spine_item.endswith(normalized_chapter):
                target_chapter_index = idx
                break
        
        if target_chapter_index is None:
            return None
        
        chars_before = sum(self.chapter_lengths[:target_chapter_index])
        chars_in_chapter = self.chapter_lengths[target_chapter_index]
        chars_read = chars_before + (chars_in_chapter * chapter_progress)
        
        return (chars_read / self.total_chars) * 100


class AnnotationSpan(TypedDict):
    """Kobo annotation span location data."""
    chapterFilename: str
    chapterProgress: float
    chapterTitle: str
    endChar: int
    endPath: str
    startChar: int
    startPath: str


class AnnotationLocation(TypedDict):
    """Kobo annotation location data."""
    span: AnnotationSpan


class KoboAnnotation(TypedDict):
    """Kobo annotation structure from Reading Services API."""
    clientLastModifiedUtc: str
    highlightColor: str
    highlightedText: NotRequired[str]
    id: str
    location: AnnotationLocation
    noteText: NotRequired[str]
    type: str  # "note" or "highlight"


def process_annotation_for_sync(
    annotation: KoboAnnotation, 
    book: db.Books, 
    identifiers, 
    progress_percent=None, 
    existing_syncs=None,
    progress_calculator: 'EpubProgressCalculator | None' = None,
    is_blacklisted: bool = False
):
    """
    Process a single annotation and sync to Hardcover if needed.
    
    Args:
        annotation: Annotation dict from Kobo
        book: Calibre book object
        identifiers: Book identifiers dict
        progress_percent: Optional overall book progress
        existing_syncs: Optional dict of {annotation_id: sync_record} for batch processing
    
    Returns:
        True if synced successfully, False otherwise
    """
    annotation_id = annotation.get('id')
    highlighted_text = annotation.get('highlightedText')
    note_text = annotation.get('noteText')
    highlight_color = annotation.get('highlightColor')

    # Skip if no text content
    if not highlighted_text and not note_text:
        log.warning("Skipping annotation with no text content")
        return False

    # Check if already synced
    existing_sync = None
    if not annotation_id:
        log.warning("Annotation ID is required for sync")
        return False

    if existing_syncs is not None:
        # Use pre-loaded sync records (batch processing)
        existing_sync = existing_syncs.get(annotation_id)
    else:
        # Fall back to individual query
        existing_sync = ub.session.query(ub.KoboAnnotationSync).filter(
            ub.KoboAnnotationSync.annotation_id == annotation_id,
            ub.KoboAnnotationSync.user_id == current_user.id
        ).first()
    
    if existing_sync and existing_sync.synced_to_hardcover and existing_sync.highlighted_text == highlighted_text and existing_sync.note_text == note_text and existing_sync.highlight_color == highlight_color:
        log.info(f"Annotation {annotation_id} already synced to Hardcover, skipping")
        return False
    
    if not current_user.hardcover_token:
        log.warning("User has no Hardcover token, skipping sync")
        return False

    if is_blacklisted:
        log.info(f"Skipping annotation sync for book {book.id} - blacklisted for annotations")
        return False
        
    progress_page = None
    chapter_filename = annotation.get('location', {}).get('span', {}).get('chapterFilename')
    chapter_progress = annotation.get('location', {}).get('span', {}).get('chapterProgress')
    
    if progress_percent is None and progress_calculator and chapter_filename:
        progress_percent = progress_calculator.calculate(chapter_filename, chapter_progress)
        if progress_percent is None:
             log.warning(f"Failed to calculate exact progress for annotation in book '{book.title}' (ID: {book.id}). Annotation will sync without progress data.")

    # Sync to Hardcover if enabled and user has valid token
    if (config.config_kobo_sync and
        config.config_hardcover_annotations_sync and
        bool(hardcover)):
        if identifiers:
            log.info(f"Syncing annotation to Hardcover with identifiers: {identifiers}")
            try:
                hardcover_client = hardcover.HardcoverClient(current_user.hardcover_token)
                result = None
                if existing_sync and existing_sync.synced_to_hardcover:
                    # existing but not the same as the previous entry so update it
                    result = hardcover_client.update_journal_entry(
                        journal_id=existing_sync.hardcover_journal_id,
                        note_text=note_text,
                        highlighted_text=highlighted_text
                    )
                else:
                    result = hardcover_client.add_journal_entry(
                        identifiers=identifiers,
                        note_text=note_text,
                        progress_percent=progress_percent,
                        progress_page=progress_page,
                        highlighted_text=highlighted_text
                    )
                
                if result:
                    # Track sync in database only after successful Hardcover sync
                    try:
                        if existing_sync:
                            existing_sync.synced_to_hardcover = True
                            existing_sync.hardcover_journal_id = result.get('id')
                            existing_sync.last_synced = datetime.now(timezone.utc)
                            existing_sync.highlighted_text = highlighted_text
                            existing_sync.note_text = note_text
                            existing_sync.highlight_color = highlight_color
                        else:
                            sync_record = ub.KoboAnnotationSync(
                                user_id=current_user.id,
                                annotation_id=annotation_id,
                                book_id=book.id,
                                synced_to_hardcover=True,
                                hardcover_journal_id=result.get('id'),
                                highlighted_text=highlighted_text,
                                note_text=note_text,
                                highlight_color=highlight_color
                            )
                            ub.session.add(sync_record)
                        ub.session_commit()
                        log.info(f"Successfully synced annotation {annotation_id} to Hardcover (journal ID: {result.get('id')})")
                        return True
                    except Exception as e:
                        log.error(f"Failed to save sync record for annotation {annotation_id}: {e}")
                        log.error(f"Hardcover journal entry {result.get('id')} was created but DB tracking failed - may cause duplicate on retry")
                        ub.session.rollback()
                        # Note: Hardcover sync succeeded but DB record failed
                        # On retry, this could create a duplicate journal entry on Hardcover
                        # TODO: Add cleanup task to reconcile orphaned journal entries
                        return False
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
    


@csrf.exempt
@readingservices_api_v3.route("/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth_and_config
def handle_annotations(entitlement_id):
    """
    Handle annotation requests for a specific book.
    GET: Retrieve all annotations for a book
    PATCH: Update/create annotations
    """
    # GET requests are proxied directly to Kobo at the end of the function
    # We only intercept PATCH requests to sync changes to Hardcover
    if request.method == "PATCH":
        try:
            data = request.get_json()
            log_annotation_data(entitlement_id, "PATCH", data)

            # Get book from database
            book = get_book_by_entitlement_id(entitlement_id)
            if not book:
                log.warning(f"Book not found for entitlement {entitlement_id}, skipping Hardcover sync")
            else:
                identifiers = get_book_identifiers(book)

                if data and "deletedAnnotationIds" in data:
                    deleted_ids = data["deletedAnnotationIds"]
                    log.info(f"Processing {len(deleted_ids)} deleted annotation IDs")
                    for annotation_id in deleted_ids:
                        sync_record = ub.session.query(ub.KoboAnnotationSync).filter(
                            ub.KoboAnnotationSync.annotation_id == annotation_id,
                            ub.KoboAnnotationSync.user_id == current_user.id
                        ).first()
                        if sync_record:
                            try:
                                hardcover_client = hardcover.HardcoverClient(current_user.hardcover_token)
                                deleted_id = hardcover_client.delete_journal_entry(journal_id=sync_record.hardcover_journal_id)
                                if deleted_id == sync_record.hardcover_journal_id:
                                    try:
                                        ub.session.delete(sync_record)
                                        ub.session_commit()
                                        log.info(f"Successfully deleted journal entry {sync_record.hardcover_journal_id} from Hardcover and local DB")
                                    except Exception as db_error:
                                        log.error(f"Failed to delete local sync record after Hardcover deletion succeeded: {db_error}")
                                        log.error(f"Annotation {annotation_id} deleted from Hardcover but DB record remains - manual cleanup may be needed")
                                        ub.session.rollback()
                                else:
                                    log.warning(f"Failed to delete journal entry {sync_record.hardcover_journal_id} from Hardcover - keeping local record")
                            except Exception as api_error:
                                log.error(f"Error deleting annotation {annotation_id} from Hardcover: {api_error}")
                                # Don't delete local record if Hardcover deletion failed
                        else:
                            log.warning(f"Sync record not found for annotation {annotation_id}, skipping deletion")
            
                # Extract updated annotations
                if data and "updatedAnnotations" in data:
                    annotations = data['updatedAnnotations']
                    log.info(f"Processing {len(annotations)} updated annotations")
                
                    # Batch load existing sync records to avoid N+1 queries
                    existing_syncs = {}
                    annotation_ids = [a.get('id') for a in annotations if a.get('id')]
                    if annotation_ids:
                        syncs = ub.session.query(ub.KoboAnnotationSync).filter(
                            ub.KoboAnnotationSync.annotation_id.in_(annotation_ids),
                            ub.KoboAnnotationSync.user_id == current_user.id
                        ).all()
                        existing_syncs = {s.annotation_id: s for s in syncs}
                    
                    # Check blacklist once per book
                    book_blacklist = ub.session.query(ub.HardcoverBookBlacklist).filter(
                        ub.HardcoverBookBlacklist.book_id == book.id
                    ).first()
                    is_blacklisted = book_blacklist and book_blacklist.blacklist_annotations

                    # Initialize progress calculator once per book
                    progress_calculator = EpubProgressCalculator(book)

                    for annotation in annotations:
                        process_annotation_for_sync(
                            annotation=annotation, 
                            book=book, 
                            identifiers=identifiers, 
                            existing_syncs=existing_syncs,
                            progress_calculator=progress_calculator,
                            is_blacklisted=is_blacklisted
                        )

        except Exception as e:
            log.error(f"Error processing PATCH annotations: {e}")
            import traceback
            log.error(traceback.format_exc())

    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_api_v3.route("/content/checkforchanges", methods=["POST"])
@requires_reading_services_auth_and_config
def handle_check_for_changes():
    """
    Handle check for changes request.
    Proxies to Kobo's reading services.
    """
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_userstorage.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth_and_config
def handle_user_storage(subpath):
    """
    Handle UserStorage API requests (e.g., /api/UserStorage/Metadata).
    Proxies to Kobo's reading services.
    """
    
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_api_v3.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth_and_config
def handle_unknown_reading_service_request(subpath):
    """
    Catch-all handler for any reading services requests not explicitly handled.
    Logs the request and proxies to Kobo's reading services.
    """
    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()

