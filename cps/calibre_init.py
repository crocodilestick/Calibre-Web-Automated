# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sqlite3

from cps import db, logger

log = logger.create()

DEFAULT_TITLE_SORT_REGEX = (
    r'^(A|The|An|Der|Die|Das|Den|Ein|Eine|Einen|Dem|Des|Einem|Eines|Le|La|Les|L\'|Un|Une)\s+'
)


class _MinimalConfig:
    def __init__(self, title_regex, calibre_dir):
        self.config_title_regex = title_regex
        self.config_calibre_dir = calibre_dir


def init_calibre_db_from_config(config, settings_path):
    """Initialize CalibreDB using an already-loaded config object."""
    if db.CalibreDB.session_factory and getattr(db.CalibreDB.config, "config_title_regex", None):
        return True
    db.CalibreDB.update_config(config)
    db.CalibreDB.setup_db(config.config_calibre_dir, settings_path)
    return db.CalibreDB.session_factory is not None


def init_calibre_db_from_app_db(app_db_path="/config/app.db"):
    """Initialize CalibreDB by reading config from app.db (for background workers)."""
    if db.CalibreDB.session_factory and getattr(db.CalibreDB.config, "config_title_regex", None):
        return True
    calibre_dir = None
    title_regex = None
    try:
        with sqlite3.connect(app_db_path, timeout=30) as con:
            cur = con.cursor()
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
    db.CalibreDB.update_config(_MinimalConfig(title_regex, calibre_dir))
    db.CalibreDB.setup_db(calibre_dir, app_db_path)
    return db.CalibreDB.session_factory is not None
