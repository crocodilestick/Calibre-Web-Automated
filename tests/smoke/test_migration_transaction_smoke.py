#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Smoke test for migration DDL transaction handling.

This is a static test to ensure the migration helper avoids nested
transactions that break under SQLAlchemy 2.x autobegin behavior.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

project_root = Path(__file__).parent.parent.parent


def _extract_function_body(text: str, func_name: str) -> str:
    marker = f"def {func_name}"
    start = text.find(marker)
    assert start != -1, f"{func_name} not found"
    rest = text[start:]
    # Find the next top-level def after this function.
    next_def = rest.find("\ndef ", len(marker))
    if next_def == -1:
        return rest
    return rest[:next_def]


def test_run_ddl_helper_avoids_nested_begin():
    ub_file = project_root / "cps" / "ub.py"
    content = ub_file.read_text(encoding="utf-8")
    body = _extract_function_body(content, "_run_ddl_with_retry")

    # Expect engine.begin() usage and avoid conn.begin() after PRAGMA execution.
    assert "engine.begin()" in body
    assert "conn.begin()" not in body


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])
