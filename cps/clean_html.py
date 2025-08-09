# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from . import logger
from lxml.etree import ParserError

log = logger.create()

try:
    # at least bleach 6.0 is needed -> incomplatible change from list arguments to set arguments
    from bleach import clean as clean_html
    from bleach.sanitizer import ALLOWED_TAGS
    bleach = True
except ImportError:
    from nh3 import clean as clean_html
    bleach = False


def clean_string(unsafe_text, book_id=0):
    try:
        if bleach:
            allowed_tags = list(ALLOWED_TAGS)
            allowed_tags.extend(["p", "span", "div", "pre", "br", "h1", "h2", "h3", "h4", "h5", "h6"])
            safe_text = clean_html(unsafe_text, tags=set(allowed_tags))
        else:
            safe_text = clean_html(unsafe_text)
    except ParserError as e:
        log.error("Comments of book {} are corrupted: {}".format(book_id, e))
        safe_text = ""
    except TypeError as e:
        log.error("Comments can't be parsed, maybe 'lxml' is too new, try installing 'bleach': {}".format(e))
        safe_text = ""
    return safe_text
