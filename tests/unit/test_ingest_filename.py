# -*- coding: utf-8 -*-
# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps.utils.filename_sanitizer.get_ingest_filename.

Regression coverage for non-ASCII uploads: ``werkzeug.utils.secure_filename``
keeps ASCII only, so "认知觉醒.epub" collapses to "epub" -- the extension is
dropped too, ingest cannot detect the format and silently discards the upload.
"""

import pytest

from cps.utils.filename_sanitizer import get_ingest_filename


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        # Non-ASCII titles survive with the extension intact.
        ("认知觉醒.epub", "认知觉醒.epub"),
        ("富足 (吴军) .epub", "富足 (吴军).epub"),
        ("日本語の本.epub", "日本語の本.epub"),
        ("Книга.epub", "Книга.epub"),
        # ASCII names are left alone.
        ("Thinking in Systems.epub", "Thinking in Systems.epub"),
        ("AI_Engineering.epub", "AI_Engineering.epub"),
        # Path components are stripped instead of being followed.
        ("../../etc/passwd.epub", "passwd.epub"),
        (r"..\..\windows\evil.epub", "evil.epub"),
        ("/tmp/dir/book.epub", "book.epub"),
        # Empty or whitespace-only input still yields a usable name.
        ("", "book"),
        (None, "book"),
        ("   ", "book"),
    ],
)
def test_get_ingest_filename(raw, expected):
    assert get_ingest_filename(raw) == expected


@pytest.mark.unit
def test_control_characters_are_removed():
    assert get_ingest_filename("bad\x00name\x1f.epub") == "badname.epub"


@pytest.mark.unit
def test_long_names_are_truncated_but_keep_the_extension():
    name = get_ingest_filename("长" * 200 + ".epub")

    assert name.endswith(".epub")
    assert len(name.encode("utf-8")) <= 180


@pytest.mark.unit
def test_cjk_title_keeps_its_extension():
    """The extension must survive, otherwise ingest rejects the file."""
    name = get_ingest_filename("聚合架构_面向数字生态的构件化企业架构_付晓岩.epub")

    assert name.endswith(".epub")
    assert name != "epub"
