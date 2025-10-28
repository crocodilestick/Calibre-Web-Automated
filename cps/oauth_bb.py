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
from functools import wraps

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
from requests_oauthlib import OAuth2Session as BaseOAuth2Session

class GenericOIDCSession(BaseOAuth2Session):
    """
    Custom OAuth2Session for generic OIDC providers like Authentik.
    
    Handles:
    1. SSL verification based on OAUTH_SSL_STRICT setting
    2. Lenient scope validation (order-independent comparison)
    3. Normalizes scope in token response to prevent mismatch warnings
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Configure SSL verification for all requests
        self.verify = constants.OAUTH_SSL_STRICT
        
        # Register compliance hook to normalize scope in token response (Issue #715)
        # This prevents "scope_changed" warnings when Authentik returns scopes in different order
        self.register_compliance_hook('access_token_response', self._normalize_token_scope)
    
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


def register_user_from_generic_oauth():
    generic = oauthblueprints[2]
    blueprint = generic['blueprint']

    try:
        resp = blueprint.session.get(generic['oauth_userinfo_url'], verify=constants.OAUTH_SSL_STRICT)
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

    user = (
        ub.session.query(ub.User)
        .filter(ub.User.name == provider_username)
    ).first()

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
        
        # Set role: admin group overrides default role, otherwise use configured default
        if should_be_admin:
            user.role = constants.ROLE_ADMIN
            log.info("New OAuth user '%s' granted admin role via group '%s'", provider_username, admin_group)
        else:
            user.role = config.config_default_role
        
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
        current_is_admin = user.role_admin()
        
        if should_be_admin and not current_is_admin:
            # User was added to admin group - grant admin role
            user.role |= constants.ROLE_ADMIN
            log.info("OAuth user '%s' will be granted admin role via group '%s'", provider_username, admin_group)
        elif not should_be_admin and current_is_admin:
            # User was removed from admin group - revoke admin role (but keep other roles)
            user.role &= ~constants.ROLE_ADMIN
            log.info("OAuth user '%s' admin role will be revoked (not in group '%s')", provider_username, admin_group)
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
    
    # Commit all changes together: OAuth entry + any role updates
    try:
        ub.session_commit()
        # Log role changes after successful commit
        if user.role_admin() and should_be_admin:
            log.info("OAuth user '%s' has admin role via group '%s'", provider_username, admin_group)
    except Exception as ex:
        log.error("Failed to save OAuth session for user '%s': %s", provider_username, ex)
        ub.session.rollback()
        return None

    return provider_user_id


def logout_oauth_user():
    for oauth_key in oauth_check.keys():
        if str(oauth_key) + '_oauth_user_id' in session:
            session.pop(str(oauth_key) + '_oauth_user_id')
    if 'generic_oauth_token' in session:
        session.pop('generic_oauth_token')


def oauth_update_token(provider_id, token, provider_user_id):
    session[provider_id + "_oauth_user_id"] = provider_user_id
    session[provider_id + "_oauth_token"] = token

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
    ele1 = dict(provider_name='github',
                id=oauth_ids[0].id,
                active=oauth_ids[0].active,
                oauth_client_id=oauth_ids[0].oauth_client_id,
                scope=None,
                oauth_client_secret=oauth_ids[0].oauth_client_secret,
                obtain_link='https://github.com/settings/developers')
    ele2 = dict(provider_name='google',
                id=oauth_ids[1].id,
                active=oauth_ids[1].active,
                scope=["https://www.googleapis.com/auth/userinfo.email"],
                oauth_client_id=oauth_ids[1].oauth_client_id,
                oauth_client_secret=oauth_ids[1].oauth_client_secret,
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


if ub.oauth_support:
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
        return oauth_update_token(str(oauthblueprints[0]['id']), token, github_user_id)


    @oauth_authorized.connect_via(oauthblueprints[1]['blueprint'])
    def google_logged_in(blueprint, token):
        if not token:
            flash(_("Failed to log in with Google."), category="error")
            log.error("Failed to log in with Google")
            return False

        resp = blueprint.session.get("/oauth2/v2/userinfo")
        if not resp.ok:
            flash(_("Failed to fetch user info from Google."), category="error")
            log.error("Failed to fetch user info from Google")
            return False

        google_info = resp.json()
        google_user_id = str(google_info["id"])
        return oauth_update_token(str(oauthblueprints[1]['id']), token, google_user_id)


    @oauth_authorized.connect_via(oauthblueprints[2]['blueprint'])
    def generic_logged_in(blueprint, token):
        if not token:
            flash(_("Failed to log in with Generic OAuth."), category="error")
            log.error("Failed to log in with Generic OAuth - no token received")
            return False

        try:
            provider_user_id = register_user_from_generic_oauth()
            if provider_user_id:
                return oauth_update_token(str(oauthblueprints[2]['id']), token, provider_user_id)
            else:
                # register_user_from_generic_oauth already logged error and flashed message
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


@oauth.route('/link/github')
@oauth_required
def github_login():
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
        flash(_("GitHub Oauth error: {}").format(e), category="error")
        log.error(e)
    return redirect(url_for('web.login'))


@oauth.route('/unlink/github', methods=["GET"])
@user_login_required
def github_login_unlink():
    return unlink_oauth(oauthblueprints[0]['id'])


@oauth.route('/link/google')
@oauth_required
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    try:
        resp = google.get("/oauth2/v2/userinfo")
        if resp.ok:
            account_info_json = resp.json()
            return bind_oauth_or_register(oauthblueprints[1]['id'], account_info_json['id'], 'google.login', 'google')
        flash(_("Google Oauth error, please retry later."), category="error")
        log.error("Google Oauth error, please retry later")
    except (InvalidGrantError, TokenExpiredError) as e:
        flash(_("Google Oauth error: {}").format(e), category="error")
        log.error(e)
    return redirect(url_for('web.login'))


@oauth.route('/unlink/google', methods=["GET"])
@user_login_required
def google_login_unlink():
    return unlink_oauth(oauthblueprints[1]['id'])


@oauth.route('/link/generic')
@oauth_required
def generic_login():
    if not oauthblueprints[2]['blueprint'].session.authorized:
        return redirect(url_for("generic.login"))
    try:
        provider_user_id = register_user_from_generic_oauth()
        return bind_oauth_or_register(oauthblueprints[2]['id'], provider_user_id, 'generic.login', 'generic')
    except (TokenExpiredError) as e:
        flash(_("OAuth error: {}").format(e), category="error")
        log.error(e)
        return redirect(url_for("generic.login"))
    except (InvalidGrantError) as e:
        flash(_("OAuth error: {}").format(e), category="error")
        log.error(e)
    return redirect(url_for("web.login"))


@oauth.route('/unlink/generic', methods=["GET"])
@user_login_required
def generic_login_unlink():
    return unlink_oauth(oauthblueprints[2]['id'])
