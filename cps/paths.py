# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
"""Centralized repository path helpers.

Provides resolved paths for resources that were previously hard-coded to
/app/calibre-web-automated so the project can be relocated transparently.
"""
from __future__ import annotations
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DIRS_JSON: Path = REPO_ROOT / "dirs.json"
CHANGE_LOGS_DIR: Path = REPO_ROOT / "metadata_change_logs"
METADATA_TEMP_DIR: Path = REPO_ROOT / "metadata_temp"

RUNTIME_DIRS = (CHANGE_LOGS_DIR, METADATA_TEMP_DIR)

def ensure_runtime_dirs() -> None:
    for p in RUNTIME_DIRS:
        p.mkdir(parents=True, exist_ok=True)
