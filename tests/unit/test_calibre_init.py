# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sqlite3
import sys
import types
import importlib.util
from pathlib import Path


def _load_calibre_init():
    class DummyCalibreDB:
        session_factory = None
        config = None

        @classmethod
        def update_config(cls, config):
            cls.config = config

        @classmethod
        def setup_db(cls, _calibre_dir, _app_db_path):
            cls.session_factory = object()
            return True

    logger_module = types.ModuleType("logger")

    class DummyLogger:
        def error(self, _message):
            return None

    def _create_logger():
        return DummyLogger()

    logger_module.create = _create_logger

    db_module = types.ModuleType("db")
    db_module.CalibreDB = DummyCalibreDB

    cps_module = types.ModuleType("cps")
    cps_module.db = db_module
    cps_module.logger = logger_module

    sys.modules["cps"] = cps_module
    sys.modules["cps.db"] = db_module
    sys.modules["cps.logger"] = logger_module

    module_path = Path(__file__).resolve().parents[2] / "cps" / "calibre_init.py"
    spec = importlib.util.spec_from_file_location("calibre_init", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, DummyCalibreDB


def _create_settings_table(con, columns):
    col_defs = ", ".join(f"{name} {ctype}" for name, ctype in columns)
    con.execute(f"CREATE TABLE settings ({col_defs})")


def _insert_settings_row(con, columns, values):
    col_names = ", ".join(name for name, _ in columns)
    placeholders = ", ".join(["?"] * len(columns))
    con.execute(
        f"INSERT INTO settings ({col_names}) VALUES ({placeholders})",
        values,
    )


def test_init_calibre_db_from_app_db_reads_settings(tmp_path):
    app_db = tmp_path / "app.db"
    columns = [
        ("config_calibre_dir", "TEXT"),
        ("config_title_regex", "TEXT"),
        ("config_books_per_page", "INTEGER"),
        ("config_random_books", "INTEGER"),
        ("config_read_column", "INTEGER"),
        ("config_restricted_column", "INTEGER"),
        ("config_columns_to_ignore", "TEXT"),
    ]
    values = [
        "/calibre-library",
        "^Test\\s+",
        77,
        9,
        2,
        3,
        "tags,authors",
    ]
    with sqlite3.connect(app_db) as con:
        _create_settings_table(con, columns)
        _insert_settings_row(con, columns, values)
        con.commit()

    calibre_init, dummy_db = _load_calibre_init()
    result = calibre_init.init_calibre_db_from_app_db(str(app_db))
    assert result is True
    config = dummy_db.config
    assert config.config_calibre_dir == "/calibre-library"
    assert config.config_title_regex == "^Test\\s+"
    assert config.config_books_per_page == 77
    assert config.config_random_books == 9
    assert config.config_read_column == 2
    assert config.config_restricted_column == 3
    assert config.config_columns_to_ignore == "tags,authors"


def test_init_calibre_db_from_app_db_defaults_missing_columns(tmp_path):
    app_db = tmp_path / "app.db"
    columns = [
        ("config_calibre_dir", "TEXT"),
        ("config_title_regex", "TEXT"),
    ]
    values = [
        "/calibre-library",
        None,
    ]
    with sqlite3.connect(app_db) as con:
        _create_settings_table(con, columns)
        _insert_settings_row(con, columns, values)
        con.commit()

    calibre_init, dummy_db = _load_calibre_init()
    result = calibre_init.init_calibre_db_from_app_db(str(app_db))
    assert result is True
    config = dummy_db.config
    assert config.config_calibre_dir == "/calibre-library"
    assert config.config_books_per_page == calibre_init.DEFAULT_BOOKS_PER_PAGE
    assert config.config_random_books == calibre_init.DEFAULT_RANDOM_BOOKS
    assert config.config_read_column == calibre_init.DEFAULT_READ_COLUMN
    assert config.config_restricted_column == calibre_init.DEFAULT_RESTRICTED_COLUMN
    assert config.config_columns_to_ignore is None
