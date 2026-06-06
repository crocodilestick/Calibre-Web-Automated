# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the Greptile-surfaced cursor-fold-advance bug
in fork #359 v4.0.147 / v4.0.151.

Greptile review on PR #361 surfaced a real correctness bug:

> When magic_shelf_arm_active=True and the batch is full (
> len(books_list) == SYNC_ITEM_LIMIT), the fold unconditionally advances
> the cursor to magic_shelf_membership_added_at. Any pending regular
> shelf books whose last_modified falls between the batch's max and
> magic_shelf_membership_added_at are then permanently skipped: on the
> next sync cursor_lm = T_magic, so lm > T_magic is False for them and
> the magic arm is now inactive.

Concrete failure (Greptile's exact scenario):

- User has 50 magic-shelf-only books (lm = T_bulk, old) + 100 regular
  shelf books (lm = T_bulk).
- Cache was rebuilt today (T_magic = now > T_bulk).
- Round 1 delivers first 100 books in (lm, id) order; new_lm = T_bulk;
  v4.0.151 fold fires because T_magic > T_bulk; cursor jumps to T_magic.
- Round 2: cursor_lm = T_magic; all 100 remaining regular books have
  lm = T_bulk < T_magic; none match any inner-cursor arm; 100 books are
  permanently dropped.

Fix: defer the fold when batch is full
(``len(books_list) < SYNC_ITEM_LIMIT`` is False). When batch is full,
there may be more pending books past the cursor; advancing the cursor
to T_magic skips them. Defer until the batch is partial (all pending
drained), then fold once. Already-emitted magic books may re-emit in
the meantime (the magic-shelf arm stays active) — that's idempotent on
the device, bandwidth waste only.
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
class TestFoldDefersWhenBatchFull:
    def test_fold_gate_uses_batch_drained_flag(self):
        """The fold must be gated on a `batch_drained` predicate
        (``len(books_list) < SYNC_ITEM_LIMIT``), not just on
        ``magic_shelf_arm_active``. Pin the named flag so a future
        refactor can't silently revert to unconditional firing."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "batch_drained" in src, (
            "HandleSyncRequest must define a `batch_drained` flag from "
            "len(books_list) < SYNC_ITEM_LIMIT. Without it the fold "
            "unconditionally jumps cursor to T_magic, dropping pending "
            "regular books between batch max and T_magic — Greptile #361 "
            "P1 finding."
        )
        # The gate must check batch_drained alongside magic_shelf_arm_active.
        # Match by AST so we don't catch the comment text.
        tree = ast.parse(src)
        gate_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp):
                names = set()
                for val in ast.walk(node.test):
                    if isinstance(val, ast.Name):
                        names.add(val.id)
                if "magic_shelf_arm_active" in names and "batch_drained" in names:
                    gate_found = True
                    break
        assert gate_found, (
            "The fold's outer if must combine `magic_shelf_arm_active and "
            "batch_drained`. Without batch_drained, fold fires when batch "
            "is full and drops pending books."
        )

    def test_no_unconditional_fold_with_only_arm_active_check(self):
        """Defense-in-depth: a future edit might re-introduce the old
        unconditional check `if magic_shelf_arm_active:` without the
        batch_drained gate. Pin that NO such bare gate exists at the
        fold site."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # Walk top-level If statements; for each, check whether
        # the test is just `magic_shelf_arm_active` (Name node) AND its
        # body advances new_books_last_modified to
        # magic_shelf_membership_added_at.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.If)
                    and isinstance(node.test, ast.Name)
                    and node.test.id == "magic_shelf_arm_active"):
                # Walk the body for any assignment to
                # new_books_last_modified from magic_shelf_membership_added_at.
                body_src = "\n".join(ast.unparse(b) for b in node.body)
                if "new_books_last_modified = magic_shelf_membership_added_at" in body_src:
                    pytest.fail(
                        "Found a bare `if magic_shelf_arm_active:` block "
                        "that advances new_books_last_modified to "
                        "magic_shelf_membership_added_at without the "
                        "batch_drained gate. This is the Greptile #361 P1 "
                        "regression — pending regular books get dropped."
                    )


# ---------------------------------------------------------------------------
# Behavioral test against a real SQLite engine that re-implements the cursor
# arithmetic with the bug + the fix side by side, proving the bug exists in
# the original semantics and the fix resolves it.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFoldDeferAlgorithmCorrectness:
    """Re-implementations of the buggy and fixed fold semantics against
    a real SQLite engine, using Greptile's exact scenario."""

    @staticmethod
    def _seed_mixed_library():
        """Greptile's exact scenario: 50 magic-shelf-only books +
        100 regular books, ALL at the same T_bulk timestamp."""
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        T_BULK = "2021-03-29 13:31:44.163290"
        # Magic shelf books: ids 1-50
        magic_ids = set(range(1, 51))
        for i in magic_ids:
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        # Regular shelf books: ids 51-150
        for i in range(51, 151):
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        con.commit()
        return con, magic_ids, T_BULK

    @staticmethod
    def _drive_buggy_fold(con, magic_ids, T_magic, limit=SYNC_ITEM_LIMIT):
        """Pre-fix cursor: fold fires unconditionally whenever
        T_magic > cursor_lm. This is what v4.0.151 ships."""
        cursor_ts = "0000-00-00 00:00:00.000000"
        cursor_id = -1
        synced, rounds = [], 0
        magic_set_clause = "(" + ",".join(str(i) for i in sorted(magic_ids)) + ")"
        while rounds < 50:
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
            # Buggy fold: advance cursor unconditionally if T_magic > new_lm
            new_ts = last_ts
            new_id = last_id
            if arm_active and T_magic > new_ts:
                new_ts = T_magic
                new_id = -1
            cursor_ts, cursor_id = new_ts, new_id
            # Cont_sync: if batch size < limit, no more pending.
            if len(batch) < limit:
                break
        return synced, rounds

    @staticmethod
    def _drive_fixed_fold(con, magic_ids, T_magic, limit=SYNC_ITEM_LIMIT):
        """Post-fix cursor: fold fires ONLY when batch is partial
        (no more pending)."""
        cursor_ts = "0000-00-00 00:00:00.000000"
        cursor_id = -1
        synced, rounds = [], 0
        magic_set_clause = "(" + ",".join(str(i) for i in sorted(magic_ids)) + ")"
        while rounds < 50:
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
            # FIXED: only advance cursor to T_magic when batch is partial
            # (len < limit — drained all pending).
            batch_drained = len(batch) < limit
            if arm_active and batch_drained and T_magic > new_ts:
                new_ts = T_magic
                new_id = -1
            cursor_ts, cursor_id = new_ts, new_id
            if len(batch) < limit:
                break
        return synced, rounds

    def test_buggy_fold_drops_regular_books(self):
        """Pin the PRE-FIX BUG: with the buggy fold, the 100 regular
        books (id 51-150) are dropped permanently after the cursor
        jumps to T_magic."""
        con, magic_ids, _ = self._seed_mixed_library()
        T_MAGIC = "9999-12-31 23:59:59.999999"  # > T_bulk
        synced, rounds = self._drive_buggy_fold(con, magic_ids, T_MAGIC, limit=100)
        con.close()
        delivered = set(synced)
        # Books 1-100 delivered in round 1; cursor jumps to T_magic;
        # books 101-150 are dropped.
        assert 51 in delivered and 100 in delivered, (
            "Round 1 of the buggy fold delivers books 1-100 (the first "
            "100 in (lm, id) order). Sanity check failed."
        )
        dropped_regulars = set(range(101, 151)) - delivered
        assert len(dropped_regulars) == 50, (
            "The buggy fold MUST drop the 50 regular books with id 101-150 "
            "(their lm = T_bulk < T_magic, magic-shelf arm only matches "
            "magic_ids 1-50). This is the Greptile #361 P1 bug."
        )

    def test_fixed_fold_delivers_every_book(self):
        """Pin the FIX: with the batch_drained gate, all 150 books
        eventually deliver (magic re-emits accepted as idempotent)."""
        con, magic_ids, _ = self._seed_mixed_library()
        T_MAGIC = "9999-12-31 23:59:59.999999"
        synced, rounds = self._drive_fixed_fold(con, magic_ids, T_MAGIC, limit=100)
        con.close()
        delivered = set(synced)
        assert len(delivered) == 150, (
            f"Fixed fold must deliver all 150 distinct books, got "
            f"{len(delivered)}. Missing: "
            f"{sorted(set(range(1, 151)) - delivered)}"
        )
        # Termination: must finish in a bounded number of rounds.
        assert rounds <= 5, (
            f"Fixed fold must terminate quickly (at most 5 rounds for "
            f"150 books at limit 100), got {rounds}."
        )

    def test_fixed_fold_terminates_with_magic_only_books(self):
        """Edge: cache has magic books but no other books pending. Fold
        must still fire and cursor advance to T_magic."""
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        T_BULK = "2021-03-29 13:31:44.163290"
        magic_ids = set(range(1, 6))  # only 5 magic books, no regulars
        for i in magic_ids:
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        con.commit()

        T_MAGIC = "9999-12-31 23:59:59.999999"
        synced, rounds = self._drive_fixed_fold(con, magic_ids, T_MAGIC, limit=100)
        con.close()
        assert len(set(synced)) == 5, (
            f"All 5 magic-shelf books must deliver. Got {len(set(synced))}."
        )
        assert rounds <= 2, (
            f"Must terminate quickly with magic-only books, got {rounds}."
        )
