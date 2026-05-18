# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest


def _install_stub(name, attrs=None):
    module = ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_duplicate_index_module():
    for name in list(sys.modules):
        if name in ("cps.duplicate_index", "cps.duplicates", "cps", "sqlalchemy") or name.startswith(
            "sqlalchemy."
        ):
            sys.modules.pop(name, None)

    cps = _install_stub("cps")

    class _Logger:
        def info(self, *args, **kwargs):
            return None

    logger = _install_stub("cps.logger", {"create": lambda: _Logger()})

    class _BookId:
        def in_(self, values):
            return ("book_id_in", tuple(values))

    class _OrderColumn:
        def desc(self):
            return self

    class _Books:
        id = _BookId()
        title = _OrderColumn()
        timestamp = _OrderColumn()
        data = object()
        authors = object()
        languages = object()
        series = object()
        publishers = object()

    db = _install_stub("cps.db", {"Books": _Books})
    calibre_db = _install_stub("cps.calibre_db", {"session": None, "order_authors": lambda books: books[0].authors})
    cps.db = db
    cps.calibre_db = calibre_db
    cps.logger = logger

    def _normalize_title(title, primary_author=None):
        normalized = (title or "untitled").lower().strip()
        if primary_author:
            prefix = f"{primary_author.lower().strip()}, "
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
        return normalized

    def _group_hash(title, author):
        import hashlib

        payload = f"{(title or 'untitled').lower().strip()}|{(author or 'unknown').lower().strip()}"
        return hashlib.md5(payload.encode()).hexdigest()

    duplicates = _install_stub(
        "cps.duplicates",
        {
            "_AWARE_MIN": datetime.min.replace(tzinfo=timezone.utc),
            "_timestamp_or_default": lambda ts, default: (
                ts.replace(tzinfo=timezone.utc) if ts and ts.tzinfo is None else (ts or default)
            ),
            "filter_dismissed_groups": lambda groups, user_id=None: [
                group for group in groups if group.get("group_hash") != "dismissed"
            ],
            "generate_group_hash": _group_hash,
            "get_common_filters": lambda user_id=None: True,
            "normalize_title_for_duplicates": _normalize_title,
        },
    )
    cps.duplicates = duplicates

    _install_stub("cwa_db", {"CWA_DB": object})

    duplicate_index_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "duplicate_index.py"
    spec = importlib.util.spec_from_file_location("cps.duplicate_index", duplicate_index_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    sys.modules["cps.duplicate_index"] = module
    spec.loader.exec_module(module)
    return module


class _FakeCwaDB:
    _connection = None

    def __init__(self):
        self.con = self.__class__._connection
        self.cur = self.con.cursor()

    @classmethod
    def reset(cls):
        cls._connection = sqlite3.connect(":memory:")
        cls._connection.executescript(
            """
            CREATE TABLE cwa_duplicate_book_keys (
                book_id INTEGER PRIMARY KEY,
                normalized_title TEXT NOT NULL DEFAULT '',
                normalized_author TEXT NOT NULL DEFAULT '',
                normalized_language TEXT NOT NULL DEFAULT '',
                normalized_series TEXT NOT NULL DEFAULT '',
                normalized_publisher TEXT NOT NULL DEFAULT '',
                format_signature TEXT NOT NULL DEFAULT '',
                duplicate_key TEXT NOT NULL,
                criteria_fingerprint TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_cwa_duplicate_book_keys_key
                ON cwa_duplicate_book_keys(criteria_fingerprint, duplicate_key);
            CREATE TABLE cwa_duplicate_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                scan_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                duplicate_groups_json TEXT,
                total_count INTEGER DEFAULT 0,
                scan_pending INTEGER DEFAULT 1,
                last_scanned_book_id INTEGER DEFAULT 0
            );
            INSERT INTO cwa_duplicate_cache (id, scan_pending) VALUES (1, 1);
            """
        )

    def get_duplicate_cache(self):
        row = self.cur.execute(
            """
            SELECT duplicate_groups_json, total_count, scan_pending, last_scanned_book_id
            FROM cwa_duplicate_cache
            WHERE id = 1
            """
        ).fetchone()
        if row and row[0]:
            return {
                "duplicate_groups": json.loads(row[0]),
                "total_count": row[1],
                "scan_pending": bool(row[2]),
                "last_scanned_book_id": row[3],
            }
        return None

    def update_duplicate_cache(self, duplicate_groups, total_count, max_book_id=None):
        serializable = [
            {
                "title": group.get("title", ""),
                "author": group.get("author", ""),
                "count": group.get("count", 0),
                "group_hash": group.get("group_hash", ""),
                "book_ids": [book.id for book in group.get("books", [])],
            }
            for group in duplicate_groups
        ]
        self.cur.execute(
            """
            UPDATE cwa_duplicate_cache
            SET duplicate_groups_json = ?, total_count = ?, scan_pending = 0, last_scanned_book_id = ?
            WHERE id = 1
            """,
            (json.dumps(serializable), total_count, max_book_id or 0),
        )
        self.con.commit()
        return True


class _Query:
    def __init__(self, books, scalar_value=None):
        self.books = list(books)
        self.scalar_value = scalar_value

    def options(self, *args):
        return self

    def filter(self, expression):
        if isinstance(expression, tuple) and expression[0] == "book_id_in":
            wanted = set(expression[1])
            self.books = [book for book in self.books if book.id in wanted]
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return list(self.books)

    def scalar(self):
        return self.scalar_value


class _Session:
    def __init__(self, books):
        self.books = list(books)

    def query(self, subject):
        subject_text = str(subject)
        if "max" in subject_text:
            return _Query([], max([book.id for book in self.books], default=0))
        if "count" in subject_text:
            return _Query([], len(self.books))
        return _Query(self.books)


def _book(
    book_id,
    title,
    author,
    language="eng",
    series=None,
    publisher=None,
    formats=None,
    timestamp=None,
):
    return SimpleNamespace(
        id=book_id,
        title=title,
        authors=[SimpleNamespace(name=author)],
        languages=[SimpleNamespace(lang_code=language)] if language is not None else [],
        series=[SimpleNamespace(name=series)] if series is not None else [],
        publishers=[SimpleNamespace(name=publisher)] if publisher is not None else [],
        data=[SimpleNamespace(format=fmt) for fmt in (formats or [])],
        timestamp=timestamp or datetime(2024, 1, book_id, tzinfo=timezone.utc),
        has_cover=False,
    )


@pytest.fixture
def duplicate_index(monkeypatch):
    module = _load_duplicate_index_module()
    _FakeCwaDB.reset()
    monkeypatch.setattr(module, "CWA_DB", _FakeCwaDB)
    monkeypatch.setattr(module, "joinedload", lambda value: value)
    yield module
    for name in (
        "cps.duplicate_index",
        "cps.duplicates",
        "cps.calibre_db",
        "cps.db",
        "cps.logger",
        "cps",
        "cwa_db",
    ):
        sys.modules.pop(name, None)


def test_effective_criteria_falls_back_to_title_author(duplicate_index):
    criteria = duplicate_index.get_effective_duplicate_criteria(
        {
            "duplicate_detection_title": 0,
            "duplicate_detection_author": 0,
            "duplicate_detection_language": 0,
            "duplicate_detection_series": 0,
            "duplicate_detection_publisher": 0,
            "duplicate_detection_format": 0,
        }
    )

    assert criteria == {
        "title": True,
        "author": True,
        "language": False,
        "series": False,
        "publisher": False,
        "format": False,
    }


def test_fingerprint_changes_when_effective_criteria_change(duplicate_index):
    title_author = duplicate_index.get_criteria_fingerprint(
        {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    )
    title_author_language = duplicate_index.get_criteria_fingerprint(
        {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 1}
    )

    assert title_author != title_author_language


def test_build_book_key_parts_matches_python_duplicate_fallbacks(duplicate_index):
    book = _book(
        1,
        "Homer, The Iliad",
        "Homer",
        language=None,
        series=None,
        publisher=None,
        formats=["EPUB", "PDF"],
    )

    parts = duplicate_index.build_book_key_parts(book, {})

    assert parts.normalized_title == "the iliad"
    assert parts.normalized_author == "homer"
    assert parts.normalized_language == "unknown"
    assert parts.normalized_series == "no_series"
    assert parts.normalized_publisher == "unknown_publisher"
    assert parts.format_signature == "epub,pdf"


def test_title_only_key_parts_still_strip_primary_author_prefix(duplicate_index):
    book = _book(1, "Homer, The Iliad", "Homer")
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 0, "duplicate_detection_language": 0}

    parts = duplicate_index.build_book_key_parts(book, settings)
    key_values = duplicate_index._enabled_key_values(parts, settings)

    assert parts.normalized_title == "the iliad"
    assert parts.normalized_author == "homer"
    assert key_values == [("title", "the iliad")]


def test_upsert_and_delete_book_keys(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert")]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}

    result = duplicate_index.upsert_book_keys({1, 2}, settings)
    cwa_db = _FakeCwaDB()
    rows = cwa_db.cur.execute(
        """
        SELECT book_id, normalized_title, normalized_author, criteria_fingerprint
        FROM cwa_duplicate_book_keys
        ORDER BY book_id
        """
    ).fetchall()

    assert result["updated"] == 2
    assert [(row[0], row[1], row[2]) for row in rows] == [
        (1, "dune", "frank herbert"),
        (2, "dune", "frank herbert"),
    ]
    assert all(row[3] == result["fingerprint"] for row in rows)

    assert duplicate_index.delete_book_keys({1}) == 1
    remaining = cwa_db.cur.execute("SELECT book_id FROM cwa_duplicate_book_keys").fetchall()
    assert remaining == [(2,)]


def test_grouped_index_queries_and_dismissed_filtering(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert"), _book(3, "Other", "Writer")]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    duplicate_index.upsert_book_keys({1, 2, 3}, settings)

    groups = duplicate_index.get_duplicate_groups_from_index(settings, include_dismissed=True)

    assert len(groups) == 1
    assert groups[0]["title"] == "Dune"
    assert groups[0]["author"] == "Frank Herbert"
    assert groups[0]["count"] == 2
    assert [book.id for book in groups[0]["books"]] == [2, 1]

    duplicate_index.filter_dismissed_groups = lambda groups, user_id=None: []
    assert duplicate_index.get_duplicate_groups_from_index(settings, include_dismissed=False, user_id=7) == []


def test_cache_merge_keeps_serialization_shape(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert"), _book(3, "Other", "Writer")]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    duplicate_index.upsert_book_keys({1, 2, 3}, settings)

    result = duplicate_index.merge_affected_groups_into_cache({1}, settings)
    cache = _FakeCwaDB().get_duplicate_cache()

    assert result["updated"] is True
    assert cache["total_count"] == 1
    assert set(cache["duplicate_groups"][0]) == {"title", "author", "count", "group_hash", "book_ids"}
    assert cache["duplicate_groups"][0]["book_ids"] == [2, 1]


def test_cache_merge_preserves_retained_group_book_ids(duplicate_index):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune", "Frank Herbert"),
        _book(3, "Foundation", "Isaac Asimov"),
        _book(4, "Foundation", "Isaac Asimov"),
    ]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    duplicate_index.upsert_book_keys({1, 2, 3, 4}, settings)

    cwa_db = _FakeCwaDB()
    retained_group = {
        "title": "Foundation",
        "author": "Isaac Asimov",
        "count": 2,
        "group_hash": "foundation-hash",
        "book_ids": [4, 3],
    }
    cwa_db.cur.execute(
        """
        UPDATE cwa_duplicate_cache
        SET duplicate_groups_json = ?, total_count = ?, scan_pending = 0, last_scanned_book_id = ?
        WHERE id = 1
        """,
        (json.dumps([retained_group]), 1, 4),
    )
    cwa_db.con.commit()

    result = duplicate_index.merge_affected_groups_into_cache({1}, settings)
    cache = _FakeCwaDB().get_duplicate_cache()
    groups_by_title = {group["title"]: group for group in cache["duplicate_groups"]}

    assert result["updated"] is True
    assert groups_by_title["Foundation"]["book_ids"] == [4, 3]
    assert groups_by_title["Dune"]["book_ids"] == [2, 1]


def test_cache_merge_deletes_key_rows_for_missing_candidate_ids(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert")]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    duplicate_index.upsert_book_keys({1, 2}, settings)
    metadata = duplicate_index.rebuild_duplicate_index(settings)
    groups = duplicate_index.get_duplicate_groups_from_index(settings, include_dismissed=True)
    _FakeCwaDB().update_duplicate_cache(groups, len(groups), metadata["max_book_id"])

    duplicate_index.calibre_db.session = _Session([books[1]])
    result = duplicate_index.merge_affected_groups_into_cache({1}, settings)
    key_rows = _FakeCwaDB().cur.execute("SELECT book_id FROM cwa_duplicate_book_keys ORDER BY book_id").fetchall()
    cache = _FakeCwaDB().get_duplicate_cache()

    assert result["updated"] is True
    assert key_rows == [(2,)]
    assert cache["duplicate_groups"] == []


def test_rebuild_duplicate_index_replaces_active_fingerprint_and_removes_orphans(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert")]
    duplicate_index.calibre_db.session = _Session(books)
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    fingerprint = duplicate_index.get_criteria_fingerprint(settings)

    cwa_db = _FakeCwaDB()
    cwa_db.cur.execute(
        """
        INSERT INTO cwa_duplicate_book_keys (
            book_id, normalized_title, normalized_author, duplicate_key, criteria_fingerprint
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (1, "stale", "stale", "stale-key", fingerprint),
    )
    cwa_db.cur.execute(
        """
        INSERT INTO cwa_duplicate_book_keys (
            book_id, normalized_title, normalized_author, duplicate_key, criteria_fingerprint
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (99, "orphan", "orphan", "orphan-key", "abandoned-fingerprint"),
    )
    cwa_db.con.commit()

    result = duplicate_index.rebuild_duplicate_index(settings)
    rows = cwa_db.cur.execute(
        """
        SELECT book_id, normalized_title, criteria_fingerprint
        FROM cwa_duplicate_book_keys
        ORDER BY book_id
        """
    ).fetchall()

    assert result == {"max_book_id": 2, "indexed_count": 2, "fingerprint": fingerprint}
    assert rows == [(1, "dune", fingerprint), (2, "dune", fingerprint)]


def _seed_cache(scan_pending=False, last_scanned_book_id=1):
    cwa_db = _FakeCwaDB()
    cwa_db.cur.execute(
        """
        UPDATE cwa_duplicate_cache
        SET duplicate_groups_json = ?, scan_pending = ?, last_scanned_book_id = ?
        WHERE id = 1
        """,
        (json.dumps([]), int(scan_pending), last_scanned_book_id),
    )
    cwa_db.con.commit()


def test_has_valid_duplicate_index_baseline_states(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert"), _book(2, "Dune", "Frank Herbert")]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1, 2}, settings)
    _seed_cache(scan_pending=False, last_scanned_book_id=2)
    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is True

    _seed_cache(scan_pending=True, last_scanned_book_id=2)
    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is False
    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={2}) is True

    _seed_cache(scan_pending=False, last_scanned_book_id=0)
    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is False

    duplicate_index.delete_book_keys({2})
    _seed_cache(scan_pending=True, last_scanned_book_id=2)
    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is False
    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={2}) is True

    _FakeCwaDB.reset()
    duplicate_index.calibre_db.session = _Session([])
    _seed_cache(scan_pending=False, last_scanned_book_id=0)
    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is True


def test_has_valid_duplicate_index_baseline_requires_candidate_to_cover_missing_current_book(duplicate_index):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune Messiah", "Frank Herbert"),
        _book(3, "Children of Dune", "Frank Herbert"),
        _book(4, "God Emperor of Dune", "Frank Herbert"),
    ]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1, 2, 3}, settings)
    _seed_cache(scan_pending=False, last_scanned_book_id=4)

    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={3}) is False
    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={4}) is True


def test_has_valid_duplicate_index_baseline_allows_initial_incremental_when_candidates_cover_library(duplicate_index):
    books = [_book(1, "Dune", "Frank Herbert")]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}

    duplicate_index.calibre_db.session = _Session(books)

    assert duplicate_index.has_valid_duplicate_index_baseline(settings) is False
    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={1}) is True
    assert duplicate_index.has_valid_duplicate_index_baseline(settings, candidate_book_ids={2}) is False


def test_manual_full_scan_not_needed_for_new_books_during_dirty_ingest(duplicate_index, monkeypatch, tmp_path):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune Messiah", "Frank Herbert"),
        _book(3, "Children of Dune", "Frank Herbert"),
        _book(4, "God Emperor of Dune", "Frank Herbert"),
    ]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    dirty_file = tmp_path / "cwa_ingest_batch_dirty"

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1, 2}, settings)
    _seed_cache(scan_pending=True, last_scanned_book_id=2)
    monkeypatch.setattr(duplicate_index, "INGEST_BATCH_DIRTY_FILE", str(dirty_file))
    dirty_file.write_text("dirty_at=1\n")

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is False


def test_manual_full_scan_not_needed_for_new_books_during_running_ingest_follow_up(
    duplicate_index, monkeypatch, tmp_path
):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune Messiah", "Frank Herbert"),
    ]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    dirty_file = tmp_path / "cwa_ingest_batch_dirty"

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1}, settings)
    _seed_cache(scan_pending=True, last_scanned_book_id=1)
    monkeypatch.setattr(duplicate_index, "INGEST_BATCH_DIRTY_FILE", str(dirty_file))
    dirty_file.with_suffix(dirty_file.suffix + ".running").write_text("dirty_at=1\n")

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is False


def test_manual_full_scan_not_needed_while_ingest_active(duplicate_index, monkeypatch, tmp_path):
    books = [_book(1, "Dune", "Frank Herbert")]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    active_file = tmp_path / "cwa_ingest_batch_active"

    duplicate_index.calibre_db.session = _Session(books)
    _seed_cache(scan_pending=True, last_scanned_book_id=0)
    monkeypatch.setattr(duplicate_index, "INGEST_BATCH_ACTIVE_FILE", str(active_file))
    active_file.write_text("active_at=1\n")

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is False


def test_initial_manual_full_scan_not_needed_during_dirty_ingest(duplicate_index, monkeypatch, tmp_path):
    books = [_book(1, "Dune", "Frank Herbert")]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    dirty_file = tmp_path / "cwa_ingest_batch_dirty"

    duplicate_index.calibre_db.session = _Session(books)
    _seed_cache(scan_pending=True, last_scanned_book_id=0)
    monkeypatch.setattr(duplicate_index, "INGEST_BATCH_DIRTY_FILE", str(dirty_file))
    dirty_file.write_text("dirty_at=1\n")

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is False


def test_manual_full_scan_not_needed_when_pending_cache_has_complete_index(duplicate_index):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune Messiah", "Frank Herbert"),
    ]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1, 2}, settings)
    _seed_cache(scan_pending=True, last_scanned_book_id=2)

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is False


def test_manual_full_scan_needed_for_old_missing_book_even_during_dirty_ingest(duplicate_index, monkeypatch, tmp_path):
    books = [
        _book(1, "Dune", "Frank Herbert"),
        _book(2, "Dune Messiah", "Frank Herbert"),
        _book(3, "Children of Dune", "Frank Herbert"),
    ]
    settings = {"duplicate_detection_title": 1, "duplicate_detection_author": 1, "duplicate_detection_language": 0}
    dirty_file = tmp_path / "cwa_ingest_batch_dirty"

    duplicate_index.calibre_db.session = _Session(books)
    duplicate_index.upsert_book_keys({1, 3}, settings)
    _seed_cache(scan_pending=True, last_scanned_book_id=3)
    monkeypatch.setattr(duplicate_index, "INGEST_BATCH_DIRTY_FILE", str(dirty_file))
    dirty_file.write_text("dirty_at=1\n")

    assert duplicate_index.duplicate_index_needs_manual_full_scan(settings) is True


def test_mark_duplicate_index_pending_sets_cache_pending(duplicate_index):
    _seed_cache(scan_pending=False, last_scanned_book_id=4)

    assert duplicate_index.mark_duplicate_index_pending("criteria changed") is True

    cache = _FakeCwaDB().get_duplicate_cache()
    assert cache["scan_pending"] is True
    assert cache["last_scanned_book_id"] == 4


def test_schema_contains_duplicate_book_key_table():
    schema = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "cwa_schema.sql"
    sql = schema.read_text()
    connection = sqlite3.connect(":memory:")
    connection.executescript(sql)

    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cwa_duplicate_book_keys'"
    ).fetchone()
    index = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_cwa_duplicate_book_keys_key'"
    ).fetchone()

    assert table == ("cwa_duplicate_book_keys",)
    assert index == ("idx_cwa_duplicate_book_keys_key",)


_modules_snapshot: dict = {}


def setup_module(module):
    _modules_snapshot.clear()
    _modules_snapshot.update(sys.modules)


def teardown_module(module):
    for name in list(sys.modules):
        if name not in _modules_snapshot:
            sys.modules.pop(name, None)
    sys.modules.update(_modules_snapshot)
