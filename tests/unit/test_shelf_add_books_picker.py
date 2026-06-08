# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shelf-page "Add books" picker — endpoint + wiring invariants.

A shelf page now has an "Add Books" button that opens a modal book-picker. The
picker reads ``GET /shelf/<id>/available_books`` (library search, each book
flagged ``in_shelf``) and submits the chosen ids to the existing, deduping
``/shelf/add_selected_to_shelf`` write path. The full open→search→select→add→
dedup flow is verified live with Playwright (desktop + mobile); these pins guard
the structural invariants so a refactor can't silently break them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELF_PY = (REPO_ROOT / "cps" / "shelf.py").read_text()
SHELF_HTML = (REPO_ROOT / "cps" / "templates" / "shelf.html").read_text()
PICKER_JS = (REPO_ROOT / "cps" / "static" / "js" / "shelf_add_books.js").read_text()


class TestAvailableBooksEndpoint:
    def test_route_defined(self):
        assert re.search(
            r'@shelf\.route\(\s*["\']/shelf/<int:shelf_id>/available_books["\']',
            SHELF_PY,
        ), "the picker endpoint /shelf/<id>/available_books must exist"

    def test_endpoint_checks_edit_permission(self):
        # the function body must gate on check_shelf_edit_permissions and 403
        m = re.search(r"def shelf_available_books\(shelf_id\):(.*?)\n@", SHELF_PY, re.S)
        assert m, "shelf_available_books function not found"
        body = m.group(1)
        assert "check_shelf_edit_permissions" in body, "endpoint must check edit permission"
        assert "403" in body, "endpoint must 403 when the user can't edit the shelf"
        assert "404" in body, "endpoint must 404 on an unknown shelf"

    def test_endpoint_normalises_search_and_plain_book_shapes(self):
        # get_search_results returns rows wrapping the book in `.Books`; the plain
        # recent query returns Books directly — the endpoint must handle both.
        m = re.search(r"def shelf_available_books\(shelf_id\):(.*?)\n@", SHELF_PY, re.S)
        body = m.group(1)
        assert "getattr(entry, 'Books', entry)" in body, (
            "must normalise the two book shapes (search rows expose .Books; the "
            "plain query yields the book) — otherwise the search path 500s on book.id"
        )
        assert "in_shelf" in body, "each book must be flagged with in_shelf"


class TestShelfPageWiring:
    def test_add_books_button_present_and_edit_gated(self):
        assert 'id="add_books_to_shelf"' in SHELF_HTML, "Add Books button must exist"
        # the button must carry the endpoint + add URLs for the JS
        assert "shelf.shelf_available_books" in SHELF_HTML
        assert "shelf.add_selected_to_shelf" in SHELF_HTML
        # it must sit before the `entries.__len__()` guard so empty shelves show it
        btn_idx = SHELF_HTML.find('id="add_books_to_shelf"')
        entries_guard_idx = SHELF_HTML.find("entries.__len__()")
        assert btn_idx != -1 and entries_guard_idx != -1 and btn_idx < entries_guard_idx, (
            "the Add Books button must render before the non-empty-entries guard so "
            "it appears on empty shelves (the main use case)"
        )

    def test_modal_and_assets_included(self):
        assert 'id="addBooksModal"' in SHELF_HTML, "picker modal must exist"
        assert "js/shelf_add_books.js" in SHELF_HTML, "picker JS must be loaded"
        assert "css/shelf_add_books.css" in SHELF_HTML, "picker CSS must be loaded"


class TestPickerJsSafety:
    def test_posts_to_dedup_write_path(self):
        assert "add_selected_to_shelf" not in PICKER_JS or "data-add-url" in SHELF_HTML
        # JS reads the add URL from the button rather than hardcoding it
        assert "data-add-url" in PICKER_JS or "getAttribute(\"data-add-url\")" in PICKER_JS

    def test_submit_checks_status_before_reload(self):
        # submit() must not blindly close + reload on any JSON response — a 4xx/5xx
        # (e.g. a session that expired while the picker was open) must surface an
        # error instead of silently closing with nothing added (Greptile finding).
        assert "res.status >= 200 && res.status < 300" in PICKER_JS, (
            "submit() must gate close+reload on a 2xx status"
        )
        assert "setError(" in PICKER_JS, "submit() must surface failures to the user"

    def test_book_text_set_via_textcontent_not_innerhtml(self):
        # titles/authors come from the library — they must be assigned with
        # textContent, never interpolated into innerHTML (XSS).
        assert ".textContent = book.title" in PICKER_JS
        # the only innerHTML use is clearing the container
        innerhtml_assigns = re.findall(r"\.innerHTML\s*=\s*([^;]+);", PICKER_JS)
        for rhs in innerhtml_assigns:
            assert rhs.strip() in ('""', "''"), (
                f"innerHTML must only be used to clear (= \"\"), got: {rhs.strip()}"
            )
