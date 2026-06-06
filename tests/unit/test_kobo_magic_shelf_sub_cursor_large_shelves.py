# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the Greptile-surfaced infinite-loop bug on
PR #366: magic-shelf arm is cursor-unaware for shelves with
``>= SYNC_ITEM_LIMIT`` books, so the same first SYNC_ITEM_LIMIT ids
re-emit forever once the natural cursor is past them.

Greptile's analysis on PR #366:

> When ``len(magic_shelf_book_ids) >= SYNC_ITEM_LIMIT`` (100), the
> deferred fold never fires. The ``id IN magic_shelf_book_ids`` arm
> unconditionally re-introduces all magic books on every round
> regardless of cursor position. With N=200 magic books at T_bulk:
> Round 1 delivers ids 1–100 (lm-ordered), cursor advances to
> ``(T_bulk, 100)``. Round 2 sees ``id IN (1…200)`` OR
> ``lm=T_bulk AND id>100`` → 200 books total → ORDER BY (lm, id) →
> LIMIT 100 yields ids 1–100 *again*. ``batch_drained = False`` every
> round; cursor never changes; ``cont_sync = True`` forever.

Fix: add a ``magic_shelf_last_id`` sub-cursor to ``SyncToken``
(VERSION 1-2-0 → 1-3-0). The arm becomes::

    Books.id IN magic_shelf_book_ids AND Books.id > magic_shelf_last_id

After each batch, advance ``magic_shelf_last_id`` to the max id of
magic-shelf books emitted. When the fold fires (cache.created_at
window closes), reset ``magic_shelf_last_id = -1`` so the next cache
rebuild starts walking the arm from id=0.
"""

import ast
import pathlib
import sqlite3

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KOBO_PY = REPO_ROOT / "cps" / "kobo.py"


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} function not found in {path}"
    return ast.unparse(fn)


SYNC_ITEM_LIMIT = 100


@pytest.mark.unit
class TestMagicShelfArmHasIdCursor:
    def test_arm_includes_id_greater_than_magic_shelf_last_id(self):
        """The magic-shelf arm must include ``Books.id > magic_shelf_last_id``
        in addition to ``Books.id IN magic_shelf_book_ids``. The bare
        membership check is cursor-unaware and re-emits the same first
        SYNC_ITEM_LIMIT ids forever (Greptile P1 on PR #366)."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The arm is now constructed once as a named `magic_shelf_arm`
        # filter that combines the membership check with the sub-cursor.
        assert "magic_shelf_arm" in src, (
            "HandleSyncRequest must build a named 'magic_shelf_arm' "
            "filter combining the membership check with the sub-cursor."
        )
        assert "db.Books.id > magic_shelf_last_id" in src, (
            "magic-shelf arm must filter `Books.id > magic_shelf_last_id` "
            "to walk through magic books across batches. Without it, "
            "shelves with >= SYNC_ITEM_LIMIT books re-emit the same "
            "first SYNC_ITEM_LIMIT ids forever (Greptile #366 P1)."
        )

    def test_sub_cursor_sourced_from_sync_token(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "magic_shelf_last_id = sync_token.magic_shelf_last_id" in src, (
            "magic_shelf_last_id local must be sourced from "
            "sync_token.magic_shelf_last_id at the top of HandleSyncRequest."
        )


@pytest.mark.unit
class TestSubCursorAdvanceAndReset:
    def test_new_magic_shelf_last_id_computed_from_batch(self):
        """After the batch loop, the new sub-cursor must advance to the
        highest magic-shelf book id emitted."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "new_magic_shelf_last_id" in src, (
            "HandleSyncRequest must compute a new_magic_shelf_last_id "
            "for the sub-cursor advance."
        )
        # Walking via `max(... for b in books_list if b.Books.id in magic_shelf_book_ids)`
        # is one acceptable shape; another is collecting into a list. Both
        # must reference `magic_shelf_book_ids` in the comprehension/filter.
        assert "magic_shelf_book_ids" in src

    def test_fold_resets_sub_cursor_to_minus_one(self):
        """When the fold fires (cursor advances past T_magic), the
        sub-cursor must reset so the next cache rebuild starts fresh."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "new_magic_shelf_last_id = -1" in src, (
            "The fold's `new_books_last_modified = T_magic` branch must "
            "also reset `new_magic_shelf_last_id = -1` so the next "
            "cache rebuild walks magic books from id=0 again."
        )

    def test_sync_token_writes_magic_shelf_last_id(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "sync_token.magic_shelf_last_id = new_magic_shelf_last_id" in src, (
            "HandleSyncRequest must write the updated sub-cursor back to "
            "sync_token at the end of the request."
        )


# ---------------------------------------------------------------------------
# Behavioral test against a real SQLite engine — the 200-book magic shelf
# scenario that Greptile flagged. PRE-FIX: infinite loop. POST-FIX: every
# book delivers exactly once.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubCursorAlgorithm:
    @staticmethod
    def _seed_large_magic_shelf(magic_count, regular_count=0):
        """Seed a magic shelf with `magic_count` books + optionally
        `regular_count` regular books. All books share one timestamp."""
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        T_BULK = "2021-03-29 13:31:44.163290"
        magic_ids = set(range(1, magic_count + 1))
        for i in magic_ids:
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        for i in range(magic_count + 1, magic_count + regular_count + 1):
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        con.commit()
        return con, magic_ids

    @staticmethod
    def _drive_pre_subcursor(con, magic_ids, T_magic, limit=SYNC_ITEM_LIMIT, max_rounds=10):
        """The PRE-FIX shape (PR #366 v4.0.152): magic-shelf arm has no
        id-cursor. For >= limit magic books, this loops forever."""
        cursor_ts = "0000-00-00 00:00:00.000000"
        cursor_id = -1
        synced, rounds = [], 0
        magic_set_clause = "(" + ",".join(str(i) for i in sorted(magic_ids)) + ")"
        while rounds < max_rounds:
            rounds += 1
            arm_active = T_magic > cursor_ts
            if arm_active:
                where = (
                    f"last_modified > ? "
                    f"OR (last_modified = ? AND id > ?) "
                    f"OR id IN {magic_set_clause}"
                )
            else:
                where = "last_modified > ? OR (last_modified = ? AND id > ?)"
            batch = con.execute(
                f"SELECT id, last_modified FROM books WHERE {where} "
                f"ORDER BY last_modified, id LIMIT ?",
                (cursor_ts, cursor_ts, cursor_id, limit)).fetchall()
            if not batch:
                break
            synced.extend(r[0] for r in batch)
            last_id, last_ts = batch[-1][0], batch[-1][1]
            new_ts = last_ts
            new_id = last_id
            batch_drained = len(batch) < limit
            if arm_active and batch_drained and T_magic > new_ts:
                new_ts = T_magic
                new_id = -1
            cursor_ts, cursor_id = new_ts, new_id
            if len(batch) < limit:
                break
        return synced, rounds

    @staticmethod
    def _drive_post_subcursor(con, magic_ids, T_magic, limit=SYNC_ITEM_LIMIT, max_rounds=10):
        """The POST-FIX shape (v4.0.153): magic-shelf arm has the
        sub-cursor `AND id > magic_shelf_last_id`. Walks magic shelves
        of any size."""
        cursor_ts = "0000-00-00 00:00:00.000000"
        cursor_id = -1
        magic_shelf_last_id = -1
        synced, rounds = [], 0
        magic_set_clause = "(" + ",".join(str(i) for i in sorted(magic_ids)) + ")"
        while rounds < max_rounds:
            rounds += 1
            arm_active = T_magic > cursor_ts
            if arm_active:
                where = (
                    f"last_modified > ? "
                    f"OR (last_modified = ? AND id > ?) "
                    f"OR (id IN {magic_set_clause} AND id > ?)"
                )
                params = (cursor_ts, cursor_ts, cursor_id, magic_shelf_last_id, limit)
            else:
                where = "last_modified > ? OR (last_modified = ? AND id > ?)"
                params = (cursor_ts, cursor_ts, cursor_id, limit)
            batch = con.execute(
                f"SELECT id, last_modified FROM books WHERE {where} "
                f"ORDER BY last_modified, id LIMIT ?", params).fetchall()
            if not batch:
                break
            synced.extend(r[0] for r in batch)
            last_id, last_ts = batch[-1][0], batch[-1][1]
            new_ts = last_ts
            new_id = last_id
            # Advance sub-cursor by max magic-shelf book id in batch
            magic_in_batch = [r[0] for r in batch if r[0] in magic_ids]
            new_magic_shelf_last_id = (
                max(magic_shelf_last_id, max(magic_in_batch))
                if magic_in_batch else magic_shelf_last_id
            )
            batch_drained = len(batch) < limit
            if arm_active and batch_drained and T_magic > new_ts:
                new_ts = T_magic
                new_id = -1
                new_magic_shelf_last_id = -1
            cursor_ts, cursor_id = new_ts, new_id
            magic_shelf_last_id = new_magic_shelf_last_id
            if len(batch) < limit:
                break
        return synced, rounds

    def test_pre_subcursor_loops_forever_on_large_magic_shelf(self):
        """Pin Greptile's exact scenario: 200 magic books, no regulars.
        The pre-fix algorithm re-emits ids 1-100 every round."""
        con, magic_ids = self._seed_large_magic_shelf(magic_count=200)
        T_MAGIC = "9999-12-31 23:59:59.999999"
        synced, rounds = self._drive_pre_subcursor(con, magic_ids, T_MAGIC, max_rounds=5)
        con.close()
        # We capped at max_rounds=5 so the loop terminates artificially;
        # without the cap it'd loop forever. Check that the same 100 ids
        # repeat across at least 2 rounds — the signature of the bug.
        first_round = synced[:100]
        second_round = synced[100:200]
        assert first_round == second_round, (
            f"Pre-subcursor bug: round 2 emits the SAME 100 books as "
            f"round 1 (Greptile #366 P1). round1={first_round[:5]}..., "
            f"round2={second_round[:5]}..."
        )
        # Books 101-200 are never delivered with the buggy algorithm.
        delivered = set(synced)
        missing = set(range(101, 201)) - delivered
        assert len(missing) == 100, (
            f"Pre-subcursor must miss books 101-200, got "
            f"{100 - len(missing)} of them delivered."
        )

    def test_post_subcursor_delivers_every_book_in_large_shelf(self):
        """Pin the FIX: with the sub-cursor, all 200 magic books deliver
        in 3 rounds (200 / 100 + final fold-fire round)."""
        con, magic_ids = self._seed_large_magic_shelf(magic_count=200)
        T_MAGIC = "9999-12-31 23:59:59.999999"
        synced, rounds = self._drive_post_subcursor(con, magic_ids, T_MAGIC, max_rounds=10)
        con.close()
        delivered = set(synced)
        assert delivered == set(range(1, 201)), (
            f"Post-subcursor must deliver all 200 magic books exactly "
            f"once. Got {len(delivered)} distinct, "
            f"missing={sorted(set(range(1, 201)) - delivered)[:10]}..."
        )
        assert rounds <= 4, (
            f"Should terminate in <=4 rounds (200/100 batches + fold), "
            f"got {rounds}"
        )

    def test_post_subcursor_handles_mixed_large_library(self):
        """Greptile's exact scenario but scaled: 200 magic books + 100
        regular books. All must deliver."""
        con, magic_ids = self._seed_large_magic_shelf(
            magic_count=200, regular_count=100,
        )
        T_MAGIC = "9999-12-31 23:59:59.999999"
        synced, rounds = self._drive_post_subcursor(con, magic_ids, T_MAGIC, max_rounds=10)
        con.close()
        delivered = set(synced)
        assert delivered == set(range(1, 301)), (
            f"Post-subcursor must deliver all 300 books (200 magic + 100 "
            f"regular). Missing: "
            f"{sorted(set(range(1, 301)) - delivered)[:10]}..."
        )
