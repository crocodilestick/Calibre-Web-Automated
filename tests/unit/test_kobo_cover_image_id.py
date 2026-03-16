# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo cover cache-busting helpers."""

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import uuid as uuidlib

import pytest


def _load_cover_cache_module():
    module_path = Path(__file__).resolve().parents[2] / "cps" / "kobo_cover_cache.py"
    spec = importlib.util.spec_from_file_location("kobo_cover_cache", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kobo_cache = _load_cover_cache_module()


@pytest.mark.unit
class TestKoboCoverImageId:
    def test_normalize_cover_uuid_keeps_plain_uuid(self):
        value = str(uuidlib.uuid4())
        assert kobo_cache.normalize_cover_uuid(value) == value

    def test_normalize_cover_uuid_strips_numeric_suffix(self):
        base = str(uuidlib.uuid4())
        value = f"{base}-1700000000"
        assert kobo_cache.normalize_cover_uuid(value) == base

    def test_normalize_cover_uuid_ignores_non_numeric_suffix(self):
        base = str(uuidlib.uuid4())
        value = f"{base}-notanumber"
        assert kobo_cache.normalize_cover_uuid(value) == value

    def test_cover_image_id_uses_mtime_when_local_cover_exists(self, tmp_path):
        book_uuid = uuidlib.uuid4()
        cover_dir = tmp_path / "Author" / "Title"
        cover_dir.mkdir(parents=True, exist_ok=True)
        cover_file = cover_dir / "cover.jpg"
        cover_file.write_bytes(b"test")

        mtime = 1700000123
        os.utime(cover_file, (mtime, mtime))

        expected = f"{book_uuid}-{mtime}"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=False,
            last_modified=None,
            cover_path=str(cover_file),
        ) == expected

    def test_cover_image_id_falls_back_without_cover(self, tmp_path):
        book_uuid = uuidlib.uuid4()
        cover_path = tmp_path / "Missing" / "Cover" / "cover.jpg"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=False,
            last_modified=None,
            cover_path=str(cover_path),
        ) == str(book_uuid)

    def test_cover_image_id_uses_last_modified_on_gdrive(self):
        book_uuid = uuidlib.uuid4()
        last_modified = datetime(2026, 2, 5, 12, 30, 0, tzinfo=timezone.utc)
        expected = f"{book_uuid}-{int(last_modified.timestamp())}"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=True,
            last_modified=last_modified,
            cover_path=None,
        ) == expected
