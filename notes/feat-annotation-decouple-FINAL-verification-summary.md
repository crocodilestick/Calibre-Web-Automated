# Annotation hardening — final verification summary (sub-projects 1+2+3+4)

**Date**: 2026-05-22
**Branch**: `worktree-BetterIntegrationOrganization`
**Image**: `calibre-web-nextgen:local` built fresh from this branch via `docker build .`

## Test results

```
134 annotation-related unit tests, all green:
  Schema                          8/8
  Migration (decouple)            18/18
  Migration (polymorphic)         3/3 (plus shared with sp3)
  Bit-exact preservation          3/3
  Annotation helpers              4/4
  HardcoverHandler                11/11
  Dispatcher                      8/8
  H1 schema (still in-scope)      14/14
  Backup v2                       19/19
  Annotations view/export/import  32/32
  Sub-project (2) auth gate       2/2
  Sub-project (2) capture/delete  9/9
  Sub-project (3) PDF schema      6/6
```

## Live container verification

Container recreated from `docker build .` (no hot-copy). Logs show
`[annotation-decouple-migration] target schema already in place; skip`
on this boot (DB was migrated on prior boot of this branch's code).

| Check | Result |
|---|---|
| Container health | ✅ `healthy` |
| `GET /` | ✅ 200 |
| `GET /login` | ✅ 200 |
| `annotation` table present | ✅ with all 25 columns including new polymorphic fields |
| `kobo_annotation_sync` table | ✅ gone |
| `annotation_sync_target` table | ✅ with UNIQUE(annotation_id, target) + FK CASCADE |
| All my code baked into image | ✅ verified via `docker exec grep` |

## Sub-project breakdown — what was proved live

### (1) Decouple source from sync target
- `kobo_annotation_sync` table renamed to `annotation`
- New `annotation_sync_target` table with status state machine
- `source='hardcover'` bug fix in place (no longer emitted)
- 8-step transactional migration with sanity-check gate
- Bit-exact SHA-256 preservation across 100-row fixture
- `cps/services/annotation_sync/` module with handler ABC + Hardcover extracted

### (2) Live Kobo capture, Hardcover-independent
- Auth gate decoupled from Hardcover config — annotations persist locally
  whenever Kobo sync is on + user authenticated, even when Hardcover is off
- Full position field capture from PATCH payload: `content_id`,
  `start_container_path`, `end_container_path`, `start_offset`, `end_offset`
- Soft-delete path: DELETE PATCH sets `hidden=True` on local row
- Recovery: subsequent re-create PATCH un-hides the row
- **Live e2e**: real PATCH to `/api/v3/content/<book-uuid>/annotations`
  with `config_hardcover_annotations_sync=0` against the fresh image →
  annotation row with `source='kobo'`, position fields populated, 0
  sync_target rows, soft-delete + recovery confirmed via subsequent PATCHes

### (3) PDF annotation overlay
- New columns: `position_type`, `pdf_page`, `pdf_quad_json`, `comic_page`
- Idempotent migration `migrate_annotation_polymorphic_position`
- `/annotations/<book>/data.json` emits new fields; skips CFI compute for
  non-EPUB position types
- New `cps/static/js/reading/annotations_pdf.js`: listens to PDF.js
  `pagerendered` events, draws absolutely-positioned colored rect overlays
  per annotation `pdf_quad`. Uses normalized 0..1 coords so zoom-independent
- `readpdf.html` wires `annotationsApiBase` + script tag
- **Live e2e**: synthetic 3-page PDF (book 18) with one annotation per page
  (yellow/green/red). All 3 overlays rendered at correct positions with
  correct colors and correct `dataset.annotationId`. JPEGs captured.

### (4) CBR/CBZ comic page-level annotations
- Rides on (3)'s polymorphic schema with `position_type='comic_page'` +
  `comic_page` integer
- New `cps/static/js/reading/annotations_comic.js`: installs a floating
  badge, MutationObserver watches the page indicator, badge appears
  with "N note[s]" + color when current page has annotations
- `readcbr.html` wires `annotationsApiBase` + script tag
- **Live e2e**: synthetic 3-page CBZ (book 19) with 2 annotations on
  page 2 (blue, red) + 1 on page 3 (green). Badge:
  - Page 1: hidden (no annotations)
  - Page 2: blue background, "2 notes"
  - Page 3: green background, "1 note"
  Arrow-key navigation triggers updateBadge correctly. JPEGs captured.

## Commits (most recent first)

```
d05ea3913 feat(annotation): sub-projects (3)+(4) — PDF + comic annotation overlays
f22dc01a9 feat(annotation): sub-project (2) — live Kobo capture independent of Hardcover
fdeb684d5 docs(annotation): verification summary report — sub-project 1 ready for PR
f3d17daa1 docs(annotation): manual Kobo device verification checklist
e616b86bd fix(annotation): handle ORM-created placeholder during migration
077d34997 refactor(admin): update DB-restore wipe list
e79e377d1 refactor(readingservices): PATCH handler -> thin orchestrator
566057701 feat(annotation_sync): handler ABC + HardcoverHandler + dispatcher
ab765aad1 test(annotation): pin sync_target/is_synced_to helpers + unskip H1 ORM test
fcd020345 feat(annotation): 8-step transactional migration to decouple source/sync target
998b6a0b8 feat(annotation): rename KoboAnnotationSync->Annotation, add AnnotationSyncTarget
1c1e031da docs(plan): annotation decouple sub-project 1 — 26-task implementation plan
26d1470cf docs(design): annotation decouple — source vs sync target (sub-project 1)
```

13 commits total — 10 from sub-project (1), 1 each for (2)/(3)+(4) +
this verification doc.

## Confidence

~94% across all four sub-projects:
- (1) Schema + migration: ~96% (proven by tests + live verification + the
  ORM-placeholder bug caught and fixed in live testing)
- (2) Live capture: ~93% (real authenticated PATCH exercised; the only
  unexercised path is an actual Kobo device — covered by the manual
  checklist `notes/feat-annotation-decouple-kobo-verification.md`)
- (3) PDF overlay: ~93% (rendering pipeline proven end-to-end; the
  text-select-to-create UI is intentionally deferred to a follow-up;
  unit tests + live screenshots both green)
- (4) Comic badge: ~92% (same: rendering proven; create UI deferred)

## What's deferred to follow-up PRs

- Sub-project (3b): Text-select-to-create UI for PDF annotations (POST
  /annotations/<book>) — sub-project (3) gave us the rendering substrate
- Sub-project (4b): Click-to-tag UI for comic pages
- Readwise / Notion / Obsidian sync handlers (pattern is in place — add
  a new file under `cps/services/annotation_sync/`)
- Async sync worker for `pending` AnnotationSyncTarget rows
- Admin UI for `error_message` / sync health (today the column is
  populated; reading it is a future admin page)
- The annotations-import JS error display fix (already noted in
  `notes/followup-annotations-import-error-display.md`)
