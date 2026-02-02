# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for Kobo sync logic."""

from datetime import datetime
import logging


log = logging.getLogger(__name__)


def get_kobo_created_ts(book):
    ts_created = None
    if book.Books.timestamp is not None:
        ts_created = book.Books.timestamp.replace(tzinfo=None)
    else:
        log.debug("Kobo Sync: book %s has no timestamp", book.Books.id)

    try:
        if book.date_added is not None:
            ts_created = max(ts_created, book.date_added) if ts_created else book.date_added
        else:
            log.debug("Kobo Sync: book %s has no date_added", book.Books.id)
    except AttributeError:
        pass

    if ts_created is None and book.Books.last_modified is not None:
        ts_created = book.Books.last_modified.replace(tzinfo=None)
    if ts_created is None:
        ts_created = datetime.min

    return ts_created
