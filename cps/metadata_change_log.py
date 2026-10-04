# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Metadata change logs picked up by CWA's cover/metadata enforcer.

A log named ``<timestamp>-<book_id>.json`` in ``CHANGE_LOGS_DIR`` tells the
enforcer to embed the book's current Calibre metadata into its files. Write one
only after the database change has been committed.
"""

import json
from datetime import datetime

from . import logger

log = logger.create()

CHANGE_LOGS_DIR = '/app/calibre-web-automated/metadata_change_logs'


def write_metadata_change_log(book, log_payload):
    """Write the change log for ``book``. ``log_payload`` maps field -> new value.

    Adds title/authors when missing and the ``_cwa_meta`` block. Failures are
    logged and swallowed, since the database change has already landed.
    Returns True when the file was written.
    """
    try:
        log_payload.setdefault('title', book.title)
        log_payload.setdefault('authors', ' & '.join([a.name for a in book.authors]))
        log_payload['_cwa_meta'] = {
            'modify_date': True,
            'change_count': len([k for k in log_payload.keys() if not k.startswith('_')]),
            'has_content': any(v != '' for k, v in log_payload.items() if not k.startswith('_')),
            'timestamp': datetime.now().isoformat()
        }

        now = datetime.now()
        log_path = f'{CHANGE_LOGS_DIR}/{now.strftime("%Y%m%d%H%M%S")}-{book.id}.json'
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log_payload, f, indent=4, ensure_ascii=False)
        log.debug(f"Created metadata change log for book {book.id} with changes: {list(log_payload.keys())}")
        return True
    except Exception as e:
        log.error_or_exception(f"Failed to write metadata change log for book {book.id}: {e}")
        return False
