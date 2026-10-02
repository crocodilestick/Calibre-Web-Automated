# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from cps import editbooks


NAME_MAX = 80
PROCESSOR_MAX = 150


def _get_path(filename, prefix_parts, pathconf: Any = NAME_MAX):
    uploaded_file = Mock(filename=filename)
    pathconf_patch = (
        patch.object(editbooks.os, "pathconf", side_effect=pathconf)
        if isinstance(pathconf, BaseException)
        else patch.object(editbooks.os, "pathconf", return_value=pathconf)
    )
    with (
        patch.object(editbooks, "get_ingest_dir", return_value="/ingest"),
        patch.object(editbooks.os, "makedirs"),
        patch.object(editbooks.os, "chown"),
        patch.object(editbooks, "_ensure_ingest_dir_writable"),
        pathconf_patch,
    ):
        return editbooks._get_ingest_path(uploaded_file, prefix_parts=prefix_parts)


@pytest.mark.unit
def test_long_new_book_name_reserves_longest_sidecar_and_processor_budget():
    final_path = _get_path("a" * 300 + ".epub", ["new", 7])
    final_name = os.path.basename(final_path)

    assert final_name.startswith("new_7_")
    assert final_name.endswith(".epub")
    assert len(final_name) == NAME_MAX - len(".cwa.failed.json")
    assert len((final_name + ".cwa.failed.json").encode("utf-8")) == NAME_MAX
    assert final_path + ".cwa.json" == os.path.join("/ingest", final_name + ".cwa.json")


@pytest.mark.unit
def test_long_format_name_preserves_utf8_and_associates_manifest():
    filename = "é" * 200 + ".pdf"
    with patch.object(editbooks, "secure_filename", return_value=filename):
        final_path = _get_path(filename, ["format", 42])
    final_name = os.path.basename(final_path)

    assert final_name.startswith("format_42_")
    assert final_name.endswith(".pdf")
    assert "é" in final_name
    assert "�" not in final_name
    assert len((final_name + ".cwa.failed.json").encode("utf-8")) <= NAME_MAX
    assert Path(final_path + ".cwa.json").name == final_name + ".cwa.json"


@pytest.mark.unit
def test_short_name_is_exactly_preserved_after_new_book_prefix():
    final_name = os.path.basename(_get_path("short.epub", ["new", 7]))

    assert final_name.endswith("_short.epub")
    assert final_name.count("short") == 1


@pytest.mark.unit
def test_invalid_pathconf_values_use_documented_posix_fallback():
    for invalid in (OSError("no pathconf"), 0, -1, None, "not-a-number"):
        assert _get_name_max(invalid) == 255


def _get_name_max(pathconf):
    with patch.object(
        editbooks.os,
        "pathconf",
        side_effect=pathconf if isinstance(pathconf, BaseException) else None,
        return_value=pathconf if not isinstance(pathconf, BaseException) else None,
    ):
        return editbooks._get_ingest_name_max("/ingest")


@pytest.mark.unit
def test_fallback_name_max_fits_all_sidecars_and_processor_budget():
    final_name = os.path.basename(
        _get_path("a" * 500 + ".epub", ["new", 7], pathconf=OSError())
    )

    assert len(final_name) == PROCESSOR_MAX
    for suffix in (".uploading", ".cwa.json", ".cwa.failed.json"):
        assert len((final_name + suffix).encode("utf-8")) <= 255


@pytest.mark.unit
def test_name_max_smaller_than_fixed_components_raises_clear_error():
    with pytest.raises(ValueError, match="fixed components"):
        _get_path("book.epub", ["x" * 100], pathconf=20)


@pytest.mark.unit
def test_multibyte_prefix_extension_and_empty_stem_fit_budgets():
    with patch.object(editbooks, "secure_filename", return_value=".é"):
        final_name = os.path.basename(_get_path("ignored", ["前"], pathconf=80))

    assert final_name.endswith(".é")
    assert len(final_name) <= PROCESSOR_MAX
    assert len((final_name + ".cwa.failed.json").encode("utf-8")) <= NAME_MAX


@pytest.mark.unit
def test_real_temp_and_manifest_paths_fit_name_limit(tmp_path):
    with (
        patch.object(editbooks, "get_ingest_dir", return_value=str(tmp_path)),
        patch.object(editbooks.os, "pathconf", return_value=NAME_MAX),
    ):
        final_path = editbooks._get_ingest_path(
            Mock(filename="a" * 300 + ".epub"), prefix_parts=["format", 42]
        )

    final_name = Path(final_path).name
    for suffix in (".uploading", ".cwa.json", ".cwa.failed.json"):
        assert len((final_name + suffix).encode()) <= NAME_MAX
    assert len(final_name) <= PROCESSOR_MAX
