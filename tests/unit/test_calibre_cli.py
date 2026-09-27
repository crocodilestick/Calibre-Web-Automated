# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from types import SimpleNamespace

import pytest

from cps.calibre_cli import get_calibre_cli_context


pytestmark = pytest.mark.unit


def test_split_library_uses_books_root_and_database_override(monkeypatch):
    config = SimpleNamespace(
        get_book_path=lambda: "/books",
        config_calibre_split=True,
        config_calibre_dir="/calibre-library",
    )
    monkeypatch.setenv("CWA_TEST_ENV", "preserved")

    library_path, calibre_env = get_calibre_cli_context(config)

    assert library_path == "/books"
    assert calibre_env["CALIBRE_OVERRIDE_DATABASE_PATH"] == "/calibre-library/metadata.db"
    assert calibre_env["CWA_TEST_ENV"] == "preserved"
    assert calibre_env is not os.environ


def test_combined_library_does_not_override_database_path(monkeypatch):
    config = SimpleNamespace(
        get_book_path=lambda: "/calibre-library",
        config_calibre_split=False,
        config_calibre_dir="/calibre-library",
    )
    monkeypatch.delenv("CALIBRE_OVERRIDE_DATABASE_PATH", raising=False)

    library_path, calibre_env = get_calibre_cli_context(config)

    assert library_path == "/calibre-library"
    assert "CALIBRE_OVERRIDE_DATABASE_PATH" not in calibre_env
