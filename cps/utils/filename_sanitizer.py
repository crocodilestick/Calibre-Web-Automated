# -*- coding: utf-8 -*-
# Shared filename sanitizer to mirror Calibre‑Web's behavior
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Optional

try:
    import unidecode  # type: ignore
except Exception:  # pragma: no cover
    unidecode = None  # will gate usage below

# Same regex as cps/string_helper.strip_whitespaces
_ZW_TRIM_RE = re.compile(r"(^[\s\u200B-\u200D\ufeff]+)|([\s\u200B-\u200D\ufeff]+$)")


def strip_whitespaces(text: str) -> str:
    return _ZW_TRIM_RE.sub("", text)


def get_valid_filename_shared(value: str,
                               replace_whitespace: bool = True,
                               chars: int = 128,
                               unicode_filename: bool = False) -> str:
    """Mirror cps.helper.get_valid_filename but without relying on CPS config.
    - unicode_filename: if True, transliterate using unidecode to ASCII.
    - chars: max length in UTF-8 safe truncation.
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""

    if value[-1:] == '.':
        value = value[:-1] + '_'

    value = value.replace("/", "_").replace(":", "_").strip('\0')

    if unicode_filename and unidecode is not None:
        value = unidecode.unidecode(value)

    if replace_whitespace:
        #  *+:\"/<>? are replaced by _
        value = re.sub(r'[*+:\\\"/<>?]+', '_', value, flags=re.U)
        # pipe has to be replaced with comma
        value = re.sub(r'[|]+', ',', value, flags=re.U)

    # utf-8 safe trimming
    value = strip_whitespaces(value.encode('utf-8')[:chars].decode('utf-8', errors='ignore'))

    if not value:
        raise ValueError("Filename cannot be empty")
    return value
