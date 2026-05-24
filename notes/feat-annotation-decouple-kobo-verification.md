# Manual Kobo device verification — annotation decouple

Run this once per release as the human verification step. Tests the
full user-facing flow against a real Kobo eReader + cwn-local.

## Prerequisites

- Physical Kobo eReader paired to your account
- DNS override on test wifi pointing `*.kobobooks.com` → your cwn-local
  instance, OR the device's `affiliate.conf` configured to point at
  cwn-local
- `cwn-local` running with this branch's image (8086)

## Test 1 — Hardcover DISABLED: annotation captured as origin=kobo, no sync target

1. In admin → Hardcover, confirm "Annotation sync" is **off**. Save.
2. Open a book on the Kobo. Highlight a sentence. Add a note (e.g.
   "decouple-test-1"). Wait for the device to sync via wifi.
3. On the host:
   ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT id, annotation_id, source, highlighted_text FROM annotation;"
   ```
   ✅ At least one row; `source` is `'kobo'` (NOT `'hardcover'`).
4. ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT COUNT(*) FROM annotation_sync_target;"
   ```
   ✅ Result: `0` rows (Hardcover sync was disabled).

> NOTE: As of sub-project (1), the live PATCH path still only persists
> annotations when Hardcover is enabled (we kept the existing gating).
> Sub-project (2) lifts that gating so test 1 captures the annotation
> *unconditionally*. Until (2) ships, test 1 may yield `annotation`
> COUNT=0 — that's expected.

## Test 2 — Hardcover ENABLED: annotation pushed + sync_target row created

1. In admin → Hardcover, enable "Annotation sync" and save your token.
2. Add another highlight to the same book ("decouple-test-2") on the
   Kobo. Sync.
3. On the host:
   ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT target, status, target_record_id FROM annotation_sync_target;"
   ```
   ✅ One row: `('hardcover', 'synced', '<numeric-id>')`.
4. Open hardcover.app, navigate to the book. Verify the journal entry
   exists with the highlighted text.

## Test 3 — Delete on Kobo transitions sync_target to tombstone

5. On the Kobo, **delete the highlight** you added in test 2. Sync.
6. ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT annotation_id, status FROM annotation_sync_target;"
   ```
   ✅ Status: `'tombstone'`.
7. On hardcover.app, the journal entry for test 2 is gone.

## Test 4 — Tombstone is terminal

8. On the Kobo, re-create the highlight (same passage, same colour).
   Sync.
9. ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT annotation_id, source, COUNT(*) OVER () AS total_anns FROM annotation;"
   ```
   ✅ A NEW annotation row exists with a fresh `annotation_id` (Kobo
   issues a new UUID for re-created highlights).
10. ```bash
    docker exec cwn-local sqlite3 /config/app.db \
      "SELECT annotation_id, target, status FROM annotation_sync_target ORDER BY id;"
    ```
    ✅ The tombstoned row from test 3 is still `'tombstone'`.
    ✅ A new sync_target row exists for the new annotation with
       `status='synced'`.

## Test 5 — Migration ran cleanly (one-time, on first boot of this branch)

```bash
docker logs cwn-local --since 24h 2>&1 | grep "annotation-decouple-migration"
```

✅ Expect exactly ONE pair of lines on first boot:
- `[annotation-decouple-migration] starting`
- `[annotation-decouple-migration] complete: N sync_target rows backfilled, M source values corrected`

On every boot AFTER the first:
- `[annotation-decouple-migration] target schema already in place; skip`

## On failure

Capture:
```bash
docker logs cwn-local --since 10m > /tmp/kobo-verify-fail.log
docker exec cwn-local sqlite3 /config/app.db \
  ".dump annotation annotation_sync_target" > /tmp/kobo-verify-fail.sql
```

Open a GitHub issue with these artifacts + the failing step number.
