# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the mobile-Safari CSRF backport from CWA #1295.

Mobile Safari does not reliably send the `X-CSRFToken` request header for fetch()
calls, which broke metadata search (fork issue #154, upstream CWA #1266). The
upstream fix introduces a shared `cwaFetch()` helper in layout.html that auto-
attaches `X-CSRFToken` for non-safe HTTP methods, hardens the legacy
`$.ajaxSetup` prefilter against an empty initial token lookup, and converts the
existing fetch() call sites to go through the wrapper.

Tests are pattern-pins on the static assets — JS is not unit-test-able in Python
without spinning a Node runtime, but a regression here would be a quiet drop of
one of the wrapper definitions or an accidental revert of a call site.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUT = REPO_ROOT / "cps" / "templates" / "layout.html"
MAIN_JS = REPO_ROOT / "cps" / "static" / "js" / "main.js"
GET_META_JS = REPO_ROOT / "cps" / "static" / "js" / "get_meta.js"
CONVERT_LIBRARY_TPL = REPO_ROOT / "cps" / "templates" / "cwa_convert_library.html"
EPUB_FIXER_TPL = REPO_ROOT / "cps" / "templates" / "cwa_epub_fixer.html"


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def test_layout_defines_getCsrfToken_helper():
    body = _read(LAYOUT)
    assert "function getCsrfToken()" in body, (
        "layout.html must define getCsrfToken() so cwaFetch can look up the token"
    )
    assert "input[name='csrf_token']" in body, (
        "getCsrfToken must query the csrf_token hidden input"
    )


def test_layout_defines_cwaFetch_wrapper_with_csrf_for_mutating_methods():
    body = _read(LAYOUT)
    assert "function cwaFetch(" in body, "layout.html must define cwaFetch()"
    # The wrapper must skip safe methods (GET/HEAD/OPTIONS/TRACE) and set the
    # X-CSRFToken header on the rest. Pattern-match the guard list and the
    # header set so an accidental change to either side will trip the test.
    safe_guard = re.search(
        r'\[\s*"GET"\s*,\s*"HEAD"\s*,\s*"OPTIONS"\s*,\s*"TRACE"\s*\]',
        body,
    )
    assert safe_guard, "cwaFetch must guard safe methods explicitly"
    assert 'headers.set("X-CSRFToken", csrfToken)' in body, (
        "cwaFetch must set X-CSRFToken on non-safe methods"
    )


def test_layout_cwaFetch_only_attaches_header_when_token_present():
    body = _read(LAYOUT)
    # `if (csrfToken && !headers.has("X-CSRFToken"))` — both clauses required:
    # mobile Safari may return an empty string from the input, and we should
    # not blow away a header the caller already set.
    assert re.search(
        r'if \(csrfToken && !headers\.has\("X-CSRFToken"\)\)', body
    ), "cwaFetch must null-guard the token AND respect a caller-set header"


def test_main_js_ajaxsetup_csrf_looks_up_token_per_request():
    body = _read(MAIN_JS)
    # Pre-fix had `var csrftoken = $("input[name='csrf_token']").val();` cached
    # at $(function() { ... }) page-load time, which loses the token if the
    # input ever rotates. Fix moves the lookup inside the beforeSend handler
    # and adds a null guard for the same Safari empty-string scenario.
    assert "$.ajaxSetup({" in body, "ajaxSetup must be configured"
    setup_block_match = re.search(
        r"\$\.ajaxSetup\(\{(.*?)\}\);", body, flags=re.DOTALL
    )
    assert setup_block_match, "ajaxSetup block must be present"
    setup_block = setup_block_match.group(1)
    assert (
        'var csrftoken = $("input[name=\'csrf_token\']").first().val();'
        in setup_block
    ), "csrftoken lookup must happen inside beforeSend (per-request, not page-load)"
    assert "if (csrftoken) {" in setup_block, (
        "ajaxSetup must null-guard csrftoken before setting the header"
    )


def test_get_meta_js_metadata_search_posts_csrf_token_in_body():
    body = _read(GET_META_JS)
    # The original mobile-Safari symptom: /metadata/search POST never carried
    # the CSRF token because the header was dropped. Fix puts it in the body
    # so the server's CSRF check passes regardless of header behavior.
    assert re.search(
        r'csrf_token:\s*\$\("input\[name=\'csrf_token\'\]"\)\.first\(\)\.val\(\)',
        body,
    ), "metadata/search POST must include csrf_token in the request body"


def test_callsites_use_cwaFetch_instead_of_raw_fetch():
    for path in (CONVERT_LIBRARY_TPL, EPUB_FIXER_TPL):
        body = _read(path)
        # Each template should route its mutating fetch() through cwaFetch().
        # We look for at least one cwaFetch call; the file may still contain
        # a raw fetch() for download links or other GETs, so we do not assert
        # absence — only presence of the wrapped call.
        assert "cwaFetch(" in body, (
            f"{path.name} must route fetch() through cwaFetch() for CSRF coverage"
        )
