# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

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
    except requests.exceptions.RequestException as e:
        log.error("Failed to fetch user info from generic OIDC provider: %s", e)
        flash(_("Login failed: Could not connect to the user info endpoint."), category="error")
        return None
    except ValueError:
        log.error("Failed to parse user info from generic OIDC provider.")
        flash(_("Login failed: The OAuth provider returned an invalid user profile."), category="error")
        return None


    # Use configurable field mappers
    username_field = generic.get('username_mapper', 'preferred_username')
    email_field = generic.get('email_mapper', 'email')
    
    provider_username = userinfo.get(username_field)
    provider_user_id = userinfo.get('sub')

    if not provider_username or not provider_user_id:
        log.error(f"User info from OIDC provider is missing '{username_field}' or 'sub' field.")
        flash(_("Login failed: User profile from provider is incomplete."), category="error")
        return None

    provider_username = str(provider_username)
    provider_user_id = str(provider_user_id)

    user = (
        ub.session.query(ub.User)
        .filter(ub.User.name == provider_username)
    ).first()

    if not user:
        user = ub.User()
        user.name = provider_username
        user.email = userinfo.get(email_field, f"{provider_username}@localhost")
        if 'groups' in userinfo and generic['oauth_admin_group'] in userinfo['groups']:
            user.role = constants.ROLE_ADMIN
        else:
            user.role = constants.ROLE_USER
        ub.session.add(user)
        ub.session_commit()

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
    ub.session_commit()

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
    query = ub.session.query(ub.OAuth).filter_by(
        provider=provider_id,
        provider_user_id=provider_user_id,
    )
    try:
        oauth_entry = query.first()
        # already bind with user, just login
        if oauth_entry.user:
            login_user(oauth_entry.user)
            log.debug("You are now logged in as: '%s'", oauth_entry.user.name)
            flash(_("Success! You are now logged in as: %(nickname)s", nickname=oauth_entry.user.name),
                  category="success")
            return redirect(url_for('web.index'))
        else:
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
            else:
                flash(_("Login failed, No User Linked With OAuth Account"), category="error")
            log.info('Login failed, No User Linked With OAuth Account')
            return redirect(url_for('web.login'))
            # return redirect(url_for('web.login'))
            # if config.config_public_reg:
            #   return redirect(url_for('web.register'))
            # else:
            #    flash(_("Public registration is not enabled"), category="error")
            #    return redirect(url_for(redirect_url))
    except (NoResultFound, AttributeError):
        return redirect(url_for(redirect_url))


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
    
    ele3 = dict(provider_name='generic',
                id=generic.id,
                active=generic.active,
                scope=generic.scope or 'openid profile email',
                oauth_client_id=generic.oauth_client_id,
                oauth_client_secret=generic.oauth_client_secret,
                oauth_base_url=generic.oauth_base_url,
                oauth_authorize_url=generic.oauth_authorize_url,
                oauth_token_url=generic.oauth_token_url,
                oauth_userinfo_url=generic.oauth_userinfo_url,
                metadata_url=generic.metadata_url,
                username_mapper=generic.username_mapper,
                email_mapper=generic.email_mapper,
                login_button=generic.login_button,
                oauth_admin_group=generic.oauth_admin_group or 'admin')
    oauthblueprints.append(ele3)

    for element in oauthblueprints:
        if element['provider_name'] == 'github':
            blueprint = make_github_blueprint(
                client_id=element['oauth_client_id'],
                client_secret=element['oauth_client_secret'],
                redirect_to="oauth."+element['provider_name']+"_login",
                scope=element['scope']
            )
        elif element['provider_name'] == 'google':
            blueprint = make_google_blueprint(
                client_id=element['oauth_client_id'],
                client_secret=element['oauth_client_secret'],
                redirect_to="oauth."+element['provider_name']+"_login",
                scope=element['scope']
            )
        else:
            blueprint = OAuth2ConsumerBlueprint(
                "generic",
                __name__,
                client_id=element['oauth_client_id'],
                client_secret=element['oauth_client_secret'],
                base_url=element['oauth_base_url'],
                authorization_url=element['oauth_authorize_url'],
                token_url=element['oauth_token_url'],
                token_url_params={'verify': constants.OAUTH_SSL_STRICT},
                redirect_to="oauth.generic_login",
                scope=element['scope']
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
            log.error("Failed to log in with Generic OAuth")
            return False

        provider_user_id = register_user_from_generic_oauth()
        return oauth_update_token(str(oauthblueprints[2]['id']), token, provider_user_id)


    # notify on OAuth provider error
    @oauth_error.connect_via(oauthblueprints[0]['blueprint'])
    def github_error(blueprint, error, error_description=None, error_uri=None):
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

    @oauth_error.connect_via(oauthblueprints[1]['blueprint'])
    def google_error(blueprint, error, error_description=None, error_uri=None):
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
