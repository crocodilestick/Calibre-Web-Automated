# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""D6 regression tests — unicode + whitespace normalization in duplicate keys.

From the 2026-06 duplicate audit (notes/duplicate-detection-fix-plan.md §D6):
every keying surface normalized with only ``.lower().strip()``. An NFD 'Café'
(macOS filenames, some metadata sources) hashed differently from the NFC
'Café' a user typed, and 'The  Book' differed from 'The Book' — so genuine
duplicates were silently invisible to the scanner. NFC + internal-whitespace
collapse now applies on all three surfaces via one shared normalizer, and
NORMALIZATION_VERSION is bumped so the criteria fingerprint changes and the
index rebuilds (stale v1 keys would otherwise persist).

These run against the real functions (no stub world needed for the
normalizers themselves) by importing duplicates.py through the shared stub
harness, since cps imports Flask at package level.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import unicodedata
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
IDX_SRC = (REPO_ROOT / "cps" / "duplicate_index.py").read_text()


@pytest.fixture(autouse=True)
def _isolate_sys_modules():
    """Restore sys.modules after the stub harness (see D8 test for why)."""
    saved = sys.modules.copy()
    yield
    for name in list(sys.modules):
        if name not in saved:
            del sys.modules[name]
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module


@pytest.fixture()
def dup():
    path = _HERE / "test_duplicate_delete_index_maintenance.py"
    spec = importlib.util.spec_from_file_location("_dup_stub_harness", path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    module, _books, _calls = harness._load_duplicates_module([])
    return module


NFC = unicodedata.normalize("NFC", "Café")
NFD = unicodedata.normalize("NFD", "Café")


class TestD6GroupHash:
    def test_nfd_and_nfc_hash_identically(self, dup):
        assert dup.generate_group_hash(NFD, "x") == dup.generate_group_hash(NFC, "x"), (
            "NFD and NFC forms of the same title must produce the same group "
            "hash — otherwise real duplicates are invisible (D6)"
        )

    def test_internal_whitespace_collapses(self, dup):
        assert dup.generate_group_hash("The  Book", "x") == dup.generate_group_hash("The Book", "x")
        assert dup.generate_group_hash("The\tBook", "x") == dup.generate_group_hash("The Book", "x")

    def test_author_side_normalizes_too(self, dup):
        assert dup.generate_group_hash("t", NFD) == dup.generate_group_hash("t", NFC)


class TestD6TitleNormalization:
    def test_nfd_title_normalizes_to_nfc_form(self, dup):
        assert dup.normalize_title_for_duplicates(NFD) == dup.normalize_title_for_duplicates(NFC)

    def test_author_prefix_strip_survives_mixed_forms(self, dup):
        # Title carries an NFD author prefix, author arrives NFC — the strip
        # must still fire because both sides share the normalizer.
        title = unicodedata.normalize("NFD", "Café, the book")
        author = unicodedata.normalize("NFC", "Café")
        assert dup.normalize_title_for_duplicates(title, author) == "the book"

    def test_whitespace_collapse_in_title(self, dup):
        assert dup.normalize_title_for_duplicates("The   Republic") == "the republic"


class TestD6SharedNormalizer:
    def test_single_normalizer_exists(self, dup):
        assert hasattr(dup, "normalize_text_for_duplicates")
        assert dup.normalize_text_for_duplicates(" Á  B ") == \
            dup.normalize_text_for_duplicates(unicodedata.normalize("NFC", " Á  B "))

    def test_empty_values_fall_back_to_default(self, dup):
        assert dup.normalize_text_for_duplicates(None, default="untitled") == "untitled"
        assert dup.normalize_text_for_duplicates("", default="unknown") == "unknown"


class TestD6IndexSurface:
    def test_normalization_version_bumped(self):
        m = re.search(r'NORMALIZATION_VERSION = "([^"]+)"', IDX_SRC)
        assert m and m.group(1) != "duplicate-index-v1", (
            "NORMALIZATION_VERSION must be bumped with the normalization "
            "change so the criteria fingerprint rotates and the index "
            "rebuilds — stale v1 keys would otherwise persist (D6)"
        )

    def test_key_parts_route_through_shared_normalizer(self):
        m = re.search(r"def build_book_key_parts\(book, settings\):(.*?)\ndef ", IDX_SRC, re.S)
        assert m, "build_book_key_parts not found"
        body = m.group(1)
        assert body.count("normalize_text_for_duplicates(") >= 4, (
            "author/language/series/publisher key parts must use the shared "
            "normalizer so all keying surfaces agree (D6)"
        )
        assert ".lower().strip()" not in body, (
            "raw .lower().strip() must not survive in build_book_key_parts"
        )
