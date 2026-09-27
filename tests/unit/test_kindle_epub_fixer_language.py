# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import pytest

from kindle_epub_fixer import EPUBFixer

pytestmark = pytest.mark.unit

CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
    '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
    '</rootfiles></container>'
)


def _opf(lang):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:language>{lang}</dc:language></metadata></package>'
    )


def _fixer(opf):
    # Bypass __init__ (which builds a CWA_DB) the same way the other unit tests use object.__new__.
    fixer = object.__new__(EPUBFixer)
    fixer.files = {'META-INF/container.xml': CONTAINER, 'content.opf': opf}
    fixer.fixed_problems = []
    fixer.aggressive_mode = False
    fixer.manually_triggered = False
    return fixer


def test_bibliographic_language_code_converted_to_terminological():
    # 'fre' is the ISO 639-2/B code for French; calibre's canonicalize_lang() discards it, so the
    # imported book goes invisible (#1495). The fixer must emit the terminological code 'fra'.
    fixer = _fixer(_opf('fre'))
    fixer.fix_book_language()
    assert '<dc:language>fra</dc:language>' in fixer.files['content.opf']
    assert 'fre' not in fixer.files['content.opf']
    problems = " ".join(fixer.fixed_problems)
    assert "to 'fra'" in problems  # the conversion is reported
    assert "case standardization" not in problems  # and not mislabelled as a case fix


def test_terminological_and_two_letter_codes_are_left_alone():
    for code in ('fra', 'de', 'en'):
        fixer = _fixer(_opf(code))
        fixer.fix_book_language()
        assert f'<dc:language>{code}</dc:language>' in fixer.files['content.opf']
