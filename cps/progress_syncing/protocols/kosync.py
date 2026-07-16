#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
KOReader Sync Server Implementation for Calibre-Web-Automated

This module provides a sync server compatible with KOReader's sync functionality,
allowing users to sync their reading progress across devices.

Protocol Specification:
    - Authentication: HTTP Basic Auth (RFC 7617)
    - Endpoints:
        * GET  /kosync/users/auth - Authenticate user
        * GET  /kosync/syncs/progress/<document> - Get reading progress
        * PUT  /kosync/syncs/progress - Update reading progress
        * GET  /kosync - Plugin download page

Security:
    - All API endpoints use HTTP Basic Authentication
    - Document identifiers validated to prevent injection attacks
    - Session management via SQLAlchemy with proper isolation
    - Rate limiting should be applied at reverse proxy level

Integration:
    - Syncs with Calibre library via BookFormatChecksum table
    - Updates ReadBook status based on reading percentage thresholds
    - Maintains KoboReadingState for compatibility with Kobo sync
    - Atomic commits ensure sync data integrity

Based on the reference implementation from koreader-sync-server
Reference: https://github.com/koreader/koreader-sync-server
"""

import base64
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Tuple

from flask import Blueprint, request, jsonify
from flask_babel import gettext as _
from werkzeug.security import check_password_hash
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from ... import logger, ub, csrf, config, constants, services
from ...usermanagement import using_basic_auth, auth
from ...render_template import render_title_template
from ..models import KOSyncProgress
from ..settings import is_koreader_sync_enabled

log = logger.create()

# Create the blueprint
kosync = Blueprint('kosync', __name__)

# Error codes matching KOReader sync server specification
ERROR_NO_STORAGE = 1000
ERROR_INTERNAL = 2000
ERROR_UNAUTHORIZED_USER = 2001
ERROR_USER_EXISTS = 2002
ERROR_INVALID_FIELDS = 2003
ERROR_DOCUMENT_FIELD_MISSING = 2004

# Field names (constants for API contract)
PROGRESS_FIELD = "progress"
PERCENTAGE_FIELD = "percentage"
DEVICE_FIELD = "device"
DEVICE_ID_FIELD = "device_id"
TIMESTAMP_FIELD = "timestamp"

# Validation constants
MAX_DOCUMENT_LENGTH = 255  # Maximum document identifier length
MAX_PROGRESS_LENGTH = 255  # Maximum progress string length
MAX_DEVICE_LENGTH = 100    # Maximum device name length
MAX_DEVICE_ID_LENGTH = 100 # Maximum device ID length


def _require_kosync_enabled():
    if not is_koreader_sync_enabled():
        return create_sync_response({
            "error": ERROR_NO_STORAGE,
            "message": "KOReader sync is disabled"
        }, 503)
    return None


class KOSyncError(Exception):
    """Custom exception for KOSync protocol errors"""
    def __init__(self, error_code: int, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)
        
def get_kosync_unauthorized_error() -> tuple:
    return handle_unauthorized(None)
        
# Basic auth decorator with custom KOSync unauthorized error handling
kosync_basic_auth = using_basic_auth(False, get_kosync_unauthorized_error)

def is_valid_field(field: Any) -> bool:
    """
    Check if a field is valid (not None, not empty string).

    Args:
        field: Value to validate

    Returns:
        True if field is a non-empty string
    """
    return isinstance(field, str) and len(field) > 0


def is_valid_key_field(field: Any, max_length: int = MAX_DOCUMENT_LENGTH) -> bool:
    """
    Check if a field is valid as a database key.

    Key fields must be non-empty strings without colons (reserved for internal use)
    and within specified length limits.

    Args:
        field: Value to validate
        max_length: Maximum allowed length

    Returns:
        True if field is valid for use as a key
    """
    return is_valid_field(field) and ":" not in field and len(field) <= max_length


def create_sync_response(data: Dict[str, Any], status_code: int = 200) -> tuple:
    """
    Create a standardized JSON sync response.

    Args:
        data: Response payload dictionary
        status_code: HTTP status code (default: 200)

    Returns:
        Tuple of (response, status_code) for Flask
    """
    return jsonify(data), status_code


def handle_sync_error(error: KOSyncError) -> tuple:
    """
    Handle sync errors and return appropriate response.

    Args:
        error: KOSyncError with error code and message

    Returns:
        JSON error response with 400 status code
    """
    log.error(f"KOSync Error {error.error_code}: {error.message}")
    return create_sync_response({
        "error": error.error_code,
        "message": error.message
    }, 400)


def get_book_by_checksum(document_checksum: str, version: str = None):
    """
    Lookup a book in the Calibre library by its partial MD5 checksum.

    Searches all stored checksums for the given checksum value, regardless of
    whether it came from library files or OPDS exports.

    Args:
        document_checksum: The partial MD5 checksum from KOReader
        version: Optional algorithm version to filter by (None = any version)

    Returns:
        Tuple of (book_id, book_format, book_title, book_path, version) or
        (None, None, None, None, None) if no match found

    Note:
        Uses parameterized queries to prevent SQL injection.
        Orders by created DESC (latest first), then version DESC.
    """
    from ... import calibre_db
    from ...db import BookFormatChecksum, Books

    try:
        query = calibre_db.session.query(
            BookFormatChecksum.book,
            BookFormatChecksum.format,
            BookFormatChecksum.version,
            Books.title,
            Books.path
        ).join(
            Books, BookFormatChecksum.book == Books.id
        ).filter(
            BookFormatChecksum.checksum == document_checksum
        )

        # Optionally filter by version
        if version is not None:
            query = query.filter(BookFormatChecksum.version == version)

        # Order by created DESC (latest first), then version DESC
        query = query.order_by(
            BookFormatChecksum.created.desc(),
            BookFormatChecksum.version.desc()
        )

        result = query.first()

        if result:
            book_id, book_format, checksum_version, book_title, book_path = result
            log.debug(f"Found book match: {book_title} (ID {book_id}, format {book_format}, checksum v{checksum_version})")
            return book_id, book_format, book_title, book_path, checksum_version

        # No match found
        log.debug(f"No book found for checksum: {document_checksum}")
        return None, None, None, None, None

    except SQLAlchemyError as e:
        log.error(f"Database error looking up book by checksum {document_checksum}: {e}")
        return None, None, None, None, None
    except Exception as e:
        log.error(f"Unexpected error looking up book by checksum {document_checksum}: {e}")
        return None, None, None, None, None


def enrich_response_with_book_info(response_data: Dict[str, Any], document_checksum: str) -> Dict[str, Any]:
    """
    Enrich a sync response with Calibre book information if the book is found.

    This adds Calibre-specific metadata to the response, allowing clients to
    display richer information about the synced document.

    Args:
        response_data: The response dictionary to enrich
        document_checksum: The document checksum to look up

    Returns:
        Tuple of (enriched_response_data, book_id, book_format, book_title, checksum_version)
    """
    book_id, book_format, book_title, book_path, checksum_version = get_book_by_checksum(document_checksum)

    if book_id:
        response_data["calibre_book_id"] = book_id
        response_data["calibre_book_title"] = book_title
        response_data["calibre_book_format"] = book_format
        response_data["calibre_checksum_version"] = checksum_version

    return response_data, book_id, book_format, book_title, checksum_version


def update_book_read_status(user_id: int, book_id: int, percentage: float) -> None:
    """
    Update the user's ReadBook status based on reading progress percentage.

    Status thresholds:
        - 0%: STATUS_UNREAD
        - 1-98%: STATUS_IN_PROGRESS
        - 99-100%: STATUS_FINISHED

    Behavior:
        - Creates ReadBook record if it doesn't exist
        - Increments times_started_reading when transitioning to IN_PROGRESS
        - Updates KoboBookmark progress_percent for Kobo sync compatibility
        - Handles status transitions gracefully

    Args:
        user_id: The ID of the user
        book_id: The ID of the book in the Calibre library
        percentage: Reading progress percentage (0.0 to 100.0)

    Raises:
        SQLAlchemyError: If database operation fails

    Note:
        Caller is responsible for committing the session.
    """
    # Determine the new read status based on percentage
    if percentage >= 99.0:
        new_status = ub.ReadBook.STATUS_FINISHED
    elif percentage > 0:
        new_status = ub.ReadBook.STATUS_IN_PROGRESS
    else:
        new_status = ub.ReadBook.STATUS_UNREAD

    log.debug(f"update_book_read_status: user {user_id}, book {book_id}, "
              f"percentage {percentage:.2f}% -> status {new_status}")

    # Query for existing ReadBook record
    book_read = ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == user_id,
        ub.ReadBook.book_id == book_id
    ).first()

    if book_read:
        # Update existing record
        old_status = book_read.read_status
        log.debug(f"Found existing ReadBook: old_status={old_status}, new_status={new_status}")

        # Increment times_started_reading when transitioning to IN_PROGRESS
        if new_status == ub.ReadBook.STATUS_IN_PROGRESS and old_status != ub.ReadBook.STATUS_IN_PROGRESS:
            book_read.times_started_reading += 1
            book_read.last_time_started_reading = datetime.now(timezone.utc)
            log.info(f"User {user_id} started reading book {book_id} "
                    f"(times started: {book_read.times_started_reading})")

        # Update status if changed
        if old_status != new_status:
            book_read.read_status = new_status
            log.info(f"User {user_id} book {book_id} status changed: "
                    f"{old_status} -> {new_status} (progress: {percentage:.1f}%)")
        else:
            log.debug(f"ReadBook status unchanged: {old_status}")

        book_read.last_modified = datetime.now(timezone.utc)

        # Update KoboBookmark progress_percent if it exists
        if book_read.kobo_reading_state and book_read.kobo_reading_state.current_bookmark:
            book_read.kobo_reading_state.current_bookmark.progress_percent = percentage
            book_read.kobo_reading_state.current_bookmark.last_modified = datetime.now(timezone.utc)

    else:
        # Create new ReadBook record
        book_read = ub.ReadBook(
            user_id=user_id,
            book_id=book_id,
            read_status=new_status
        )

        # Set started reading fields for IN_PROGRESS books
        # Note: Following Kobo/CWA convention, times_started_reading only increments
        # when status is IN_PROGRESS. Books that jump straight to FINISHED (e.g.,
        # syncing at 100% without intermediate syncs) will have times_started_reading=0
        if new_status == ub.ReadBook.STATUS_IN_PROGRESS:
            book_read.times_started_reading = 1
            book_read.last_time_started_reading = datetime.now(timezone.utc)
            log.info(f"User {user_id} started reading book {book_id} (new entry)")

        # Create associated KoboReadingState
        kobo_reading_state = ub.KoboReadingState(
            user_id=user_id,
            book_id=book_id
        )
        kobo_reading_state.current_bookmark = ub.KoboBookmark()
        kobo_reading_state.current_bookmark.progress_percent = percentage
        kobo_reading_state.statistics = ub.KoboStatistics()
        book_read.kobo_reading_state = kobo_reading_state

        ub.session.add(book_read)
        log.info(f"User {user_id} book {book_id} created with status {new_status} "
                f"(progress: {percentage:.1f}%)")

    # Merge the record (caller commits)
    ub.session.merge(book_read)


################################################################################
# API Endpoints
################################################################################

@kosync.route("/kosync")
def kosync_plugin_page():
    """
    Display the KOReader plugin download and installation page.

    This page provides:
        - Plugin download link
        - Installation instructions
        - Configuration guidance
        - Troubleshooting tips

    Returns:
        Rendered HTML page
    """
    return render_title_template(
        "kosync_plugin.html",
        title=_("KOReader Sync Plugin"),
        page="cwa-kosync",
        kosync_enabled=is_koreader_sync_enabled()
    )


@csrf.exempt
@kosync.route("/kosync/users/auth", methods=["GET"])
@kosync_basic_auth
def auth_user():
    """
    Authenticate user endpoint (KOSync protocol).

    This endpoint act as a ping with credentials
    during KOReader sync setup to validate the connection.

    Returns:
        200: {"authorized": "OK"} if authentication succeeds
        401: {"error": 2001, "message": "Unauthorized"} if authentication fails (handled by the @kosync_basic_auth decorator)

    Note:
        Rate limiting should be applied at reverse proxy level to prevent
        brute force attacks (suggested: 10 requests per minute per IP).
    """
    blocked = _require_kosync_enabled()
    if blocked:
        return blocked

    return create_sync_response({"authorized": "OK"})

@csrf.exempt
@kosync.route("/kosync/syncs/progress/<document>", methods=["GET"])
@kosync_basic_auth
def get_progress(document: str):
    """
    Get reading progress for a document (KOSync protocol).

    Returns the latest progress for the specified document identifier,
    enriched with Calibre library metadata if the book is matched.

    Args:
        document: Document identifier (KOReader partial MD5 hash)

    Returns:
        200: Progress data with optional Calibre metadata
        400: Error response if validation fails
        401: Unauthorized if authentication fails

    Response format:
        {
            "document": "abc123...",
            "progress": "location string",
            "percentage": 0.4567,  # Decimal fraction (0.4567 = 45.67%)
            "device": "KOReader",
            "device_id": "device123",
            "timestamp": 1699564800,
            "calibre_book_id": 42,  # Optional: if matched
            "calibre_book_title": "Book Title",  # Optional
            "calibre_book_format": "EPUB",  # Optional
            "calibre_checksum_version": "koreader"  # Optional
        }

    Note:
        Percentage is returned as decimal (0.4567 = 45.67%) as expected by KOReader.
        Internally stored as percentage (0-100) in database.
    """
    try:
        blocked = _require_kosync_enabled()
        if blocked:
            return blocked

        user = auth.current_user()

        if not is_valid_key_field(document):
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        # Query progress from database
        progress_record = ub.session.query(KOSyncProgress).filter(
            KOSyncProgress.user_id == user.id,
            KOSyncProgress.document == document
        ).first()

        if not progress_record:
            log.debug(f"No progress found for user {user.id}, document {document}")
            return create_sync_response({})

        # KOReader expects percentage as a decimal fraction (0.9411 = 94.11%)
        # We store it as percentage (0-100), so convert back to decimal (0-1)
        percentage_decimal = progress_record.percentage / 100.0

        response_data = {
            "document": document,
            "progress": progress_record.progress,
            "percentage": percentage_decimal,
            "device": progress_record.device,
            "device_id": progress_record.device_id,
            "timestamp": int(progress_record.timestamp.timestamp())
        }

        # Enrich response with Calibre book information if available
        response_data, book_id, book_format, book_title, _ = enrich_response_with_book_info(
            response_data, document
        )

        return create_sync_response(response_data)

    except KOSyncError as e:
        return handle_sync_error(e)
    except SQLAlchemyError as e:
        log.error(f"get_progress: Database error: {str(e)}")
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Database error"))
    except Exception as e:
        log.error(f"get_progress: Unexpected error: {str(e)}")
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Internal server error"))


@csrf.exempt
@kosync.route("/kosync/syncs/progress", methods=["PUT"])
@kosync_basic_auth
def update_progress():
    """
    Update reading progress for a document (KOSync protocol).

    This endpoint receives progress updates from KOReader devices and:
        1. Validates and stores the sync data in kosync_progress table
        2. Attempts to match the document to a Calibre library book
        3. Updates ReadBook status if a match is found

    The commit strategy ensures sync data is always persisted, even if
    ReadBook updates fail (preventing sync data loss).

    Request body:
        {
            "document": "abc123...",  # Required: Document identifier
            "progress": "location",   # Required: Current reading position
            "percentage": 0.4567,     # Required: Progress as decimal (0-1)
            "device": "KOReader",     # Required: Device name
            "device_id": "device123"  # Optional: Device identifier
        }

    Returns:
        200: Success with document and timestamp
        400: Validation error
        401: Unauthorized
        500: Internal error

    Response format:
        {
            "document": "abc123...",
            "timestamp": 1699564800,
            "calibre_book_id": 42,  # Optional: if matched
            "calibre_book_title": "Book Title",  # Optional
            "calibre_book_format": "EPUB",  # Optional
            "calibre_checksum_version": "koreader"  # Optional
        }

    Note:
        Percentage is converted from decimal (0.9411 = 94.11%) to percentage (94.11).
    """
    try:
        blocked = _require_kosync_enabled()
        if blocked:
            return blocked

            user = auth.current_user()

        data = request.get_json()
        if not data:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid request data")

        # Extract and validate required fields
        document = data.get("document")
        if not is_valid_key_field(document):
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        progress = data.get("progress")
        percentage = data.get("percentage")
        device = data.get("device")
        device_id = data.get("device_id")

        # Validate required fields
        if not progress or percentage is None or not device:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Missing required fields")

        # Validate field lengths
        if not is_valid_field(progress) or len(progress) > MAX_PROGRESS_LENGTH:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid progress field")
        if not is_valid_field(device) or len(device) > MAX_DEVICE_LENGTH:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid device field")
        if device_id and len(device_id) > MAX_DEVICE_ID_LENGTH:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid device_id field")

        # KOReader sends percentage as a decimal fraction (0.9411 = 94.11%)
        # Convert to actual percentage (0-100 range)
        try:
            percentage_float = float(percentage)
            if percentage_float <= 1.0:
                percentage_float *= 100.0
            if percentage_float < 0 or percentage_float > 100:
                raise ValueError("Percentage out of range")
        except (ValueError, TypeError) as e:
            raise KOSyncError(ERROR_INVALID_FIELDS, f"Invalid percentage value: {e}")

        timestamp = datetime.now(timezone.utc)

        # Check if progress record exists
        progress_record = ub.session.query(KOSyncProgress).filter(
            KOSyncProgress.user_id == user.id,
            KOSyncProgress.document == document
        ).first()

        if progress_record:
            # Update existing record
            progress_record.progress = progress
            progress_record.percentage = percentage_float
            progress_record.device = device
            progress_record.device_id = device_id
            progress_record.timestamp = timestamp
            log.debug(f"Updated kosync progress for user {user.id}, document {document}")
        else:
            # Create new record
            progress_record = KOSyncProgress(
                user_id=user.id,
                document=document,
                progress=progress,
                percentage=percentage_float,
                device=device,
                device_id=device_id,
                timestamp=timestamp
            )
            ub.session.add(progress_record)
            log.debug(f"Created kosync progress for user {user.id}, document {document}")

        # CRITICAL: Always commit kosync_progress first before attempting ReadBook updates
        # This ensures sync location is persisted even if ReadBook update fails
        try:
            ub.session.commit()
            log.info(f"Saved kosync progress: user={user.id}, document={document}, "
                    f"progress={percentage_float:.2f}%")
        except SQLAlchemyError as e:
            log.error(f"Failed to commit kosync_progress: {e}")
            ub.session.rollback()
            raise KOSyncError(ERROR_INTERNAL, "Failed to save sync progress")

        response_data = {
            "document": document,
            "timestamp": int(timestamp.timestamp())
        }

        # Enrich response with Calibre book information if available
        response_data, book_id, book_format, book_title, _ = enrich_response_with_book_info(
            response_data, document
        )

        # Update user's ReadBook status if we matched a book
        # This is done AFTER kosync_progress is committed, so sync location is always safe
        if book_id:
            try:
                update_book_read_status(user.id, book_id, percentage_float)
                ub.session.commit()
                log.info(f"Updated ReadBook status: user={user.id}, book={book_id} "
                        f"({book_title}), status based on {percentage_float:.1f}%")
            except SQLAlchemyError as e:
                log.error(f"Failed to update ReadBook status for book {book_id}: {e}")
                # Rollback only affects the failed ReadBook update
                # kosync_progress was already committed and is safe
                ub.session.rollback()
            except Exception as e:
                log.error(f"Unexpected error updating ReadBook status for book {book_id}: {e}")
                ub.session.rollback()

        return create_sync_response(response_data)

    except KOSyncError as e:
        return handle_sync_error(e)
    except SQLAlchemyError as e:
        log.error(f"update_progress: Database error: {str(e)}")
        ub.session.rollback()
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Database error"))
    except Exception as e:
        log.error(f"update_progress: Unexpected error: {str(e)}")
        ub.session.rollback()
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Internal server error"))


################################################################################
# Error Handlers
################################################################################

@kosync.errorhandler(400)
def handle_bad_request(error):
    """Handle HTTP 400 Bad Request errors"""
    return create_sync_response({
        "error": ERROR_INVALID_FIELDS,
        "message": "Bad request"
    }, 400)


@kosync.errorhandler(401)
def handle_unauthorized(error):
    """Handle HTTP 401 Unauthorized errors"""
    return create_sync_response({
        "error": ERROR_UNAUTHORIZED_USER,
        "message": "Unauthorized"
    }, 401)


@kosync.errorhandler(500)
def handle_internal_error(error):
    """Handle HTTP 500 Internal Server errors"""
    log.error(f"Internal server error: {error}")
    return create_sync_response({
        "error": ERROR_INTERNAL,
        "message": "Internal server error"
    }, 500)
