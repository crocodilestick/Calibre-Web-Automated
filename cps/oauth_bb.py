# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
OAuth Integration for Calibre-Web Automated

This module handles OAuth/OIDC authentication for GitHub, Google, and generic OIDC providers.

Issue #663 Fix: Invalid Redirect URI Error
=========================================

The "invalid redirect URI" error that occurs after some time away is caused by Flask-Dance
generating redirect URIs dynamically based on the current request context. When users
return after time away, their context (hostname, protocol, proxy headers) may have changed,
causing a different redirect URI to be generated.

Solution implemented:
1. Added config_oauth_redirect_host setting to force consistent redirect URIs
2. Enhanced error messages to guide users when redirect URI issues occur  
3. Added validation for the OAuth redirect host configuration
4. Integrated with Flask's FORCE_HOST_FOR_REDIRECTS for URL consistency

Usage:
- Set "OAuth Redirect Host" in Admin > Basic Configuration > OAuth
- Use full URL with protocol: https://your-domain.com
- Required when: accessing via multiple hostnames, behind reverse proxy, 
  or experiencing "invalid redirect URI" errors
"""

import json
import requests
import os
from functools import wraps

# Relax OAuthlib scope validation to prevent errors when providers return different scopes
# This fixes Issue #715 where missing 'groups' scope causes 500 Internal Server Error
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from flask import session, request, make_response, abort
from flask import Blueprint, flash, redirect, url_for
from flask_babel import gettext as _
from flask_dance.consumer import oauth_authorized, oauth_error, OAuth2ConsumerBlueprint
from flask_dance.contrib.github import make_github_blueprint, github
from flask_dance.contrib.google import make_google_blueprint, google
from oauthlib.oauth2 import TokenExpiredError, InvalidGrantError
from .cw_login import login_user, current_user
from sqlalchemy.orm.exc import NoResultFound
from .usermanagement import user_login_required

from . import constants, logger, config, app, ub

try:
    from .oauth import OAuthBackend, backend_resultcode
except NameError:
    pass

# Custom OAuth2Session for generic OIDC to handle SSL and scope validation (Issue #715)
from flask_dance.consumer.requests import OAuth2Session as BaseOAuth2Session

class GenericOIDCSession(BaseOAuth2Session):
    """
    Custom OAuth2Session for generic OIDC providers like Authentik.
    
    Handles:
    1. SSL verification based on OAUTH_SSL_STRICT setting
    2. Lenient scope validation (order-independent comparison)
    3. Normalizes scope in token response to prevent mismatch warnings
    4. Explicit token usage without blueprint (Issue #715)
    """
    def __init__(self, *args, **kwargs):
        self._explicit_token = kwargs.get('token')
        super().__init__(*args, **kwargs)
        # Configure SSL verification for all requests
        self.verify = constants.OAUTH_SSL_STRICT
        
        # Register compliance hook to normalize scope in token response (Issue #715)
        # This prevents "scope_changed" warnings when Authentik returns scopes in different order
        self.register_compliance_hook('access_token_response', self._normalize_token_scope)

    @property
    def token(self):
        """
        Override token property to support explicit token usage without blueprint.
        Flask-Dance's token property crashes if blueprint is None.
        """
        if self._explicit_token:
            return self._explicit_token
        if hasattr(self, 'blueprint') and self.blueprint:
            return self.blueprint.token
        return None

    @token.setter
    def token(self, value):
        """
        Allow setting token (required for token refresh/update).
        This mimics cached_property behavior by shadowing the blueprint token.
        """
        self._explicit_token = value

    @token.deleter
    def token(self):
        """
        Handle deletion of token.
        Flask-Dance deletes the token in __init__ to ensure it uses the blueprint's token.
        We want to preserve our explicit token if it was passed, so we do nothing here
        if we are in explicit mode.
        """
        # If we are not in explicit mode, we might want to clear something?
        # But since we store everything in _explicit_token or delegate to blueprint,
        # and _explicit_token is what we want to keep, we can just ignore the delete
        # if it's coming from Flask-Dance's init.
        pass
    
    def _normalize_token_scope(self, response):
        """
        Normalize scope in token response to match request format.
        
        Handles:
        - Scope as array → convert to space-separated string
        - Different scope order → sort alphabetically for consistent comparison
        - Extra whitespace → normalize
        """
        try:
            if response.status_code == 200:
                token = response.json()
                if 'scope' in token:
                    scope = token['scope']
                    
                    # Convert array to string
                    if isinstance(scope, list):
                        scope = ' '.join(scope)
                    
                    # Normalize: split, sort, rejoin to handle order differences
                    if isinstance(scope, str):
                        scopes = [s.strip() for s in scope.split() if s.strip()]
                        scopes.sort()  # Sort for consistent comparison
                        token['scope'] = ' '.join(scopes)
                        
                        # Update response content with normalized token
                        response._content = json.dumps(token).encode('utf-8')
        except (ValueError, KeyError, AttributeError) as e:
            # If we can't parse/normalize, let Flask-Dance handle it
            log.debug("Could not normalize token response scope: %s", e)
        
        return response
    
    def request(self, method, url, *args, **kwargs):
        """Override request to ensure SSL verification is applied"""
        if 'verify' not in kwargs:
            kwargs['verify'] = self.verify
            
        # If we have an explicit token and no blueprint, we need to handle request manually
        # to avoid Flask-Dance's dependency on blueprint
        if self._explicit_token and not self.blueprint:
            # Bypass Flask-Dance's request method which requires blueprint
            # Call requests_oauthlib.OAuth2Session.request directly
            return super(BaseOAuth2Session, self).request(method, url, *args, **kwargs)
            
        return super().request(method, url, *args, **kwargs)


oauth_check = {}
oauthblueprints = []
oauth = Blueprint('oauth', __name__)
log = logger.create()


def oauth_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if config.config_login_type == constants.LOGIN_OAUTH:
            return f(*args, **kwargs)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = {'status': 'error', 'message': 'Not Found'}
            response = make_response(json.dumps(data, ensure_ascii=False))
            response.headers["Content-Type"] = "application/json; charset=utf-8"
            return response, 404
        abort(404)

    return inner


def register_oauth_blueprint(cid, show_name):
    oauth_check[cid] = show_name


def register_user_with_oauth(user=None):
    all_oauth = {}
    for oauth_key in oauth_check.keys():
        if str(oauth_key) + '_oauth_user_id' in session and session[str(oauth_key) + '_oauth_user_id'] != '':
            all_oauth[oauth_key] = oauth_check[oauth_key]
    if len(all_oauth.keys()) == 0:
        return
    if user is None:
        flash(_("Register with %(provider)s", provider=", ".join(list(all_oauth.values()))), category="success")
    else:
        for oauth_key in all_oauth.keys():
            # Find this OAuth token in the database, or create it
            query = ub.session.query(ub.OAuth).filter_by(
                provider=oauth_key,
                provider_user_id=session[str(oauth_key) + "_oauth_user_id"],
            )
            try:
                oauth_key = query.one()
                oauth_key.user_id = user.id
            except NoResultFound:
                # no found, return error
                return
            ub.session_commit("User {} with OAuth for provider {} registered".format(user.name, oauth_key))


def fetch_metadata_from_url(metadata_url):
    """Fetch OIDC metadata from a custom URL"""
    if not metadata_url:
        return None
    
    try:
        resp = requests.get(metadata_url, timeout=5, verify=constants.OAUTH_SSL_STRICT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        log.error("Failed to fetch OAuth metadata from %s: %s", metadata_url, e)
        return None
    except ValueError:
        log.error("Failed to parse OAuth metadata JSON from %s", metadata_url)
        return None


def register_user_from_generic_oauth(token=None):
    generic = oauthblueprints[2]
    blueprint = generic['blueprint']

    try:
        if token:
            # Use the provided token directly to avoid race conditions with DB storage
            # This ensures we use the fresh token even if it hasn't been committed to DB yet
            client_id = generic['oauth_client_id']
            # Use GenericOIDCSession to maintain SSL/Scope handling logic
            oauth_session = GenericOIDCSession(client_id=client_id, token=token)
        else:
            # Fallback to blueprint session (loads from DB)
            oauth_session = blueprint.session

        resp = oauth_session.get(generic['oauth_userinfo_url'], verify=constants.OAUTH_SSL_STRICT)
        resp.raise_for_status()
        userinfo = resp.json()
    except InvalidGrantError as e:
        # Scope mismatch or token validation error (Issue #715)
        log.error("OAuth token validation failed (scope mismatch?): %s", e)
        flash(_("Login failed: OAuth token validation error. This may be due to scope configuration mismatch. "
               "Please check your OAuth scopes configuration or contact your administrator."), category="error")
        return None
    except TokenExpiredError as e:
        log.error("OAuth token expired during user info fetch: %s", e)
        flash(_("Login failed: OAuth token expired. Please try logging in again."), category="error")
        return None
    except requests.exceptions.RequestException as e:
        log.error("Failed to fetch user info from generic OIDC provider: %s", e)
        flash(_("Login failed: Could not connect to the OAuth provider's user info endpoint. "
               "Please try again or contact your administrator."), category="error")
        return None
    except ValueError:
        log.error("Failed to parse user info from generic OIDC provider.")
        flash(_("Login failed: The OAuth provider returned invalid user profile data. "
               "Please contact your administrator."), category="error")
        return None


    # Use configurable field mappers
    username_field = generic.get('username_mapper', 'preferred_username')
    email_field = generic.get('email_mapper', 'email')
    
    provider_username = userinfo.get(username_field)
    provider_user_id = userinfo.get('sub')

    if not provider_username or not provider_user_id:
        missing_fields = []
        if not provider_username:
            missing_fields.append(username_field)
        if not provider_user_id:
            missing_fields.append("sub")
        
        missing_fields_str = ', '.join(missing_fields)
        log.error(f"User info from OIDC provider is missing required fields: {missing_fields_str}. "
                 f"Check your OAuth scopes and field mappings.")
        flash(_("Login failed: OAuth provider response is missing required fields: %(fields)s. "
               "Please check your OAuth configuration or contact your administrator.", 
               fields=missing_fields_str), category="error")
        return None

    provider_username = str(provider_username)
    provider_user_id = str(provider_user_id)
    provider_email = userinfo.get(email_field)
    if provider_email is not None:
        provider_email = str(provider_email)

    is_linking = (
        current_user and current_user.is_authenticated and
        session.get('oauth_linking_provider') == str(generic['id'])
    )

    user = None
    if is_linking:
        if provider_email:
            existing_email_user = (
                ub.session.query(ub.User)
                .filter(ub.User.email == provider_email)
            ).first()
            if existing_email_user and existing_email_user.id != current_user.id:
                log.warning("OAuth link rejected: email '%s' already belongs to user '%s'", 
                            provider_email, existing_email_user.name)
                flash(_("Failed to link OAuth account. Please try again."), category="error")
                session.pop('oauth_linking_provider', None)
                session.modified = True
                return redirect(url_for('web.profile'))
        user = current_user
    else:
        user = (
            ub.session.query(ub.User)
            .filter(ub.User.name == provider_username)
        ).first()
        if not user and provider_email:
            user = (
                ub.session.query(ub.User)
                .filter(ub.User.email == provider_email)
            ).first()
            if user:
                log.info("OAuth login matched existing user by email '%s' (user '%s'), provider username '%s'",
                         provider_email, user.name, provider_username)

    # Check if user should have admin role based on group membership
    # Handle various group formats: list, string, or None
    user_groups = userinfo.get('groups', [])
    if isinstance(user_groups, str):
        # Handle comma-separated or space-separated string
        user_groups = [g.strip() for g in user_groups.replace(',', ' ').split() if g.strip()]
    elif not isinstance(user_groups, list):
        user_groups = []
    
    admin_group = generic.get('oauth_admin_group', 'admin')
    # Case-insensitive group comparison to handle "admin" vs "Admin" etc.
    should_be_admin = (admin_group and 
                       any(g.lower() == admin_group.lower() for g in user_groups))

    if not user:
        user = ub.User()
        user.name = provider_username
        user.email = userinfo.get(email_field, f"{provider_username}@localhost")
        
        # Apply default configuration settings for new OAuth users (Issue #660)
        # Match the same pattern as normal user creation in admin.py
        
        # Set role: admin group overrides default role (only if group management enabled), otherwise use configured default
        if should_be_admin and config.config_enable_oauth_group_admin_management:
            user.role = constants.ROLE_ADMIN
            log.info("New OAuth user '%s' granted admin role via group '%s' (groups: %s)", 
                    provider_username, admin_group, user_groups)
        else:
            user.role = config.config_default_role
            if should_be_admin and not config.config_enable_oauth_group_admin_management:
                log.debug("New OAuth user '%s' not granted admin role - group-based management disabled", 
                         provider_username)
        
        # Apply default user settings (same as normal user registration)
        user.sidebar_view = getattr(config, 'config_default_show', 1)
        user.locale = getattr(config, 'config_default_locale', 'en')
        user.default_language = getattr(config, 'config_default_language', 'all')
        
        # Apply default restrictions and permissions (same as _handle_new_user)
        user.allowed_tags = getattr(config, 'config_allowed_tags', '')
        user.denied_tags = getattr(config, 'config_denied_tags', '')
        user.allowed_column_value = getattr(config, 'config_allowed_column_value', '')
        user.denied_column_value = getattr(config, 'config_denied_column_value', '')
        
        # Set default theme (use configured theme, fallback to caliBlur=1)
        try:
            user.theme = getattr(config, 'config_theme', 1)
        except Exception:
            user.theme = 1
            
        # Kobo sync setting defaults to 0 (disabled) for new users
        user.kobo_only_shelves_sync = 0
        
        try:    
            ub.session.add(user)
            ub.session_commit()
            log.info("OAuth auto-created user: '%s' from provider: %s", provider_username, generic.get('provider_name', 'unknown'))
        except Exception as ex:
            log.error("Failed to create OAuth user '%s': %s", provider_username, ex)
            ub.session.rollback()
            return None
    else:
        # Existing user: update admin role based on current group membership (Issue #715)
        # This ensures that users who are added to or removed from admin groups get proper access
        # Only enforce if group-based admin management is enabled (global setting)
        current_is_admin = user.role_admin()
        
        if config.config_enable_oauth_group_admin_management:
            if should_be_admin and not current_is_admin:
                # User was added to admin group - grant admin role
                user.role |= constants.ROLE_ADMIN
                log.info("OAuth user '%s' granted admin role via group '%s' (groups: %s)", 
                        provider_username, admin_group, user_groups)
            elif not should_be_admin and current_is_admin:
                # User was removed from admin group - revoke admin role (but keep other roles)
                user.role &= ~constants.ROLE_ADMIN
                log.warning("OAuth user '%s' admin role revoked - not in required group '%s' (user groups: %s)", 
                           provider_username, admin_group, user_groups)
        else:
            log.debug("OAuth group-based admin management disabled - preserving manual role assignments for '%s'", 
                     provider_username)
        # Note: Changes are not committed yet - will be committed with OAuth entry below

    oauth = ub.session.query(ub.OAuth).filter_by(
        provider=str(generic['id']),
        provider_user_id=provider_user_id,
    ).first()

    if not oauth:
        oauth = ub.OAuth(
            provider=str(generic['id']),
            provider_user_id=provider_user_id,
            token={},
        )
        ub.session.add(oauth)

    oauth.user = user
    
    # Atomic Token Update: If we have a fresh token, save it NOW in the same transaction
    if token:
        oauth.token = token

    # Commit all changes together: OAuth entry + Token + User + Role updates
    try:
        ub.session_commit()
        # Log role changes after successful commit (only if group management is enabled)
        if user.role_admin() and should_be_admin and config.config_enable_oauth_group_admin_management:
            log.info("OAuth user '%s' has admin role via group '%s'", provider_username, admin_group)
    except Exception as ex:
        log.error("Failed to save OAuth session for user '%s': %s", provider_username, ex)
        ub.session.rollback()
        return None

    # ATOMIC SESSION CLEANUP
    # We must clean the session triggers to avoid "Cookie Too Large" errors (4KB limit).
    # Since we just saved the token to the DB, it is safe to remove it from the session.
    if token:
        provider_id = str(generic['id'])
        keys_to_remove = [
            'google_oauth_token', 'github_oauth_token', 'generic_oauth_token',
            provider_id + "_oauth_token"
        ]
        for key in keys_to_remove:
            if key in session:
                try:
                    session.pop(key)
                except Exception as e:
                    log.warning(f"Failed to clean session key '{key}': {e}")
        # We assume the user is about to be logged in by bind_oauth_or_register, 
        # but we set the user_id in session just in case, matching oauth_update_token behavior.
        session[provider_id + "_oauth_user_id"] = provider_user_id
        session.modified = True

    # DIRECT LOGIN: Return the response from binding/login (redirect)
    # This aligns with the "Atomic" strategy to prevent loops
    session.pop('oauth_linking_provider', None)
    session.modified = True
    return bind_oauth_or_register(str(generic['id']), provider_user_id, 'generic.login', 'generic')


def logout_oauth_user():
    for oauth_key in oauth_check.keys():
        if str(oauth_key) + '_oauth_user_id' in session:
            session.pop(str(oauth_key) + '_oauth_user_id')
    if 'generic_oauth_token' in session:
        session.pop('generic_oauth_token')


def oauth_update_token(provider_id, token, provider_user_id):


    # Aggressively clean up potential duplicate tokens to prevent cookie overflow (4KB limit)
    # We remove ALL token data from session and rely on DB storage
    keys_to_remove = [
        'google_oauth_token', 'github_oauth_token', 'generic_oauth_token',
        provider_id + "_oauth_token"
    ]
    for key in keys_to_remove:
        if key in session:
            try:
                session.pop(key)
            except Exception as e:
                log.warning(f"Failed to clean session key '{key}': {e}")

    session[provider_id + "_oauth_user_id"] = provider_user_id
    # Do NOT store token in session - it's too big and causes cookie drop
    # session[provider_id + "_oauth_token"] = token 
    session.modified = True



    # Find this OAuth token in the database, or create it
    query = ub.session.query(ub.OAuth).filter_by(
        provider=provider_id,
        provider_user_id=provider_user_id,
    )
    try:
        oauth_entry = query.one()
        # update token
        oauth_entry.token = token
    except NoResultFound:
        oauth_entry = ub.OAuth(
            provider=provider_id,
            provider_user_id=provider_user_id,
            token=token,
        )
    ub.session.add(oauth_entry)
    ub.session_commit()

    # Disable Flask-Dance's default behavior for saving the OAuth token
    # Value differrs depending on flask-dance version
    return backend_resultcode


def bind_oauth_or_register(provider_id, provider_user_id, redirect_url, provider_name):
    """Bind OAuth account to user or handle login"""
    if not provider_user_id:
        log.error("OAuth provider %s returned empty user ID", provider_name)
        flash(_("OAuth error: Provider returned invalid user information. Please try again."), category="error")
        return redirect(url_for('web.login'))
    
    query = ub.session.query(ub.OAuth).filter_by(
        provider=provider_id,
        provider_user_id=provider_user_id,
    )
    try:
        oauth_entry = query.first()
        # already bind with user, just login
        if oauth_entry and oauth_entry.user:
            login_user(oauth_entry.user)
            log.debug("You are now logged in as: '%s'", oauth_entry.user.name)
            flash(_("Success! You are now logged in as: %(nickname)s", nickname=oauth_entry.user.name),
                  category="success")
            return redirect(url_for('web.index'))
        elif oauth_entry:
            # bind to current user
            if current_user and current_user.is_authenticated:
                oauth_entry.user = current_user
                try:
                    ub.session.add(oauth_entry)
                    ub.session.commit()
                    flash(_("Link to %(oauth)s Succeeded", oauth=provider_name), category="success")
                    log.info("Link to {} Succeeded".format(provider_name))
                    return redirect(url_for('web.profile'))
                except Exception as ex:
                    log.error_or_exception(ex)
                    ub.session.rollback()
                    flash(_("Failed to link OAuth account. Please try again."), category="error")
            else:
                flash(_("Login failed: No user account is linked to your %(provider)s account. "
                       "Please contact your administrator to create an account or link your existing account.", 
                       provider=provider_name), category="error")
            log.info('Login failed, No User Linked With OAuth Account for provider %s', provider_name)
            return redirect(url_for('web.login'))
        else:
            # No OAuth entry found - this shouldn't happen if OAuth creation worked
            log.error("OAuth entry not found for provider %s, user %s", provider_name, provider_user_id)
            flash(_("OAuth authentication failed. Please try again or contact administrator."), category="error")
            return redirect(url_for('web.login'))
    except (NoResultFound, AttributeError) as e:
        log.error("OAuth binding error for provider %s: %s", provider_name, e)
        flash(_("OAuth system error. Please contact administrator."), category="error")
        return redirect(url_for('web.login'))


def get_oauth_status():
    status = []
    query = ub.session.query(ub.OAuth).filter_by(
        user_id=current_user.id,
    )
    try:
        oauths = query.all()
        for oauth_entry in oauths:
            status.append(int(oauth_entry.provider))
        return status
    except NoResultFound:
        return None


def unlink_oauth(provider):
    if request.host_url + 'me' != request.referrer:
        pass
    query = ub.session.query(ub.OAuth).filter_by(
        provider=provider,
        user_id=current_user.id,
    )
    try:
        oauth_entry = query.one()
        if current_user and current_user.is_authenticated:
            oauth_entry.user = current_user
            try:
                ub.session.delete(oauth_entry)
                ub.session.commit()
                logout_oauth_user()
                flash(_("Unlink to %(oauth)s Succeeded", oauth=oauth_check[provider]), category="success")
                log.info("Unlink to {} Succeeded".format(oauth_check[provider]))
            except Exception as ex:
                log.error_or_exception(ex)
                ub.session.rollback()
                flash(_("Unlink to %(oauth)s Failed", oauth=oauth_check[provider]), category="error")
    except NoResultFound:
        log.warning("oauth %s for user %d not found", provider, current_user.id)
        flash(_("Not Linked to %(oauth)s", oauth=provider), category="error")
    return redirect(url_for('web.profile'))


def generate_oauth_blueprints():
    if not ub.session.query(ub.OAuthProvider).count():
        for provider in ("github", "google"):
            oauthProvider = ub.OAuthProvider()
            oauthProvider.provider_name = provider
            oauthProvider.active = False
            ub.session.add(oauthProvider)
            ub.session_commit("{} Blueprint Created".format(provider))

    oauth_ids = ub.session.query(ub.OAuthProvider).filter(ub.OAuthProvider.provider_name.in_(['github', 'google'])).all()
    
    # Ensure deterministic assignment of providers regardless of DB query order
    github_provider = next((p for p in oauth_ids if p.provider_name == 'github'), None)
    google_provider = next((p for p in oauth_ids if p.provider_name == 'google'), None)
    
    # Fallback if providers are missing (shouldn't happen due to creation logic above)
    if not github_provider or not google_provider:
        log.error("OAuth providers missing after creation check")
        return []

    ele1 = dict(provider_name='github',
                id=github_provider.id,
                active=github_provider.active,
                oauth_client_id=github_provider.oauth_client_id,
                scope=None,
                oauth_client_secret=github_provider.oauth_client_secret,
                obtain_link='https://github.com/settings/developers')
    ele2 = dict(provider_name='google',
                id=google_provider.id,
                active=google_provider.active,
                scope=["https://www.googleapis.com/auth/userinfo.email"],
                oauth_client_id=google_provider.oauth_client_id,
                oauth_client_secret=google_provider.oauth_client_secret,
                obtain_link='https://console.developers.google.com/apis/credentials')
    oauthblueprints.append(ele1)
    oauthblueprints.append(ele2)

    generic = ub.session.query(ub.OAuthProvider).filter_by(provider_name='generic').first()
    # Create generic provider if missing
    if not generic:
        generic = ub.OAuthProvider()
        generic.provider_name = 'generic'
        generic.active = False
        ub.session.add(generic)
        ub.session_commit()
    
    # Update endpoints from metadata URL if available
    if generic.metadata_url:
        metadata = fetch_metadata_from_url(generic.metadata_url)
        if metadata:
            # Update from metadata (takes precedence over manual settings)
            if metadata.get('issuer'):
                generic.oauth_base_url = metadata.get('issuer')
            if metadata.get('authorization_endpoint'):
                generic.oauth_authorize_url = metadata.get('authorization_endpoint')
            if metadata.get('token_endpoint'):
                generic.oauth_token_url = metadata.get('token_endpoint')
            if metadata.get('userinfo_endpoint'):
                generic.oauth_userinfo_url = metadata.get('userinfo_endpoint')
            ub.session_commit("Updated generic OAuth provider from metadata URL")
            log.info("Updated OAuth endpoints from metadata URL: %s", generic.metadata_url)
    
    # Normalize scope: OAuth2Session expects space-separated string, not list
    # Clean up extra whitespace and sort alphabetically to prevent scope mismatch warnings (Issue #715)
    scope_value = generic.scope or 'openid profile email'
    if isinstance(scope_value, str):
        # Clean, sort, and normalize: split then rejoin to remove extra whitespace
        scopes = [s.strip() for s in scope_value.split() if s.strip()]
        scopes.sort()  # Sort alphabetically for consistent comparison with token response
        scope_value = ' '.join(scopes)
    elif isinstance(scope_value, list):
        # Convert list to sorted space-separated string
        scopes = [s.strip() for s in scope_value if s.strip()]
        scopes.sort()
        scope_value = ' '.join(scopes)
    
    # Ensure we have at least default scopes if result is empty
    if not scope_value or not scope_value.strip():
        scope_value = 'email openid profile'  # Sorted alphabetically
    
    ele3 = dict(provider_name='generic',
                id=generic.id,
                active=generic.active,
                scope=scope_value,
                oauth_client_id=generic.oauth_client_id,
                oauth_client_secret=generic.oauth_client_secret,
                oauth_base_url=generic.oauth_base_url,
                oauth_authorize_url=generic.oauth_authorize_url,
                oauth_token_url=generic.oauth_token_url,
                oauth_userinfo_url=generic.oauth_userinfo_url,
                metadata_url=generic.metadata_url,
                username_mapper=generic.username_mapper,
                email_mapper=generic.email_mapper,
                login_button=generic.login_button or 'OpenID Connect',
                oauth_admin_group=generic.oauth_admin_group or 'admin')
    oauthblueprints.append(ele3)

    for element in oauthblueprints:
        redirect_uri = None
        if hasattr(config, 'config_oauth_redirect_host') and config.config_oauth_redirect_host and config.config_oauth_redirect_host.strip():
            # Build absolute redirect URI for consistent OAuth flows
            host = config.config_oauth_redirect_host.strip()
            if not host.startswith(('http://', 'https://')):
                host = f"https://{host}"
            provider_name = element['provider_name']
            redirect_uri = f"{host.rstrip('/')}/login/{provider_name}/authorized"
            
        if element['provider_name'] == 'github':
            blueprint_params = {
                'client_id': element['oauth_client_id'],
                'client_secret': element['oauth_client_secret'],
                'redirect_to': "oauth."+element['provider_name']+"_login",
                'scope': element['scope']
            }
            # Only add redirect_url if we have a configured host and the blueprint supports it
            if redirect_uri:
                try:
                    blueprint = make_github_blueprint(redirect_url=redirect_uri, **blueprint_params)
                except TypeError:
                    # Fallback if redirect_url parameter is not supported
                    blueprint = make_github_blueprint(**blueprint_params)
            else:
                blueprint = make_github_blueprint(**blueprint_params)
        elif element['provider_name'] == 'google':
            blueprint_params = {
                'client_id': element['oauth_client_id'],
                'client_secret': element['oauth_client_secret'],
                'redirect_to': "oauth."+element['provider_name']+"_login",
                'scope': element['scope']
            }
            # Only add redirect_url if we have a configured host and the blueprint supports it
            if redirect_uri:
                try:
                    blueprint = make_google_blueprint(redirect_url=redirect_uri, **blueprint_params)
                except TypeError:
                    # Fallback if redirect_url parameter is not supported
                    blueprint = make_google_blueprint(**blueprint_params)
            else:
                blueprint = make_google_blueprint(**blueprint_params)
        else:
            # For generic OIDC, build parameters dictionary properly
            blueprint_params = {
                'client_id': element['oauth_client_id'],
                'client_secret': element['oauth_client_secret'],
                'base_url': element['oauth_base_url'],
                'authorization_url': element['oauth_authorize_url'],
                'token_url': element['oauth_token_url'],
                'redirect_to': "oauth.generic_login",
                'scope': element['scope'],
                'session_class': GenericOIDCSession  # Use custom session for SSL and scope handling
            }
            # Note: SSL verification is now handled by GenericOIDCSession, not token_url_params
            
            # Only add redirect_url if we have a configured host
            if redirect_uri:
                blueprint_params['redirect_url'] = redirect_uri
                
            try:
                blueprint = OAuth2ConsumerBlueprint(
                    "generic",
                    __name__,
                    **blueprint_params
                )
            except Exception as e:
                log.error("Failed to create generic OAuth blueprint: %s", e)
                # Fallback without redirect_url if it fails
                blueprint_params.pop('redirect_url', None)
                blueprint = OAuth2ConsumerBlueprint(
                    "generic",
                    __name__,
                    **blueprint_params
                )
        element['blueprint'] = blueprint
        element['blueprint'].backend = OAuthBackend(ub.OAuth, ub.session, str(element['id']),
                                                    user=current_user, user_required=True)
        app.register_blueprint(blueprint, url_prefix="/login")
        if element['active']:
            register_oauth_blueprint(element['id'], element['provider_name'])
    return oauthblueprints


def init_oauth_blueprints():
    """
    Initialize OAuth blueprints and register signal handlers.
    
    This function MUST be called after babel.init_app() in __init__.py to ensure
    translations are properly loaded. When OAuth blueprints are generated during
    module import (before babel init), babel.list_translations() returns an empty
    list, causing the language selection dropdown to only show English.
    
    Issue: https://discord.com/channels/.../... (BortS 01/01/2026)
    """
    if not ub.oauth_support:
        return []
    
    global oauthblueprints
    oauthblueprints = generate_oauth_blueprints()

    @oauth_authorized.connect_via(oauthblueprints[0]['blueprint'])
    def github_logged_in(blueprint, token):
        if not token:
            flash(_("Failed to log in with GitHub."), category="error")
            log.error("Failed to log in with GitHub")
            return False

        resp = blueprint.session.get("/user")
        if not resp.ok:
            flash(_("Failed to fetch user info from GitHub."), category="error")
            log.error("Failed to fetch user info from GitHub")
            return False

        github_info = resp.json()
        github_user_id = str(github_info["id"])
        
        # Save token to DB
        oauth_update_token(str(oauthblueprints[0]['id']), token, github_user_id)
        
        # DIRECT LOGIN: Hijack flow to prevent redirect loop
        response = bind_oauth_or_register(oauthblueprints[0]['id'], github_user_id, 'github.login', 'github')
        if response:
            abort(response)
            
        return False


    @oauth_authorized.connect_via(oauthblueprints[1]['blueprint'])
    def google_logged_in(blueprint, token):
        if not token:
            flash(_("Failed to log in with Google."), category="error")
            log.error("Failed to log in with Google")
            return False

        # We do NOT store token in session["google_oauth_token"] here to avoid duplication/bloat.
        # It will be stored in session[provider_id + "_oauth_token"] by oauth_update_token.

        resp = blueprint.session.get("/oauth2/v2/userinfo")
        if not resp.ok:
            flash(_("Failed to fetch user info from Google."), category="error")
            log.error("Failed to fetch user info from Google")
            return False

        google_info = resp.json()
        google_user_id = str(google_info["id"])
        
        # Save token to DB
        oauth_update_token(str(oauthblueprints[1]['id']), token, google_user_id)
        
        # DIRECT LOGIN: Hijack flow to prevent redirect loop
        # We perform the binding/login logic right here
        response = bind_oauth_or_register(oauthblueprints[1]['id'], google_user_id, 'google.login', 'google')
        
        # If we got a response (redirect), abort the current request and send it immediately
        # This stops Flask-Dance from doing its own redirect to /link/google
        if response:
            abort(response)
            
        return False


    @oauth_authorized.connect_via(oauthblueprints[2]['blueprint'])
    def generic_logged_in(blueprint, token):
        if not token:
            flash(_("Failed to log in with Generic OAuth."), category="error")
            log.error("Failed to log in with Generic OAuth - no token received")
            return False

        try:
            # Pass token explicitly to avoid DB race condition
            # FUNCTION NOW RETURNS A RESPONSE OBJECT (Redirect)
            response = register_user_from_generic_oauth(token)
            if response:
                return response
            
            # If no response, something failed silently (already logged)
            return False

        except (InvalidGrantError, TokenExpiredError) as e:
            log.error("OAuth token error in generic_logged_in: %s", e)
            flash(_("OAuth authentication failed: Token validation error. Please try again."), category="error")
            return False
        except Exception as e:
            log.error("Unexpected error in generic OAuth login: %s", e)
            flash(_("OAuth authentication failed due to an unexpected error. Please contact administrator."), category="error")
            return False


    # notify on OAuth provider error
    @oauth_error.connect_via(oauthblueprints[0]['blueprint'])
    def github_error(blueprint, error, error_description=None, error_uri=None):
        if error and 'redirect_uri' in str(error).lower():
            msg = _("OAuth error: Invalid redirect URI. If you're experiencing this error repeatedly, "
                   "please configure the 'OAuth Redirect Host' setting in Admin > Basic Configuration > OAuth.")
        else:
            msg = (
                "OAuth error from {name}! "
                "error={error} description={description} uri={uri}"
            ).format(
                name=blueprint.name,
                error=error,
                description=error_description,
                uri=error_uri,
            )  # ToDo: Translate
        flash(msg, category="error")
        log.error("GitHub OAuth error: %s", msg)

    @oauth_error.connect_via(oauthblueprints[1]['blueprint'])
    def google_error(blueprint, error, error_description=None, error_uri=None):
        if error and 'redirect_uri' in str(error).lower():
            msg = _("OAuth error: Invalid redirect URI. If you're experiencing this error repeatedly, "
                   "please configure the 'OAuth Redirect Host' setting in Admin > Basic Configuration > OAuth.")
        else:
            msg = (
                "OAuth error from {name}! "
                "error={error} description={description} uri={uri}"
            ).format(
                name=blueprint.name,
                error=error,
                description=error_description,
                uri=error_uri,
            )  # ToDo: Translate
        flash(msg, category="error")
        log.error("Google OAuth error: %s", msg)

    @oauth_error.connect_via(oauthblueprints[2]['blueprint'])
    def generic_error(blueprint, error, error_description=None, error_uri=None):
        if error and 'redirect_uri' in str(error).lower():
            msg = _("OAuth error: Invalid redirect URI. If you're experiencing this error repeatedly, "
                   "please configure the 'OAuth Redirect Host' setting in Admin > Basic Configuration > OAuth.")
        else:
            msg = (
                "OAuth error from {name}! "
                "error={error} description={description} uri={uri}"
            ).format(
                name=blueprint.name,
                error=error,
                description=error_description,
                uri=error_uri,
            )  # ToDo: Translate
        flash(msg, category="error")
        log.error("Generic OAuth error: %s", msg)

    return oauthblueprints


# Initialize empty oauthblueprints list at module level
# This will be populated when init_oauth_blueprints() is called
oauthblueprints = []


@oauth.route('/link/github')
@oauth_required
def github_login():
    # This route is now only a fallback if the direct login hijack fails
    # or if the user navigates here manually.
    log.warning("Fallback OAuth route '/link/github' accessed - direct login may have failed")
    if not github.authorized:
        return redirect(url_for('github.login'))
    try:
        account_info = github.get('/user')
        if account_info.ok:
            account_info_json = account_info.json()
            return bind_oauth_or_register(oauthblueprints[0]['id'], account_info_json['id'], 'github.login', 'github')
        flash(_("GitHub Oauth error, please retry later."), category="error")
        log.error("GitHub Oauth error, please retry later")
    except (InvalidGrantError, TokenExpiredError) as e:
        try:
            del github.token
        except Exception:
            pass
        flash(_("GitHub Oauth error: {}").format(e), category="error")
        log.error(e)
        return redirect(url_for('github.login'))
    return redirect(url_for('web.login'))


@oauth.route('/unlink/github', methods=["GET"])
@user_login_required
def github_login_unlink():
    return unlink_oauth(oauthblueprints[0]['id'])


@oauth.route('/link/google')
@oauth_required
def google_login():
    log.warning("Fallback OAuth route '/link/google' accessed - direct login may have failed")
    # Try to find token in session using the provider ID key
    provider_id = str(oauthblueprints[1]['id'])
    user_id_key = provider_id + "_oauth_user_id"
    
    # 1. Try to get User ID from session (Small cookie!)
    if user_id_key in session:
        provider_user_id = session[user_id_key]
        
        # 2. Fetch the huge token from Database instead of session
        oauth_entry = ub.session.query(ub.OAuth).filter_by(
            provider=provider_id,
            provider_user_id=provider_user_id
        ).first()
        
        if oauth_entry and oauth_entry.token:
            # 3. Manually inject token into blueprint
            google.token = oauth_entry.token
            
            # 4. Proceed directly to login
            return bind_oauth_or_register(oauthblueprints[1]['id'], provider_user_id, 'google.login', 'google')

    if not google.authorized:
        return redirect(url_for("google.login"))
    
    try:
        # If google.authorized is False but we have a token, google.get might fail
        # We can try to use the token directly with requests if needed, but let's try google.get first
        # If google.token was set, google.get should use it
        
        resp = google.get("/oauth2/v2/userinfo")
        if resp.ok:
            account_info_json = resp.json()
            return bind_oauth_or_register(oauthblueprints[1]['id'], account_info_json['id'], 'google.login', 'google')
        
        flash(_("Google Oauth error, please retry later."), category="error")
        log.error("Google Oauth error, please retry later")
    except (InvalidGrantError, TokenExpiredError) as e:
        try:
            del google.token
        except Exception:
            pass
        flash(_("Google Oauth error: {}").format(e), category="error")
        log.error(e)
        return redirect(url_for("google.login"))
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        
    return redirect(url_for('web.login'))


@oauth.route('/unlink/google', methods=["GET"])
@user_login_required
def google_login_unlink():
    return unlink_oauth(oauthblueprints[1]['id'])


@oauth.route('/link/generic')
@oauth_required
def generic_login():
    log.warning("Fallback OAuth route '/link/generic' accessed - direct login may have failed")
    # This route is now only a fallback if the direct login hijack fails
    # or if the user navigates here manually.
    if current_user and current_user.is_authenticated:
        session['oauth_linking_provider'] = str(oauthblueprints[2]['id'])
        session.modified = True
    if not oauthblueprints[2]['blueprint'].session.authorized:
        return redirect(url_for("generic.login"))
    try:
        # Here we rely on the stored token since we don't have it in args
        # If the previous step (generic_logged_in) succeeded, the token is in DB
        # This function now returns a Response object (redirect)
        return register_user_from_generic_oauth()
    except (TokenExpiredError) as e:
        try:
            del oauthblueprints[2]['blueprint'].token
        except Exception:
            pass
        flash(_("OAuth error: {}").format(e), category="error")
        log.error(e)
        return redirect(url_for("generic.login"))
    except (InvalidGrantError) as e:
        try:
            del oauthblueprints[2]['blueprint'].token
        except Exception:
            pass
        flash(_("OAuth error: {}").format(e), category="error")
        log.error(e)
        return redirect(url_for("generic.login"))
    return redirect(url_for("web.login"))


@oauth.route('/unlink/generic', methods=["GET"])
@user_login_required
def generic_login_unlink():
    return unlink_oauth(oauthblueprints[2]['id'])
