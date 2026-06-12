# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #428 (@iroQuai): custom body text in
the email function.

Reporter sends books to an eReader from CWNG and wants to replace the
hardcoded "This Email has been sent via Calibre-Web NextGen." with a
personal message in their own language (and optionally a link to their
library). Asked for text first; metadata templating ({%title%} ...) was
raised later as an explicit "nice to have, not important".

## Design (focused v1)

- New `mail_body_text` String column on the settings table (default "").
  The mail_ prefix means it auto-migrates via config_sql._migrate_table
  and flows through get_mail_settings() into the Edit Email Server
  Settings page with no extra wiring.
- Admin edits it in /admin/mailsettings (textarea). Saved on every
  submit branch via _config_string.
- helper.get_email_body_text() returns the admin value when non-blank,
  else the shipped translated default. The three book-bearing send
  paths (convert+send, test mail, direct send-to-eReader) call it
  instead of the hardcoded literal.
- Sent as plain text, verbatim (trust-the-admin, like the #225 banner
  and #323 custom CSS). Whitespace-only reverts to the default so an
  admin can't accidentally blank the body.

## v2 follow-ups (deferred, stated honestly)

Metadata/templating placeholders ({title}/{author}/{username}/library
counts) and HTML/markdown formatting are explicitly out of v1 — the
reporter ranked them low. A per-event body (welcome vs. send-book) is
also v2.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SQL = REPO_ROOT / "cps" / "config_sql.py"
HELPER_PY = REPO_ROOT / "cps" / "helper.py"
ADMIN_PY = REPO_ROOT / "cps" / "admin.py"
EMAIL_EDIT_HTML = REPO_ROOT / "cps" / "templates" / "email_edit.html"

DEFAULT_BODY = "This Email has been sent via Calibre-Web NextGen."


def _extract_function(source: str, name: str):
    """Compile a single top-level function from source in isolation.

    Lets us exercise the real fallback logic without importing cps.helper
    (which pulls Flask/db). Mirrors the AST-extract pattern used for the
    #323 _style_safe_css breakout test.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            ns: dict = {}
            exec(compile(module, f"<{name}>", "exec"), ns)  # noqa: S102
            return ns[name]
    raise AssertionError(f"function {name!r} not found in source")


# --- Behavioral: the real resolver, run in isolation -----------------------

@pytest.fixture(scope="module")
def resolve():
    return _extract_function(HELPER_PY.read_text(), "_resolve_email_body_text")


def test_blank_falls_back_to_default(resolve):
    assert resolve("", DEFAULT_BODY) == DEFAULT_BODY


def test_none_falls_back_to_default(resolve):
    assert resolve(None, DEFAULT_BODY) == DEFAULT_BODY


def test_whitespace_only_falls_back_to_default(resolve):
    assert resolve("   \n\t ", DEFAULT_BODY) == DEFAULT_BODY


def test_custom_value_is_used_and_stripped(resolve):
    assert resolve("  Veel leesplezier!  ", DEFAULT_BODY) == "Veel leesplezier!"


def test_custom_multiline_body_preserved(resolve):
    body = "Hoi!\nHier is je boek.\nhttps://books.example.com"
    assert resolve(body, DEFAULT_BODY) == body


# --- Source pins: every wiring site ----------------------------------------

def test_config_column_defined():
    src = CONFIG_SQL.read_text()
    assert re.search(
        r"mail_body_text\s*=\s*Column\(String,\s*default\s*=\s*[\"']{2}\)",
        src,
    ), 'config_sql.py must define mail_body_text = Column(String, default="")'


def test_column_uses_mail_prefix_so_get_mail_settings_includes_it():
    # get_mail_settings() returns every attr starting with "mail_"; the
    # prefix is what wires the value into the settings page with no extra
    # code. Pin both the prefix and the dict comprehension contract.
    assert "mail_body_text" in CONFIG_SQL.read_text()
    src = CONFIG_SQL.read_text()
    assert 'k.startswith(\'mail_\')' in src or 'k.startswith("mail_")' in src, (
        "get_mail_settings() must filter on the mail_ prefix"
    )


def test_helper_defines_resolver_and_getter():
    src = HELPER_PY.read_text()
    assert "def _resolve_email_body_text(" in src
    assert "def get_email_body_text(" in src
    # getter reads the config value and passes the translated default
    assert "config.mail_body_text" in src
    assert DEFAULT_BODY in src


def test_all_three_send_paths_use_the_getter():
    src = HELPER_PY.read_text()
    # The literal default must survive ONLY inside the getter's fallback,
    # never again as an inline TaskEmail/settings argument.
    assert src.count(f'_(\'{DEFAULT_BODY}\')') == 1, (
        "the default literal should appear once, inside get_email_body_text()"
    )
    assert src.count("get_email_body_text()") >= 3, (
        "convert+send, test-mail, and send-to-eReader must call the getter"
    )


def test_admin_saves_the_field():
    src = ADMIN_PY.read_text()
    assert re.search(r'_config_string\(to_save,\s*"mail_body_text"\)', src), (
        "update_mailsettings must persist mail_body_text"
    )


def test_admin_saves_before_config_save():
    # The save must run before config.save() so it lands in the same commit
    # for every submit branch (standard / gmail / invalidate / test).
    src = ADMIN_PY.read_text()
    save_idx = src.index('_config_string(to_save, "mail_body_text")')
    # the next config.save() after our line, within update_mailsettings
    tail = src[save_idx:]
    assert "config.save()" in tail, "config.save() must follow the mail_body_text save"


def test_template_has_textarea_field():
    src = EMAIL_EDIT_HTML.read_text()
    assert re.search(
        r'<textarea[^>]*name="mail_body_text"', src
    ), "email_edit.html must render a <textarea name=\"mail_body_text\">"
    assert "content.mail_body_text" in src, "textarea must show the saved value"


def test_registration_mail_body_untouched():
    # Scope guard: #428 is about book-bearing mails. The welcome/registration
    # email composes its own body and must NOT be rerouted through the getter.
    src = HELPER_PY.read_text()
    reg = src[src.index("def send_registration_mail("):]
    reg = reg[: reg.index("\ndef ", 1)]
    assert "get_email_body_text()" not in reg, (
        "registration email keeps its own body, out of scope for #428"
    )
