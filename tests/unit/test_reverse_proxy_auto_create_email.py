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


def test_proxy_email_header_wins_when_free(um):
    with patch.object(um, "_email_taken", _taken()):
        assert um._auto_create_email("reader@example.com", "other@example.com") == "other@example.com"


def test_taken_proxy_email_falls_back_to_username(um):
    with patch.object(um, "_email_taken", _taken("other@example.com")):
        assert um._auto_create_email("reader@example.com", "other@example.com") == "reader@example.com"


def test_invalid_or_multi_address_proxy_email_is_ignored(um):
    with patch.object(um, "_email_taken", _taken()):
        assert um._auto_create_email("reader@example.com", "not-an-email") == "reader@example.com"
        assert um._auto_create_email("reader@example.com", "a@example.com,b@example.com") == "reader@example.com"
        assert um._auto_create_email("reader", "a@b@example.com") == "reader@localhost"


def test_create_authenticated_user_stores_the_picked_email(um):
    um.ub.session.query.return_value.filter.return_value.first.return_value = None
    with patch.object(um, "_email_taken", _taken("rob@example.com")):
        user = um.create_authenticated_user("rob@example.com", None, "reverse proxy")
    assert user is not None
    assert user.email == "rob.example.com@localhost"
    um.ub.session.commit.assert_called_once()
