# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #312 — Tier 2: debug-pack redactor.

The audit in this thread caught that `/admin/debug` zip includes:

* `mail_password` — plaintext SMTP password
* `mail_gmail_token` — JSON OAuth refresh token
* `config_ldap_serv_password` — plaintext LDAP bind password

…among other secrets the `to_dict()` substring filter missed. A user
who downloads that zip and uploads it to a GitHub issue (the scenario
this whole feature exists for) hands those credentials to the
internet.

Pin the new contract: a `_redact_for_export()` function takes the
settings dict and returns a copy with every known-secret field replaced
by a placeholder, plus regex-based defense-in-depth for anything that
looks like a JWT, bearer token, base64 OAuth response, or AWS-shape key.
"""

from __future__ import annotations

import json

import pytest


def _redactor():
    from cps.debug_info import _redact_for_export
    return _redact_for_export


@pytest.mark.unit
class TestRedactorRemovesNamedSecrets:
    def test_mail_password_redacted(self):
        out = _redactor()({"mail_password": "hunter2", "config_port": 8083})
        assert out["mail_password"] != "hunter2"
        assert "hunter2" not in json.dumps(out), (
            "Plaintext SMTP password must not appear anywhere in redacted "
            "output, even as a substring of another field."
        )

    def test_mail_password_e_encrypted_shadow_also_redacted(self):
        """The encrypted shadow `mail_password_e` is a Fernet token; it's
        not directly a credential, but exposing the ciphertext + the key
        in the same export breaks the encryption. Redact both."""
        out = _redactor()({"mail_password_e": "gAAAAABm..."})
        assert "gAAAAABm" not in json.dumps(out)

    def test_ldap_bind_password_redacted(self):
        out = _redactor()({"config_ldap_serv_password": "binddn-secret"})
        assert "binddn-secret" not in json.dumps(out)

    def test_gmail_oauth_token_redacted(self):
        token_json = json.dumps({
            "refresh_token": "1//abc.def.ghi",
            "access_token": "ya29.xyz",
        })
        out = _redactor()({"mail_gmail_token": token_json})
        body = json.dumps(out)
        assert "1//abc.def.ghi" not in body
        assert "ya29.xyz" not in body

    def test_unknown_secret_named_password_redacted_by_substring(self):
        out = _redactor()({"some_future_password_field": "leak-me"})
        assert "leak-me" not in json.dumps(out)

    def test_unknown_secret_named_token_redacted_by_substring(self):
        out = _redactor()({"some_future_token_field": "bearer-xyz"})
        assert "bearer-xyz" not in json.dumps(out)

    def test_unknown_secret_named_secret_redacted_by_substring(self):
        out = _redactor()({"some_future_client_secret": "deadbeef"})
        assert "deadbeef" not in json.dumps(out)


@pytest.mark.unit
class TestRedactorDefenseInDepth:
    def test_jwt_shaped_value_redacted_regardless_of_field_name(self):
        # Three base64 segments separated by dots = JWT shape.
        jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
               "eyJzdWIiOiJ0ZXN0In0."
               "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        out = _redactor()({"unrelated_field": f"prefix {jwt} suffix"})
        assert jwt not in json.dumps(out), (
            "JWT-shaped values must be redacted even when not in a "
            "secret-named field (defense-in-depth)."
        )

    def test_long_random_token_redacted_in_sensitive_named_field(self):
        # The aggressive long-token pattern only runs on sensitive-named
        # fields, where defense-in-depth has a clear payoff.
        long_token = "a1b2c3d4e5f6g7h8i9j0" * 4  # 80 chars
        out = _redactor()({"my_token_holder": long_token})
        assert long_token not in json.dumps(out)

    def test_long_random_string_in_innocuous_field_preserved(self):
        # Calibre book paths, SHA-256 hashes, long URLs etc. are >=40
        # chars but legitimate diagnostic content. Container testing
        # caught these being blanked when the aggressive pattern ran
        # on every field. Now only sensitive-named fields trigger it.
        long_path = "/library/Some Long Author Name With Many Words/Book Title.epub"
        sha256 = "a" * 64
        out = _redactor()({
            "config_calibre_dir": long_path,
            "some_checksum_diagnostic": sha256,
        })
        assert out["config_calibre_dir"] == long_path
        assert out["some_checksum_diagnostic"] == sha256


@pytest.mark.unit
class TestRedactorTypePreservation:
    """Regression for code-review finding: previous _redact_value called
    str(value) on lists/dicts, corrupting the exported JSON shape."""

    def test_list_value_preserved_as_list(self):
        out = _redactor()({"allowed_domains": ["a.com", "b.com"]})
        assert out["allowed_domains"] == ["a.com", "b.com"]
        assert isinstance(out["allowed_domains"], list)

    def test_dict_value_preserved_as_dict(self):
        out = _redactor()({"feature_flags": {"k": 1, "m": True}})
        assert out["feature_flags"] == {"k": 1, "m": True}
        assert isinstance(out["feature_flags"], dict)

    def test_none_value_preserved_as_none(self):
        out = _redactor()({"optional_setting": None})
        assert out["optional_setting"] is None


@pytest.mark.unit
class TestRedactorPreservesNonSensitiveData:
    def test_port_setting_unchanged(self):
        out = _redactor()({"config_port": 8083})
        assert out["config_port"] == 8083

    def test_boolean_settings_unchanged(self):
        out = _redactor()({"config_anonbrowse": False, "config_uploading": True})
        assert out["config_anonbrowse"] is False
        assert out["config_uploading"] is True

    def test_book_title_keyword_preserved(self):
        # Book titles in settings would be unusual but the redactor must
        # not nuke legitimate textual data — only secrets.
        out = _redactor()({"config_title_regex": r"^(A|The|An)\s+"})
        assert out["config_title_regex"] == r"^(A|The|An)\s+"

    def test_password_policy_ints_preserved(self):
        """`config_password_min_length` is a policy integer, NOT a
        password. Container testing of #312 caught the false positive
        — the substring filter must only redact actual string credentials."""
        out = _redactor()({"config_password_min_length": 8})
        assert out["config_password_min_length"] == 8

    def test_password_policy_bools_preserved(self):
        out = _redactor()({
            "config_password_lower": True,
            "config_password_upper": True,
            "config_password_special": False,
        })
        assert out["config_password_lower"] is True
        assert out["config_password_upper"] is True
        assert out["config_password_special"] is False

    def test_returns_a_copy_not_in_place_mutation(self):
        original = {"mail_password": "hunter2", "config_port": 8083}
        out = _redactor()(original)
        assert original["mail_password"] == "hunter2", (
            "Redactor must not mutate the caller's dict — that would "
            "destroy the running app's settings."
        )
        assert out is not original
