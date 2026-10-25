# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

# Shared filename sanitizer to mirror Calibre‑Web's behavior
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re
from typing import Optional

try:
    import unidecode  # type: ignore
except Exception:  # pragma: no cover
    unidecode = None  # will gate usage below

# Same regex as cps/string_helper.strip_whitespaces
_ZW_TRIM_RE = re.compile(r"(^[\s\u200B-\u200D\ufeff]+)|([\s\u200B-\u200D\ufeff]+$)")
# Control characters are never valid in a path component.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


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


def get_ingest_filename(filename: str) -> str:
    """Return a filesystem-safe basename for files queued into the ingest dir.

    ``werkzeug.utils.secure_filename`` keeps ASCII characters only, so a purely
    CJK (or Cyrillic, Greek, ...) title such as "认知觉醒.epub" collapses to
    "epub" -- the extension is dropped as well. Ingest then cannot detect the
    format, logs "is currently unsupported / is not a known ebook format" and
    discards the upload without keeping a copy.

    Ingest and its directory watcher are UTF-8 safe, so keep the original name
    instead and only neutralise path components, control characters and an
    over-long name. The extension is always preserved as ingest relies on it to
    detect the format.
    """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(name)
    stem = _CONTROL_CHARS_RE.sub("", stem).strip().strip(".")
    ext = _CONTROL_CHARS_RE.sub("", ext).strip()
    if not stem:
        stem = "book"
    # Keep the result within the 255-byte limit of common filesystems while
    # leaving room for the "<prefix>_<timestamp>_" the caller prepends.
    budget = max(1, 180 - len(ext.encode("utf-8")))
    if len(stem.encode("utf-8")) > budget:
        stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore")
    return stem + ext
