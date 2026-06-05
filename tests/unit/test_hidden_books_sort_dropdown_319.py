# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test for fork #319 sort-dropdown sub-bug.

@SethMilliken originally reported the per-user-hidden feature as
"broken and user-hostile". The broken-half (hidden books impossible to
recover) was fixed in v4.0.136/v4.0.140. @droM4X then surfaced a
follow-up: clicking the sort dropdown on the hidden-books page
dropped the user into an unfiltered library view instead of re-sorting
the hidden listing.

Root cause: ``render_hidden_books`` had to rename its page identifier
from "hidden" to "hidden_books" because Bootstrap's ``.hidden {
display: none !important }`` was being applied to ``<body class="{{
page }}">``, blanking the whole page. The ``_book_organizer.html``
sort dropdown builds URLs via ``url_for('web.books_list', data=page,
sort_param=...)``, so sort links became ``/hidden_books/<sort>``.
``books_list``'s match on ``data == "hidden"`` didn't recognize
``"hidden_books"``, so the request fell into the catch-all that
renders the full library with no hidden filter.

Fix: ``books_list`` now treats ``data in ("hidden", "hidden_books")``
as the same listing. Both URL shapes route to ``render_hidden_books``.
This pins both behaviors:

1. The page identifier in ``render_hidden_books`` stays the
   non-Bootstrap-colliding ``"hidden_books"`` (the v4.0.136 fix
   stays in).
2. ``books_list`` accepts both ``"hidden"`` and ``"hidden_books"`` as
   the route segment — the sort dropdown's URL works.
"""

import ast
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB_PY = REPO_ROOT / "cps" / "web.py"


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} function not found in {path}"
    return ast.unparse(fn)


def _data_string_literals_compared_against(path: pathlib.Path, fn_name: str) -> set:
    """Return the set of string literals compared against any `data` variable
    in the given function. Catches both `data == "hidden"` and
    `data in ("hidden", "hidden_books")` shapes without confusing the literal
    "hidden_books" with the identifier `render_hidden_books`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == fn_name),
        None,
    )
    assert fn is not None, f"{fn_name} not found"
    literals = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "data":
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and isinstance(right.value, str):
                    literals.add(right.value)
                elif isinstance(op, ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
                    for elt in right.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            literals.add(elt.value)
    return literals


@pytest.mark.unit
class TestHiddenBooksSortDropdown319:
    def test_render_books_list_accepts_hidden_books_alias(self):
        """The books_list dispatcher must compare ``data`` against both
        ``"hidden"`` and ``"hidden_books"``. The latter is what the sort
        dropdown builds because the page identifier is ``"hidden_books"``
        (Bootstrap CSS collision avoidance from v4.0.136)."""
        compared = _data_string_literals_compared_against(WEB_PY, "render_books_list")
        assert "hidden" in compared, (
            "render_books_list must compare data against the literal "
            "'hidden' (the canonical route segment)."
        )
        assert "hidden_books" in compared, (
            "render_books_list must compare data against the literal "
            "'hidden_books' too. Without it, the sort dropdown on the "
            "hidden-books page — which generates /hidden_books/<sort> "
            "URLs because page='hidden_books' in render_hidden_books — "
            "falls into the catch-all that renders the UNFILTERED "
            "library. That's the @droM4X follow-up regression in #319."
        )

    def test_render_hidden_books_keeps_non_colliding_page_identifier(self):
        """The v4.0.136 fix that renamed page from "hidden" to
        "hidden_books" must stay — reverting it would re-trigger the
        Bootstrap .hidden {display:none} blank-page bug. Pin the
        non-colliding identifier."""
        src = _function_source(WEB_PY, "render_hidden_books")
        assert '"hidden_books"' in src or "'hidden_books'" in src, (
            "render_hidden_books must keep the non-Bootstrap-colliding "
            "page identifier 'hidden_books'. Reverting to 'hidden' "
            "re-triggers the .hidden{display:none!important} CSS rule "
            "on <body class='{{ page }}'> and blanks the entire page "
            "(fork #319 v4.0.136 fix)."
        )

    def test_hidden_books_redirect_target_remains_hidden(self):
        """The bare /hidden URL redirect target should remain
        ``data="hidden"`` (the original/canonical segment). The alias
        adds compatibility for the sort dropdown's URL shape without
        forcing the redirect to change."""
        src = _function_source(WEB_PY, "hidden_books_redirect")
        assert 'data="hidden"' in src or "data='hidden'" in src, (
            "hidden_books_redirect should redirect to /hidden/stored "
            "(data='hidden', sort_param='stored') — the canonical URL "
            "form. The hidden_books alias exists in books_list to handle "
            "sort dropdown URLs but does not change the canonical "
            "redirect target."
        )


@pytest.mark.unit
class TestBooksListAliasShape:
    def test_both_route_segments_route_to_render_hidden_books(self):
        """Pin that the alias actually routes BOTH segments to the same
        handler. A future edit that recognizes 'hidden_books' but routes
        it to a different handler (e.g. the catch-all) would still
        regress the user-visible bug, so check that render_hidden_books
        is called from the branch that matches both."""
        tree = ast.parse(WEB_PY.read_text(encoding="utf-8"))
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "render_books_list"),
            None,
        )
        assert fn is not None

        # Walk if/elif branches; for each branch whose test compares data
        # against a string literal (==) or string-in-tuple, look at the
        # branch body for a render_hidden_books call.
        def _strings_in_test(test):
            out = set()
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "data":
                for op, right in zip(test.ops, test.comparators):
                    if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and isinstance(right.value, str):
                        out.add(right.value)
                    elif isinstance(op, ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
                        for elt in right.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                out.add(elt.value)
            return out

        def _calls_render_hidden_books(body):
            for node in ast.walk(ast.Module(body=body, type_ignores=[])):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "render_hidden_books"):
                    return True
            return False

        matched = set()
        # Walk the function looking at If nodes (and chained elif via orelse).
        stack = list(fn.body)
        while stack:
            node = stack.pop()
            if isinstance(node, ast.If):
                strs = _strings_in_test(node.test)
                if strs and _calls_render_hidden_books(node.body):
                    matched |= strs
                stack.extend(node.orelse)

        assert "hidden" in matched, (
            "An if/elif branch testing data=='hidden' (or 'hidden' in "
            "tuple) must call render_hidden_books. Found matched: "
            f"{sorted(matched)}."
        )
        assert "hidden_books" in matched, (
            "An if/elif branch testing data=='hidden_books' (or "
            "'hidden_books' in tuple) must call render_hidden_books. "
            "Without this, the sort dropdown URL /hidden_books/<sort> "
            "falls into the catch-all that renders the unfiltered "
            f"library (fork #319 droM4X follow-up). Matched: {sorted(matched)}."
        )
