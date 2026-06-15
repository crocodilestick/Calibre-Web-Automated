# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork #323 (@olskar): admin-set custom CSS injection.

The feature adds a `config_custom_css` setting that is injected as the last
stylesheet in `layout.html`'s <head> (so it overrides the shipped themes).
Because it is rendered raw (`|safe`) -- HTML-escaping would mangle valid CSS
like the `>` child combinator -- the security-critical invariant is that the
value can never close the RAWTEXT <style> element. `render_template._style_safe_css`
enforces that by neutralizing every `</` to `<\/`.

These tests:
  * exercise the REAL `_style_safe_css` source (AST-extracted, no Flask import)
    so the breakout guard can't be silently removed;
  * source-pin every wiring site (column, migration, save, textarea, render).
"""

import ast
import os
import re

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CPS = os.path.join(REPO_ROOT, "cps")


def _read(*parts):
    with open(os.path.join(CPS, *parts), encoding="utf-8") as fh:
        return fh.read()


def _load_style_safe_css():
    """Extract `_style_safe_css` from render_template.py and exec it standalone.

    Avoids importing the whole Flask app while still testing the real code:
    if the function is removed or its breakout guard is dropped, this fails.
    """
    src = _read("render_template.py")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_style_safe_css":
            module = ast.Module(body=[node], type_ignores=[])
            namespace = {}
            exec(compile(module, "<render_template:_style_safe_css>", "exec"), namespace)
            return namespace["_style_safe_css"]
    raise AssertionError("_style_safe_css not found in render_template.py")


style_safe_css = _load_style_safe_css()


# --- Behavioral: the breakout guard (security-critical) -----------------------

@pytest.mark.parametrize("payload", [
    "body{}</style><script>alert(1)</script>",
    ".x{}</STYLE><img src=x onerror=alert(1)>",
    "</style >",
    "a{}</\nstyle>",
])
def test_breakout_sequences_cannot_close_style_element(payload):
    out = style_safe_css(payload)
    # No literal `</` survives, so the HTML parser can never see `</style` and
    # close the RAWTEXT element early. Case-insensitive defense.
    assert "</" not in out
    assert "</style" not in out.lower()


def test_valid_css_is_left_untouched():
    # `>` child combinator, comments, url() paths, media queries: none contain
    # `</`, so legitimate CSS must pass through byte-for-byte.
    css = (
        ".navbar > .brand { color: #2b2b2b; }\n"
        "/* tweak */ .grid { background: url(/static/x.png); }\n"
        "@media (max-width: 600px) { .book + .book { margin: 0; } }"
    )
    assert style_safe_css(css) == css


def test_empty_and_none_collapse_to_empty_string():
    # The layout guard is `{% if custom_css %}`; falsy input must stay falsy.
    assert style_safe_css("") == ""
    assert style_safe_css(None) == ""


def test_neutralized_slash_renders_as_real_slash_in_css():
    # `<\/` keeps the original glyphs recoverable: inside a CSS string `\/` is
    # an escaped `/`, so the only place `</` could legitimately appear (never,
    # in practice) still round-trips visually.
    assert style_safe_css("content:'</'") == "content:'<\\/'"


# --- Source-pins: every wiring site must stay connected -----------------------

def test_column_declared_with_empty_default():
    src = _read("config_sql.py")
    assert re.search(
        r"config_custom_css\s*=\s*Column\(String,\s*default=\"\"\)", src
    ), "config_custom_css column missing or wrong default on _Settings"


def test_defensive_migration_present():
    src = _read("ub.py")
    assert "config_custom_css" in src
    assert "ALTER TABLE settings ADD column 'config_custom_css'" in src


def test_admin_save_handler_present():
    src = _read("admin.py")
    assert '_config_string(to_save, "config_custom_css")' in src


def test_config_view_edit_template_has_textarea():
    # Fork #463: the Custom CSS field lives on the UI Configuration page
    # (config_view_edit.html), not the Basic Configuration page.
    src = _read("templates", "config_view_edit.html")
    assert 'name="config_custom_css"' in src
    assert "<textarea" in src  # free-text multiline, not a single-line input


def test_render_template_uses_style_safe_helper():
    src = _read("render_template.py")
    # The kwarg must flow through the guard, not bypass it with a raw getattr.
    assert re.search(
        r"custom_css=_style_safe_css\(getattr\(config,\s*'config_custom_css'", src
    ), "custom_css must be passed through _style_safe_css"


def test_layout_renders_raw_in_a_style_element_under_a_guard():
    src = _read("templates", "layout.html")
    # Rendered raw (|safe) so CSS isn't entity-mangled...
    assert "{{ custom_css|safe }}" in src
    # ...inside a <style> element...
    assert re.search(r"<style[^>]*>\{\{ custom_css\|safe \}\}</style>", src)
    # ...and only when set (keeps an empty <style> out of every page).
    assert "{% if custom_css %}" in src
    # Guard against a regression that drops |safe (which would HTML-escape CSS).
    assert "{{ custom_css }}" not in src
