# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for fork #223 follow-up — anchor scroll after creation.

After v4.0.90 shipped the inline app-password box, reporter @droM4X
suggested a UX layer: after POSTing the form and redirecting to /me, the
page should scroll to the App passwords section so the user doesn't have
to hunt for the newly-created token.

The fix appends the fragment ``#pending-app-password`` to the redirect
target so browsers jump to the inline-box anchor on load. The
``<div id="pending-app-password">`` shipped in v4.0.90 already exists;
this PR only changes the redirect URL.
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _web_py_source():
    return (REPO_ROOT / "cps" / "web.py").read_text()


def test_app_password_create_redirects_to_pending_anchor():
    """The successful-creation redirect must carry the
    ``#pending-app-password`` fragment so browsers scroll to the inline
    box on load.
    """
    src = _web_py_source()
    # Find the function body
    func_match = re.search(
        r"def app_password_create\(\):(.*?)(?=^def |^@\w)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert func_match, "Could not locate app_password_create in cps/web.py"
    body = func_match.group(1)

    # The success branch (after flask_session write) must include
    # _anchor= in its url_for call, OR concatenate "#pending-app-password"
    # to the redirect target.
    success_redirect_with_anchor = bool(
        re.search(r"url_for\(\s*['\"]web\.profile['\"][^)]*_anchor\s*=\s*['\"]pending-app-password['\"]", body)
    ) or bool(
        re.search(r"redirect\([^)]*pending-app-password", body)
    )
    assert success_redirect_with_anchor, (
        "After writing session['pending_app_password'], app_password_create "
        "must redirect to `/me#pending-app-password` so the browser scrolls "
        "to the inline box. Use `url_for('web.profile', _anchor='pending-app-password')` "
        "or concatenate '#pending-app-password' to the redirect URL. "
        "Fork issue #223 follow-up (@droM4X)."
    )


def test_label_validation_error_path_does_not_use_anchor():
    """When the label is invalid (empty / too long), the redirect is back
    to ``/me`` with a flash. There's no pending-app-password box to scroll
    to, so the URL fragment must NOT be appended on that error path.
    """
    src = _web_py_source()
    func_match = re.search(
        r"def app_password_create\(\):(.*?)(?=^def |^@\w)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    body = func_match.group(1)
    # Find the error branch (the redirect that happens before the
    # `flask_session[...]` write — typically inside `if not label or...`).
    # Locate the error branch by anchoring on the label-must-be-1-64 flash
    # message, then take the next redirect call.
    flash_at = body.find("App-password label must be 1-64")
    assert flash_at >= 0, (
        "Couldn't find the label-validation flash. If wording changed, "
        "update this test."
    )
    # The following ~120 chars should include the `return redirect(...)`.
    error_branch_chunk = body[flash_at:flash_at + 300]
    error_redirect = re.search(
        r"return redirect\(([^)]*\([^)]*\)[^)]*|[^)]*)\)",
        error_branch_chunk,
    )
    assert error_redirect, (
        "Couldn't find the redirect call in the label-validation error "
        "branch chunk."
    )
    redirect_args = error_redirect.group(1)
    assert "pending-app-password" not in redirect_args, (
        "The label-validation error path must NOT redirect to the "
        "pending-app-password anchor — no new password was created, so "
        "the scroll target is meaningless. Keep `redirect(url_for('web.profile'))` "
        "without the anchor on this branch."
    )
