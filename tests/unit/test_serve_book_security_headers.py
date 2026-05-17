# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for janeczku/calibre-web PR #3624 (jvoisin):
serve_book() must set three defense-in-depth response headers on the
send_from_directory path so book content cannot be MIME-sniffed into an
executable type or run inline scripts when rendered by the browser.

Source-pin test: parses cps/web.py and walks the serve_book AST to
confirm the three header assignments are present. A regression that
silently drops any of these headers fails this test.
"""

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_PY = REPO_ROOT / "cps" / "web.py"

REQUIRED_HEADERS = {
    "Content-Disposition": "inline",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "script-src 'none'; object-src 'none'",
}


def _serve_book_func():
    tree = ast.parse(WEB_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "serve_book":
            return node
    raise AssertionError("serve_book() not found in cps/web.py")


def _collect_header_assignments(func_node):
    """Yield (header_name, header_value_or_None) for every
    `response.headers['Header'] = value` in serve_book's body."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            sub_value = target.value
            if not (isinstance(sub_value, ast.Attribute) and sub_value.attr == "headers"):
                continue
            key_node = target.slice
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                val = node.value.value if isinstance(node.value, ast.Constant) else None
                yield key_node.value, val


@pytest.mark.unit
class TestServeBookSecurityHeaders:
    def test_all_three_security_headers_present(self):
        func = _serve_book_func()
        seen = {h for h, _ in _collect_header_assignments(func)}
        missing = set(REQUIRED_HEADERS) - seen
        assert not missing, (
            f"serve_book() is missing security headers: {sorted(missing)}. "
            "Backport from janeczku/calibre-web PR #3624 (jvoisin) requires "
            "Content-Disposition, X-Content-Type-Options, Content-Security-Policy."
        )

    @pytest.mark.parametrize("header,expected", sorted(REQUIRED_HEADERS.items()))
    def test_header_value_matches_upstream(self, header, expected):
        func = _serve_book_func()
        assignments = dict(_collect_header_assignments(func))
        assert assignments.get(header) == expected, (
            f"serve_book() sets {header!r} to {assignments.get(header)!r}, "
            f"expected {expected!r} per janeczku/calibre-web PR #3624."
        )

    def test_headers_attached_to_send_from_directory_response(self):
        """The headers must live on the PDF/generic path that uses
        send_from_directory, not on the EPUB-repair or TXT paths."""
        func_source = ast.get_source_segment(
            WEB_PY.read_text(encoding="utf-8"), _serve_book_func()
        )
        idx_send_from_dir = func_source.find("send_from_directory(")
        idx_csp = func_source.find("Content-Security-Policy")
        assert idx_send_from_dir > 0, "send_from_directory call missing in serve_book()"
        assert idx_csp > idx_send_from_dir, (
            "Content-Security-Policy header must be set on the response built "
            "from send_from_directory() inside serve_book(); it appears earlier instead."
        )
