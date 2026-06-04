# Manual device verification — KOReader annotation bridge (Phase 2)

Run this once on real hardware before Phase 2 is considered complete. It
verifies the one thing CI cannot: the `KoboReader.sqlite` ↔ Nickel round-trip.
Everything else (server pull/push, diff/merge, field mapping) is automated +
green; this gate covers the device write.

Design: `notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md` §4.
Until this passes, keep the plugin's "Sync highlights" toggle default **off**.

> **Already verified (2026-05-25) against a real `KoboReader.sqlite`** (1,771
> bookmarks) — see `feat-annotation-phase2-realdb-verification.md`: the
> provider's INSERT satisfies every NOT-NULL constraint (a missing
> `EndContainerChildIndex` was found + fixed this way), is idempotent, and the
> readAll SELECT round-trips. So Tests 1/2 below are really confirming the
> **Nickel render** + the live KOReader sqlite-FFI I/O — the SQL/schema fit is
> already proven.

## Prerequisites

- A physical Kobo running **KOReader** with the `cwasync.koplugin` from this
  branch installed (copy `koreader/plugins/cwasync.koplugin/` to the device's
  `koreader/plugins/`).
- The Kobo also has a CW-synced **kepub** of a test book (so it has KoboSpans +
  a `Bookmark`-compatible VolumeID).
- CWNG (`cwn-local` or teenyverse) reachable from the device, with **KOReader
  sync enabled** (`cwa_settings.koreader_sync_enabled = 1`).
- In the plugin: Set NextGen Server, Login, then enable **Sync highlights
  (experimental, Kobo only)**.

## Test 1 — web → device (the headline: server highlight reaches Nickel)

1. In the CWNG **web reader**, open the test book, select a sentence, save a
   highlight (e.g. green, note "bridge-test-1").
2. On the Kobo, open the book in **KOReader** → plugin menu → **Sync highlights
   now**. Expect an info message "Highlights synced: N to device, …".
3. On the host, inspect the device DB (or pull it):
   ```
   sqlite3 KoboReader.sqlite \
     "SELECT BookmarkID, Color, Text, substr(StartContainerPath,1,20) \
      FROM Bookmark WHERE Text LIKE '%bridge-test-1%' OR Annotation='bridge-test-1';"
   ```
   ✅ A row exists; `BookmarkID` is the server's `cwn-web-…` id; `Color=2`
      (green); `StartContainerPath` is `span#kobo\.x\.y`.
4. **Close KOReader and open the book in stock Nickel.** Navigate to the
   highlighted passage.
   ✅ The highlight shows in the stock reader. *(This is the whole point of the
      bridge — a web-created highlight on a stock Kobo.)*

## Test 2 — device → web (reverse direction)

5. In KOReader (or Nickel), create a highlight on a different sentence
   ("bridge-test-2"). Sync highlights now.
6. In the CWNG web reader, reload the book.
   ✅ "bridge-test-2" appears as an overlay; the `/annotations/<book>` page
      lists it with `source: kobo` (read out of KoboReader.sqlite) or
      `koreader`.

## Test 3 — safety: backup + integrity

7. On the device, confirm a backup was made before the first write:
   ```
   ls -la .kobo/KoboReader.sqlite.cwn-bak-*
   ```
   ✅ At least one backup file exists.
8. Integrity check the live DB:
   ```
   sqlite3 KoboReader.sqlite "PRAGMA integrity_check;"
   ```
   ✅ `ok`. No corruption from our writes.

## Test 4 — idempotency / no feedback loop

9. Run **Sync highlights now** twice in a row without changing anything.
   ✅ Second run reports "0 to device, 0 to server" (or only genuinely-new
      rows). No duplicate `Bookmark` rows for the same passage:
   ```
   sqlite3 KoboReader.sqlite \
     "SELECT BookmarkID, COUNT(*) FROM Bookmark GROUP BY BookmarkID HAVING COUNT(*)>1;"
   ```
   ✅ Empty (INSERT OR IGNORE held; no dupes).

## On failure

Capture and open a GitHub issue with:
```
cp .kobo/KoboReader.sqlite /tmp/koboreader-fail.sqlite
# KOReader log: koreader/crash.log or the plugin's logger.dbg output
```
Note the failing step number. Do **not** flip the toggle default to on until
all four tests pass.

## Sign-off

**2026-05-26 — render half proven by direct insert** (not via the plugin yet):
a highlight with the provider's exact 17-column output, written straight into
the real device `KoboReader.sqlite`, **rendered in stock Nickel** (green, correct
passage, note shown, slotted into the right chapter). See
`feat-annotation-phase2-realdb-verification.md`. So the SQL→Nickel path is
confirmed; Tests 1/2 below now only need to confirm the *plugin* performs that
write + the wifi pull/push (mechanical glue; pure logic already unit-tested).

- [x] Nickel renders a provider-shaped highlight (direct-insert, 2026-05-26)
- [ ] Test 1 (web → Nickel **via the plugin**) passed
- [ ] Test 2 (device → web) passed
- [ ] Test 3 (backup present + integrity ok) passed
- [ ] Test 4 (idempotent, no dupes) passed

Once Tests 1–4 pass via the plugin, the device-write default may be flipped on
in a follow-up.

## Known limitations (found during P1+P2 integration, 2026-05-30)

Surfaced while writing `tests/unit/test_kobo_sqlite_provider_real_schema.py`
(replays the provider's exact INSERT/SELECT against the real `Bookmark` schema —
embedded for CI, and against a real device-DB copy locally; all green):

1. **`INSERT OR IGNORE` turns a malformed row into a silent skip, not an error.**
   If `buildBookmarkRow` ever emits a row missing a NOT-NULL column (the class of
   bug the May-26 run caught for `EndContainerChildIndex`), the device write is
   *silently dropped* — the highlight just never appears on the Kobo, with no
   crash and no log line. Safer for the DB than a hard failure, but harder to
   diagnose. The schema-fit test now pins both the constraint (a plain INSERT
   raises) and this behaviour (OR IGNORE skips) so neither can regress unnoticed.

2. **`applyToDevice` over-counts.** It does `inserted = inserted + 1` after every
   `stmt:step()` regardless of whether OR IGNORE actually wrote the row. So the
   "N highlights synced to device" message counts *attempts*, not inserts —
   re-syncing an unchanged book (all BookmarkIDs already present → all ignored)
   still reports the full N, and a malformed row inflates the count. Cosmetic
   only (user-facing info text in an experimental, default-off feature); not a
   data-correctness issue. Fixing it needs `sqlite_changes()` after each step,
   which is `lua-ljsqlite3`-specific and only exercisable on-device — deferred to
   the same hardware session that runs Tests 1–4, so it can be verified, not
   guessed. Tracked here rather than silently shipped.
