# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Every upload answer must go through ``_upload_response()``.

``uploadprogress.js`` posts the upload forms over XHR and reads
``{"location": ...}`` out of the body to decide where to navigate. A client
that does not use the widget (JavaScript still loading, script blocked by an
extension, proxy or automation resubmitting the form) receives that same body
as the page document, so the user ends up staring at raw JSON on a blank page.

``_upload_response()`` keeps the JSON for XHR callers and falls back to a plain
redirect otherwise. These tests pin down that no upload path builds the JSON
body on its own again.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EDITBOOKS = REPO_ROOT / "cps" / "editbooks.py"

# A response body the upload widget understands: {"location": ...} as JSON.
UPLOAD_JSON = re.compile(r"Response\(\s*json\.dumps\(\s*\{\s*['\"]location['\"]")


def _source():
    return EDITBOOKS.read_text(encoding="utf-8")


def _helper_body(source):
    start = source.index("def _upload_response")
    end = source.index("def upload_required")
    return source[start:end]


@pytest.mark.unit
def test_helper_is_the_only_producer_of_the_location_body():
    source = _source()
    helper = _helper_body(source)
    assert "json.dumps({'location': target})" in helper

    assert not UPLOAD_JSON.search(source.replace(helper, ""))


@pytest.mark.unit
def test_helper_negotiates_on_the_xhr_header():
    helper = _helper_body(_source())
    assert "X-Requested-With" in helper
    assert "xmlhttprequest" in helper
    assert "redirect(target)" in helper


@pytest.mark.unit
def test_all_upload_paths_use_the_helper():
    source = _source()
    # upload(), the format branch of edit_book() and file_handling_on_upload()
    # return ten, one and four answers respectively.
    assert source.count("_upload_response(") >= 15
