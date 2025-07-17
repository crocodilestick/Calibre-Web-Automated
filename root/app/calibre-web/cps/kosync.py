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
import base64
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
    return isinstance(field, str) and len(field) > 0


def is_valid_key_field(field: Any) -> bool:
    """Check if a field is valid as a key (not empty string and contains no colon)"""
    return is_valid_field(field) and ":" not in field


def authenticate_user() -> Optional[ub.User]:
    """
    Authenticate user using standard HTTP Basic Authentication
    Expects Authorization header with 'Basic <base64(username:password)>'
    """
    auth_header = request.headers.get('Authorization')

    if not auth_header or not auth_header.startswith('Basic '):
        log.warning("authenticate_user: Missing or invalid Authorization header")
        return None

    try:
        # Extract and decode the base64 encoded credentials
        encoded_credentials = auth_header[6:]  # Remove 'Basic ' prefix
        decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')

        # Split username and password
        if ':' not in decoded_credentials:
            log.warning("authenticate_user: Invalid credentials format")
            return None

        username, password = decoded_credentials.split(':', 1)

    except (ValueError, UnicodeDecodeError) as e:
        log.warning(f"authenticate_user: Failed to decode credentials: {str(e)}")
        return None

    if not is_valid_field(password) or not is_valid_key_field(username):
        log.warning("authenticate_user: Invalid username or password format")
        return None

    # Find user by username (case-insensitive, like Calibre-Web)
    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username.lower()).first()

    if not user:
        log.warning(f"authenticate_user: User not found: {username}")
        return None

    # Standard password check (convert password to string like Calibre-Web does)
    if check_password_hash(str(user.password), password):
        log.info(f"authenticate_user: Successfully authenticated user: {user.name}")
        return user

    log.warning(f"authenticate_user: Password mismatch for user: {user.name}")
    return None


def create_sync_response(data: Dict[str, Any], status_code: int = 200) -> tuple:
    """Create a standardized sync response"""
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
    return render_template("kosync_plugin.html", title=_("KOReader Sync Plugin"))


@csrf.exempt
@kosync.route("/kosync/users/auth", methods=["GET"])
def auth_user():
    """
    Authenticate user endpoint
    Returns 200 if user is authenticated, 401 otherwise
    """
    user = authenticate_user()
    if user:
        return create_sync_response({"authorized": "OK"})
    else:
        return create_sync_response({
            "error": ERROR_UNAUTHORIZED_USER,
            "message": "Unauthorized user"
        }, 401)

@csrf.exempt
@kosync.route("/kosync/syncs/progress/<document>", methods=["GET"])
def get_progress(document: str):
    """
    Get reading progress for a document
    """
    try:
        user = authenticate_user()
        if not user:
            raise KOSyncError(ERROR_UNAUTHORIZED_USER, "Unauthorized user")

        if not is_valid_key_field(document):
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        # Query progress from database
        progress_record = ub.session.query(ub.KOSyncProgress).filter(
            ub.KOSyncProgress.user_id == user.id,
            ub.KOSyncProgress.document == document
        ).first()

        if not progress_record:
            return create_sync_response({})

        response_data = {
            "document": document,
            "progress": progress_record.progress,
            "percentage": progress_record.percentage,
            "device": progress_record.device,
            "device_id": progress_record.device_id,
            "timestamp": int(progress_record.timestamp.timestamp())
        }

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
    try:
        user = authenticate_user()
        if not user:
            raise KOSyncError(ERROR_UNAUTHORIZED_USER, "Unauthorized user")

        data = request.get_json()
        if not data:
            raise KOSyncError(ERROR_INVALID_FIELDS, "Invalid request data")

        document = data.get("document")
        if not is_valid_key_field(document):
            raise KOSyncError(ERROR_DOCUMENT_FIELD_MISSING, "Invalid document field")

        progress = data.get("progress")
        percentage = data.get("percentage")
        device = data.get("device")
        device_id = data.get("device_id")

        if not (progress and percentage is not None and device):
            raise KOSyncError(ERROR_INVALID_FIELDS, "Missing required fields")

        timestamp = datetime.now(timezone.utc)

        # Check if progress record exists
        progress_record = ub.session.query(ub.KOSyncProgress).filter(
            ub.KOSyncProgress.user_id == user.id,
            ub.KOSyncProgress.document == document
        ).first()

        if progress_record:
            # Update existing record
            progress_record.progress = progress
            progress_record.percentage = float(percentage)
            progress_record.device = device
            progress_record.device_id = device_id
            progress_record.timestamp = timestamp
        else:
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
    return create_sync_response({
        "error": ERROR_INVALID_FIELDS,
        "message": "Bad request"
    }, 400)


@kosync.errorhandler(401)
def handle_unauthorized(error):
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
