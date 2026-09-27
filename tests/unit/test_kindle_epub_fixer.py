# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytestmark = pytest.mark.unit

project_root = Path(__file__).parent.parent.parent
scripts_dir = project_root / "scripts"
sys.path.insert(0, str(scripts_dir))

import kindle_epub_fixer
from kindle_epub_fixer import EPUBFixer


def _update_html_charset(content: str, target_encoding: str = "utf-8") -> str:
    fixer = EPUBFixer.__new__(EPUBFixer)
    return fixer._update_html_charset(content, target_encoding)


def _fix_html_entry(content: str) -> tuple[str, list[str]]:
    fixer = EPUBFixer.__new__(EPUBFixer)
    filename = "OPS/chapter.html"
    fixer.files = {filename: content}
    fixer.file_target_encodings = {filename: "utf-8"}
    fixer.fixed_problems = []

    fixer.fix_encoding()

    return fixer.files[filename], fixer.fixed_problems


def _assert_well_formed_xml(content: str) -> None:
    ElementTree.fromstring(content)


def test_constructor_acquires_fixer_lock(monkeypatch, tmp_path):
    class FakeCwaDb:
        cwa_settings = {"kindle_epub_fixer_aggressive": 0}

    lock_path = tmp_path / "kindle_epub_fixer.lock"
    monkeypatch.setattr(kindle_epub_fixer, "LOCK_FILE_PATH", str(lock_path))
    monkeypatch.setattr(kindle_epub_fixer, "lock_acquired", False)
    monkeypatch.setattr(kindle_epub_fixer, "CWA_DB", FakeCwaDb)

    EPUBFixer()

    assert lock_path.exists()
    assert kindle_epub_fixer.lock_acquired is True

    kindle_epub_fixer.removeLock()
    assert not lock_path.exists()
    assert kindle_epub_fixer.lock_acquired is False


def test_updates_http_equiv_charset_when_content_attribute_comes_first():
    content = (
        '<html><head><meta content="text/html; charset=WINDOWS-1252" '
        'http-equiv="Content-Type"/></head><body></body></html>'
    )

    updated = _update_html_charset(content)

    assert 'content="text/html; charset=utf-8"' in updated
    assert 'http-equiv="Content-Type"' in updated
    _assert_well_formed_xml(updated)


def test_replaces_html5_meta_charset_with_xhtml_compatible_meta():
    content = '<html><head><meta charset="windows-1252"></head><body></body></html>'

    updated = _update_html_charset(content)

    assert '<meta charset="utf-8">' not in updated
    assert '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />' in updated
    _assert_well_formed_xml(updated)


def test_inserts_xhtml_compatible_meta_inside_head():
    content = '<html><head></head><body></body></html>'

    updated = _update_html_charset(content)

    assert '<head>\n    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />' in updated
    _assert_well_formed_xml(updated)


def test_leaves_html_without_head_unchanged():
    content = '<html><body><p>No head element</p></body></html>'

    assert _update_html_charset(content) == content


def test_fix_encoding_keeps_html_named_epub_content_well_formed():
    content = (
        '<html><head><meta content="text/html; charset=WINDOWS-1252" '
        'http-equiv="Content-Type"/></head><body><p>Chapter</p></body></html>'
    )

    updated, fixed_problems = _fix_html_entry(content)

    assert fixed_problems == ["Updated HTML charset in OPS/chapter.html to utf-8"]
    assert 'content="text/html; charset=utf-8"' in updated
    _assert_well_formed_xml(updated)
