# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cover_enforcer_retries_supported_file_scan_for_expected_formats():
    source = (PROJECT_ROOT / "scripts/cover_enforcer.py").read_text(encoding="utf-8")

    assert "def get_expected_supported_formats" in source
    assert "def get_supported_files_from_dir_with_retries" in source
    assert "expected_formats" in source
    assert "time.sleep(delay_seconds)" in source


def test_cover_enforcer_logs_directory_files_when_expected_format_missing():
    source = (PROJECT_ROOT / "scripts/cover_enforcer.py").read_text(encoding="utf-8")

    assert "Expected supported format(s)" in source
    assert "Files found in selected directory" in source
