# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Kobo `KoboReader.sqlite` parser for H1 Phase 3.

Pure-Python module — no Flask, no `ub` direct imports — so it stays
testable in isolation. The blueprint at ``cps/annotations.py`` calls
:func:`parse_kobo_bookmarks` to extract annotation rows from an
uploaded sqlite file, then translates them into ``KoboAnnotationSync``
inserts.

See ``notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md`` §7 for the parser
sketch this module implements.

Security shape:

* Caller is responsible for size capping + MIME validation before
  invoking this module. We validate the SQLite header anyway as
  defense-in-depth.
* We open the upload read-only via ``mode=ro`` URI and never write
  back to it.
* The Bookmark table is the only table touched; any other contents
  are ignored even if present.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

log = logging.getLogger(__name__)

# Kobo's Bookmark.Color encoding — empirically observed on real devices.
# See notes/KOBO-PROTOCOL-REFERENCE.md §10.1 finding 5.
_COLOR_MAP = {0: "yellow", 1: "red", 2: "green", 3: "blue"}

# SQLite database file magic — first 16 bytes of any valid SQLite 3.x file.
_SQLITE_MAGIC = b"SQLite format 3\x00"


@dataclass(frozen=True)
class ParsedBookmark:
    """One row from a Kobo Bookmark table, plus the bits we derive
    from it for the H1 model. ``volume_id`` is the device's
    book-id (typically the EPUB UUID); the caller maps it to a CW
    ``books.id`` separately."""

    bookmark_id: str               # Bookmark.BookmarkID (UUID)
    volume_id: str                 # Bookmark.VolumeID — match against Books.uuid
    content_id: Optional[str]      # Bookmark.ContentID — chapter pointer
    start_container_path: Optional[str]
    start_container_child_index: Optional[int]
    start_offset: Optional[int]
    end_container_path: Optional[str]
    end_container_child_index: Optional[int]
    end_offset: Optional[int]
    text: str                      # Bookmark.Text (the highlighted passage)
    annotation: Optional[str]      # Bookmark.Annotation (user's typed note)
    context_string: Optional[str]
    chapter_progress: Optional[float]
    color: str                     # COLOR_MAP-normalized: 'yellow'/'red'/'green'/'blue'
    hidden: bool
    date_created: Optional[str]    # ISO-8601 strings as stored by Kobo
    date_modified: Optional[str]


def looks_like_sqlite(blob_or_path) -> bool:
    """Cheap magic-bytes check. Accepts either bytes (first 16+
    bytes of the file) or a path-like the caller wants us to read."""
    if isinstance(blob_or_path, (bytes, bytearray)):
        return bytes(blob_or_path[:16]) == _SQLITE_MAGIC
    p = Path(blob_or_path)
    if not p.is_file():
        return False
    try:
        with open(p, "rb") as fh:
            return fh.read(16) == _SQLITE_MAGIC
    except OSError:
        return False


def parse_kobo_bookmarks(sqlite_path: Path) -> Iterator[ParsedBookmark]:
    """Open ``sqlite_path`` read-only, walk every Bookmark row whose
    ``Text`` is non-empty, yield :class:`ParsedBookmark` instances.

    Yields nothing if the file is not SQLite, the Bookmark table
    doesn't exist, or the table is empty — never raises on a
    malformed payload. Callers test the iterator for emptiness to
    distinguish "no annotations" from "import failed for a real
    reason" (which we log).
    """
    if not isinstance(sqlite_path, Path):
        sqlite_path = Path(sqlite_path)
    if not looks_like_sqlite(sqlite_path):
        log.warning("kobo_import: %s is not a SQLite file", sqlite_path)
        return

    # mode=ro + immutable=1 — never touch the file, no journal, no
    # write attempts. Even if the user maliciously crafted a sqlite
    # with triggers, we can't fire them in read-only mode.
    uri = f"file:{sqlite_path}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        log.warning("kobo_import: cannot open %s read-only: %s", sqlite_path, e)
        return

    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='Bookmark'"
        )
        if cur.fetchone() is None:
            log.info("kobo_import: %s has no Bookmark table — skipping", sqlite_path)
            return

        rows = conn.execute("""
            SELECT
                BookmarkID, VolumeID, ContentID,
                StartContainerPath, StartContainerChildIndex, StartOffset,
                EndContainerPath, EndContainerChildIndex, EndOffset,
                Text, Annotation, Color, ContextString,
                ChapterProgress, DateCreated, DateModified, Hidden
            FROM Bookmark
            WHERE Text IS NOT NULL AND Text != ''
        """).fetchall()
    except sqlite3.DatabaseError as e:
        log.warning("kobo_import: SQL error on %s: %s", sqlite_path, e)
        return
    finally:
        conn.close()

    for r in rows:
        (bm_id, volume_id, content_id,
         sp, sci, so, ep, eci, eo,
         text, annotation, color, ctx,
         chapter_progress, dcreated, dmod, hidden) = r
        if not bm_id or not volume_id:
            # Malformed row — Kobo doesn't normally emit these. Skip
            # rather than abort the whole import.
            continue
        yield ParsedBookmark(
            bookmark_id=bm_id,
            volume_id=volume_id,
            content_id=content_id,
            start_container_path=sp,
            start_container_child_index=sci,
            start_offset=so,
            end_container_path=ep,
            end_container_child_index=eci,
            end_offset=eo,
            text=text,
            annotation=annotation,
            context_string=ctx,
            chapter_progress=chapter_progress,
            color=_COLOR_MAP.get(color or 0, "yellow"),
            hidden=bool(hidden),
            date_created=dcreated,
            date_modified=dmod,
        )
