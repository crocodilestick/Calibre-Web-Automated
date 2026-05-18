# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Builder for synthetic KoboReader.sqlite fixtures used by the H1
import path tests.

Real device backups contain personal reading history (PII). These
fixtures recreate the Bookmark table schema exactly per
``notes/KOBO-PROTOCOL-REFERENCE.md`` §10.1 without shipping anyone's
data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


BOOKMARK_DDL = """
CREATE TABLE Bookmark (
    BookmarkID TEXT PRIMARY KEY,
    VolumeID TEXT,
    ContentID TEXT,
    StartContainerPath TEXT,
    StartContainerChildIndex INTEGER,
    StartOffset INTEGER,
    EndContainerPath TEXT,
    EndContainerChildIndex INTEGER,
    EndOffset INTEGER,
    Text TEXT,
    Annotation TEXT,
    Color INTEGER,
    ContextString TEXT,
    ChapterProgress REAL,
    DateCreated TEXT,
    DateModified TEXT,
    Hidden INTEGER DEFAULT 0
)
"""


def build_synthetic_kobo_db(
    path: Path,
    book_uuid: str = "b3d1b38b-74fd-43b7-a796-996e5a6a8b04",
    extra_book_uuid: str = "11111111-2222-3333-4444-555555555555",
    sideloaded_uri: str = "file:///mnt/onboard/sideloaded.epub",
) -> Path:
    """Write a KoboReader.sqlite with a mix of bookmarks the H1 import
    path needs to handle:

    * 3 highlights on a UUID-tagged book (matches CW library)
    * 1 highlight with a typed note (Annotation populated)
    * 1 highlight in red color (color != 0)
    * 1 highlight on a sideloaded book (``file://`` URI) — must be skipped
    * 1 hidden highlight (Hidden=1) — must be skipped
    * 1 highlight on an unrelated UUID (no CW book) — must be skipped
    """
    if not isinstance(path, Path):
        path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(BOOKMARK_DDL)

    rows = [
        # bm_id, volume_id, content_id, sp, sci, so, ep, eci, eo, text, ann, color, ctx, prog, dcreated, dmod, hidden
        ("bm-001", book_uuid, f"{book_uuid}!!chapter1.html",
         "span#kobo\\.1\\.1", -99, 0, "span#kobo\\.1\\.1", -99, 15,
         "All animals are equal.", None, 0, "... All animals are equal. But ...",
         0.01, "2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z", 0),
        ("bm-002", book_uuid, f"{book_uuid}!!chapter1.html",
         "span#kobo\\.1\\.2", -99, 0, "span#kobo\\.1\\.3", -99, 21,
         "Four legs good, two legs bad.", "my favorite line", 1,
         "Four legs good, two legs bad.", 0.024, "2026-01-01T10:05:00Z",
         "2026-01-01T10:05:00Z", 0),
        ("bm-003", book_uuid, f"{book_uuid}!!chapter2.html",
         "span#kobo\\.2\\.1", -99, 8, "span#kobo\\.2\\.1", -99, 17,
         "Comrade Napoleon", None, 2, "...Comrade Napoleon is always right...",
         0.5, "2026-01-02T10:00:00Z", "2026-01-02T10:00:00Z", 0),
        # sideloaded — must be skipped
        ("bm-004", sideloaded_uri, "sideloaded!!ch1.html",
         "span#kobo\\.4\\.1", -99, 0, "span#kobo\\.4\\.1", -99, 10,
         "sideloaded text", None, 0, None, 0.1,
         "2026-01-03T10:00:00Z", "2026-01-03T10:00:00Z", 0),
        # hidden — must be skipped
        ("bm-005", book_uuid, f"{book_uuid}!!chapter1.html",
         "span#kobo\\.1\\.4", -99, 0, "span#kobo\\.1\\.4", -99, 30,
         "deleted on device", None, 0, None, 0.05,
         "2026-01-04T10:00:00Z", "2026-01-04T10:00:00Z", 1),
        # unrelated UUID — must be skipped (no CW book matches)
        ("bm-006", extra_book_uuid, f"{extra_book_uuid}!!intro.html",
         "span#kobo\\.5\\.1", -99, 0, "span#kobo\\.5\\.1", -99, 12,
         "orphan highlight", None, 3, None, 0.0,
         "2026-01-05T10:00:00Z", "2026-01-05T10:00:00Z", 0),
        # malformed: empty BookmarkID — must be skipped silently
        ("", book_uuid, None, None, None, None, None, None, None,
         "malformed", None, 0, None, None, None, None, 0),
        # empty text — must be skipped (parser WHERE clause filters)
        ("bm-008", book_uuid, f"{book_uuid}!!chapter1.html",
         "span#kobo\\.1\\.7", -99, 0, "span#kobo\\.1\\.7", -99, 5,
         "", None, 0, None, 0.0,
         "2026-01-06T10:00:00Z", "2026-01-06T10:00:00Z", 0),
    ]

    conn.executemany(
        "INSERT INTO Bookmark VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def build_empty_sqlite_no_bookmark_table(path: Path) -> Path:
    """A valid SQLite file with no Bookmark table — exercises the
    schema-validation skip path."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE OtherTable (id INTEGER)")
    conn.commit()
    conn.close()
    return path


def build_not_sqlite(path: Path) -> Path:
    """Not a SQLite file at all — exercises the magic-bytes rejection."""
    path.write_bytes(b"This is not a sqlite file. " * 100)
    return path
