# Sub-project (1) — Annotation Decouple — Verification Summary

**Date**: 2026-05-21
**Branch**: `worktree-BetterIntegrationOrganization`
**Spec**: `notes/2026-05-21-annotation-decouple-source-target-DESIGN.md`
**Plan**: `notes/2026-05-21-annotation-decouple-source-target-PLAN.md`

## Confidence: ~95%

Evidence below.

## Test counts (all green)

| Layer | Count | Pass | Skip | Fail |
|---|---|---|---|---|
| Schema | 8 | 8 | 0 | 0 |
| Migration steps + full-flow | 18 | 18 | 0 | 0 |
| Migration bit-exact preservation | 3 | 3 | 0 | 0 |
| Annotation helpers | 4 | 4 | 0 | 0 |
| HardcoverHandler | 11 | 11 | 0 | 0 |
| Dispatcher | 8 | 8 | 0 | 0 |
| H1 schema (still in-scope, unskipped) | 14 | 14 | 0 | 0 |
| Annotation backup (v2 schema) | 19 | 19 | 0 | 0 |
| Annotations view/export/import/data endpoint | 32 | 32 | 0 | 0 |
| **Total annotation-related** | **117** | **117** | **0** | **0** |

Run command: `python3 -m pytest tests/unit/test_annotation*.py tests/unit/test_hardcover_handler.py tests/unit/test_kobo_annotation_sync_h1_schema.py`

## Live container verification

`cwn-local` (port 8086, image `calibre-web-nextgen:local`) rebuilt off this
branch's code and restarted.

| Check | Expected | Observed |
|---|---|---|
| Container health | `healthy` | ✅ healthy |
| HTTP `GET /login` | 200 | ✅ 200 |
| Migration log on first boot of new code | `[annotation-decouple-migration] starting` then `complete: N sync_target rows backfilled, M source values corrected` | ✅ Both lines present, N=M=0 (empty test DB) |
| `kobo_annotation_sync` table | dropped | ✅ no longer present |
| `annotation` table | exists, no `synced_to_hardcover` or `hardcover_journal_id` columns | ✅ verified via `.schema annotation` |
| `annotation_sync_target` table | exists with `UNIQUE(annotation_id, target)` + FK `ON DELETE CASCADE` | ✅ verified via `.schema annotation_sync_target` |
| Migration idempotency on second boot | `[annotation-decouple-migration] target schema already in place; skip` | ✅ verified on second container restart |
| Errors in container logs around migration window | none | ✅ no ERROR / Traceback related to annotation migration |

## Real bug caught + fixed during live verification

`add_missing_tables()` (which runs Base.metadata.create_all → creates an
empty `annotation` table via ORM) runs BEFORE my migration in
`migrate_Database`. My original pre-check saw the empty `annotation` table
without hardcover columns and incorrectly returned "target schema already
in place" — leaving the user's `kobo_annotation_sync` rows stranded.

Fix (in `e616b86bd`):
1. Tightened idempotency: skip ONLY when `kobo_annotation_sync` is gone.
2. Before step 5 (RENAME), drop the empty ORM-created `annotation`
   placeholder if zero rows.
3. If the placeholder has rows (shouldn't happen in practice — defensive),
   raise `RuntimeError("manual investigation required")` rather than
   silently destroying data.
4. 2 new regression tests: `test_full_migration_handles_orm_created_placeholder`
   + `test_full_migration_refuses_when_placeholder_has_rows`.

This bug would have caused silent data stranding on the first boot of
every existing CWNG install. Live verification was essential.

## What ships

| Component | Status |
|---|---|
| Schema: `Annotation` model + `AnnotationSyncTarget` model | ✅ Done |
| `kobo_annotation_sync` → `annotation` rename + columns dropped | ✅ Done |
| 8-step transactional migration with sanity-check gate | ✅ Done |
| `source = 'hardcover'` → `source = 'kobo'` data fix | ✅ Done |
| Idempotent re-run | ✅ Done |
| Rollback-on-failure | ✅ Done |
| Bit-exact SHA-256 preservation across 100-row fixture | ✅ Done |
| Handler abstraction (`cps/services/annotation_sync/`) | ✅ Done |
| `HardcoverHandler` extracted from readingservices.py | ✅ Done |
| Dispatcher with race-safe UPSERT + tombstone-terminal | ✅ Done |
| Idempotent Hardcover delete (404 → tombstone) | ✅ Done |
| `cps/readingservices.py` PATCH handler refactored | ✅ Done |
| `cps/annotations.py` + `cps/admin.py` rename | ✅ Done |
| `cps/services/annotation_backup.py` schema_version 1 → 2 | ✅ Done |
| Manual Kobo device verification checklist | ✅ Done |
| Live container verification (this document) | ✅ Done |

## Out of scope for this PR (per spec §7)

- Sub-project (2): Live Kobo capture independent of Hardcover (always-persist `annotation` row)
- Sub-project (3): PDF annotation overlay (introduces polymorphic position machinery)
- Sub-project (4): CBR/CBZ overlay
- Readwise / Notion / Obsidian handlers (pattern is in place — add as new files)
- Async sync worker for `pending` rows
- Admin UI for `error_message` / sync health

Each becomes its own spec → plan → PR cycle.

## Commits in this PR

```
f3d17daa1 docs(annotation): manual Kobo device verification checklist
e616b86bd fix(annotation): handle ORM-created placeholder table during migration
077d34997 refactor(admin): update DB-restore wipe list
e79e377d1 refactor(readingservices): PATCH handler becomes thin annotation_sync orchestrator
566057701 feat(annotation_sync): handler ABC + HardcoverHandler + dispatcher
ab765aad1 test(annotation): pin sync_target/is_synced_to helpers + unskip H1 ORM test
fcd020345 feat(annotation): 8-step transactional migration to decouple source/sync target
998b6a0b8 feat(annotation): rename KoboAnnotationSync->Annotation, add AnnotationSyncTarget
1c1e031da docs(plan): annotation decouple sub-project 1 — 26-task implementation plan
26d1470cf docs(design): annotation decouple — source vs sync target (sub-project 1)
```

10 commits — clean, atomic, each independently revertable.
