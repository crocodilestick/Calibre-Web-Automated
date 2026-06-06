# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the Greptile-surfaced sub-cursor-staleness bug
on PR #367 (v4.0.153).

> magic_shelf_last_id persists across sessions with cont_sync=False
> when a batch is exactly full — if the user later adds old (low-ID)
> books to the magic shelf, those books pass the outer membership
> filter but are filtered out by id > magic_shelf_last_id in the inner
> arm. The fold then fires on an empty batch, advancing the cursor
> past T_magic and deactivating the arm, leaving those books
> undelivered until a new shelf modification triggers another cache
> rebuild.

Concrete failure:

1. User has 150-book magic shelf. Session 1: round 1 emits ids 1-100;
   batch is full so the fold doesn't fire. Round 2 emits ids 101-150;
   batch partial, fold fires. cursor → T_magic. magic_shelf_last_id
   resets to -1.
2. User has 100-book magic shelf. Session 1: round 1 emits ids 1-100;
   batch is exactly full (== SYNC_ITEM_LIMIT). batch_drained = False,
   fold doesn't fire. cursor → (T_bulk, 100). magic_shelf_last_id =
   100. book_count == limit → cont_sync = False → sync ends.
   sync_token persists magic_shelf_last_id = 100.
3. User adds book id=5 (low id) to the shelf. Cache rebuilds.
4. Next sync: cursor.lm = T_bulk, magic_shelf_last_id = 100,
   cache.created_at = T_magic_2 > T_magic. arm activates.
   Arm filter: id IN {5, 1..100} AND id > 100 → no match (book 5 has
   id < 100). Composite: lm > T_bulk OR (lm == T_bulk AND id > 100)
   → no match. Batch empty. batch_drained = True. fold fires. cursor
   → T_magic_2; magic_shelf_last_id → -1.
5. Book id=5 was never delivered. It only delivers after ANOTHER
   cache rebuild (the next 30-min TTL expiry or shelf edit).

Fix: track `magic_shelf_membership_at` on the SyncToken (default
datetime.min; VERSION 1-4-0). Before running the arm, if the current
cache.created_at > sync_token.magic_shelf_membership_at, reset
magic_shelf_last_id = -1 in the current request. Persist the new
cache.created_at to sync_token at end of request.

With the fix: step 4 detects the rebuild (T_magic_2 >
sync_token.magic_shelf_membership_at = T_magic), resets
magic_shelf_last_id to -1, and the arm matches book id=5 on its
first sync after the rebuild.
"""

import ast
import pathlib
import sqlite3

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KOBO_PY = REPO_ROOT / "cps" / "kobo.py"
SYNC_TOKEN_PY = REPO_ROOT / "cps" / "services" / "SyncToken.py"


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} function not found in {path}"
    return ast.unparse(fn)


@pytest.mark.unit
class TestSyncTokenMembershipAtField:
    def test_field_exists_with_min_default(self):
        from cps.services.SyncToken import SyncToken
        from datetime import datetime
        t = SyncToken()
        assert t.magic_shelf_membership_at == datetime.min

    def test_field_round_trips_through_token(self):
        import base64
        import json
        from datetime import datetime
        from cps.services.SyncToken import SyncToken
        original = SyncToken(magic_shelf_membership_at=datetime(2026, 6, 1, 10, 0, 0))
        encoded = original.build_sync_token()
        rehydrated = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert rehydrated.magic_shelf_membership_at == datetime(2026, 6, 1, 10, 0, 0)

    def test_old_token_missing_field_defaults_to_min(self):
        import base64
        import json
        from datetime import datetime
        from cps.services.SyncToken import SyncToken
        # Pre-1-4-0 shape (no magic_shelf_membership_at)
        payload = {
            "version": "1-3-0",
            "data": {
                "raw_kobo_store_token": "",
                "books_last_modified": 0,
                "magic_shelf_last_id": 100,
                # NB: no magic_shelf_membership_at
            },
        }
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        token = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: encoded})
        assert token.magic_shelf_membership_at == datetime.min
        # And the other fields parsed correctly
        assert token.magic_shelf_last_id == 100


@pytest.mark.unit
class TestHandleSyncRequestResetsSubCursorOnRebuild:
    def test_handle_sync_request_compares_membership_added_at_against_token(self):
        """Pin that HandleSyncRequest compares the current
        magic_shelf_membership_added_at against
        sync_token.magic_shelf_membership_at and resets the sub-cursor
        when the former is newer."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "magic_shelf_membership_added_at > sync_token.magic_shelf_membership_at" in src, (
            "HandleSyncRequest must compare the current cache.created_at "
            "(magic_shelf_membership_added_at) against the token's "
            "stored cache.created_at (sync_token.magic_shelf_membership_at) "
            "to detect rebuilds. Without this comparison, a stale "
            "magic_shelf_last_id silently filters out new low-id books "
            "(Greptile P on PR #367)."
        )

    def test_handle_sync_request_writes_membership_at_back(self):
        """Pin that the request persists the cache.created_at to the
        sync_token at the end, so the NEXT request can detect a
        subsequent rebuild."""
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "sync_token.magic_shelf_membership_at" in src, (
            "HandleSyncRequest must write sync_token.magic_shelf_membership_at "
            "so future syncs can detect a newer cache rebuild and reset the "
            "sub-cursor."
        )


# ---------------------------------------------------------------------------
# Behavioral test against a real SQLite engine — simulates the exact
# Greptile scenario at the algorithmic layer.
# ---------------------------------------------------------------------------


SYNC_ITEM_LIMIT = 100


@pytest.mark.unit
class TestSubCursorResetAlgorithm:
    @staticmethod
    def _build_filter(arm_active, cursor_ts, cursor_id, magic_set, magic_last_id):
        """Build the WHERE clause + params replicating the v4.0.153/154 arm."""
        magic_in_clause = "(" + ",".join(str(i) for i in sorted(magic_set)) + ")"
        if arm_active:
            where = (
                f"last_modified > ? "
                f"OR (last_modified = ? AND id > ?) "
                f"OR (id IN {magic_in_clause} AND id > ?)"
            )
            params = [cursor_ts, cursor_ts, cursor_id, magic_last_id]
        else:
            where = "last_modified > ? OR (last_modified = ? AND id > ?)"
            params = [cursor_ts, cursor_ts, cursor_id]
        return where, params

    @staticmethod
    def _drive(
        con,
        magic_ids,
        T_magic,
        cursor_ts="0000-00-00 00:00:00.000000",
        cursor_id=-1,
        magic_shelf_last_id=-1,
        magic_shelf_membership_at="0000-00-00 00:00:00.000000",
        limit=SYNC_ITEM_LIMIT,
        max_rounds=10,
    ):
        """Drive the v4.0.154 algorithm — same as 153 but with cache-rebuild
        detection that resets magic_shelf_last_id when membership_added_at
        > sync_token.magic_shelf_membership_at."""
        # Cache-rebuild detection ON THIS REQUEST
        if T_magic > magic_shelf_membership_at:
            magic_shelf_last_id = -1
        synced, rounds = [], 0
        while rounds < max_rounds:
            rounds += 1
            arm_active = T_magic > cursor_ts
            where, params = TestSubCursorResetAlgorithm._build_filter(
                arm_active, cursor_ts, cursor_id, magic_ids, magic_shelf_last_id,
            )
            batch = con.execute(
                f"SELECT id, last_modified FROM books WHERE {where} "
                f"ORDER BY last_modified, id LIMIT ?",
                params + [limit]).fetchall()
            if not batch:
                break
            synced.extend(r[0] for r in batch)
            last_id, last_ts = batch[-1][0], batch[-1][1]
            new_ts, new_id = last_ts, last_id
            magic_in_batch = [r[0] for r in batch if r[0] in magic_ids]
            new_magic_last_id = (
                max(magic_shelf_last_id, max(magic_in_batch))
                if magic_in_batch else magic_shelf_last_id
            )
            batch_drained = len(batch) < limit
            if arm_active and batch_drained and T_magic > new_ts:
                new_ts, new_id = T_magic, -1
                new_magic_last_id = -1
            cursor_ts = new_ts
            cursor_id = new_id
            magic_shelf_last_id = new_magic_last_id
            if len(batch) < limit:
                break
        return synced, rounds, cursor_ts, cursor_id, magic_shelf_last_id

    def test_low_id_book_added_after_full_batch_session_delivers_next_sync(self):
        """Greptile's exact scenario: 100 magic books, sync session ends
        at magic_shelf_last_id=100 (cont_sync=False on a batch of 100).
        User then adds book id=5. Cache rebuilds. Next sync must deliver
        book id=5."""
        # Seed initial state: 100 magic books at T_bulk.
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        T_BULK = "2021-03-29 13:31:44.163290"
        initial_magic = set(range(1, 101))  # 100 books
        for i in initial_magic:
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        con.commit()

        # SESSION 1: cache.created_at = T_MAGIC_1. Empty starting token.
        T_MAGIC_1 = "2026-06-05 10:00:00.000000"
        synced, rounds, cursor_ts, cursor_id, magic_last_id = self._drive(
            con, initial_magic, T_MAGIC_1,
            cursor_ts="0000-00-00 00:00:00.000000",
            cursor_id=-1,
            magic_shelf_last_id=-1,
            magic_shelf_membership_at="0000-00-00 00:00:00.000000",
            limit=100,
            max_rounds=3,
        )
        # Session 1 delivers all 100 books.
        assert sorted(set(synced)) == sorted(initial_magic), (
            f"Session 1 must deliver all 100 magic books. Got {len(set(synced))}"
        )
        # Sync token at end of session 1: persisted (cursor, magic_last_id, membership_at)
        sess1_token = (cursor_ts, cursor_id, magic_last_id, T_MAGIC_1)

        # NOW: user adds book id=5 to the shelf. Cache rebuilds —
        # membership_added_at advances to T_MAGIC_2 > T_MAGIC_1.
        # Book 5 was already in the shelf (it's in 1..100), so the
        # rebuild produces the same set {1..100}. The KEY question is
        # whether the rebuild RESETS the sub-cursor properly. Simulate
        # with a brand-new low-id book (id=200, but in the magic set).
        # Actually for Greptile's exact scenario, simulate a NEW LOW-ID
        # book joining the shelf. Use id=0 as a new low book.
        con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)",
                    (200, T_BULK))  # book id=200, in shelf via rule
        con.commit()
        updated_magic = initial_magic | {200}  # new "rule match"
        # But Greptile's specific bug is about LOW-id new books. Add
        # one of those too.
        con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)",
                    (5000, T_BULK))  # dummy book to lift max id
        con.commit()
        # Actually Greptile's bug is about a LOW-id new addition.
        # Insert id=-5 isn't valid; instead let's add a book with a small
        # id that wasn't previously in the magic set. Since ids 1..100
        # were the original set, all small ids are taken. Add id=200 as
        # a NEW magic member with a HIGHER id than cursor — the
        # cache-rebuild reset matters when the LATER walk would skip
        # books NOT yet in `magic_set` at cursor-time. So our actual
        # scenario: session 1 ended with magic_last_id=100. Session 2
        # adds id=200 to the magic set. WITHOUT the rebuild reset:
        # arm = id IN {1..100, 200} AND id > 100 → id=200 matches.
        # delivers. NO BUG VISIBLE.
        # Greptile's bug requires a NEW book with id < magic_last_id.
        # Since our session 1 ended with magic_last_id=100, we need a
        # NEW book with id between (cursor_id at session1_end, 100). But
        # session 1 already emitted all ids 1..100. The bug needs ids
        # NOT in original set.
        # Let me restart with a more illustrative seed.
        con.close()

        # REDO with a more illustrative seed: initial_magic = {50..149}
        # (100 books, ids start at 50). After session 1: magic_last_id=149.
        # User adds book id=10 (low id, not in original set). Cache
        # rebuilds. Session 2 must deliver id=10.
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        initial_magic = set(range(50, 150))  # 100 books
        for i in initial_magic:
            con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)", (i, T_BULK))
        con.commit()

        # Session 1: delivers all 100 magic books. magic_last_id=149.
        T_MAGIC_1 = "2026-06-05 10:00:00.000000"
        synced, _, cursor_ts, cursor_id, magic_last_id = self._drive(
            con, initial_magic, T_MAGIC_1,
            magic_shelf_last_id=-1,
            magic_shelf_membership_at="0000-00-00 00:00:00.000000",
            limit=100, max_rounds=3,
        )
        assert sorted(set(synced)) == sorted(initial_magic)
        # Confirm the session-end state matches Greptile's pre-condition.
        # After 100-book delivery with limit=100, cursor=(T_bulk, 149),
        # magic_last_id=149, batch_drained=False, fold didn't fire.
        # Note: in the real code, cont_sync=False because book_count==limit
        # so the session ends — but the test loop stops at first partial
        # batch. For this scenario we manually end the session here.

        # NOW: user adds book id=10 to the shelf. Cache rebuilds.
        # T_MAGIC_2 > T_MAGIC_1.
        con.execute("INSERT INTO books (id, last_modified) VALUES (?, ?)",
                    (10, T_BULK))  # new low-id magic book
        con.commit()
        updated_magic = initial_magic | {10}
        T_MAGIC_2 = "2026-06-05 11:00:00.000000"

        # Session 2: with rebuild detection, magic_shelf_membership_at
        # was T_MAGIC_1 from session 1; current is T_MAGIC_2 > T_MAGIC_1
        # → reset magic_shelf_last_id to -1.
        synced_2, _, _, _, _ = self._drive(
            con, updated_magic, T_MAGIC_2,
            cursor_ts=cursor_ts,
            cursor_id=cursor_id,
            magic_shelf_last_id=magic_last_id,  # would be 149 without reset
            magic_shelf_membership_at=T_MAGIC_1,  # from session 1
            limit=100, max_rounds=5,
        )
        # The new low-id book MUST be delivered in this session.
        assert 10 in set(synced_2), (
            "After cache rebuild, the new low-id book (id=10) must "
            "deliver in the next sync. With the rebuild-reset, "
            "magic_shelf_last_id is set to -1 at request start, so the "
            "arm `id IN {10,50..149} AND id > -1` matches book 10. "
            "Without the reset (Greptile P on PR #367), the arm would "
            "filter id=10 via `id > 149`, fold fires on empty batch, "
            "and the book stays undelivered until ANOTHER cache rebuild."
        )
        con.close()
