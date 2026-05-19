# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for fork #223 — app password inline display.

Reporter @droM4X observed that the newly-generated app password was shown
in a 10-second toast at the bottom of the page. Hard to spot, hard to
read, hard to copy. The fix moves the cleartext to a prominent inline
box at the top of the app-password section on ``/me``, persistent across
reloads of that page, and cleared automatically when the user navigates
to any other route.

Implementation contract pinned by these tests:

1. ``app_password_create`` writes the generated cleartext (NOT the hash)
   plus the label into ``session["pending_app_password"]`` before
   redirecting. Existing label-validation flash path is preserved.
2. The cleartext is never persisted to the database — only the hash is.
3. A request to any non-profile route clears the session key
   (``before_request`` hook). This is the "disappear once they navigate
   away" half of the requirement.
4. Reloading ``/me`` itself keeps the cleartext visible — refresh does
   not consume it.
5. The template includes the cleartext when ``pending_app_password`` is
   set; does not include it otherwise.
"""

import inspect
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _web_py_source():
    return (REPO_ROOT / "cps" / "web.py").read_text()


def _user_edit_template_source():
    return (REPO_ROOT / "cps" / "templates" / "user_edit.html").read_text()


def _init_py_source():
    return (REPO_ROOT / "cps" / "__init__.py").read_text()


def test_app_password_create_writes_session_not_flash_token():
    """``app_password_create`` must put the cleartext into the session,
    not into a Flask flash message.

    The previous shape `flash(...token...)` produced the 10-second toast
    that @droM4X reported. Removing the token from the flash string and
    routing it through the session is the user-visible behavior change.
    """
    src = _web_py_source()
    # Find the function.
    func_match = re.search(
        r"def app_password_create\(\):(.*?)(?=^def |^@\w)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert func_match, "Could not locate app_password_create in cps/web.py."
    body = func_match.group(1)

    # The pre-fix flash contained the token. The post-fix path must store
    # cleartext in session keyed by 'pending_app_password' and the flash
    # must not include the token variable.
    assert "session[" in body and "pending_app_password" in body, (
        "app_password_create must write the cleartext + label to "
        "session['pending_app_password'] so the profile template can "
        "render it inline. Current body did not reference "
        "session['pending_app_password']."
    )
    # The flashed token form is gone — no `flash(...token...` line with
    # the cleartext variable.
    bad_flash = re.search(
        r"flash\([^)]*token=cleartext[^)]*\)",
        body,
    )
    assert not bad_flash, (
        "Cleartext token must NOT appear in a flash() call anymore — the "
        "whole point of fork #223 is to remove the bottom-toast surface. "
        "Use session['pending_app_password'] + the inline template "
        "render instead."
    )


def test_session_payload_includes_label_and_token():
    """The session value must carry both the label (so the inline box
    can say "for 'Kobo Forma'") and the token (the user-visible string
    they need to copy). A future refactor that drops one or the other
    breaks the UX promise.
    """
    src = _web_py_source()
    func_match = re.search(
        r"def app_password_create\(\):(.*?)(?=^def |^@\w)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    body = func_match.group(1)
    # Both 'label' and 'cleartext' (or 'token') must appear within the
    # session assignment. Pin by proximity to the session write.
    session_write = re.search(
        r"session\[['\"]pending_app_password['\"]\]\s*=\s*(\{[^}]+\}|[^\n]+)",
        body,
    )
    assert session_write, (
        "Could not find a `session['pending_app_password'] = ...` "
        "assignment in app_password_create. Add one carrying both "
        "the label and the cleartext token."
    )
    payload = session_write.group(1)
    assert "label" in payload, (
        f"session['pending_app_password'] must carry the label so the "
        f"inline box can identify which password was just created. "
        f"Current payload: {payload}"
    )
    assert "cleartext" in payload or "token" in payload, (
        f"session['pending_app_password'] must carry the cleartext "
        f"token. Current payload: {payload}"
    )


def test_cleartext_never_persisted_to_db():
    """The DB row must store only the hash. The cleartext only ever
    lives in session + the inline render — never on disk.
    """
    src = _web_py_source()
    func_match = re.search(
        r"def app_password_create\(\):(.*?)(?=^def |^@\w)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    body = func_match.group(1)
    # Pin generate_password_hash(cleartext) is what goes to the DB row.
    assert "generate_password_hash(cleartext)" in body, (
        "The DB row must be created with `generate_password_hash(cleartext)` "
        "(only the hash on disk). Current body did not show this exact call."
    )
    # And the raw cleartext is not passed to UserAppPassword constructor.
    assert not re.search(
        r"UserAppPassword\([^)]*password_hash\s*=\s*cleartext\b",
        body,
    ), (
        "UserAppPassword must NEVER be constructed with the raw cleartext "
        "in password_hash. Hash it first via generate_password_hash()."
    )


def test_profile_route_passes_pending_app_password_to_template():
    """The ``/me`` profile route must read the session key and pass it
    to the template as ``pending_app_password``. Template renders it
    inline; if the route doesn't pass it, the box never appears.
    """
    src = _web_py_source()
    # The profile route is the function decorated with the /me path.
    profile_match = re.search(
        r"def profile\(\):(.*?)(?=^def |^@web\.route)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert profile_match, "Could not locate `def profile():` in cps/web.py."
    body = profile_match.group(1)
    assert "pending_app_password" in body, (
        "The profile route must pass `pending_app_password=` to its "
        "render_template / render_title_template call so the inline box "
        "knows whether to render."
    )


def test_before_request_clears_session_on_non_profile_routes():
    """A before_request hook must clear ``pending_app_password`` from
    the session when the user navigates to any route other than the
    profile page. This implements "disappear once they navigate away".
    """
    init_src = _init_py_source()
    web_src = _web_py_source()
    combined = init_src + "\n" + web_src
    # The hook can live in either file. Pin its existence.
    hook_present = (
        "pending_app_password" in combined
        and re.search(
            r"session\.pop\(['\"]pending_app_password['\"]",
            combined,
        )
    )
    assert hook_present, (
        "Could not find a `session.pop('pending_app_password', ...)` "
        "call anywhere in cps/__init__.py or cps/web.py. Add a "
        "before_request hook (or equivalent) that clears the session "
        "key when the user navigates away from /me."
    )


def test_template_renders_pending_app_password_inline():
    """The user_edit.html template must render
    ``pending_app_password`` inline in the App passwords section when
    the variable is truthy. Without this, the session value never
    surfaces to the user.
    """
    src = _user_edit_template_source()
    # The template branch shape: a conditional that gates on
    # pending_app_password and renders the .token / cleartext.
    assert "pending_app_password" in src, (
        "cps/templates/user_edit.html must reference pending_app_password "
        "in a conditional block that renders the cleartext + label inline "
        "in the App passwords section."
    )
    # And the box must contain the actual cleartext value, not just the
    # variable name.
    rendered = re.search(
        r"\{\{\s*pending_app_password\.(?:token|cleartext)\s*\}\}",
        src,
    )
    assert rendered, (
        "The template must render pending_app_password.token (or "
        ".cleartext) inside a `{{ ... }}` Jinja expression so the user "
        "actually sees the password. Current template did not include "
        "the rendered token."
    )


def test_template_does_not_show_when_pending_app_password_missing():
    """When pending_app_password is None/absent, the inline box must
    not render. Conditional shape, not unconditional.

    Pin the Jinja `{% if pending_app_password %}` guard.
    """
    src = _user_edit_template_source()
    guard = re.search(
        r"\{%\s*if\s+pending_app_password\s*%\}",
        src,
    )
    assert guard, (
        "The template must guard the inline cleartext render with "
        "`{% if pending_app_password %}` — without the guard, an empty "
        "box would appear on every /me visit."
    )
