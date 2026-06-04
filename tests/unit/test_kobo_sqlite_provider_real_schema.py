# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 2 schema-fit guard for the KOReader bridge's KoboReader.sqlite provider.

The provider (`koreader/plugins/cwasync.koplugin/kobo_sqlite_provider.lua`) writes
web-created highlights straight into a Kobo's `Bookmark` table so the stock reader
(Nickel) renders them. That table is Lua-side, so the busted tests can only cover
the *pure* helpers (colour codes, selector escaping, row building) — they cannot
prove the row the provider emits actually satisfies the real Kobo `Bookmark`
schema.

That gap is exactly where the one real Phase-2 bug lived: an early provider
omitted `EndContainerChildIndex`, which is `NOT NULL` with no default on real
hardware, so every device insert would have failed (see
`notes/feat-annotation-phase2-realdb-verification.md`). It was caught by replaying
the INSERT against a real device DB.

This test makes that check repeatable and PII-safe: it embeds the *schema* of the
real Kobo `Bookmark` table (public — Kobo's column layout, not anyone's data) and
replays the provider's *exact* INSERT/SELECT column lists (source-pinned from the
Lua so drift trips the test) against it. Set `CWNG_REAL_KOBO_DB=/path/to/copy` to
additionally replay against a real device DB copy locally (never committed).
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "koreader" / "plugins" / "cwasync.koplugin"
PROVIDER_LUA = PLUGIN_DIR / "kobo_sqlite_provider.lua"

# The real Kobo `Bookmark` schema (column layout only — public, no user data).
# Captured from a real KoboReader.sqlite (FW 4.39.x). The load-bearing facts are
# the nine NOT-NULL-no-default columns; the rest carry their real types/defaults
# so an INSERT that fits this fixture fits a device.
REAL_BOOKMARK_SCHEMA = """
CREATE TABLE Bookmark (
    BookmarkID TEXT NOT NULL,
    VolumeID TEXT NOT NULL,
    ContentID TEXT NOT NULL,
    StartContainerPath TEXT NOT NULL,
    StartContainerChildIndex INTEGER NOT NULL,
    StartOffset INTEGER NOT NULL,
    EndContainerPath TEXT NOT NULL,
    EndContainerChildIndex INTEGER NOT NULL,
    EndOffset INTEGER NOT NULL,
    Text TEXT,
    Annotation TEXT,
    ExtraAnnotationData BLOB,
    DateCreated TEXT,
    ChapterProgress REAL NOT NULL DEFAULT 0,
    Hidden BOOL NOT NULL DEFAULT 0,
    Version TEXT,
    DateModified TEXT,
    Creator TEXT,
    UUID TEXT,
    UserID TEXT,
    SyncTime TEXT,
    Published BIT default false,
    ContextString TEXT,
    Type TEXT,
    Color INTEGER DEFAULT 0,
    PRIMARY KEY (BookmarkID)
);
"""

# The columns the provider sets, in INSERT order. Mirrors buildBookmarkRow +
# applyToDevice in kobo_sqlite_provider.lua. test_insert_columns_match_lua_source
# pins this against the Lua so a future edit can't silently diverge.
PROVIDER_INSERT_COLUMNS = [
    "BookmarkID", "VolumeID", "ContentID", "StartContainerPath",
    "StartContainerChildIndex", "StartOffset", "EndContainerPath",
    "EndContainerChildIndex", "EndOffset", "Text", "Annotation", "Color",
    "ContextString", "Type", "DateCreated", "DateModified", "Hidden",
]

# What readAll SELECTs back.
PROVIDER_SELECT_COLUMNS = [
    "BookmarkID", "VolumeID", "ContentID", "StartContainerPath", "StartOffset",
    "EndContainerPath", "EndOffset", "Text", "Annotation", "Color",
    "ContextString", "ChapterProgress",
]


def _provider_shaped_row(bookmark_id="cwn-web-abc123", volume_id="vol-uuid-1"):
    """A row exactly as the Lua provider's buildBookmarkRow would emit: -99 child
    sentinels, integer colour, Type='highlight', escaped KoboSpan selectors."""
    return {
        "BookmarkID": bookmark_id,
        "VolumeID": volume_id,
        "ContentID": volume_id + "!!chapter6.html",
        "StartContainerPath": r"span#kobo\.4\.1",
        "StartContainerChildIndex": -99,
        "StartOffset": 0,
        "EndContainerPath": r"span#kobo\.4\.2",
        "EndContainerChildIndex": -99,
        "EndOffset": 116,
        "Text": "a highlighted passage",
        "Annotation": "a user note",
        "Color": 2,  # green
        "ContextString": "...surrounding passage text...",
        "Type": "highlight",
        "DateCreated": "2026-05-30T12:00:00Z",
        "DateModified": "2026-05-30T12:00:00Z",
        "Hidden": 0,
    }


def _insert_sql(columns):
    cols = ", ".join(columns)
    marks = ",".join("?" for _ in columns)
    return f"INSERT OR IGNORE INTO Bookmark ({cols}) VALUES ({marks})"


def _fresh_schema_db():
    con = sqlite3.connect(":memory:")
    con.executescript(REAL_BOOKMARK_SCHEMA)
    return con


# ── source-pin: the Python column lists must match the Lua provider ────────────

def _lua_insert_columns():
    body = PROVIDER_LUA.read_text(encoding="utf-8")
    # Reassemble the Lua-concatenated INSERT, then pull the (col, col, ...) list.
    m = re.search(r'INSERT OR IGNORE INTO Bookmark\s*"(.*?)VALUES', body, re.S)
    assert m, "could not find the provider INSERT in kobo_sqlite_provider.lua"
    glued = re.sub(r'"\s*\.\.\s*"', "", m.group(1))           # drop "..".. joins
    cols = re.search(r"\((.*?)\)", glued, re.S).group(1)
    return [c.strip() for c in cols.replace("\n", " ").split(",") if c.strip()]


def _lua_select_columns():
    body = PROVIDER_LUA.read_text(encoding="utf-8")
    m = re.search(r'"SELECT (.*?)FROM Bookmark', body, re.S)
    assert m, "could not find the provider readAll SELECT in the Lua"
    glued = re.sub(r'"\s*\.\.\s*"', "", m.group(1))
    return [c.strip() for c in glued.replace("\n", " ").split(",") if c.strip()]


def test_insert_columns_match_lua_source():
    assert _lua_insert_columns() == PROVIDER_INSERT_COLUMNS, (
        "kobo_sqlite_provider.lua INSERT column list drifted from the schema-fit "
        "test — update PROVIDER_INSERT_COLUMNS and re-verify against the real schema."
    )


def test_select_columns_match_lua_source():
    assert _lua_select_columns() == PROVIDER_SELECT_COLUMNS, (
        "kobo_sqlite_provider.lua readAll SELECT drifted from the schema-fit test."
    )


# ── the schema-fit checks ─────────────────────────────────────────────────────

def test_provider_insert_satisfies_all_not_null_constraints():
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    # The whole point: this must NOT raise IntegrityError on the real schema.
    con.execute(_insert_sql(PROVIDER_INSERT_COLUMNS), [row[c] for c in PROVIDER_INSERT_COLUMNS])
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM Bookmark").fetchone()[0] == 1


def test_every_not_null_no_default_column_is_set_by_the_provider():
    """Independent of the INSERT working: assert the provider covers exactly the
    columns the real schema demands. This is what the May-26 device run added."""
    not_null_no_default = {
        "BookmarkID", "VolumeID", "ContentID", "StartContainerPath",
        "StartContainerChildIndex", "StartOffset", "EndContainerPath",
        "EndContainerChildIndex", "EndOffset",
    }
    missing = not_null_no_default - set(PROVIDER_INSERT_COLUMNS)
    assert not missing, f"provider INSERT omits NOT-NULL columns: {missing}"


def test_real_schema_enforces_end_child_index_not_null():
    """Pin that the schema fixture matches reality: a *plain* INSERT that omits
    EndContainerChildIndex must raise NOT-NULL. If this ever stops raising, the
    embedded schema has drifted from a real device's `Bookmark` table — which is
    exactly the constraint the May-26 device run discovered the hard way."""
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    bad_cols = [c for c in PROVIDER_INSERT_COLUMNS if c != "EndContainerChildIndex"]
    sql = f"INSERT INTO Bookmark ({', '.join(bad_cols)}) VALUES ({','.join('?' for _ in bad_cols)})"
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(sql, [row[c] for c in bad_cols])


def test_provider_or_ignore_silently_skips_a_malformed_row():
    """The provider uses INSERT OR IGNORE, so a row missing a NOT-NULL column is
    *silently dropped* on-device — no crash, no row. Documents the real failure
    mode (a malformed highlight just doesn't appear, rather than erroring) so the
    behaviour is a pinned decision, not an accident. NB: applyToDevice still
    counts it as "inserted" — see the known-limitation note in
    feat-annotation-koreader-bridge-device-verification.md."""
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    bad_cols = [c for c in PROVIDER_INSERT_COLUMNS if c != "EndContainerChildIndex"]
    con.execute(_insert_sql(bad_cols), [row[c] for c in bad_cols])  # OR IGNORE
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM Bookmark").fetchone()[0] == 0


def test_insert_or_ignore_is_idempotent_on_bookmark_id():
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    sql = _insert_sql(PROVIDER_INSERT_COLUMNS)
    con.execute(sql, [row[c] for c in PROVIDER_INSERT_COLUMNS])
    con.execute(sql, [row[c] for c in PROVIDER_INSERT_COLUMNS])  # same BookmarkID
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM Bookmark").fetchone()[0] == 1


def test_readall_select_round_trips_the_inserted_row():
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    con.execute(_insert_sql(PROVIDER_INSERT_COLUMNS), [row[c] for c in PROVIDER_INSERT_COLUMNS])
    con.commit()
    got = con.execute(
        f"SELECT {', '.join(PROVIDER_SELECT_COLUMNS)} FROM Bookmark "
        "WHERE VolumeID = ? AND Type = 'highlight'",
        (row["VolumeID"],),
    ).fetchall()
    assert len(got) == 1
    assert got[0][PROVIDER_SELECT_COLUMNS.index("Text")] == "a highlighted passage"
    assert got[0][PROVIDER_SELECT_COLUMNS.index("Color")] == 2


def test_integrity_check_clean_after_provider_write():
    con = _fresh_schema_db()
    row = _provider_shaped_row()
    con.execute(_insert_sql(PROVIDER_INSERT_COLUMNS), [row[c] for c in PROVIDER_INSERT_COLUMNS])
    con.commit()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.skipif(
    not os.environ.get("CWNG_REAL_KOBO_DB"),
    reason="set CWNG_REAL_KOBO_DB=/path/to/KoboReader.sqlite copy to replay on a real device DB",
)
def test_provider_insert_against_a_real_device_db_copy():
    """Local-only: replay the exact INSERT/SELECT against a *copy* of a real
    device DB (the original is never touched; nothing is committed)."""
    src = os.environ["CWNG_REAL_KOBO_DB"]
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        shutil.copy(src, tmp.name)
        copy_path = tmp.name
    try:
        con = sqlite3.connect(copy_path)
        before = con.execute("SELECT COUNT(*) FROM Bookmark").fetchone()[0]
        # anchor to a real VolumeID so the readAll WHERE matches real rows
        vol = con.execute(
            "SELECT VolumeID FROM Bookmark WHERE Type='highlight' "
            "AND Text IS NOT NULL LIMIT 1"
        ).fetchone()[0]
        row = _provider_shaped_row(bookmark_id="cwn-web-realdb-verify", volume_id=vol)
        con.execute(_insert_sql(PROVIDER_INSERT_COLUMNS), [row[c] for c in PROVIDER_INSERT_COLUMNS])
        con.execute(_insert_sql(PROVIDER_INSERT_COLUMNS), [row[c] for c in PROVIDER_INSERT_COLUMNS])
        con.commit()
        after = con.execute("SELECT COUNT(*) FROM Bookmark").fetchone()[0]
        assert after == before + 1, "INSERT OR IGNORE not idempotent on real DB"
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        read = con.execute(
            f"SELECT {', '.join(PROVIDER_SELECT_COLUMNS)} FROM Bookmark "
            "WHERE VolumeID = ? AND Type='highlight' AND BookmarkID='cwn-web-realdb-verify'",
            (vol,),
        ).fetchall()
        assert len(read) == 1
        con.close()
    finally:
        os.unlink(copy_path)
