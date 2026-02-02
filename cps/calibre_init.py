# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import sqlite3

from cps import db, logger

log = logger.create()

DEFAULT_TITLE_SORT_REGEX = (
    r'^(A|The|An|Der|Die|Das|Den|Ein|Eine|Einen|Dem|Des|Einem|Eines|Le|La|Les|L\'|Un|Une)\s+'
)
DEFAULT_BOOKS_PER_PAGE = 60
DEFAULT_RANDOM_BOOKS = 4
DEFAULT_READ_COLUMN = 0
DEFAULT_RESTRICTED_COLUMN = 0


class _MinimalConfig:
    def __init__(self, title_regex, calibre_dir, books_per_page=DEFAULT_BOOKS_PER_PAGE,
                 random_books=DEFAULT_RANDOM_BOOKS, read_column=DEFAULT_READ_COLUMN,
                 restricted_column=DEFAULT_RESTRICTED_COLUMN, columns_to_ignore=None):
        self.config_title_regex = title_regex
        self.config_calibre_dir = calibre_dir
        self.config_books_per_page = books_per_page
        self.config_random_books = random_books
        self.config_read_column = read_column
        self.config_restricted_column = restricted_column
        self.config_columns_to_ignore = columns_to_ignore


def init_calibre_db_from_config(config, settings_path):
    """Initialize CalibreDB using an already-loaded config object."""
    if db.CalibreDB.session_factory and getattr(db.CalibreDB.config, "config_title_regex", None):
        return True
    db.CalibreDB.update_config(config)
    db.CalibreDB.setup_db(config.config_calibre_dir, settings_path)
    return db.CalibreDB.session_factory is not None


def init_calibre_db_from_app_db(app_db_path=None):
    """Initialize CalibreDB by reading config from app.db (for background workers)."""
    if app_db_path is None:
        base_path = os.environ.get("CALIBRE_DBPATH", "/config")
        if base_path.endswith(".db"):
            if os.path.basename(base_path) != "app.db":
                app_db_path = os.path.join(os.path.dirname(base_path), "app.db")
            else:
                app_db_path = base_path
        else:
            app_db_path = os.path.join(base_path, "app.db")
    if db.CalibreDB.session_factory and getattr(db.CalibreDB.config, "config_title_regex", None):
        return True
    calibre_dir = None
    title_regex = None
    books_per_page = DEFAULT_BOOKS_PER_PAGE
    random_books = DEFAULT_RANDOM_BOOKS
    read_column = DEFAULT_READ_COLUMN
    restricted_column = DEFAULT_RESTRICTED_COLUMN
    columns_to_ignore = None
    try:
        with sqlite3.connect(app_db_path, timeout=30) as con:
            cur = con.cursor()
            try:
                row = cur.execute(
                    "SELECT config_calibre_dir, config_title_regex, config_books_per_page, "
                    "config_random_books, config_read_column, config_restricted_column, "
                    "config_columns_to_ignore FROM settings LIMIT 1"
                ).fetchone()
                if row:
                    calibre_dir = row[0]
                    title_regex = row[1]
                    books_per_page = row[2] if row[2] is not None else DEFAULT_BOOKS_PER_PAGE
                    random_books = row[3] if row[3] is not None else DEFAULT_RANDOM_BOOKS
                    read_column = row[4] if row[4] is not None else DEFAULT_READ_COLUMN
                    restricted_column = row[5] if row[5] is not None else DEFAULT_RESTRICTED_COLUMN
                    columns_to_ignore = row[6]
            except sqlite3.OperationalError:
                row = cur.execute(
                    "SELECT config_calibre_dir, config_title_regex FROM settings LIMIT 1"
                ).fetchone()
                if row:
                    calibre_dir, title_regex = row[0], row[1]
    except Exception as e:
        log.error(f"Failed to read calibre settings from {app_db_path}: {e}")
        return False
    if not calibre_dir:
        log.error("Calibre library path missing in app.db; cannot initialize CalibreDB")
        return False
    title_regex = title_regex or DEFAULT_TITLE_SORT_REGEX
    db.CalibreDB.update_config(
        _MinimalConfig(title_regex, calibre_dir, books_per_page, random_books,
                       read_column, restricted_column, columns_to_ignore)
    )
    db.CalibreDB.setup_db(calibre_dir, app_db_path)
    return db.CalibreDB.session_factory is not None
