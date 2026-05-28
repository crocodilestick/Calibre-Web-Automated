# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #319 UX-safety half.

SethMilliken's original report (issue body) asks for three things on the
per-user hide-books feature beyond the recoverability bug fixes:

1. **Off by default + behind a feature flag.** "This is an absolutely
   terrible feature to not have behind some kind of feature flag" —
   admins must opt in before the hide button surfaces for users.
2. **Different icon from Read/Unread.** "It uses the same icon as the
   'Read/Unread' toggle (and is nearly adjacent to it in the UI) and
   effectively disappears a book from a user's library with no
   discoverable means of recovery."
3. **Place the button well away from frequently used buttons.** Reduce
   the chance of an inadvertent click.

droM4X's 2026-05-26 verification echoed the icon ambiguity: "the eye
icon should remain dedicated to the hide/unhide function, and the
'Toggle Read Status' icon should be changed to a checkmark or
double-checkmark if possible."

These tests pin the UX-safety contract added in PR #337:

A. ``config_user_hide_enabled`` column exists on settings, defaults to
   False, has a migration entry so existing installs pick it up.
B. Admin form (Feature Configuration) exposes the toggle.
C. detail.html: the hide BUTTON is rendered only when
   ``config.config_user_hide_enabled`` is true OR the book is already
   hidden (defense-in-depth: an admin disabling the feature mid-flight
   must not strand a user's already-hidden books).
D. detail.html: the read-status icon uses ``glyphicon-ok`` /
   ``glyphicon-unchecked`` (checkmark per droM4X), not
   ``glyphicon-eye-open`` / ``glyphicon-eye-close``.
E. detail.html: the toggle-read JS handler swaps ok/unchecked.
F. detail.html: the hide button is not the immediate sibling of the
   toggle-read button (placement separation).
G. /me Hidden Books recovery link stays visible regardless of flag
   when the user has hidden books (defense-in-depth recovery).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DETAIL_HTML = REPO_ROOT / "cps" / "templates" / "detail.html"
USER_EDIT_HTML = REPO_ROOT / "cps" / "templates" / "user_edit.html"
CONFIG_EDIT_HTML = REPO_ROOT / "cps" / "templates" / "config_edit.html"
CONFIG_SQL = REPO_ROOT / "cps" / "config_sql.py"
ADMIN_PY = REPO_ROOT / "cps" / "admin.py"
WEB_PY = REPO_ROOT / "cps" / "web.py"


@pytest.fixture(scope="module")
def detail_html() -> str:
    assert DETAIL_HTML.exists()
    return DETAIL_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def user_edit_html() -> str:
    assert USER_EDIT_HTML.exists()
    return USER_EDIT_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_edit_html() -> str:
    assert CONFIG_EDIT_HTML.exists()
    return CONFIG_EDIT_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_sql_src() -> str:
    assert CONFIG_SQL.exists()
    return CONFIG_SQL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def admin_src() -> str:
    assert ADMIN_PY.exists()
    return ADMIN_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def web_src() -> str:
    assert WEB_PY.exists()
    return WEB_PY.read_text(encoding="utf-8")


# ----- A. config_user_hide_enabled column -----

@pytest.mark.unit
class TestConfigUserHideEnabledColumn:
    def test_column_defined_on_settings(self, config_sql_src):
        """SethMilliken: 'making this default off'. The column must exist
        on the _Settings ORM model so admin saves persist + reads
        default to False on fresh installs."""
        assert re.search(
            r"config_user_hide_enabled\s*=\s*Column\(",
            config_sql_src,
        ), (
            "config_user_hide_enabled column missing from _Settings — "
            "without it the admin toggle has nowhere to persist (#319 "
            "SethMilliken: 'making this default off')"
        )

    def test_column_defaults_to_false(self, config_sql_src):
        """Off by default — SethMilliken's #1 ask. Existing installs
        without the column already get False from the model default; the
        migration ALTER below ensures legacy DBs match."""
        m = re.search(
            r"config_user_hide_enabled\s*=\s*Column\([^)]+\)",
            config_sql_src,
        )
        assert m, "config_user_hide_enabled column declaration not found"
        body = m.group(0)
        assert "default=False" in body or "default=0" in body, (
            f"config_user_hide_enabled must default to False so the "
            f"feature is off on every fresh install (#319). Got: {body!r}"
        )

    def test_migration_alters_legacy_db_via_auto_reflection(self, config_sql_src):
        """Existing CWA installs upgrading to the new column without an
        ALTER would see SQLAlchemy fail on first SELECT. CWNG's
        ``_migrate_table`` walks every Column on the ORM via
        ``orm_class.__dict__``, catches OperationalError on missing
        columns, and emits ALTER TABLE — so adding the Column
        declaration is sufficient as long as the auto-migration runs
        against _Settings. Pin both: column exists + _migrate_table is
        wired for _Settings."""
        # Column must be declared on _Settings (where _migrate_table
        # iterates).
        m_settings = re.search(
            r"class\s+_Settings\b.*?(?=\nclass\s|\Z)",
            config_sql_src,
            re.DOTALL,
        )
        assert m_settings, "_Settings class not found in config_sql.py"
        assert "config_user_hide_enabled" in m_settings.group(0), (
            "config_user_hide_enabled must be declared inside class "
            "_Settings — that's the table _migrate_table reflects over "
            "on first boot post-upgrade. Without it, the auto-ALTER "
            "won't fire and the column never lands in legacy DBs."
        )
        # The migration helper must iterate _Settings at upgrade time.
        assert re.search(
            r"_migrate_table\s*\(\s*session\s*,\s*_Settings",
            config_sql_src,
        ), (
            "_migrate_table(session, _Settings, ...) must be invoked "
            "during DB init — that's the call that triggers the "
            "ALTER TABLE for any new column on _Settings."
        )


# ----- B. Admin Feature Configuration toggle -----

@pytest.mark.unit
class TestAdminFeatureConfigToggle:
    def test_admin_save_handler_persists_field(self, admin_src):
        """The admin /admin/config POST must include
        config_user_hide_enabled in its persistence pass. Pattern in
        admin.py is _config_checkbox_int(to_save, '<name>') for boolean
        config flags."""
        assert re.search(
            r"_config_checkbox(?:_int|_no_lock)?\(\s*to_save\s*,\s*['\"]config_user_hide_enabled['\"]",
            admin_src,
        ), (
            "admin save handler must call "
            "_config_checkbox_int(to_save, 'config_user_hide_enabled') "
            "so the form value persists to settings — without this, "
            "toggling the checkbox in /admin/config has no effect (#319)"
        )

    def test_admin_template_renders_checkbox(self, config_edit_html):
        """config_edit.html must render an <input type=checkbox> for the
        new flag so admins can toggle it in the UI."""
        assert re.search(
            r'name=["\']config_user_hide_enabled["\']',
            config_edit_html,
        ), (
            "config_edit.html missing <input name='config_user_hide_enabled'> "
            "— the admin needs a UI control to opt the server into the "
            "hide feature (SethMilliken: 'behind some kind of feature flag')"
        )
        # Pin the checked-when-on pattern so the displayed state matches DB.
        assert re.search(
            r"\{%\s*if\s+config\.config_user_hide_enabled\s*%\}\s*checked",
            config_edit_html,
        ), (
            "config_edit.html checkbox must use "
            "{% if config.config_user_hide_enabled %}checked{% endif %} "
            "so the rendered state reflects the persisted DB value"
        )

    def test_admin_template_label_describes_the_feature(self, config_edit_html):
        """The label must clearly describe what the toggle does — admins
        shouldn't have to read the source to know what the checkbox
        controls."""
        # Find the label adjacent to the checkbox (next sibling within
        # the same form-group block) and assert it includes the user-
        # facing 'hide' wording.
        m = re.search(
            r'name=["\']config_user_hide_enabled["\'].*?</label>',
            config_edit_html,
            re.DOTALL,
        )
        assert m, "label for config_user_hide_enabled not found within form-group"
        body = m.group(0).lower()
        assert "hide" in body, (
            "label for config_user_hide_enabled must include 'hide' — "
            "admins need plain-English context for the toggle"
        )


# ----- C. Hide button gating in detail.html -----

@pytest.mark.unit
class TestDetailHideButtonGated:
    def test_toggle_hide_btn_is_gated_on_config_or_is_hidden(self, detail_html, admin_src):
        """The hide button block must be wrapped in an {% if %} that
        opens the button when EITHER the admin enabled the feature OR
        the book is already hidden (recovery defense-in-depth).

        Implementation detail: in Jinja the global ``config`` resolves
        to Flask's app.config, NOT cps.config — see PR #335 lessons.
        So the gate uses ``g.user_hide_enabled`` (populated from
        ``config.config_user_hide_enabled`` in admin.py's
        ``@admi.before_app_request`` handler, mirroring
        ``g.allow_anonymous``). Both halves of the wiring are pinned:
        the template gate AND the before_request population.
        """
        m = re.search(
            r'id="toggle-hide-btn"',
            detail_html,
        )
        assert m, "toggle-hide-btn not found in detail.html"
        head = detail_html[: m.start()]
        # Grab the last ~1500 chars and search for the most recent {% if %}.
        window = head[-1500:]
        ifs = list(re.finditer(r"\{%\s*if\s+([^%]+?)\s*%\}", window))
        assert ifs, (
            "toggle-hide-btn is not wrapped in any {% if %} — without a "
            "gate the button shows for every user regardless of admin "
            "preference (#319 SethMilliken: 'behind some kind of "
            "feature flag')"
        )
        gate_condition = ifs[-1].group(1)
        normalized = re.sub(r"\s+", " ", gate_condition).lower()
        # The gate must reference the runtime flag — either via the
        # g.user_hide_enabled indirection (correct, current) OR via
        # config.config_user_hide_enabled (which would silently fail
        # since Jinja config != cps.config).
        flag_ok = "g.user_hide_enabled" in normalized
        config_ok = "config.config_user_hide_enabled" in normalized
        has_hidden = "is_hidden" in normalized
        assert flag_ok or config_ok, (
            f"The gating {{% if %}} around toggle-hide-btn must reference "
            f"the user-hide flag (preferably g.user_hide_enabled — the "
            f"`config` Jinja global is Flask's app.config, not cps.config). "
            f"Found condition: {gate_condition!r}"
        )
        assert has_hidden, (
            f"The gating {{% if %}} around toggle-hide-btn must also "
            f"check is_hidden so the button always remains available "
            f"for unhide when the book is currently hidden by the user "
            f"(defense-in-depth recovery — admins must not be able to "
            f"strand users' already-hidden books). Got: {gate_condition!r}"
        )
        # If the template uses g.user_hide_enabled, also pin the
        # before_app_request wiring so the value is populated.
        if flag_ok and not config_ok:
            assert re.search(
                r"g\.user_hide_enabled\s*=\s*[^=]",
                admin_src,
            ), (
                "Template gate uses g.user_hide_enabled but no "
                "`g.user_hide_enabled = ...` assignment exists in admin.py "
                "— the flag will always be Undefined in the template, "
                "silently disabling the hide button for everyone."
            )
            assert re.search(
                r"@admi\.before_app_request",
                admin_src,
            ), (
                "before_app_request decorator missing from admin.py — "
                "the g.user_hide_enabled assignment must live in a "
                "@admi.before_app_request handler so it runs for every "
                "route, not just admin routes."
            )


# ----- D + E. Read-status icon is a checkmark -----

@pytest.mark.unit
class TestDetailReadStatusIconIsCheckmark:
    def test_read_icon_uses_ok_unchecked_classes(self, detail_html):
        """droM4X (#319 pushback): 'the Toggle Read Status icon should
        be changed to a checkmark or double-checkmark if possible.' Pin
        the swap to glyphicon-ok / glyphicon-unchecked so the read
        toggle no longer collides visually with the hide button."""
        # Match the full class="..." attribute including embedded Jinja
        # single-quoted strings. Use a backreference to the opening
        # quote so inner quotes of a different style don't terminate.
        m = re.search(
            r'id=["\']read-icon["\'][^>]*class=(["\'])(.+?)\1',
            detail_html,
            re.DOTALL,
        )
        assert m, "read-icon span not found in detail.html"
        klass = m.group(2)
        # The class attribute is rendered through a Jinja conditional;
        # pin both glyphicon names appear in the rendered class string.
        assert "glyphicon-ok" in klass, (
            f"read-icon must use glyphicon-ok (single check) for the "
            f"'read' state — droM4X's pushback ask. Got class: {klass!r}"
        )
        assert "glyphicon-unchecked" in klass, (
            f"read-icon must use glyphicon-unchecked (empty box) for the "
            f"'unread' state. Got class: {klass!r}"
        )
        # Defense: the OLD eye-open/eye-close pair must NOT remain on
        # read-icon (otherwise the visual collision with hide is back).
        assert "glyphicon-eye-open" not in klass, (
            "read-icon must NOT use glyphicon-eye-open any more — "
            "that's exactly the collision SethMilliken called out"
        )
        assert "glyphicon-eye-close" not in klass, (
            "read-icon must NOT use glyphicon-eye-close any more"
        )

    def test_read_toggle_js_swaps_ok_unchecked(self, detail_html):
        """The JS handler for toggle-read-btn must toggle ok/unchecked
        in lockstep with the server response, otherwise the icon goes
        stale after the first click."""
        # Find the toggle-read-btn handler block.
        m = re.search(
            r'\$\("#toggle-read-btn"\).on\("click".*?\}\);\s*\n',
            detail_html,
            re.DOTALL,
        )
        assert m, "toggle-read-btn click handler not found in detail.html"
        body = m.group(0)
        assert "glyphicon-ok" in body and "glyphicon-unchecked" in body, (
            f"toggle-read-btn click handler must toggleClass('glyphicon-ok', isRead) "
            f"and toggleClass('glyphicon-unchecked', !isRead) so the icon "
            f"updates after the AJAX response. Got handler body length: "
            f"{len(body)}"
        )
        # The OLD eye-open/eye-close pair must NOT remain in the handler.
        assert "glyphicon-eye-open" not in body, (
            "toggle-read-btn handler still references glyphicon-eye-open "
            "— icon will drift to eye after first click"
        )
        assert "glyphicon-eye-close" not in body, (
            "toggle-read-btn handler still references glyphicon-eye-close "
            "— icon will drift to eye after first click"
        )


# ----- F. Placement separation -----

@pytest.mark.unit
class TestDetailHideButtonPlacement:
    def test_hide_button_is_not_immediate_sibling_of_read_button(self, detail_html):
        """SethMilliken's #3 ask: 'placing the button well away from
        frequently used buttons in a place it is less likely to be
        inadvertently clicked.' Pin that the hide button is not the
        immediate sibling of the read-status button (visual separation
        via at least 2 intervening interactive elements, NOT counting
        the hide button's own opening tag)."""
        # Find offsets of the toggle-read-btn and toggle-hide-btn ids.
        read_m = re.search(r'id=["\']toggle-read-btn["\']', detail_html)
        hide_m = re.search(r'id=["\']toggle-hide-btn["\']', detail_html)
        assert read_m and hide_m, (
            "both toggle-read-btn and toggle-hide-btn must exist in detail.html"
        )
        # Locate the OPENING <button tag for toggle-hide-btn (it precedes
        # the id attribute by a few characters) and exclude it from the
        # 'between' window. Otherwise the hide button's own opener
        # inflates the count by 1 even when the two buttons are direct
        # siblings.
        hide_btn_open = detail_html.rfind("<button", 0, hide_m.start())
        assert hide_btn_open > -1, "could not locate <button opener for toggle-hide-btn"
        if read_m.start() < hide_m.start():
            between = detail_html[read_m.end(): hide_btn_open]
        else:
            # Hide is BEFORE read — invert window.
            read_btn_open = detail_html.rfind("<button", 0, read_m.start())
            between = detail_html[hide_m.end(): read_btn_open]
        # Count button-like elements: <button> tags and <a class="btn"> tags.
        button_tags = re.findall(r"<button\b", between, re.IGNORECASE)
        anchor_btns = re.findall(
            r"<a\b[^>]*class=[\"'][^\"']*\bbtn\b",
            between,
            re.IGNORECASE,
        )
        n_between = len(button_tags) + len(anchor_btns)
        assert n_between >= 2, (
            f"hide button must be separated from read-status button by "
            f"at least 2 intervening interactive elements (#319 "
            f"SethMilliken: 'placing the button well away from "
            f"frequently used buttons'). Found only {n_between} "
            f"between them (excluding the hide button's own opening tag)."
        )


# ----- H. Route-level gate (defense-in-depth) -----

@pytest.mark.unit
class TestToggleHiddenRouteGate:
    """Without route-level gating, a user could still hide books via
    direct POST (curl, bookmarklet, extension) even when the admin has
    disabled the feature. The route must mirror the template gate:
    refuse new hides when the flag is off, but always allow unhide
    (recovery defense-in-depth)."""

    def test_route_refuses_hide_when_flag_off(self, web_src):
        # Locate the toggle_hidden function and pin: the hide-path
        # (else branch) checks the config flag and aborts 403 when off;
        # the unhide-path (if existing) does NOT consult the flag.
        m = re.search(
            r"def toggle_hidden\(book_id\):.*?(?=\n@web\.route|\n\ndef |\nclass |\Z)",
            web_src,
            re.DOTALL,
        )
        assert m, "toggle_hidden function not found in cps/web.py"
        body = m.group(0)
        # The function must reference the feature flag.
        assert "config_user_hide_enabled" in body, (
            "toggle_hidden must consult config_user_hide_enabled so "
            "direct POSTs can't bypass the admin's opt-out (#319 "
            "SethMilliken safety)"
        )
        # The function must abort/403 somewhere — pin that.
        assert re.search(r"abort\s*\(\s*403\s*\)", body), (
            "toggle_hidden must abort(403) on the hide-when-disabled path"
        )
        # Defense-in-depth: the unhide branch (existing row found) must
        # execute BEFORE the flag-checked abort. There may be multiple
        # abort(403)s (e.g. an anonymous-guard at the top); the one we
        # care about is the LAST one — the hide-disabled path.
        delete_pos = body.find("session.delete(existing)")
        last_abort_pos = body.rfind("abort(403)")
        assert delete_pos > -1 and last_abort_pos > -1, (
            f"Could not locate both unhide and last abort positions. "
            f"delete_pos={delete_pos}, last_abort_pos={last_abort_pos}"
        )
        assert delete_pos < last_abort_pos, (
            "The unhide branch (session.delete(existing)) must execute "
            "BEFORE the flag-check abort(403) — otherwise users with "
            "already-hidden books can't recover when admin disables "
            "the feature (#319 recovery defense-in-depth)."
        )
        # Verify the flag-check abort is co-located with the
        # config_user_hide_enabled reference (same statement / nearby).
        flag_pos = body.rfind("config_user_hide_enabled")
        assert abs(last_abort_pos - flag_pos) < 400, (
            f"The flag check and the abort(403) should be within ~400 "
            f"chars of each other (same conditional block, allowing for "
            f"comments + log statements). "
            f"flag_pos={flag_pos}, abort_pos={last_abort_pos}"
        )


# ----- G. Recovery defense-in-depth -----

@pytest.mark.unit
class TestRecoveryAlwaysAvailable:
    def test_change_profile_error_path_also_passes_hidden_book_count(self, web_src):
        """Greptile catch on PR #337: the GET profile() path computes
        hidden_book_count, but the change_profile() error-path render
        (validation-error re-render) historically didn't, so a user
        with hidden books would see the recovery link silently
        disappear after a bad save (e.g. invalid email). Pin that
        BOTH render sites pass the count."""
        # Find both render sites for user_edit.html and assert each
        # call kwargs include hidden_book_count.
        renders = re.findall(
            r'render_title_template\(\s*["\']user_edit\.html["\'][^)]*\)',
            web_src,
            re.DOTALL,
        )
        assert len(renders) >= 2, (
            f"Expected at least 2 render sites for user_edit.html "
            f"(profile() GET + change_profile() error-path); found "
            f"{len(renders)}. Either there are more re-render sites "
            f"to update, or one was removed."
        )
        for r in renders:
            assert "hidden_book_count" in r, (
                "Every render_title_template('user_edit.html', ...) site "
                "must pass hidden_book_count, otherwise the /me Hidden "
                "Books link silently disappears on validation errors. "
                f"Offender:\n{r[:300]}"
            )

    def test_profile_hidden_books_link_not_gated_on_config_flag(self, user_edit_html):
        """If admin disables the hide feature while users still have
        hidden books, the Hidden Books link on /me must remain visible
        — otherwise users can never recover. The gate is on
        ``hidden_book_count > 0``, NOT on the config flag."""
        # Find any {% if %} block that gates on hidden_book_count, and
        # verify it does NOT also test the config flag.
        gates = re.findall(
            r"\{%\s*if\s+[^%]*?hidden_book_count[^%]*?%\}",
            user_edit_html,
        )
        assert gates, (
            "Could not find any {% if %} testing hidden_book_count in "
            "user_edit.html — recovery link cannot be conditionally shown"
        )
        # Pin: the gate referencing hidden_book_count must not also
        # reference config_user_hide_enabled (would defeat recovery).
        for gate in gates:
            assert "config_user_hide_enabled" not in gate, (
                f"The hidden_book_count gate must NOT test the admin "
                f"config flag — if admin disables the feature, users "
                f"with already-hidden books still need this link to "
                f"recover them. Got: {gate!r}"
            )
        # Pin: the {% if %} block must immediately enclose a link to the
        # books_list endpoint with data='hidden'. Search the body after
        # any such gate for that pattern.
        anchor_match = re.search(
            r"hidden_book_count[\s\S]{1,800}?url_for\([^)]*web\.books_list[^)]*hidden",
            user_edit_html,
        )
        assert anchor_match, (
            "Expected url_for('web.books_list', ..., data='hidden', ...) "
            "within ~800 chars of the hidden_book_count gate — the gate "
            "must wrap an actual link, not be empty/dead code."
        )
