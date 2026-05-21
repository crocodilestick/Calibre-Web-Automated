# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acceptance tests for fork issue #276 (@magdalar): admin checkboxes
to send a book to OTHER users' kindle_mail addresses from the Send-to-
eReader modal on the book detail page.

Reporter manages eReaders for their family and copy-pastes addresses
from /admin/view → user-edit → kindle_mail every time they want to send
to a different family member. The feature: surface other users with a
kindle_mail set as checkboxes alongside the existing self.kindle_mail
list.

Privacy: only admins see other users' email addresses (other users'
addresses are PII from their perspective). Non-admin sessions keep the
existing self-only behavior.

Storage: no new columns. The other-user list is derived at render time
from `ub.User.kindle_mail` for users with at least one address set.
The POST handler validates selected emails against an allow-set that
includes self.kindle_mail + (for admins) other users' kindle_mail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_PY = REPO_ROOT / "cps" / "web.py"
DETAIL_HTML = REPO_ROOT / "cps" / "templates" / "detail.html"


def _web_src() -> str:
    return WEB_PY.read_text()


def _detail_src() -> str:
    return DETAIL_HTML.read_text()


# ---------------------------------------------------------------------------
# show_book passes other-users-with-kindle to the template (admin only)
# ---------------------------------------------------------------------------

def test_show_book_passes_other_users_with_kindle_context():
    """The detail.html render_title_template call must include the new
    `other_users_with_kindle` context list."""
    src = _web_src()
    # Locate the show_book function body (between def show_book and the
    # next top-level def).
    # show_book is the last function in cps/web.py — match through EOF.
    match = re.search(
        r"(def show_book\(book_id\):.*)",
        src, re.DOTALL,
    )
    assert match, "show_book function not found"
    body = match.group(1)
    assert "other_users_with_kindle" in body, (
        "show_book must build + pass other_users_with_kindle in the "
        "detail.html template context"
    )


def test_other_users_with_kindle_is_admin_gated():
    """Non-admin sessions must NOT see other users' email addresses
    (PII). The build must be guarded by role_admin()."""
    src = _web_src()
    # show_book is the last function in cps/web.py — match through EOF.
    match = re.search(
        r"(def show_book\(book_id\):.*)",
        src, re.DOTALL,
    )
    body = match.group(1)
    # Same-paragraph proximity: role_admin appears within 600 chars of the
    # other_users_with_kindle assignment.
    var_idx = body.find("other_users_with_kindle")
    assert var_idx != -1
    window = body[max(0, var_idx - 600):var_idx + 600]
    assert "role_admin" in window, (
        "other_users_with_kindle build must check current_user.role_admin() "
        "in the same code block — privacy gate"
    )


def test_other_users_excludes_current_user_and_unfconfigured():
    """The build must filter (a) current_user themselves and (b) users
    with empty / None kindle_mail."""
    src = _web_src()
    # show_book is the last function in cps/web.py — match through EOF.
    match = re.search(
        r"(def show_book\(book_id\):.*)",
        src, re.DOTALL,
    )
    body = match.group(1)
    var_idx = body.find("other_users_with_kindle")
    block = body[var_idx:var_idx + 1500]
    # Self-exclusion: filter on ub.User.id != current_user.id (or similar).
    assert re.search(r"User\.id\s*!=\s*current_user\.id|user\.id\s*!=\s*current_user\.id|\.id\s*!=\s*int\(current_user\.id\)", block), (
        "must exclude current_user from the other-users list"
    )
    # Kindle-mail filter: query rejects empty / None.
    assert re.search(r"kindle_mail.*!=|kindle_mail.*is_not\(None\)|kindle_mail", block), (
        "must filter by kindle_mail being set"
    )


# ---------------------------------------------------------------------------
# send_to_selected_ereaders validates against the admin-extended allow set
# ---------------------------------------------------------------------------

def test_send_to_selected_admin_can_send_to_other_users():
    """The POST handler's allow-set check must include other users'
    kindle_mail addresses when current_user.role_admin() is true."""
    src = _web_src()
    match = re.search(
        r"(def send_to_selected_ereaders\(book_id\):.*?)(?=\n(?:def \w|@\w|class ))",
        src, re.DOTALL,
    )
    assert match, "send_to_selected_ereaders function not found"
    body = match.group(1)
    assert "role_admin" in body, (
        "send_to_selected_ereaders must check role_admin() to grant "
        "permission to send to other users' kindle_mail"
    )


# ---------------------------------------------------------------------------
# Template surfaces the new admin section in the email-select modal
# ---------------------------------------------------------------------------

def test_detail_template_renders_other_users_section():
    src = _detail_src()
    # Section header strings — exact i18n-wrapped form.
    assert "other_users_with_kindle" in src, (
        "detail.html must iterate other_users_with_kindle in the modal"
    )
    # Must be guarded with {% if other_users_with_kindle %} (so non-admin
    # sessions with empty list don't render a confusing empty header).
    assert re.search(
        r"\{%\s*if\s+other_users_with_kindle\s*%\}",
        src,
    ), "template section must be {% if other_users_with_kindle %} guarded"


def test_detail_template_checkbox_value_is_user_email():
    """Each other-user row's checkbox value must be the user's
    kindle_mail (the actual email to send to), not the user's name or id."""
    src = _detail_src()
    # Find the other_users_with_kindle loop + verify the checkbox value
    # references the user's email/kindle_mail attribute.
    match = re.search(
        r"\{%\s*for\s+\w+\s+in\s+other_users_with_kindle\s*%\}(.*?)\{%\s*endfor\s*%\}",
        src, re.DOTALL,
    )
    assert match, "other_users_with_kindle for-loop not found in template"
    loop_body = match.group(1)
    assert 'type="checkbox"' in loop_body
    assert 'name="selected_emails"' in loop_body, (
        "checkbox must POST under 'selected_emails' to reuse the existing endpoint"
    )
    # Value must reference an email/kindle_mail attribute, not a name/id.
    assert re.search(
        r'value="\{\{\s*\w+\.(kindle_mail|email)',
        loop_body,
    ), "checkbox value must be the user's kindle_mail / email"
