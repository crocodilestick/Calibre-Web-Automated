# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from functools import wraps

from sqlalchemy.sql.expression import func
from .cw_login import login_required

from flask import request, g
from flask_httpauth import HTTPBasicAuth
from werkzeug.datastructures import Authorization
from werkzeug.security import check_password_hash

from . import lm, ub, config, logger, limiter, constants, services


log = logger.create()
auth = HTTPBasicAuth()


def create_authenticated_user(username, email=None, auth_source="unknown"):
    """Create new user with default configuration settings for external authentication"""
    try:
        # Sanitize and validate username
        if not username:
            log.error("Cannot create user: username is None or empty")
            return None
            
        username = username.strip()
        if not username or len(username) < 1:
            log.error("Cannot create user: username is empty after stripping")
            return None
            
        if len(username) > 64:  # Reasonable username length limit
            log.error("Cannot create user: username too long (%d chars)", len(username))
            return None
            
        # Check for existing user to prevent duplicate creation
        existing_user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username.lower()).first()
        if existing_user:
            log.warning("User '%s' already exists, returning existing user", username)
            return existing_user
            
        # Generate email if not provided
        if not email:
            email = f"{username}@localhost"
        
        # Create user with same defaults as OAuth users
        user = ub.User()
        user.name = username
        user.email = email
        user.password = ''  # No local password for external auth users
        
        # Apply default configuration settings (same pattern as OAuth and normal registration)
        user.role = config.config_default_role
        user.sidebar_view = config.config_default_show
        user.locale = config.config_default_locale
        user.default_language = config.config_default_language
        
        # Apply default restrictions and permissions
        user.allowed_tags = getattr(config, 'config_allowed_tags', '')
        user.denied_tags = getattr(config, 'config_denied_tags', '')
        user.allowed_column_value = getattr(config, 'config_allowed_column_value', '')
        user.denied_column_value = getattr(config, 'config_denied_column_value', '')
        
        # Force dark theme (light theme deprecated)
        user.theme = 1
            
        # Kobo sync setting defaults to 0 (disabled) for new users
        user.kobo_only_shelves_sync = 0
        
        ub.session.add(user)
        ub.session.commit()
        
        log.info("Auto-created user '%s' from %s authentication", username, auth_source)
        return user
        
    except Exception as e:
        log.error("Failed to create authenticated user '%s': %s", username, e)
        ub.session.rollback()
        return None


@auth.verify_password
def verify_password(username, password):
    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username.lower()).first()
    
    # Handle existing users
    if user:
        if user.name.lower() == "guest":
            if config.config_anonbrowse == 1:
                return user
        if config.config_login_type == constants.LOGIN_LDAP and services.ldap:
            login_result, error = services.ldap.bind_user(user.name, password)
            if login_result:
                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                return user
            if error is not None:
                log.error(error)
        else:
            limiter.check()
            if check_password_hash(str(user.password), password):
                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                return user
    
    # Handle new LDAP users (auto-creation for OPDS/API access)
    elif config.config_login_type == constants.LOGIN_LDAP and services.ldap and getattr(config, 'config_ldap_auto_create_users', True):
        try:
            # Try LDAP authentication for new user
            login_result, error = services.ldap.bind_user(username, password)
            if login_result:
                # Authentication successful, get user details and create account
                ldap_user_details = services.ldap.get_object_details(username)
                if ldap_user_details:
                    from . import admin
                    create_result, error_msg = admin.ldap_import_create_user(username, ldap_user_details)
                    if create_result:
                        # Get the newly created user
                        user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == username.lower()).first()
                        if user:
                            log.info("LDAP auto-created user for OPDS/API: '%s'", username)
                            [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                            return user
                
                log.warning("LDAP authentication succeeded but user creation failed for '%s'", username)
            elif error:
                log.debug("LDAP authentication failed for new user '%s': %s", username, error)
        except Exception as ex:
            log.error("LDAP auto-creation error for OPDS user '%s': %s", username, ex)
    
    # Use request.remote_addr (already corrected by ProxyFix) instead of raw header
    ip_address = request.remote_addr
    log.warning('OPDS Login failed for user "%s" IP-address: %s', username, ip_address)
    return None

def get_basic_auth_error():
    try:
        return auth.auth_error_callback(status)
    except TypeError:
        return auth.auth_error_callback()
    
def using_basic_auth(allow_anonymous: bool, unauthorized_hanlder):
    def wrapper(f):
        @wraps(f)
        def decorator(*args, **kwargs):
            authorisation = auth.get_auth()
            status = None
            user = None
            if config.config_allow_reverse_proxy_header_login and not authorisation:
                user = load_user_from_reverse_proxy_header(request)
            if allow_anonymous and config.config_anonbrowse == 1 and not authorisation:
                authorisation = Authorization(
                    b"Basic", {'username': "Guest", 'password': ""})
            if not user:
                user = auth.authenticate(authorisation, "")
            if user in (False, None):
                status = 401
            if status:
                return unauthorized_hanlder()
            g.flask_httpauth_user = user if user is not True \
                else auth.username if auth else None
            return auth.ensure_sync(f)(*args, **kwargs)
        return decorator
    return wrapper
basic_auth_or_anonymous = using_basic_auth(True, get_basic_auth_error)
basic_auth_required = using_basic_auth(False, get_basic_auth_error)

def using_user_login(allow_anonymous: bool):
    def wrapper(f):
        @wraps(f)
        def decorator(*args, **kwargs):
            if config.config_allow_reverse_proxy_header_login:
                user = load_user_from_reverse_proxy_header(request)
                if user:
                    g.flask_httpauth_user = user
                    return f(*args, **kwargs)
                g.flask_httpauth_user = None
            if allow_anonymous and config.config_anonbrowse == 1:
                return f(*args, **kwargs)
            return login_required(f)(*args, **kwargs)
        return decorator
    return wrapper
user_login_or_anonymous = using_user_login(True)
user_login_required = using_user_login(False)


def load_user_from_reverse_proxy_header(req):
    """Load user from reverse proxy header, optionally creating new users"""
    rp_header_name = config.config_reverse_proxy_login_header_name
    if not rp_header_name:
        return None
        
    rp_header_username = req.headers.get(rp_header_name)
    if not rp_header_username:
        return None
        
    # Clean username (strip whitespace, etc.)
    rp_header_username = rp_header_username.strip()
    if not rp_header_username:
        return None
    
    # Look for existing user first
    user = ub.session.query(ub.User).filter(func.lower(ub.User.name) == rp_header_username.lower()).first()
    if user:
        [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
        log.debug("Reverse proxy authentication: found existing user '%s'", user.name)
        return user
    
    # If user not found and auto-creation is enabled, create new user
    if getattr(config, 'config_reverse_proxy_auto_create_users', False):
        log.info("Reverse proxy authentication: attempting to create user '%s'", rp_header_username)
        
        # Get additional headers for user info (common reverse proxy headers)
        email = req.headers.get('Remote-Email') or req.headers.get('X-Remote-Email')
        
        user = create_authenticated_user(rp_header_username, email, "reverse proxy")
        if user:
            [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
            log.info("Reverse proxy authentication: successfully created user '%s'", user.name)
            return user
        else:
            log.error("Reverse proxy authentication: failed to create user '%s'", rp_header_username)
    else:
        log.debug("Reverse proxy authentication: user '%s' not found, auto-creation disabled", rp_header_username)
    
    return None


@lm.user_loader
def load_user(user_id, random, session_key):
    try:
        # Handle potential invalid user_id
        if not user_id:
            return None
        user = ub.session.query(ub.User).filter(ub.User.id == int(user_id)).first()
        if not user:
            return None
            
        if session_key:
            entry = ub.session.query(ub.User_Sessions).filter(ub.User_Sessions.random == random,
                                                              ub.User_Sessions.session_key == session_key).first()
            if not entry or entry.user_id != user.id:
                return None
        elif random:
            entry = ub.session.query(ub.User_Sessions).filter(ub.User_Sessions.random == random).first()
            if not entry or entry.user_id != user.id:
                return None
        return user
    except (ValueError, TypeError) as e:
        log.error("Invalid user_id in load_user: %s", e)
        return None

