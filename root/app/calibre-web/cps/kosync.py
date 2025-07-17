#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KOReader Sync Server Implementation for Calibre-Web-Automated

This module provides a sync server compatible with KOReader's sync functionality,
allowing users to sync their reading progress across devices.

Based on the reference implementation from koreader-sync-server
"""

import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Tuple

from flask import Blueprint, request, jsonify, g, render_template
from flask_babel import gettext as _
from werkzeug.security import check_password_hash
from sqlalchemy import func

from . import logger, ub, config, csrf, constants, services
from .cw_login import current_user
from .usermanagement import user_login_required

log = logger.create()

# Create the blueprint
kosync = Blueprint('kosync', __name__)

# Error codes matching the original implementation
ERROR_NO_STORAGE = 1000
ERROR_INTERNAL = 2000
ERROR_UNAUTHORIZED_USER = 2001
ERROR_USER_EXISTS = 2002
ERROR_INVALID_FIELDS = 2003
ERROR_DOCUMENT_FIELD_MISSING = 2004

# Field names
PROGRESS_FIELD = "progress"
PERCENTAGE_FIELD = "percentage"
DEVICE_FIELD = "device"
DEVICE_ID_FIELD = "device_id"
TIMESTAMP_FIELD = "timestamp"


class KOSyncError(Exception):
    """Custom exception for KOSync errors"""
    def __init__(self, error_code: int, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def is_valid_field(field: Any) -> bool:
    """Check if a field is valid (not empty string)"""
    result = isinstance(field, str) and len(field) > 0
    log.debug(f"is_valid_field check: field={field}, result={result}")
    return result


def is_valid_key_field(field: Any) -> bool:
    """Check if a field is valid as a key (not empty string and contains no colon)"""
    result = is_valid_field(field) and ":" not in field
    log.debug(f"is_valid_key_field check: field={field}, result={result}")
    return result


def authenticate_user() -> Optional[ub.User]:
    """
    Authenticate user using x-auth-user and x-auth-key headers
    Similar to the original authorize() function and Calibre-Web's verify_password
    """
    auth_user = request.headers.get('x-auth-user')
    auth_key = request.headers.get('x-auth-key')

    log.debug(f"authenticate_user: headers received - x-auth-user: {auth_user}, x-auth-key: {auth_key}")

    if not is_valid_field(auth_key) or not is_valid_key_field(auth_user):
        log.warning("authenticate_user: Invalid auth fields")
        return None

    # Find user by username (case-insensitive, like Calibre-Web)
    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == auth_user.lower()).first()

    if not user:
        log.warning(f"authenticate_user: User not found: {auth_user}")
        return None

    log.debug(f"authenticate_user: Found user: {user.name} (ID: {user.id})")
    log.debug(f"authenticate_user: User password hash starts with: {user.password[:20]}...")
    log.debug(f"authenticate_user: Auth key length: {len(auth_key) if auth_key else 0}")

    # Standard password check (convert password to string like Calibre-Web does)
    if check_password_hash(str(user.password), auth_key):
        log.info(f"authenticate_user: Successfully authenticated user: {user.name}")
        return user

    log.warning(f"authenticate_user: Password mismatch for user: {user.name}")
    log.debug(f"authenticate_user: Tried password check with str(password): {check_password_hash(str(user.password), auth_key)}")
    return None


def create_sync_response(data: Dict[str, Any], status_code: int = 200) -> tuple:
    """Create a standardized sync response"""
    log.debug(f"create_sync_response: status_code={status_code}, data={json.dumps(data, indent=2)}")
    return jsonify(data), status_code


def handle_sync_error(error: KOSyncError) -> tuple:
    """Handle sync errors and return appropriate response"""
    log.error(f"KOSync Error {error.error_code}: {error.message}")
    return create_sync_response({
        "error": error.error_code,
        "message": error.message
    }, 400)


################################################################################
# Routes
################################################################################
@kosync.route("/kosync")
def kosync_plugin_page():
    """
    Display the KOReader plugin download and installation page
    """
    log.info("kosync_plugin_page: Displaying KOReader plugin page")
    return render_template("kosync_plugin.html", title=_("KOReader Sync Plugin"))


@csrf.exempt
@kosync.route("/kosync/users/auth", methods=["GET"])
def auth_user():
    """
    Authenticate user endpoint
    Returns 200 if user is authenticated, 401 otherwise
    """
    log.info("auth_user: Starting authentication check")
    user = authenticate_user()
    if user:
        log.info(f"auth_user: Successfully authenticated user: {user.name}")
        return create_sync_response({"authorized": "OK"})
    else:
        log.warning("auth_user: Authentication failed")
        return create_sync_response({
            "error": ERROR_UNAUTHORIZED_USER,
            "message": "Unauthorized user"
        }, 401)


@csrf.exempt
@kosync.route("/kosync/users/create", methods=["POST"])
def create_user():
    """
    Create user endpoint - not implemented as we use existing Calibre-Web users
    Returns an error indicating users should be created through Calibre-Web
    """
    log.info("create_user: User creation attempt (not implemented)")
    return create_sync_response({
        "error": ERROR_USER_EXISTS,
        "message": "User management is handled by Calibre-Web. Please create users through the admin interface."
    }, 409)


@csrf.exempt
@kosync.route("/kosync/syncs/progress/<document>", methods=["GET"])
def get_progress(document: str):
    """
    Get reading progress for a document
    """
    log.info(f"get_progress: Starting progress retrieval for document: {document}")

    try:
        user = authenticate_user()
        if not user:
            log.warning("get_progress: Authentication failed")
            raise KOSyncError(ERROR_UNAUTHORIZED_USER, "Unauthorized user")

        if not is_valid_key_field(document):
            log.warning(f"get_progress: Invalid document field: {document}")
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        log.debug(f"get_progress: Querying progress for user_id={user.id}, document={document}")

        # Query progress from database
        progress_record = ub.session.query(ub.KOSyncProgress).filter(
            ub.KOSyncProgress.user_id == user.id,
            ub.KOSyncProgress.document == document
        ).first()

        if not progress_record:
            log.info(f"get_progress: No progress found for document: {document}")
            return create_sync_response({})

        response_data = {
            "document": document,
            "progress": progress_record.progress,
            "percentage": progress_record.percentage,
            "device": progress_record.device,
            "device_id": progress_record.device_id,
            "timestamp": int(progress_record.timestamp.timestamp())
        }

        log.info(f"get_progress: Found progress for document: {document}")
        log.debug(f"get_progress: Progress data: {json.dumps(response_data, indent=2)}")

        return create_sync_response(response_data)

    except KOSyncError as e:
        return handle_sync_error(e)
    except Exception as e:
        log.error(f"get_progress: Error getting progress: {str(e)}")
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Internal server error"))


@csrf.exempt
@kosync.route("/kosync/syncs/progress", methods=["PUT"])
def update_progress():
    """
    Update reading progress for a document
    """
    log.info("update_progress: Starting progress update")

    try:
        user = authenticate_user()
        if not user:
            log.warning("update_progress: Authentication failed")
            raise KOSyncError(ERROR_UNAUTHORIZED_USER, "Unauthorized user")

        data = request.get_json()
        log.debug(f"update_progress: Received data: {json.dumps(data, indent=2)}")

        if not data:
            log.warning("update_progress: No JSON data received")
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid request data")

        document = data.get("document")
        if not is_valid_key_field(document):
            log.warning(f"update_progress: Invalid document field: {document}")
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        progress = data.get("progress")
        percentage = data.get("percentage")
        device = data.get("device")
        device_id = data.get("device_id")

        if not (progress and percentage is not None and device):
            log.warning(f"update_progress: Missing required fields - progress: {progress}, percentage: {percentage}, device: {device}")
            raise KOSyncError(ERROR_INVALID_FIELDS, "Missing required fields")

        timestamp = datetime.now(timezone.utc)
        log.debug(f"update_progress: Processing update for document: {document}, user_id: {user.id}")

        # Check if progress record exists
        progress_record = ub.session.query(ub.KOSyncProgress).filter(
            ub.KOSyncProgress.user_id == user.id,
            ub.KOSyncProgress.document == document
        ).first()

        if progress_record:
            log.info(f"update_progress: Updating existing progress record for document: {document}")
            # Update existing record
            progress_record.progress = progress
            progress_record.percentage = float(percentage)
            progress_record.device = device
            progress_record.device_id = device_id
            progress_record.timestamp = timestamp
        else:
            log.info(f"update_progress: Creating new progress record for document: {document}")
            # Create new record
            progress_record = ub.KOSyncProgress(
                user_id=user.id,
                document=document,
                progress=progress,
                percentage=float(percentage),
                device=device,
                device_id=device_id,
                timestamp=timestamp
            )
            ub.session.add(progress_record)

        ub.session.commit()
        log.info(f"update_progress: Successfully updated progress for document: {document}")

        return create_sync_response({
            "document": document,
            "timestamp": int(timestamp.timestamp())
        })

    except KOSyncError as e:
        return handle_sync_error(e)
    except Exception as e:
        log.error(f"update_progress: Error updating progress: {str(e)}")
        ub.session.rollback()
        return handle_sync_error(KOSyncError(ERROR_INTERNAL, "Internal server error"))


# Error handlers
@kosync.errorhandler(400)
def handle_bad_request(error):
    log.warning("handle_bad_request: Bad request received")
    return create_sync_response({
        "error": ERROR_INVALID_FIELDS,
        "message": "Bad request"
    }, 400)


@kosync.errorhandler(401)
def handle_unauthorized(error):
    log.warning("handle_unauthorized: Unauthorized access attempt")
    return create_sync_response({
        "error": ERROR_UNAUTHORIZED_USER,
        "message": "Unauthorized"
    }, 401)


@kosync.errorhandler(500)
def handle_internal_error(error):
    log.error("handle_internal_error: Internal server error occurred")
    return create_sync_response({
        "error": ERROR_INTERNAL,
        "message": "Internal server error"
    }, 500)
