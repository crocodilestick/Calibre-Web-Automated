# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for GenericOIDCSession in cps/oauth_bb.py

Tests the fix for Issue #819 (Generic OIDC Crash) and ensures
the "Direct Login" flow (manual token injection) works correctly.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

# -----------------------------------------------------------------------------
# Dependency Mocking Setup
# -----------------------------------------------------------------------------
# We need to mock these BEFORE importing cps.oauth_bb because it imports them
# at the top level, and we want to test in isolation without a full app context.

# Create mocks for the dependencies
mock_flask = MagicMock()
mock_flask_dance = MagicMock()
mock_flask_dance_consumer = MagicMock()
mock_flask_dance_requests = MagicMock()
mock_flask_dance_contrib = MagicMock()
mock_sqlalchemy = MagicMock()
mock_cps = MagicMock()
mock_cps_ub = MagicMock()
mock_cps_constants = MagicMock()

# Configure specific mock behaviors
mock_cps_constants.OAUTH_SSL_STRICT = True

# Fix for AttributeError: __spec__
# When mocking modules in sys.modules, they need to look like real modules
def create_mock_module(name):
    m = MagicMock()
    m.__spec__ = MagicMock()
    m.__spec__.name = name
    m.__name__ = name
    m.__path__ = []
    m.__loader__ = MagicMock()
    return m

mock_flask = create_mock_module('flask')
mock_flask_dance = create_mock_module('flask_dance')
mock_flask_dance_consumer = create_mock_module('flask_dance.consumer')
mock_flask_dance_requests = create_mock_module('flask_dance.consumer.requests')
mock_flask_dance_contrib = create_mock_module('flask_dance.contrib')
mock_sqlalchemy = create_mock_module('sqlalchemy')
mock_cps = create_mock_module('cps')
mock_cps_ub = create_mock_module('cps.ub')
mock_cps_constants = create_mock_module('cps.constants')

# Re-apply specific attributes
mock_cps_constants.OAUTH_SSL_STRICT = True

# Configure ub (Database) mocks to support blueprint generation
mock_cps_ub.oauth_support = True

# Create mock OAuth providers
def create_mock_provider(name, id_val):
    p = MagicMock()
    p.provider_name = name
    p.id = id_val
    p.active = True
    p.oauth_client_id = 'client_id'
    p.oauth_client_secret = 'client_secret'
    p.oauth_base_url = 'http://base'
    p.oauth_authorize_url = 'http://auth'
    p.oauth_token_url = 'http://token'
    p.oauth_userinfo_url = 'http://userinfo'
    p.metadata_url = None
    p.scope = 'scope'
    p.username_mapper = 'sub'
    p.email_mapper = 'email'
    p.login_button = 'Login'
    p.oauth_admin_group = 'admin'
    return p

github_p = create_mock_provider('github', '1')
google_p = create_mock_provider('google', '2')
generic_p = create_mock_provider('generic', '3')

mock_providers = [github_p, google_p]

# Configure session query
mock_query = MagicMock()
# For the first query (github/google)
mock_query.all.return_value = mock_providers
# For the generic query
mock_query.filter_by.return_value.first.return_value = generic_p
# For the count query
mock_query.count.return_value = 2

# Make sure chained calls work
mock_cps_ub.session.query.return_value = mock_query
mock_query.filter.return_value = mock_query

# Mock BaseOAuth2Session for inheritance
class MockBaseSession:
    def __init__(self, *args, **kwargs):
        pass
    def register_compliance_hook(self, *args, **kwargs):
        pass
    def get(self, *args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {'sub': '12345', 'name': 'Test User'}
        return mock_resp

mock_flask_dance_requests.OAuth2Session = MockBaseSession

# Configure oauth_authorized signal mock to act as a transparent decorator
mock_signal = MagicMock()
def side_effect_connect_via(*args, **kwargs):
    def decorator(f):
        return f
    return decorator
mock_signal.connect_via.side_effect = side_effect_connect_via
mock_flask_dance_consumer.oauth_authorized = mock_signal
mock_flask_dance_consumer.oauth_error = mock_signal # Also for error handler

# Apply mocks to sys.modules
module_patches = {
    'flask': mock_flask,
    'flask_dance': mock_flask_dance,
    'flask_dance.consumer': mock_flask_dance_consumer,
    'flask_dance.consumer.requests': mock_flask_dance_requests,
    'flask_dance.contrib': mock_flask_dance_contrib,
    'flask_dance.contrib.github': create_mock_module('flask_dance.contrib.github'),
    'flask_dance.contrib.google': create_mock_module('flask_dance.contrib.google'),
    'flask_babel': create_mock_module('flask_babel'),
    'flask_principal': create_mock_module('flask_principal'),
    'werkzeug.middleware.proxy_fix': create_mock_module('werkzeug.middleware.proxy_fix'),
    'sqlalchemy': mock_sqlalchemy,
    'sqlalchemy.orm': create_mock_module('sqlalchemy.orm'),
    'sqlalchemy.orm.exc': create_mock_module('sqlalchemy.orm.exc'),
    # We do NOT mock 'cps' top-level so we can import oauth_bb from it
    # But we mock all its submodules that are imported in __init__.py or oauth_bb.py
    'cps.ub': mock_cps_ub,
    'cps.constants': mock_cps_constants,
    'cps.logger': create_mock_module('cps.logger'),
    'cps.cw_login': create_mock_module('cps.cw_login'),
    'cps.usermanagement': create_mock_module('cps.usermanagement'),
    'cps.helper': create_mock_module('cps.helper'),
    'cps.cache_buster': create_mock_module('cps.cache_buster'),
    'cps.oauth': create_mock_module('cps.oauth'),
    'cps.MyLoginManager': create_mock_module('cps.MyLoginManager'),
    'cps.cli': create_mock_module('cps.cli'),
    'cps.reverseproxy': create_mock_module('cps.reverseproxy'),
    'cps.server': create_mock_module('cps.server'),
    'cps.dep_check': create_mock_module('cps.dep_check'),
    'cps.updater': create_mock_module('cps.updater'),
    'cps.config_sql': create_mock_module('cps.config_sql'),
    'cps.db': create_mock_module('cps.db'),
}

# We use patch.dict to temporarily replace modules during import
with patch.dict(sys.modules, module_patches):
    # Import the module
    # We need to ensure the project root is in sys.path
    import os
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import cps.oauth_bb as oauth_bb

# Keep oauth_bb in sys.modules so patch() can find it later
# even after the patch.dict context manager exits
sys.modules['cps.oauth_bb'] = oauth_bb


class TestGenericOIDCSession:
    """Tests for the GenericOIDCSession class"""

    def test_manual_instantiation_with_token(self):
        """
        Test that GenericOIDCSession can be instantiated with an explicit token
        and that the .token property works without a blueprint.
        
        This verifies the fix for the crash where accessing .token would fail
        if self.blueprint was missing.
        """
        GenericOIDCSession = oauth_bb.GenericOIDCSession
        token = {'access_token': 'test_token_123', 'token_type': 'Bearer'}
        
        # Instantiate with explicit token (Direct Login style)
        session = GenericOIDCSession(client_id='test_client', token=token)
        
        # Access the token property
        # This should NOT raise AttributeError
        retrieved_token = session.token
        
        assert retrieved_token == token, "Token property should return the explicitly set token"

    def test_blueprint_fallback(self):
        """
        Test that .token falls back to the blueprint if no explicit token is provided.
        """
        GenericOIDCSession = oauth_bb.GenericOIDCSession
        
        # Create a session without explicit token
        session = GenericOIDCSession(client_id='test_client')
        
        # Mock the blueprint
        mock_blueprint = MagicMock()
        mock_blueprint.token = {'access_token': 'blueprint_token'}
        session.blueprint = mock_blueprint
        
        # Access the token property
        retrieved_token = session.token
        
        assert retrieved_token == {'access_token': 'blueprint_token'}, "Token should be retrieved from blueprint"

    def test_token_setter(self):
        """Test that the token setter works (required for token refresh)"""
        GenericOIDCSession = oauth_bb.GenericOIDCSession
        session = GenericOIDCSession(client_id='test_client')
        
        new_token = {'access_token': 'new_token'}
        session.token = new_token
        
        assert session.token == new_token


class TestOAuthLogic:
    """Tests for the OAuth login logic functions (Generic, GitHub, Google)"""
    
    def setup_method(self):
        # Reset mocks before each test
        # We need to mock the oauthblueprints list to match what the code expects
        # Index 0: GitHub, Index 1: Google, Index 2: Generic
        
        mock_github_bp = MagicMock()
        mock_github_bp.session.get.return_value.ok = True
        mock_github_bp.session.get.return_value.json.return_value = {"id": "12345"}
        
        mock_google_bp = MagicMock()
        mock_google_bp.session.get.return_value.ok = True
        mock_google_bp.session.get.return_value.json.return_value = {"id": "67890"}
        
        mock_generic_bp = MagicMock()
        mock_generic_bp.name = 'generic'
        
        oauth_bb.oauthblueprints = [
            {
                'blueprint': mock_github_bp,
                'id': 'github_id',
                'provider_name': 'github'
            },
            {
                'blueprint': mock_google_bp,
                'id': 'google_id',
                'provider_name': 'google'
            },
            {
                'blueprint': mock_generic_bp,
                'oauth_client_id': 'client_id_123',
                'oauth_userinfo_url': 'http://example.com/user',
                'id': 'generic_id',
                'provider_name': 'generic'
            }
        ]

    def test_register_user_uses_manual_session(self):
        """
        Verify register_user_from_generic_oauth uses manual session instantiation
        when a token is provided.
        """
        token = {'access_token': 'test_token'}
        
        # Spy on GenericOIDCSession
        with patch('cps.oauth_bb.GenericOIDCSession', side_effect=oauth_bb.GenericOIDCSession) as MockSession:
            oauth_bb.register_user_from_generic_oauth(token=token)
            
            # Verify it was called with the token
            call_args = MockSession.call_args
            assert call_args is not None
            assert call_args[1].get('token') == token

    def test_generic_logged_in_aborts(self):
        """
        Verify generic_logged_in calls abort() when a response is received.
        This confirms the 'Direct Login' flow is active.
        """
        token = {'access_token': 'test_token'}
        
        # Use a simple class instead of MagicMock to avoid property/attribute confusion
        class FakeBlueprint:
            name = 'generic'
            
        mock_blueprint = FakeBlueprint()
        
        # Mock register_user_from_generic_oauth to return a response (redirect)
        mock_response = MagicMock()
        
        with patch.object(oauth_bb, 'register_user_from_generic_oauth', return_value=mock_response) as mock_reg:
            with patch.object(oauth_bb, 'abort') as mock_abort:
                # Also patch log to see errors
                with patch.object(oauth_bb, 'log') as mock_log:
                    oauth_bb.generic_logged_in(mock_blueprint, token)
                    
                    # Check if register was called
                    assert mock_reg.called, "register_user_from_generic_oauth was not called"
                    
                    mock_abort.assert_called_once_with(mock_response)

    def test_github_logged_in_aborts(self):
        """
        Verify github_logged_in calls abort() (Direct Login flow).
        """
        token = {'access_token': 'github_token'}
        mock_blueprint = oauth_bb.oauthblueprints[0]['blueprint']
        
        mock_response = MagicMock()
        
        # Mock bind_oauth_or_register which is used by GitHub flow
        with patch.object(oauth_bb, 'bind_oauth_or_register', return_value=mock_response) as mock_bind:
            with patch.object(oauth_bb, 'abort') as mock_abort:
                with patch.object(oauth_bb, 'oauth_update_token'):
                    oauth_bb.github_logged_in(mock_blueprint, token)
                    
                    mock_bind.assert_called()
                    mock_abort.assert_called_once_with(mock_response)

    def test_google_logged_in_aborts(self):
        """
        Verify google_logged_in calls abort() (Direct Login flow).
        """
        token = {'access_token': 'google_token'}
        mock_blueprint = oauth_bb.oauthblueprints[1]['blueprint']
        
        mock_response = MagicMock()
        
        # Mock bind_oauth_or_register which is used by Google flow
        with patch.object(oauth_bb, 'bind_oauth_or_register', return_value=mock_response) as mock_bind:
            with patch.object(oauth_bb, 'abort') as mock_abort:
                with patch.object(oauth_bb, 'oauth_update_token'):
                    oauth_bb.google_logged_in(mock_blueprint, token)
                    
                    mock_bind.assert_called()
                    mock_abort.assert_called_once_with(mock_response)
