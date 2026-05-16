# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pin the templates and the Jinja-filter registration that close stored XSS via
the book-comment rendering path.

Upstream `janeczku/calibre-web` PR #3625 (@jvoisin) flagged that custom columns
of type ``comments`` were rendered with ``|safe`` but no sanitisation. The same
template idiom appears in our CWA-derived base on both the custom-column path
*and* the regular ``entry.comments[0].text`` path, in both ``detail.html`` and
``listenmp3.html``. Without ``clean_string`` upstream of ``|safe``, any user
with edit permission on a book (or a Calibre import containing crafted comment
HTML) can store ``<script>alert(document.cookie)</script>`` and execute it for
every viewer of the detail page or the listen-mp3 modal.

These tests source-pin three invariants:

1. ``cps.jinjia`` registers ``clean_string`` as an ``app_template_filter`` so
   templates can use ``|clean_string|safe``.
2. The four known vulnerable template lines render their comment values through
   ``clean_string`` before applying ``|safe``.
3. ``clean_string`` itself strips a representative XSS payload set (no
   regression in the sanitiser's behaviour while we extend its reach).
"""

import ast
import os
import re
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO_ROOT)


TEMPLATES_DIR = os.path.join(REPO_ROOT, 'cps', 'templates')


def _read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


# --- 1) clean_string is registered as a Jinja app_template_filter ---


def test_jinjia_module_registers_clean_string_filter():
    """``cps.jinjia`` must register ``clean_string`` as an app_template_filter.

    Without this, the ``|clean_string|safe`` template idiom raises
    ``TemplateAssertionError: No filter named 'clean_string'`` at first render.
    """
    src = _read(os.path.join(REPO_ROOT, 'cps', 'jinjia.py'))
    tree = ast.parse(src)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            attr = getattr(func, 'attr', None)
            if attr != 'app_template_filter':
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) \
                    and dec.args[0].value == 'clean_string':
                found = True
                break
        if found:
            break

    assert found, (
        "cps/jinjia.py must register a Jinja filter named 'clean_string' so "
        "that book-comment templates can sanitise user-controlled HTML before "
        "applying |safe."
    )


def test_jinjia_clean_string_filter_imports_real_sanitiser():
    """The registered filter must wrap ``cps.clean_html.clean_string`` (not a
    stub) so the actual bleach/nh3 sanitiser runs at render time."""
    src = _read(os.path.join(REPO_ROOT, 'cps', 'jinjia.py'))
    # Either `from .clean_html import clean_string` or `from cps.clean_html ...`
    pattern = re.compile(
        r"from\s+\.?(?:cps\.)?clean_html\s+import\s+(?:[\w,\s]+,\s*)?clean_string"
    )
    assert pattern.search(src), (
        "cps/jinjia.py must `from .clean_html import clean_string` so the "
        "registered Jinja filter delegates to the real sanitiser."
    )


# --- 2) the four vulnerable template lines now use |clean_string|safe ---


# Each entry: (template path, regex describing the FIXED line).
# Regex is anchored on the right-hand side ("clean_string|safe") so any
# template re-layout (whitespace, attribute order, etc.) still passes.
_FIXED_LINES = [
    (
        'detail.html',
        r"\{\{\s*column\.value\s*\|\s*clean_string\s*\|\s*safe\s*\}\}",
        "detail.html custom-column comment must filter through clean_string",
    ),
    (
        'detail.html',
        r"\{\{\s*entry\.comments\[0\]\.text\s*\|\s*clean_string\s*\|\s*safe\s*\}\}",
        "detail.html book-comment text must filter through clean_string",
    ),
    (
        'listenmp3.html',
        r"\{\{\s*column\.value\s*\|\s*clean_string\s*\|\s*safe\s*\}\}",
        "listenmp3.html custom-column comment must filter through clean_string",
    ),
    (
        'listenmp3.html',
        r"\{\{\s*entry\.comments\[0\]\.text\s*\|\s*clean_string\s*\|\s*safe\s*\}\}",
        "listenmp3.html book-comment text must filter through clean_string",
    ),
]


@pytest.mark.parametrize("template,pattern,message", _FIXED_LINES)
def test_vulnerable_comment_lines_pass_through_clean_string(template, pattern, message):
    src = _read(os.path.join(TEMPLATES_DIR, template))
    assert re.search(pattern, src), message


# --- 3) clean_string strips a representative XSS payload set ---


@pytest.fixture(scope='module')
def clean_string_fn():
    try:
        from cps.clean_html import clean_string
    except Exception as exc:
        pytest.skip(f"cps.clean_html not importable in this env: {exc}")
    return clean_string


@pytest.mark.parametrize("payload,fragments_that_must_disappear", [
    # Disallowed tags get HTML-entity-escaped by bleach (e.g. <script> → &lt;script&gt;),
    # which is equally safe — the browser never parses them as live HTML. We pin
    # the live-form ("<script", with raw `<`) is gone; escaped text is fine.
    ("<script>alert(1)</script>", ["<script"]),
    ("<img src=x onerror=alert(1)>", ["<img"]),
    ('<a href="javascript:alert(1)">x</a>', ["javascript:"]),
    ("<svg/onload=alert(1)>", ["<svg"]),
    # `<b>` is in ALLOWED_TAGS, so bleach KEEPS the tag and strips just the
    # event-handler attribute. Check `onclick` is truly gone from output.
    ('<b onclick="alert(1)">hi</b>', ["onclick"]),
    ("<iframe src=javascript:alert(1)></iframe>", ["<iframe"]),
])
def test_clean_string_strips_xss_vectors(clean_string_fn, payload, fragments_that_must_disappear):
    """Behavioural pin: every common XSS vector loses its dangerous fragment
    after passing through clean_string. Escaped (`&lt;script&gt;`) is fine —
    the rendered text just must not contain a live `<script` tag, an `onerror`
    attribute, or a `javascript:` protocol."""
    out = clean_string_fn(payload)
    for frag in fragments_that_must_disappear:
        assert frag not in out, (
            f"clean_string must strip {frag!r} from {payload!r}, "
            f"got {out!r}"
        )


def test_clean_string_preserves_benign_html(clean_string_fn):
    """Sanitiser must not regress on legitimate book-comment markup."""
    payload = "<p>A <b>great</b> book about <i>cats</i>.</p>"
    out = clean_string_fn(payload)
    # All tags should be preserved (clean_string allows p, b, i via ALLOWED_TAGS)
    assert "<p>" in out
    assert "<b>" in out
    assert "<i>" in out
    assert "great" in out
    assert "cats" in out
