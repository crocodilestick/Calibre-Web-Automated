# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the email picked for users auto-created from reverse-proxy headers
(cps/usermanagement.py: _auto_create_email, create_authenticated_user).

cps.usermanagement is loaded against a stub cps package, scoped to each test with
patch.dict(sys.modules), so no app context or database is needed. valid_email is
replaced with a simple stand-in; these tests cover which candidate gets picked,
not the address regex.
"""

import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))


def _fake_valid_email(value):
    local, _, domain = value.partition("@")
    if not local or not domain or "@" in domain or " " in value:
        raise Exception("Invalid Email address format")
    return value


@pytest.fixture
def um():
    """cps.usermanagement imported against stubbed dependencies."""
    cps_pkg = types.ModuleType("cps")
    cps_pkg.__path__ = [os.path.join(PROJECT_ROOT, "cps")]
    helper = types.ModuleType("cps.helper")
    helper.valid_email = _fake_valid_email
    stubs = {name: MagicMock() for name in (
        "flask", "flask_httpauth", "werkzeug", "werkzeug.datastructures", "werkzeug.security",
        "sqlalchemy", "sqlalchemy.sql", "sqlalchemy.sql.expression", "cps.cw_login",
    )}
    for name in ("lm", "ub", "config", "logger", "limiter", "constants", "services"):
        mod = MagicMock()
        setattr(cps_pkg, name, mod)
        stubs[f"cps.{name}"] = mod
    stubs.update({"cps": cps_pkg, "cps.helper": helper})
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("cps.usermanagement", None)
        module = importlib.import_module("cps.usermanagement")
        yield module
        sys.modules.pop("cps.usermanagement", None)


def _taken(*emails):
    taken = {e.lower() for e in emails}
    return lambda email: email.lower() in taken


def test_email_username_is_used_as_email(um):
    with patch.object(um, "_email_taken", _taken()):
        assert um._auto_create_email("reader@example.com") == "reader@example.com"


def test_non_email_username_gets_placeholder(um):
    with patch.object(um, "_email_taken", _taken()):
        assert um._auto_create_email("reader") == "reader@localhost"


def test_email_already_on_another_account_falls_back_to_placeholder(um):
    # e.g. an admin pre-created "rob" with email rob@example.com, then the same
    # person arrives through the proxy as "rob@example.com"
    with patch.object(um, "_email_taken", _taken("Rob@Example.com")):
        email = um._auto_create_email("rob@example.com")
    assert email == "rob.example.com@localhost"
    # the placeholder must itself pass validation, or the profile save breaks again
    assert _fake_valid_email(email) == email


def test_invalid_or_multi_address_username_gets_placeholder(um):
    with patch.object(um, "_email_taken", _taken()):
        assert um._auto_create_email("a@example.com,b@example.com") == "a.example.com,b.example.com@localhost"
        assert um._auto_create_email("a@b@example.com") == "a.b.example.com@localhost"


def _header_request(**headers):
    req = MagicMock()
    req.headers = headers
    return req


def _no_user_by_name(um):
    um.config.config_reverse_proxy_login_header_name = "Cf-Access-Authenticated-User-Email"
    um.ub.session.query.return_value.filter.return_value.first.return_value = None


def test_header_email_logs_into_the_account_that_has_it(um):
    _no_user_by_name(um)
    um.config.config_reverse_proxy_auto_create_users = True
    rob = MagicMock(name="rob")
    with patch.object(um, "_user_with_email", lambda a: rob if a == "rob@example.com" else None), \
            patch.object(um, "create_authenticated_user") as create:
        user = um.load_user_from_reverse_proxy_header(
            _header_request(**{"Cf-Access-Authenticated-User-Email": "rob@example.com"}))
    assert user is rob
    create.assert_not_called()


def test_email_match_is_off_when_auto_create_is_off(um):
    _no_user_by_name(um)
    um.config.config_reverse_proxy_auto_create_users = False
    rob = MagicMock(name="rob")
    with patch.object(um, "_user_with_email", lambda a: rob), \
            patch.object(um, "create_authenticated_user") as create:
        user = um.load_user_from_reverse_proxy_header(
            _header_request(**{"Cf-Access-Authenticated-User-Email": "rob@example.com"}))
    assert user is None
    create.assert_not_called()


def test_remote_email_header_is_never_used_to_match_an_account(um):
    # Behind Cloudflare Access a client can send Remote-Email itself. Matching on it
    # would let anyone who passes Access log in as whoever owns that address.
    _no_user_by_name(um)
    um.config.config_reverse_proxy_auto_create_users = True
    admin = MagicMock(name="admin")
    owners = {"admin@example.com": admin}
    with patch.object(um, "_user_with_email", lambda a: owners.get(a)), \
            patch.object(um, "create_authenticated_user", return_value=None):
        user = um.load_user_from_reverse_proxy_header(_header_request(**{
            "Cf-Access-Authenticated-User-Email": "stranger@example.com",
            "Remote-Email": "admin@example.com",
            "X-Remote-Email": "admin@example.com",
        }))
    assert user is None


def test_remote_email_header_is_never_stored_on_an_auto_created_account(um):
    # stranger@example.com passes the proxy and sends Remote-Email: victim@example.com.
    # If that were stored, victim@example.com's own login would later match by email
    # into the stranger's account.
    _no_user_by_name(um)
    um.config.config_reverse_proxy_auto_create_users = True
    with patch.object(um, "_user_with_email", lambda a: None), \
            patch.object(um, "_email_taken", _taken()), \
            patch.object(um, "create_authenticated_user", wraps=um.create_authenticated_user) as create:
        um.load_user_from_reverse_proxy_header(_header_request(**{
            "Cf-Access-Authenticated-User-Email": "stranger@example.com",
            "Remote-Email": "victim@example.com",
            "X-Remote-Email": "victim@example.com",
        }))
    create.assert_called_once_with("stranger@example.com", "reverse proxy")
    created = um.ub.session.add.call_args[0][0]
    assert created.email == "stranger@example.com"


def test_non_email_username_with_remote_email_gets_the_placeholder(um):
    _no_user_by_name(um)
    um.config.config_reverse_proxy_auto_create_users = True
    with patch.object(um, "_user_with_email", lambda a: None), \
            patch.object(um, "_email_taken", _taken()):
        um.load_user_from_reverse_proxy_header(_header_request(**{
            "Cf-Access-Authenticated-User-Email": "stranger",
            "Remote-Email": "victim@example.com",
        }))
    assert um.ub.session.add.call_args[0][0].email == "stranger@localhost"


def test_user_with_email_ignores_values_that_are_not_one_address(um):
    for value in ("rob", "", None, "a@example.com,b@example.com", "a@b@example.com"):
        assert um._user_with_email(value) is None
    um.ub.session.query.assert_not_called()


def test_create_authenticated_user_stores_the_picked_email(um):
    um.ub.session.query.return_value.filter.return_value.first.return_value = None
    with patch.object(um, "_email_taken", _taken("rob@example.com")):
        user = um.create_authenticated_user("rob@example.com", "reverse proxy")
    assert user is not None
    assert user.email == "rob.example.com@localhost"
    um.ub.session.commit.assert_called_once()
