# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Timestamps written with a "+00:00" suffix must be real UTC.

datetime.now() is local time; formatting it with a hard-coded +00:00 labels local
wall-clock time as UTC. In containers with a non-UTC TZ that put newly imported
books hours off in "date added", so they sorted below older books (#1563).
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# now() with no timezone argument, formatted with a literal +00:00 offset
NAIVE_NOW_AS_UTC = re.compile(r"\bnow\(\s*\)\s*\.strftime\([^)]*\+00:00")


@pytest.mark.parametrize("folder", ["cps", "scripts"])
def test_no_local_time_is_labelled_utc(folder):
    offenders = []
    for path in (REPO_ROOT / folder).rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if NAIVE_NOW_AS_UTC.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "local time formatted as UTC:\n" + "\n".join(offenders)
