#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Connection-level SQLite pragmas.

Kept in its own module because both `cps.db` (metadata.db) and `cps.ub` (app.db)
need it, and `cps.db` already imports `cps.ub` -- so the helper cannot live in
either one without creating an import cycle.
"""

from sqlalchemy import event

from . import logger

log = logger.create()


def enable_sqlite_foreign_keys(engine):
    """Turn on SQLite foreign key enforcement for every connection `engine` opens.

    SQLite defaults `foreign_keys` to OFF, per connection. Until it is switched on,
    every `ON DELETE CASCADE` declared in the schema is inert: deleting a parent row
    leaves the children behind rather than removing them, and no error is raised.

    Three cascades in this codebase depend on it:

      * `books_pages_link` (metadata.db) -- Calibre's own table, populated for every
        book by an `AFTER INSERT ON books` trigger. Calibre's `books_delete_trg`
        lists its other child tables explicitly but not this one, because the
        `ON DELETE CASCADE` is expected to cover it.
      * `book_format_checksums` (metadata.db) -- CWA's KOReader sync checksums.
      * `kosync_progress` (app.db) -- CWA's reading progress, cascaded on user
        deletion.

    Without this, deleting a book or a user silently orphans those rows. The orphans
    are invisible until something trips over them: `PRAGMA foreign_key_check`
    reports violations, and Calibre's own trigger-based integrity checks can abort a
    later write with "Foreign key violation: book not in books".

    The pragma is applied here, to the raw DBAPI connection at connect time, rather
    than alongside the `journal_mode` pragmas in `setup_db`. SQLite ignores
    `foreign_keys` when it is issued inside a transaction and does not report an
    error for doing so, which makes the obvious placement a silent no-op.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            log.warning("Could not enable SQLite foreign key enforcement (%s); "
                        "ON DELETE CASCADE will not fire on this connection", e)
        finally:
            cursor.close()

    return engine
