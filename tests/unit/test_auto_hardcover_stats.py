# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Exercise the task persistence method with real CWA_DB and SQLite.

Load only the method to avoid unrelated application startup and providers.
The database class, schema initialization and persistence code run unchanged.
"""
import ast
import io
import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cwa_db import CWA_DB

source = Path(__file__).resolve().parents[2] / 'cps/tasks/auto_hardcover_id.py'
tree = ast.parse(source.read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TaskAutoHardcoverID')
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_save_stats')
namespace = {'datetime': datetime}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
save_stats = namespace['_save_stats']


@pytest.mark.unit
class StatsPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previous_path = os.environ.get("CWA_DB_PATH")

        def restore_path():
            if previous_path is None:
                os.environ.pop("CWA_DB_PATH", None)
            else:
                os.environ["CWA_DB_PATH"] = previous_path

        self.addCleanup(restore_path)
        os.environ['CWA_DB_PATH'] = self.tmp.name
        self.path = Path(self.tmp.name) / 'cwa.db'

    def database(self):
        db = CWA_DB()
        self.addCleanup(db.con.close)
        return db

    def test_schema_and_direct_write_control(self):
        db = self.database()
        self.assertIsNotNone(db.cur.execute("SELECT name FROM sqlite_master WHERE name='hardcover_auto_fetch_stats'").fetchone())
        db.cur.execute('INSERT INTO hardcover_auto_fetch_stats (timestamp, books_processed) VALUES (?, ?)', ('control', 4))
        db.con.commit()
        with closing(sqlite3.connect(self.path)) as reader:
            self.assertEqual(reader.execute('SELECT books_processed FROM hardcover_auto_fetch_stats').fetchall(), [(4,)])

    def test_initialization_restores_missing_stats_table_preserving_data(self):
        db = self.database()
        db.cur.execute('CREATE TABLE owner_marker (value TEXT)')
        db.cur.execute("INSERT INTO owner_marker VALUES ('preserve')")
        db.cur.execute('DROP TABLE hardcover_auto_fetch_stats')
        db.con.commit()
        reopened = self.database()
        self.assertEqual(reopened.cur.execute('SELECT * FROM owner_marker').fetchall(), [('preserve',)])
        self.assertEqual(reopened.cur.execute('SELECT count(*) FROM hardcover_auto_fetch_stats').fetchone(), (0,))

    def assert_persists(self, counts, total_confidence, expected_average, initialize=True):
        if initialize:
            self.database()
        output = io.StringIO()
        log = logging.Logger('stats-regression', logging.DEBUG)
        log.addHandler(logging.StreamHandler(output))
        task = SimpleNamespace(log=log, books_processed=counts[0], auto_matched=counts[1],
                               queued_for_review=counts[2], skipped_no_results=counts[3],
                               errors=counts[4], total_confidence=total_confidence)
        before = datetime.utcnow()
        save_stats(task)
        after = datetime.utcnow()
        with closing(sqlite3.connect(self.path)) as reader:
            rows = reader.execute('SELECT timestamp, books_processed, auto_matched, queued_for_review, skipped_no_results, errors, avg_confidence FROM hardcover_auto_fetch_stats').fetchall()
        print('captured persistence log:', output.getvalue().strip(), flush=True)
        self.assertEqual(len(rows), 1, f'Expected one committed stats row; got {rows}; log: {output.getvalue()}')
        timestamp, *values = rows[0]
        self.assertEqual(tuple(values[:5]), counts)
        self.assertAlmostEqual(values[5], expected_average)
        self.assertLessEqual(before, datetime.fromisoformat(timestamp))
        self.assertLessEqual(datetime.fromisoformat(timestamp), after)
        self.assertNotIn('Error saving stats', output.getvalue())

    def test_save_stats_persists_counts_and_average(self):
        self.assert_persists((5, 2, 1, 1, 1), 1.8, 0.9)

    def test_save_stats_persists_with_no_auto_matches(self):
        self.assert_persists((4, 0, 4, 0, 0), 0.0, 0.0)

    def test_save_stats_restores_missing_table(self):
        db = self.database()
        db.cur.execute('CREATE TABLE owner_marker (value TEXT)')
        db.cur.execute("INSERT INTO owner_marker VALUES ('preserve')")
        db.cur.execute('DROP TABLE hardcover_auto_fetch_stats')
        db.con.commit()
        # Do not reinitialize here: the task itself must restore the table.
        self.assert_persists((3, 1, 1, 1, 0), 0.75, 0.75, initialize=False)
        self.assertEqual(db.cur.execute('SELECT * FROM owner_marker').fetchall(), [('preserve',)])

    def test_rejected_write_warns_and_releases_transaction(self):
        db = self.database()
        db.cur.execute("""
            CREATE TRIGGER reject_stats BEFORE INSERT ON hardcover_auto_fetch_stats
            BEGIN SELECT RAISE(ABORT, 'stats rejected'); END
        """)
        db.con.commit()
        output = io.StringIO()
        log = logging.Logger('stats-write-error')
        log.addHandler(logging.StreamHandler(output))
        task = SimpleNamespace(log=log, books_processed=1, auto_matched=0,
                               queued_for_review=0, skipped_no_results=1,
                               errors=0, total_confidence=0.0)
        save_stats(task)
        self.assertIn('Error saving stats to database: stats rejected', output.getvalue())
        self.assertNotIn('Saved Hardcover auto-fetch stats', output.getvalue())
        # A failed INSERT must not leave a transaction blocking another writer.
        with closing(sqlite3.connect(self.path, timeout=0)) as writer, writer:
            writer.execute('BEGIN EXCLUSIVE')
            self.assertEqual(writer.execute('SELECT count(*) FROM hardcover_auto_fetch_stats').fetchone(), (0,))
            writer.execute('DROP TRIGGER reject_stats')
        self.assert_persists((1, 0, 0, 1, 0), 0.0, 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
