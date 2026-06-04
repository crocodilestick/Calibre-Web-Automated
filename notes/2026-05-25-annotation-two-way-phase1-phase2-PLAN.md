# Annotation two-way (Phase 1 + Phase 2) — Implementation Plan

> Execute-in-session plan (inline, TDD). Design of record:
> `notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md`. Steps are
> checkbox-tracked; each task ends at a green test + a commit.

**Goal:** Ship web-reader highlight create/edit/delete (Phase 1) and the
KOReader→KoboReader.sqlite annotation bridge (Phase 2, generic transport, Kobo
target first), fully tested except the on-device round-trip (operator gate).

**Tech:** Flask blueprint routes (`cps/annotations.py`), epub.js reader JS
(`cps/static/js/reading/annotations.js`), SQLAlchemy model/migration
(`cps/ub.py`), kosync Flask routes (`cps/progress_syncing/protocols/`), Lua
KOReader plugin (`koreader/plugins/cwasync.koplugin`), pytest + busted +
Playwright.

---

## File map

**Phase 1**
- Modify `cps/annotations.py` — add create/edit/delete routes + helpers.
- Modify `cps/static/js/reading/annotations.js` — selection→anchor, create/edit/delete popups, CSRF.
- Modify `cps/templates/read.html` — popup markup container (+ existing csrf input reused).
- Create `tests/unit/test_annotations_create_endpoint.py`
- Create `tests/unit/test_annotations_edit_delete_endpoint.py`
- Create `tests/unit/test_annotations_create_csrf.py`
- Create `tests/playwright/test_webreader_annotation_crud.py` (+ harness if absent)

**Phase 2**
- Modify `cps/ub.py` — `Annotation.device_origin_id` column + `migrate_annotation_device_origin()` (PRAGMA-guarded), call from `migrate_Database()`.
- Create `cps/progress_syncing/protocols/koreader_annotations.py` — `GET/PUT /kosync/syncs/annotations`, registered on the `kosync` blueprint.
- Modify `cps/progress_syncing/protocols/kosync.py` (or `main.py`) — register the new routes (import into the kosync blueprint module).
- Create `cps/services/annotation_portable.py` — portable annotation <-> Annotation row projection (shared by Phase 2 endpoints + reused shape).
- Modify `koreader/plugins/cwasync.koplugin/api.json` — `pull_annotations`, `push_annotations`.
- Modify `koreader/plugins/cwasync.koplugin/CWASyncClient.lua` — the two client methods.
- Modify `koreader/plugins/cwasync.koplugin/sync_logic.lua` — `diffAnnotations`, `mergeAnnotation`.
- Create `koreader/plugins/cwasync.koplugin/device_annotations.lua` — provider seam.
- Create `koreader/plugins/cwasync.koplugin/kobo_sqlite_provider.lua` — KoboReader.sqlite read/write.
- Modify `koreader/plugins/cwasync.koplugin/main.lua` — settings toggle + sync wiring.
- Create `tests/unit/test_koreader_annotations_endpoints.py`
- Create `tests/unit/test_annotation_device_origin_migration.py`
- Create `tests/unit/test_annotation_portable.py`
- Modify/Create `koreader/plugins/cwasync.koplugin/tests/sync_logic_test.lua` + `device_annotations_test.lua`
- Create `notes/feat-annotation-koreader-bridge-device-verification.md` (operator gate)

---

## Phase 1 tasks

### P1-T1: create endpoint (RED→GREEN)
- [ ] Write `tests/unit/test_annotations_create_endpoint.py`: POST valid body → 201; row has `source='webreader'`, `annotation_id` startswith `cwn-web-`, `start_container_path == "span#kobo.4.1"`, offsets stored, `hidden False`; `_extract_kobospan_id(row.start_container_path) == "kobo.4.1"`; foreign book_id → 404; empty/missing anchors → 400.
- [ ] Run → fails (route 404 / helper missing).
- [ ] Implement `POST /annotations/<int:book_id>` in `cps/annotations.py` + `_create_annotation_from_payload` helper (uuid, span path, source, cfi compute via `_ensure_cfi_range`).
- [ ] Run → green. Commit `feat(annotations): web-reader create endpoint (Phase 1)`.

### P1-T2: edit + delete endpoints (RED→GREEN)
- [ ] Write `tests/unit/test_annotations_edit_delete_endpoint.py`: PATCH changes color+note only (position unchanged); DELETE sets `hidden=True`, row drops from `_load_user_annotations`; idempotent re-DELETE → 200; user B PATCH/DELETE on user A annotation_id → 404.
- [ ] Run → fails.
- [ ] Implement `PATCH`/`DELETE …/<annotation_id>`.
- [ ] Run → green. Commit `feat(annotations): web-reader edit + soft-delete (Phase 1)`.

### P1-T3: CSRF + Hardcover fan-out
- [ ] Write `tests/unit/test_annotations_create_csrf.py` (no token → 400/403; token → ok) and a fan-out test (Hardcover annotation sync on → `synced` sync_target via mocked client; off → none).
- [ ] Run → fails.
- [ ] Wire fan-out (call HardcoverHandler.push + AnnotationSyncTarget upsert when enabled); confirm CSRF behavior (already enforced by global middleware — assert it).
- [ ] Run → green. Commit `test(annotations): csrf + hardcover fan-out for web create`.

### P1-T4: reader UI
- [ ] Extend `annotations.js`: `selectionToAnchor(range, contents)`; create popup (4 swatches + note + save) on epub.js `selected` (+ mouseup fallback); edit/delete popup on highlight click; CSRF header from read.html input; optimistic paint via `applyToContents`.
- [ ] Add popup container markup to `read.html`.
- [ ] Commit `feat(reader): select-to-highlight create/edit/delete UI (Phase 1)`.

### P1-T5: Playwright e2e (user-flow gate)
- [ ] `tests/playwright/test_webreader_annotation_crud.py`: login → open kepub reader → select → save yellow → screenshot overlay → reload → overlay persists → click → recolor green + note → screenshot → delete → screenshot gone → assert `data.json` count + view page shows `source: webreader`.
- [ ] Run against `cwn-local`. Commit `test(playwright): web-reader annotation CRUD e2e`.

### P1-T6: i18n + verification
- [ ] Wrap new user-facing strings; `scripts/compile_translations.sh`; add household locales; `tests/unit/test_translations_compile.py` green.
- [ ] Container rebuild + HTTP probe + log scan (per CLAUDE.md enterprise standard).
- [ ] CHANGES-vs-upstream row (after squash SHA known).

---

## Phase 2 tasks

### P2-T1: device_origin_id column + migration (RED→GREEN)
- [ ] Write `tests/unit/test_annotation_device_origin_migration.py`: bare table → column added; already-present → no-op (reproduces v4.0.131 stale-inspector trap via PRAGMA); model has attribute.
- [ ] Run → fails.
- [ ] Add `Annotation.device_origin_id` + `migrate_annotation_device_origin(engine)` (PRAGMA table_info guard, per-stmt try/except), call from `migrate_Database()`.
- [ ] Run → green. Commit `feat(annotation): device_origin_id column + idempotent migration (Phase 2)`.

### P2-T2: portable projection (RED→GREEN)
- [ ] Write `tests/unit/test_annotation_portable.py`: `to_portable(row)` emits the §4.1 shape (color, start_kobospan from path, offsets, content_id, hidden, source); `from_portable(payload, user, book)` builds/updates a row with right source + device_origin_id; unicode/None safe.
- [ ] Run → fails.
- [ ] Implement `cps/services/annotation_portable.py`.
- [ ] Run → green. Commit `feat(annotation): portable annotation projection (Phase 2)`.

### P2-T3: server pull/push endpoints (RED→GREEN)
- [ ] Write `tests/unit/test_koreader_annotations_endpoints.py`: auth required (401 w/o Basic); GET resolves digest→book via `get_book_by_checksum`, returns only this user's rows incl hidden; PUT upserts (`source='koreader'`), soft-deletes on `hidden`, records `device_origin_id`, Hardcover fan-out when on; malformed → 400; unknown digest → empty.
- [ ] Run → fails.
- [ ] Implement `koreader_annotations.py` (`GET/PUT /kosync/syncs/annotations`), reuse `authenticate_user`/`is_koreader_sync_enabled`/`get_book_by_checksum`; register on blueprint.
- [ ] Run → green. Commit `feat(kosync): device-agnostic annotation pull/push API (Phase 2)`.

### P2-T4: plugin transport (Lua) + busted tests
- [ ] `sync_logic.lua`: `diffAnnotations(local, remote)` + `mergeAnnotation(a,b)` (last-synced-wins, hidden propagates, position immutable). busted truth table in `tests/sync_logic_test.lua`.
- [ ] `device_annotations.lua` seam + `kobo_sqlite_provider.lua` (read SELECT; write INSERT OR IGNORE w/ backup; named→int color; dot re-escape; -99 sentinel; Type='highlight'). busted `device_annotations_test.lua` against in-memory sqlite.
- [ ] `api.json` + `CWASyncClient.lua` pull/push methods (mirror async-HTTP plumbing).
- [ ] `main.lua` settings toggle (default off) + sync-on-close wiring guarded by toggle + provider.available().
- [ ] Run busted → green. Commit `feat(koreader-plugin): annotation bridge transport + Kobo provider (Phase 2)`.

### P2-T5: device verification checklist + gate
- [ ] Write `notes/feat-annotation-koreader-bridge-device-verification.md` (install plugin → web-create → pull → Bookmark row in KoboReader.sqlite → Nickel shows it → device-create → push → web reader shows it; backup present; `PRAGMA integrity_check` clean).
- [ ] Coordinate with operator for the hardware run. Device-write toggle default stays OFF until pass.

---

## Self-review (against spec, run after writing this plan)
- Spec coverage: edge 1 → P1-T1..T5; edge 5 → P2-T1..T5; device_origin_id → P2-T1; safety → P2-T4; i18n/verify → P1-T6 + Phase-2 verification. ✓
- No silent gaps: Hardcover fan-out (P1-T3), IDOR (P1-T1/T2), feedback-loop device_origin_id (P2-T2/T3/T4). ✓
- Naming consistency: `device_origin_id`, `cwn-web-`, `span#kobo.x.y`, `to_portable`/`from_portable`, `diffAnnotations`/`mergeAnnotation` used consistently across tasks. ✓
