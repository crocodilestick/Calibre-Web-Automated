# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Cancelling Convert Library must clean up its own files, not ingest's."""

import pytest

from cps import cwa_functions

pytestmark = pytest.mark.unit


def test_cancel_cleanup_removes_only_convert_library_dirs(tmp_path):
    shared = tmp_path / ".cwa_conversion_tmp"
    shared.mkdir()
    (shared / "ingest.epub").write_text("x", encoding="utf-8")
    mine = tmp_path / ".cwa_convert_library_abc123"
    mine.mkdir()
    (mine / "half.epub").write_text("x", encoding="utf-8")

    cwa_functions.remove_convert_library_tmp_dirs(str(shared) + "/")

    assert not mine.exists()
    assert (shared / "ingest.epub").exists()
