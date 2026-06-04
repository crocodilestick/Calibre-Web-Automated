# Phase 2 — KoboReader.sqlite provider verified against a REAL device DB

Date: 2026-05-25. Operator supplied a real `KoboReader.sqlite` (1,771 Bookmark
rows, 1,722 highlights) so the provider's SQL could be checked against the
genuine Kobo schema without the device.

## Bug found + fixed (the real schema caught what the doc didn't)

The real `Bookmark` table has **`EndContainerChildIndex` as NOT NULL with no
default** — `KOBO-PROTOCOL-REFERENCE.md` §10.1 only documented
`StartContainerChildIndex`. `kobo_sqlite_provider.buildBookmarkRow` set the
start sentinel but not the end one, and the INSERT omitted the column — so
**every device insert would have failed with a NOT NULL constraint violation**
on real hardware. This is exactly the class of bug the device gate exists to
catch; the real DB caught it pre-hardware.

Fix: `buildBookmarkRow` now sets `EndContainerChildIndex = -99`; the INSERT
column list + bind include it (17 cols). Pinned by a busted assertion. Also
captured `ChapterProgress` in `readAll`/`bookmarkRowToPortable` (real highlights
populate it) so device→web carries progress.

## Verified against the real schema (copy; original never touched)

`/tmp/kobo_insert_verify.py` ran the provider's **exact** INSERT + `readAll`
SELECT column lists against a copy of the real DB:

- INSERT satisfies all 9 NOT-NULL-no-default columns (BookmarkID, VolumeID,
  ContentID, Start/EndContainerPath, Start/EndContainerChildIndex,
  Start/EndOffset). Inserts a web highlight cleanly (Color=2, `-99` sentinels).
- `INSERT OR IGNORE` idempotent — double insert → 1 row, no error.
- `readAll` SELECT valid against the real schema; reads our row back (the test
  volume went 577 → 578 highlights).
- All my INSERT/SELECT column **names** exist in the real schema (0 unknown).

## Nickel render — VERIFIED on real hardware (2026-05-26)

Inserted a highlight with the provider's **exact 17-column output** into the
operator's real device `KoboReader.sqlite` (backed up off-device first), anchored
to a real KoboSpan in *The Iliad*, note `CWNG-BRIDGE-TEST`, `Color=2`. After a
safe eject, **stock Nickel rendered it**: it appears in the book's Annotations
list under "BOOK 9: THE EMBASSY", green, over the correct passage ("Seven new
tripods and ten pounds of gold…"), with the note shown and correctly slotted
into the chapter (dated "TODAY"). Operator-confirmed with a device photo.

**Key finding:** it rendered with **only the 17 columns the provider sets** —
Nickel did NOT require `UserID`, `ChapterProgress`, or `Published`
(defaulted/NULL). So `buildBookmarkRow` needs no additional columns. This was
the single irreducibly device-side unknown, and it passed.

## Residual (lower-risk) — the actual plugin runtime on-device

Still only unit-tested (not yet run inside KOReader on the device): the Lua
plugin opening `KoboReader.sqlite` via its sqlite FFI + writing this exact
INSERT + the backup file, and the pull/push transport over wifi. The pure logic
(diff/merge, field mapping) is busted-tested; the server endpoints are verified
over the wire; the INSERT/SELECT + the Nickel render are now proven against real
hardware. What remains is mechanical glue — exercise it by installing the plugin
and running `feat-annotation-koreader-bridge-device-verification.md` Tests 1/2
when convenient. The device-write toggle stays **default-off** until that run.
