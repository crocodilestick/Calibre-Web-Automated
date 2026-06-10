# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #405 — the interactive metadata-search modal must present providers
in the user-configured hierarchy order, not alphabetically by class name.

Before this fix ``cps/search_metadata.py::metadata_search`` ended with
``provider_status.sort(key=lambda p: p["name"].lower())`` — alphabetical,
ignoring ``metadata_provider_hierarchy`` that the ingest auto-fetch in
``cps/metadata_helper.py`` obeys. A user who set a preferred order in
settings did not get that order in the search dialog.

``cps/search_metadata.py`` cannot be imported in the unit env (it pulls
``cwa_db`` which only exists in the container), so the ordering function is
extracted from source and exercised directly; the integration points are
source-pinned.
"""
from __future__ import annotations

import ast
import os

HERE = os.path.dirname(__file__)
SEARCH_META = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "search_metadata.py")
)


def _src():
    with open(SEARCH_META, encoding="utf-8") as fh:
        return fh.read()


def _load_func(name):
    """Extract a top-level function from search_metadata.py and exec it in an
    isolated namespace (the helpers under test depend only on stdlib)."""
    tree = ast.parse(_src())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            ns: dict = {}
            exec(compile(module, SEARCH_META, "exec"), ns)
            return ns[name]
    raise AssertionError(f"{name} not found in search_metadata.py")


def test_hierarchy_sort_key_orders_by_configured_then_alpha():
    key = _load_func("_hierarchy_sort_key")(["google", "openlibrary", "ibdb"])
    rows = [
        {"id": "douban", "name": "Douban"},
        {"id": "google", "name": "Google"},
        {"id": "amazon", "name": "Amazon"},
        {"id": "ibdb", "name": "iBDB"},
        {"id": "openlibrary", "name": "Open Library"},
    ]
    rows.sort(key=lambda p: key(p["id"], p["name"]))
    ids = [r["id"] for r in rows]
    # Configured providers in configured order first...
    assert ids[:3] == ["google", "openlibrary", "ibdb"]
    # ...then the unlisted ones, alphabetical by name (Amazon before Douban).
    assert ids[3:] == ["amazon", "douban"]


def test_hierarchy_sort_key_empty_hierarchy_is_alphabetical():
    key = _load_func("_hierarchy_sort_key")([])
    rows = [{"id": "zzz", "name": "Zed"}, {"id": "aaa", "name": "Alpha"}]
    rows.sort(key=lambda p: key(p["id"], p["name"]))
    assert [r["id"] for r in rows] == ["aaa", "zzz"]


def test_metadata_search_orders_provider_status_by_hierarchy():
    src = _src()
    # The old alphabetical-only sort must be gone.
    assert 'provider_status.sort(key=lambda p: p["name"].lower())' not in src
    # provider_status is ordered through the hierarchy key helper.
    assert "_hierarchy_sort_key(" in src
    assert "provider_status.sort(key=lambda p: _hkey(" in src


def test_metadata_search_orders_results_by_hierarchy():
    src = _src()
    # The flattened results are also reordered by provider hierarchy.
    assert "results.sort(key=lambda r:" in src
    assert '(r.get("source") or {}).get("id")' in src


def test_get_provider_hierarchy_helper_exists():
    src = _src()
    assert "def _get_provider_hierarchy(" in src
    # Falls back to the single-source-of-truth default constant on any error.
    assert "DEFAULT_METADATA_PROVIDER_HIERARCHY" in src
