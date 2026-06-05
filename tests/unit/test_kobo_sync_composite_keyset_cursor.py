# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork #347 (Kobo sync stuck) + #359 (Magic Shelves
kobo_sync don't deliver) — unified composite-keyset cursor.

#347 symptom (@andree392): full Kobo sync never finishes. Device "My Books"
counter climbs past real library size; debug log shows
``changed entries: 4458 / selected to sync: 50 / remaining: 4458`` repeating.
Three users hit it on the thread (@andree392, @shavitmichael, @Glennza1962).

#347 root cause: keyset pagination on a non-unique sort key. The cursor was
``books_last_modified`` alone, but the ORDER BY is ``(last_modified, id)``.
When >SYNC_ITEM_LIMIT books share one ``last_modified`` (classic bulk-import
signature, all rows stamped with one second from a SQL import), the cursor
can either re-send the same first SYNC_ITEM_LIMIT forever (observed loop)
or skip the remainder.

#359 symptom (@recruiterguy): Magic Shelves with ``kobo_sync=1`` never put
their books on the Kobo, even with ``magic_shelf_cache`` populated. Regular
``kobo_sync=1`` shelves work for the same user/device/session.

#359 root cause: the inner cursor (``last_modified > token`` OR
``date_added > token``) ran before the outer ``(kobo_sync shelf OR
magic-shelf membership)`` filter. Magic-shelf-only books had NULL
``BookShelf.date_added`` (not in book_shelf_link) and old ``last_modified``,
so both arms returned false and the rows were excluded before the outer
filter ever saw them.

#213 constraint (the trap): @raphi011's earlier CWA #1351 fix DELIBERATELY
removed ``magic_shelf_book_ids`` from the inner OR because adding it
unconditionally produces an infinite ``cont_sync`` loop — magic books
re-emit every sync, ``cont_sync`` never goes False, the device syncs
forever. The new arm must respect this constraint structurally.

Unified fix (this test file pins):

1. SyncToken gains ``books_last_id`` (tested in
   ``test_kobo_synctoken_books_last_id.py``).
2. Both cursor sites in ``HandleSyncRequest`` use a composite keyset:
   ``(last_modified > token.lm) OR (last_modified == token.lm AND id > token.lid)``.
3. The magic-shelf branch adds a THIRD inner-OR arm:
   ``id IN magic_shelf_book_ids`` — gated on
   ``magic_shelf_membership_added_at > token.books_last_modified`` (so the
   arm goes False once the cursor advances past the cache's created_at,
   preserving the #213 termination guarantee).
4. Cursor advance folds ``max(magic_shelf_membership_added_at, ...)`` into
   ``new_books_last_modified`` to make (3) terminate.
5. ``sync_token.books_last_id`` is written at the end of HandleSyncRequest.
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


def _module_source() -> str:
    return KOBO_PY.read_text(encoding="utf-8")


SYNC_ITEM_LIMIT = 100


# --------------------------------------------------------------------------
# Source-pin invariants on HandleSyncRequest — the inline query, the cursor
# advance, the wire-token write. If any of these regress, the entire fix
# falls back to one or both of the original bug shapes.
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestCompositeKeysetCursorPinned:
    def test_composite_keyset_filter_construction_exists(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "composite_keyset_books_only" in src, (
            "HandleSyncRequest must build the composite-keyset filter "
            "'composite_keyset_books_only' that combines "
            "(last_modified > cursor_lm) OR (last_modified == cursor_lm AND "
            "id > cursor_id). Without it, fork #347 regresses — bulk-imported "
            "books sharing one last_modified can't be walked past."
        )

    def test_composite_keyset_uses_strictly_greater_or_id_tiebreaker(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The fix's composite is `(lm > cursor_lm) OR (lm == cursor_lm AND id > cursor_id)`.
        # Pin both arms exactly so a future edit can't silently revert one.
        assert "db.Books.last_modified > cursor_lm" in src, (
            "Composite-keyset filter must include the strict-greater arm "
            "on last_modified (fork #347)."
        )
        assert "db.Books.last_modified == cursor_lm" in src, (
            "Composite-keyset filter must include the equal-cursor-lm arm "
            "so paginated batches can walk through ties (fork #347)."
        )
        assert "db.Books.id > cursor_id" in src, (
            "Composite-keyset filter must include the id tiebreaker — "
            "the whole point of fork #347 is that ORDER BY (lm, id) "
            "needs cursor (lm, id) to walk through last_modified ties."
        )

    def test_else_branch_uses_composite_keyset_not_old_strict_greater_only(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The pre-fix 'else' branch was: `.filter(db.Books.last_modified >
        # sync_token.books_last_modified)`. The fix replaces it with the
        # composite filter. If a future change reverts to the old call shape
        # for the non-kobo-shelves user, fork #347 regresses for them too.
        assert ".filter(db.Books.last_modified > sync_token.books_last_modified)" not in src, (
            "The 'else' branch (kobo_only_shelves_sync=False) must use the "
            "composite-keyset filter, not the old timestamp-only strict-greater "
            "filter that drops books at the bulk-import boundary (fork #347)."
        )

    def test_magic_shelf_branch_does_not_use_old_inline_strict_greater_or(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The pre-fix magic-shelf branch was an inline `or_(date_added > token,
        # last_modified > token)`. The fix moves it into `inner_cursor_filter`
        # which composes the date_added arm + composite keyset + (conditionally)
        # the magic-shelf membership arm. If a future change re-inlines the
        # OR with only the two original arms, both fork #347 and fork #359
        # regress.
        assert "inner_cursor_filter" in src, (
            "HandleSyncRequest must build the named 'inner_cursor_filter' that "
            "composes the date_added arm + composite keyset + conditional "
            "magic-shelf membership arm. Replacing it with an inline OR "
            "regresses #347 and/or #359."
        )


@pytest.mark.unit
class TestMagicShelfMembershipArmPinned:
    def test_magic_shelf_arm_active_flag_is_computed(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "magic_shelf_arm_active" in src, (
            "HandleSyncRequest must compute 'magic_shelf_arm_active' to gate "
            "the third inner-OR arm (fork #359). The arm must only be active "
            "when the cache was rebuilt after the device's cursor — "
            "otherwise it's #213's infinite-loop trap."
        )

    def test_magic_shelf_arm_gated_on_membership_added_at_greater_than_cursor(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The gate is: only add the arm when cache.created_at > cursor.lm.
        # Removing the gate is the #213 regression vector (every sync re-emits,
        # cont_sync never goes False).
        assert "magic_shelf_membership_added_at > cursor_lm" in src, (
            "The magic-shelf arm must be gated on 'magic_shelf_membership_added_at "
            "> cursor_lm'. Without the gate, the arm fires on every sync, "
            "magic books re-emit forever, and cont_sync never goes False — "
            "the exact #213 regression CWA #1351 was written to fix."
        )

    def test_magic_shelf_membership_added_at_helper_exists(self):
        src = _module_source()
        assert "def get_magic_shelf_membership_added_at" in src, (
            "Helper 'get_magic_shelf_membership_added_at(user_id)' must exist. "
            "It computes the max MagicShelfCache.created_at across the user's "
            "kobo-sync magic shelves — the membership timestamp that plays the "
            "role BookShelf.date_added plays for regular shelves."
        )

    def test_membership_helper_filters_on_kobo_sync_true(self):
        src = _function_source(KOBO_PY, "get_magic_shelf_membership_added_at")
        # Must only include shelves the user has explicitly marked for Kobo
        # sync — otherwise it triggers magic-shelf arm activation on shelves
        # the user never authorized for Kobo delivery.
        assert "kobo_sync == True" in src or "kobo_sync=True" in src, (
            "get_magic_shelf_membership_added_at must filter on "
            "MagicShelf.kobo_sync == True. Otherwise non-Kobo magic shelves "
            "trigger the arm and contaminate the sync cursor."
        )

    def test_membership_helper_returns_none_when_config_disabled(self):
        src = _function_source(KOBO_PY, "get_magic_shelf_membership_added_at")
        assert "config_kobo_sync_magic_shelves" in src, (
            "Helper must short-circuit to None when "
            "config.config_kobo_sync_magic_shelves is False — the magic-shelf "
            "feature being globally disabled must NOT advance the cursor."
        )


@pytest.mark.unit
class TestCursorAdvanceWritesBooksLastId:
    def test_sync_token_books_last_id_is_written(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        assert "sync_token.books_last_id = new_books_last_id" in src, (
            "HandleSyncRequest must write sync_token.books_last_id at the end "
            "of the request alongside sync_token.books_last_modified. Without "
            "the write, the keyset cursor is dead-code — every sync sees "
            "books_last_id == -1, and the bulk-import block re-emits forever."
        )

    def test_books_last_id_resets_to_minus_one_when_cursor_advances_past_batch(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # When new_books_last_modified gets pushed past the batch's max ts
        # (via date_added fold or magic_shelf_membership fold), the batch's
        # last id is no longer relevant — reset to -1 so all books at the
        # new ts pass next sync's keyset arm.
        assert "new_books_last_id = -1" in src, (
            "When new_books_last_modified advances past the batch's max book "
            "ts (date_added fold from #220 or magic_shelf_cache fold from "
            "#359), the cursor id must reset to -1 — there are no books at "
            "the new ts in this batch, so the next sync's keyset arm "
            "'id > -1' must match every valid id at that ts."
        )

    def test_batch_materialized_once_into_books_list(self):
        src = _function_source(KOBO_PY, "HandleSyncRequest")
        # The pre-fix shape called `books = changed_entries.limit(...)` then
        # `len(books.all())` for logging, then `for book in books` — that
        # round-tripped the joined-load query twice per sync request.
        assert "books_list = changed_entries.limit(SYNC_ITEM_LIMIT).all()" in src, (
            "The query must materialize into 'books_list' exactly once. "
            "Iterating a lazy .limit() result twice (once for the count log, "
            "once for the for-loop) runs the joined-load query twice — "
            "doubles DB load on every Kobo sync request."
        )
        assert "for book in books_list:" in src, (
            "The for-loop must iterate over 'books_list' (the materialized "
            "result), not a fresh .limit() query."
        )


# --------------------------------------------------------------------------
# Behavioral test on a real SQLite engine that re-implements the cursor
# arithmetic in isolation. This proves the algorithm itself is correct, in
# the same engine the production code runs against. The container e2e
# (Phase 6 in goal_act) verifies the inline query in kobo.py wires up to
# this algorithm correctly.
#
# Same shape as notes/fork-347-repro/cursor_keyset_repro.py — promoted into
# a pinned CI test so a future cursor refactor cannot silently regress it.
# --------------------------------------------------------------------------


@pytest.mark.unit
class TestCompositeKeysetAlgorithm:
    @staticmethod
    def _seed_collision(collide_count, later_timestamps):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TEXT NOT NULL)")
        T0 = "2021-03-29 13:31:44.163290"  # @andree392's stuck timestamp
        rows = [(i, T0) for i in range(1, collide_count + 1)]
        for j, ts in enumerate(later_timestamps):
            rows.append((collide_count + 1 + j, ts))
        con.executemany("INSERT INTO books (id, last_modified) VALUES (?, ?)", rows)
        con.commit()
        return con, len(rows), T0

    @staticmethod
    def _drive_timestamp_only(con, limit, max_rounds=200):
        """The PRE-FIX cursor — pins the original bug shape."""
        cursor_ts = "0000-00-00 00:00:00.000000"
        synced, rounds = [], 0
        while rounds < max_rounds:
            rounds += 1
            batch = con.execute(
                "SELECT id, last_modified FROM books WHERE last_modified > ? "
                "ORDER BY last_modified, id LIMIT ?", (cursor_ts, limit)).fetchall()
            if not batch:
                break
            synced.extend(r[0] for r in batch)
            new_ts = max([r[1] for r in batch] + [cursor_ts])
            cursor_ts = new_ts
            remaining = con.execute(
                "SELECT COUNT(*) FROM books WHERE last_modified > ?", (cursor_ts,)).fetchone()[0]
            if remaining == 0:
                break
        return synced, rounds

    @staticmethod
    def _drive_composite_keyset(con, limit, max_rounds=200):
        """The POST-FIX cursor — pins the keyset algorithm correctness."""
        cursor_ts, cursor_id = "0000-00-00 00:00:00.000000", -1
        synced, rounds = [], 0
        while rounds < max_rounds:
            rounds += 1
            batch = con.execute(
                "SELECT id, last_modified FROM books "
                "WHERE last_modified > ? OR (last_modified = ? AND id > ?) "
                "ORDER BY last_modified, id LIMIT ?",
                (cursor_ts, cursor_ts, cursor_id, limit)).fetchall()
            if not batch:
                break
            synced.extend(r[0] for r in batch)
            cursor_ts, cursor_id = batch[-1][1], batch[-1][0]
            if len(batch) < limit:
                break
        return synced, rounds

    def test_timestamp_only_cursor_drops_books_at_boundary_block(self):
        """Pins the pre-fix BUG: this is what fork #347 actually observed."""
        con, total, _ = self._seed_collision(
            collide_count=250,
            later_timestamps=["2024-01-01 00:00:00.000000",
                              "2024-06-15 09:30:00.000000",
                              "2025-02-20 12:00:00.000000"])
        synced, rounds = self._drive_timestamp_only(con, limit=100)
        con.close()
        dropped = total - len(set(synced))
        assert dropped > 0, (
            "The PRE-FIX timestamp-only cursor MUST drop books at the bulk-"
            "import boundary. If this assertion fails, either the cursor is "
            "no longer timestamp-only (good, but rewrite this test) or the "
            "test seed isn't actually exercising the boundary."
        )
        # Specifically: 250 books at T0 + limit=100 = exactly 150 dropped
        # (the first 100 are emitted, cursor advances to T0, next round
        # filters strictly > T0 and the remaining 150 are gone forever).
        assert dropped == 150, (
            f"Expected exactly 150 books dropped at the T0 boundary "
            f"(250 - SYNC_ITEM_LIMIT=100), got {dropped}."
        )

    def test_composite_keyset_cursor_syncs_every_book_exactly_once(self):
        """Pins the FIX: every book delivered once, cursor monotonic."""
        con, total, _ = self._seed_collision(
            collide_count=250,
            later_timestamps=["2024-01-01 00:00:00.000000",
                              "2024-06-15 09:30:00.000000",
                              "2025-02-20 12:00:00.000000"])
        synced, rounds = self._drive_composite_keyset(con, limit=100)
        con.close()
        uniq = set(synced)
        assert len(uniq) == total, (
            f"Composite keyset must deliver every book — expected {total} "
            f"unique, got {len(uniq)}. Dropped: "
            f"{sorted(set(range(1, total + 1)) - uniq)[:10]}..."
        )
        assert len(synced) == total, (
            f"Composite keyset must deliver each book EXACTLY once — "
            f"got {len(synced)} sends for {total} books "
            f"({len(synced) - total} duplicate sends)."
        )
        # 253 books / 100 limit = 3 batches (100 + 100 + 53), so 3 rounds.
        assert rounds <= 4, (
            f"Composite keyset must walk through 253 books in ~3 rounds at "
            f"limit=100, got {rounds}."
        )

    def test_composite_keyset_handles_giant_collision_block(self):
        """The reporter's actual case: 4458 books all sharing one second."""
        con, total, _ = self._seed_collision(
            collide_count=4458,
            later_timestamps=[])
        synced, rounds = self._drive_composite_keyset(con, limit=50)
        con.close()
        assert len(set(synced)) == total, (
            f"4458-book collision (the @andree392 case) must deliver every "
            f"book. Got {len(set(synced))}/{total}."
        )
        # 4458 / 50 = 89.16 → 90 batches max
        assert rounds <= 90, (
            f"4458-book collision must walk through in <= 90 batches at "
            f"SYNC_ITEM_LIMIT=50, got {rounds}."
        )
