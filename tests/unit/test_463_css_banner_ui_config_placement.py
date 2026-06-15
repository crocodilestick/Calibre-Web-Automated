# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test for fork issue #463 (@Andrew-H2O).

The "Custom CSS" (Fork #323) and "Server announcement banner" (Fork #225)
admin options were appended to the **Logfile Configuration** section of the
*Basic Configuration* page (``config_edit.html``), an unintuitive place that
also disagreed with the documentation — which says custom CSS lives under
*UI Configuration*. This pins them onto the *UI Configuration* page
(``config_view_edit.html`` / ``update_view_configuration``) so a future edit
can't quietly move them back next to the log-level dropdown.

Both halves matter and must stay in sync:
  * the form fields render on the UI-config template, not the basic one, and
  * the POST handler that persists them is ``update_view_configuration``,
    not ``_configuration_update_helper`` — otherwise saving one page would
    silently drop the value the other page shows.
"""

import ast
import os

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "cps", "templates")
ADMIN_PY = os.path.join(REPO_ROOT, "cps", "admin.py")

FIELD_NAMES = ('name="config_custom_css"', 'name="config_server_announcement"')
CONFIG_KEYS = ("config_custom_css", "config_server_announcement")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_source(tree, source, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"function {name!r} not found in admin.py")


@pytest.mark.unit
def test_fields_render_on_ui_config_page():
    body = _read(os.path.join(TEMPLATES_DIR, "config_view_edit.html"))
    for field in FIELD_NAMES:
        assert field in body, (
            f"{field} must render on the UI Configuration page "
            "(config_view_edit.html) per fork issue #463"
        )


@pytest.mark.unit
def test_fields_absent_from_basic_config_page():
    body = _read(os.path.join(TEMPLATES_DIR, "config_edit.html"))
    for field in FIELD_NAMES:
        assert field not in body, (
            f"{field} must NOT remain on the Basic Configuration page "
            "(config_edit.html) — fork issue #463 moved it to UI Configuration"
        )


@pytest.mark.unit
def test_ui_fields_use_conf_context_variable():
    """config_view_edit.html exposes the config object as ``conf`` (see
    ``render_title_template(..., conf=config)``), not ``config`` like the
    basic page. A blind copy that kept ``config.`` would render blank."""
    body = _read(os.path.join(TEMPLATES_DIR, "config_view_edit.html"))
    assert "conf.config_custom_css" in body
    assert "conf.config_server_announcement" in body
    assert "config.config_custom_css" not in body
    assert "config.config_server_announcement" not in body


@pytest.mark.unit
def test_ui_handler_persists_the_two_fields():
    source = _read(ADMIN_PY)
    tree = ast.parse(source)
    handler = _function_source(tree, source, "update_view_configuration")
    for key in CONFIG_KEYS:
        assert f'_config_string(to_save, "{key}")' in handler, (
            f"update_view_configuration must persist {key} (fork #463 move)"
        )


@pytest.mark.unit
def test_basic_handler_no_longer_persists_the_two_fields():
    source = _read(ADMIN_PY)
    tree = ast.parse(source)
    helper = _function_source(tree, source, "_configuration_update_helper")
    for key in CONFIG_KEYS:
        assert f'_config_string(to_save, "{key}")' not in helper, (
            f"_configuration_update_helper must NOT persist {key} after the "
            "fork #463 move — that would let a Basic Config save clobber the "
            "value the UI Config page now owns"
        )
