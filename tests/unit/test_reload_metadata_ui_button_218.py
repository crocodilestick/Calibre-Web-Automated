# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #218 reload-metadata UI button.

@yodatak originally asked for a way to reload embedded EPUB metadata
into the catalog when editing externally (grimmory etc.). v4.0.110
shipped the POST /admin/book/<id>/reload_metadata endpoint, but the
follow-up surfaced two UX gaps:

- @yodatak (2026-05-27): trying to call it manually with curl, got
  HTTP 400 — no CSRF token in their request, but the endpoint is
  CSRF-protected like the other edit-book routes.
- @magdalar (2026-05-29): opened the URL in Chrome, got 405 — the
  route is POST-only and Chrome sent GET.

The endpoint works correctly. The missing piece was a UI button so
the user doesn't have to construct the call themselves. This file
pins that:

1. The button exists in the book detail template (`detail.html`),
   gated on `current_user.role_edit()` — same gate as the route's
   `@edit_required`.
2. The button is a real `<button type="button">` (not an `<a href>`)
   so the browser doesn't navigate-on-GET like @magdalar's case.
3. The click handler POSTs to /admin/book/<id>/reload_metadata with
   X-CSRFToken so the CSRF protect gate doesn't 400 it like
   @yodatak's curl.
4. The handler reloads the page on a successful update so the user
   sees the refreshed metadata immediately (the whole point of
   pulling the on-disk file as source of truth).
"""

import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DETAIL_HTML = REPO_ROOT / "cps" / "templates" / "detail.html"


@pytest.fixture(scope="module")
def detail_template() -> str:
    return DETAIL_HTML.read_text(encoding="utf-8")


@pytest.mark.unit
class TestReloadMetadataButtonInTemplate:
    def test_button_exists_with_id(self, detail_template: str):
        assert 'id="reload-metadata-btn"' in detail_template, (
            "The reload-metadata button must have id='reload-metadata-btn' "
            "so the click handler can bind to it. Without the button, the "
            "user has to construct the POST manually — @yodatak's curl 400 "
            "and @magdalar's Chrome 405 are both symptoms of this."
        )

    def test_button_is_a_button_not_an_anchor(self, detail_template: str):
        # Pin that the element is `<button type="button">`, not `<a href>`.
        # An anchor with href would let a user open the URL in a new tab
        # via GET, which the route rejects with 405 (matched @magdalar's
        # exact error).
        import re
        match = re.search(
            r'<button[^>]*id="reload-metadata-btn"[^>]*type="button"',
            detail_template,
        )
        if match is None:
            # Order-insensitive: type may come before id.
            match = re.search(
                r'<button[^>]*type="button"[^>]*id="reload-metadata-btn"',
                detail_template,
            )
        assert match is not None, (
            "The reload-metadata UI element must be a <button "
            "type='button'>, not an <a href> — an anchor would let a "
            "user open the URL in a new tab via GET, which the route "
            "405s (the @magdalar Chrome reproduction)."
        )

    def test_button_gated_on_role_edit(self, detail_template: str):
        # The button must live inside a `{% if current_user.role_edit() %}`
        # block — same gate as the route's @edit_required. Search for
        # the button id and check the surrounding gate context.
        idx = detail_template.find('id="reload-metadata-btn"')
        assert idx != -1, "button must exist in template"
        # Walk backward looking for the nearest `{% if %}` / `{% endif %}`.
        # The button is inside the same `if current_user.role_edit()` block
        # as the Edit Metadata link.
        backward = detail_template[:idx]
        last_if = backward.rfind("{% if ")
        last_endif = backward.rfind("{% endif %}")
        assert last_if > last_endif, (
            "The reload-metadata button must be inside an `{% if %}` "
            "block — same role gate as Edit Metadata."
        )
        # The opening if condition must reference role_edit (the route's
        # @edit_required gate).
        if_block_start = detail_template[last_if:last_if + 200]
        assert "role_edit()" in if_block_start, (
            "The button's enclosing if block must check "
            "current_user.role_edit() — same gate as the route's "
            f"@edit_required. Found: {if_block_start[:150]}"
        )


@pytest.mark.unit
class TestReloadMetadataClickHandler:
    def test_handler_posts_to_reload_metadata_endpoint(self, detail_template: str):
        # POST URL must match the route declared in cps/editbooks.py
        # (`/admin/book/<int:book_id>/reload_metadata`).
        assert '"/admin/book/" + bookId + "/reload_metadata"' in detail_template, (
            "Click handler must POST to /admin/book/<id>/reload_metadata. "
            "If the URL drifts, the @yodatak / @magdalar workaround stays "
            "broken."
        )

    def test_handler_sets_xcsrf_token_header(self, detail_template: str):
        # @yodatak's curl 400 happened because the CSRF token wasn't
        # included. The handler must read the csrf meta tag and put it
        # in the X-CSRFToken header on every POST.
        assert '"X-CSRFToken":' in detail_template, (
            "Handler must send X-CSRFToken header on the POST. Without "
            "it, the route returns 400 (the @yodatak curl reproduction). "
            "Pattern: \"X-CSRFToken\": $('meta[name=\"csrf-token\"]')..."
        )
        assert 'meta[name="csrf-token"]' in detail_template, (
            "Handler must read the CSRF token from the standard "
            "<meta name='csrf-token' content='...'> tag so the same "
            "token rotates across in-flight requests."
        )

    def test_handler_disables_button_during_request(self, detail_template: str):
        # The reload re-parses an EPUB on disk — not instant. Without
        # the disable, an impatient double-click would fire two POSTs
        # against the same book, doubling the metadata-db write workload.
        assert ".prop(\"disabled\", true);" in detail_template, (
            "Click handler must disable the button while the AJAX is in "
            "flight to prevent double-submit (re-reading the EPUB twice)."
        )

    def test_handler_reloads_page_on_successful_update(self, detail_template: str):
        # If the user reloaded title/comments/publisher, the rendered
        # page is now stale. A page reload is the simplest, lowest-risk
        # way to surface the refreshed metadata to the user.
        assert "location.reload()" in detail_template, (
            "Click handler must reload the page on a successful update "
            "(updated_fields not empty). Without it, the user sees the "
            "toast 'Reloaded' but the rendered title/comments/publisher "
            "stays stale until they manually refresh — defeats the point."
        )

    def test_handler_surfaces_route_error_message_when_provided(self, detail_template: str):
        # The route returns helpful errors (file-not-found, parse-fail,
        # commit-fail) in `data.error`. The handler must surface them
        # rather than show a generic "could not reload" — otherwise the
        # user has no idea why it failed.
        assert "responseJSON" in detail_template, (
            "Click handler must check xhr.responseJSON.error to surface "
            "the route's specific error message (404 for missing file, "
            "500 for parse fail) instead of a generic 'could not reload'. "
            "Without this, the user has no actionable signal."
        )
