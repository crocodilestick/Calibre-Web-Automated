# Annotation two-way sync — Phase 1 (web-reader create) + Phase 2 (KOReader bridge)

Status: design — awaiting operator approval before implementation
Author: new-usemame
Date: 2026-05-25
Parents:
- `notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md` (the 5-edge matrix; Phase 1/2/3 plan)
- `notes/2026-05-21-annotation-decouple-source-target-DESIGN.md` (the `annotation` + `annotation_sync_target` model + dispatcher this builds on)
- `notes/KOBO-PROTOCOL-REFERENCE.md` §10.1 (Kobo `Bookmark` kepub field format)

## 0. Where we are (shipped) vs. what this adds

Shipped through v4.0.135: Kobo device → server capture (live reading-services
tap + USB `KoboReader.sqlite` import), server → web-reader render (epub.js
overlays + PDF/comic), per-book view + Markdown/CSV/JSON export, Hardcover push
as a sync target. The `annotation` table stores Kobo-native position fields +
a computed `cfi_range`; `annotation_sync_target` tracks per-destination state.

Two edges of the 5-edge matrix are still open:

| Edge | Direction | Status before this work | This work |
|---|---|---|---|
| 1 | Web reader → Server (create) | ❌ render-only, no create endpoint | **Phase 1** |
| 5 | Server ↔ KOReader-on-Kobo (→ Nickel) | ❌ plugin is progress-only | **Phase 2** |

Edge 4 (Server → stock Nickel directly) stays out of scope — Kobo's closed
protocol blocks it; Phase 2's KoboReader.sqlite bridge is the sanctioned path
to get a server/web highlight onto a Kobo.

This is two independent sub-projects sharing one data model. They can ship in
either order. Phase 1 is self-contained and lower-risk; Phase 2 touches a
device system DB and is gated on real-hardware verification.

## 1. Decisions locked with the operator (2026-05-25)

1. **Phase 2 = generic transport, Kobo target first.** The server annotation
   API + the plugin's transport are device-agnostic; the *device-write target*
   is a pluggable provider, and we implement the `KoboReader.sqlite` provider
   first (the only path to stock Nickel). KOReader-native (`.sdr` sidecar,
   works on Android/Kindle/etc.) is a later provider behind the same seam.
2. **Phase 1 = full create + edit + delete** in the web reader.
3. **Phase 2 "done" blocks on real-device verification.** Everything testable
   without hardware is automated (server endpoints in pytest, plugin logic in
   the busted Lua suite, web-create flow in Playwright). The
   `KoboReader.sqlite` ↔ Nickel round-trip is verified on a physical Kobo
   before Phase 2 is called complete; a turnkey checklist makes that one sweep.

## 2. Model reuse — no schema change for Phase 1; one nullable column for Phase 2

The `annotation` model (`cps/ub.py`) already carries everything Phase 1 needs:
`source` accepts `'webreader'` (validator `_VALID_SOURCES`), the Kobo-native
position columns round-trip a web selection, `cfi_range` is computed on read by
`_ensure_cfi_range`, `hidden` is the soft-delete flag. **Phase 1 needs no
migration.**

Phase 2 adds **one** nullable column to `annotation`:

```python
device_origin_id = Column(String, nullable=True)
# Opaque per-device id of the row the KOReader plugin last wrote/saw for this
# annotation (e.g. the KoboReader.sqlite Bookmark.BookmarkID it created). Lets
# the plugin dedup + avoid feedback loops without the server caring which
# device kind it is. NULL for annotations no device has materialized yet.
```

Migration: a single idempotent `ALTER TABLE annotation ADD COLUMN
device_origin_id` guarded by `PRAGMA table_info(annotation)` — same pattern as
the v4.0.131 polymorphic hotfix (`migrate_annotation_polymorphic_position`),
which learned the hard way to use PRAGMA over the stale SQLAlchemy inspector.
Nullable, so zero data risk; teenyverse + existing installs no-op-add it on
boot.

`source='koreader'` is already a valid value — annotations the plugin pushes
land with that origin.

## 3. Phase 1 — web-reader create / edit / delete

### 3.1 Endpoints (new, in `cps/annotations.py`)

All `@user_login_required`, all per-user-scoped, all CSRF-protected (the
blueprint is under Flask-WTF's global middleware; the reader sends the token —
see §3.3).

```
POST   /annotations/<int:book_id>                  -> create  (201 + row json)
PATCH  /annotations/<int:book_id>/<annotation_id>  -> edit color/note (200)
DELETE /annotations/<int:book_id>/<annotation_id>  -> soft-delete hidden=True (200)
```

**Create** request body (produced by the reader from the live kepub DOM):

```json
{
  "start_kobospan": "kobo.4.1", "start_offset": 0,
  "end_kobospan":   "kobo.4.2", "end_offset": 116,
  "content_id": "<book_uuid>!!chapter6.html",
  "highlighted_text": "…", "highlight_color": "yellow", "note_text": null
}
```

Server create logic:
- `annotation_id = "cwn-web-" + uuid4().hex` (origin-tagged, collision-free,
  distinguishable from Kobo's device UUIDs in logs/exports).
- `start_container_path = "span#" + start_kobospan` (unescaped dots; the stored
  form `_extract_kobospan_id` already parses, and the data.json projection
  re-derives `start_kobospan` from it — symmetry verified against the existing
  `_data_json_row`). `start_container_child_index = -99` (the kepub selector
  sentinel, matching what Kobo writes, so `kobo_position.compute_cfi_range`
  takes the KoboSpan path).
- `source='webreader'`, `hidden=False`, `position_type` left NULL (= EPUB CFI).
- Compute + persist `cfi_range` via `compute_cfi_range` (reuse `_resolve_epub_path`
  + `_ensure_cfi_range` plumbing). If it can't resolve, store NULL — the row
  still renders (the reader rebuilds the CFI client-side from the KoboSpan id;
  that's the whole point of the #317 architecture) and still exports.
- `highlighted_text` is validated against the resolved span text server-side
  when possible (defense against a tampered client); on mismatch we store what
  the client sent but log a warning (the client read the live DOM, we trust it
  but record divergence).
- Optional Hardcover fan-out: if `config.config_hardcover_annotations_sync` is
  on, push the freshly-created row to Hardcover via the existing
  `annotation_sync` Hardcover handler (the row is created directly, then handed
  to `handler.push` + an `AnnotationSyncTarget` upsert — the same persistence
  the dispatcher does) so a web highlight also reaches Hardcover. Included.

**Edit** — only `highlight_color` and `note_text` are mutable. Position is
immutable once set (design §5 of the parent decouple doc). `last_synced`
bumps. If a Hardcover sync_target exists, re-push via its handler so the note
updates remotely.

**Delete** — set `hidden=True` (reuse the exact soft-delete semantics of
`dispatch_annotation_deletes`); transition any non-tombstone sync_target via
its handler. Idempotent: deleting an already-hidden row is a 200 no-op.

Ownership: every route resolves the row by `(current_user.id, book_id,
annotation_id)`; a mismatch is a 404, never another user's row (IDOR guard,
mirrors `_load_user_annotations`).

### 3.2 Reader UI (`cps/static/js/reading/annotations.js`, extended)

The file already renders overlays + a sidebar + click-to-navigate, and already
walks text nodes inside koboSpans (`locateOffset`). Phase 1 adds the inverse:

- **Selection → anchor.** Hook epub.js `rendition.on("selected", (cfiRange,
  contents) => …)` (primary) with a `selectionchange`/`mouseup` listener on
  each rendered `contents.document` as a fallback. On a non-collapsed
  selection, take the Range, walk each endpoint up to its nearest ancestor
  `span.koboSpan[id^="kobo."]`, and compute the character offset within that
  span (the inverse of `locateOffset` — sum text-node lengths up to the
  endpoint). Yields `{start_kobospan, start_offset, end_kobospan, end_offset}`
  + `content_id` from the section href + `highlighted_text` from
  `range.toString()`.
- **Create popup.** A small popup near the selection: four color swatches
  (yellow/red/green/blue — the set Kobo round-trips), an optional note field, a
  Save button. Save → `POST` → on success, push the row into `allRows`, call
  the existing `applyToContents` to paint it immediately (no reload), and add
  the sidebar entry.
- **Edit/delete popup.** epub.js fires a click callback on a highlight (the 3rd
  arg to `annotations.highlight`). Wire it to a popup with the current color
  swatches + note + a Delete button. Edit → `PATCH`; Delete → `DELETE` +
  `rendition.annotations.remove(cfi, "highlight")` + drop from `allRows`/sidebar.
- Selections that don't resolve to a koboSpan (e.g. a non-kepub render path)
  disable the Save button with a tooltip rather than failing silently.

Styling lives in `reader.css`/a small injected block; the popup reuses existing
`.cwa-annotation-*` color tokens.

### 3.3 CSRF

`read.html` is a standalone page (does **not** extend `layout.html`, so the
global fetch shim that auto-adds `X-CSRFToken` is absent) but it already renders
`<input name="csrf_token" value="{{ csrf_token() }}">` (line 26). `annotations.js`
reads that input once and sets `X-CSRFToken` on every mutating fetch. GET
`data.json` stays unauthenticated-of-CSRF (idempotent).

### 3.4 Phase 1 tests

Unit (`tests/unit/`):
- `test_annotations_create_endpoint.py` — create returns 201 + correct row;
  `source='webreader'`; `annotation_id` prefix; `start_container_path` round-
  trips through `_extract_kobospan_id`; `cfi_range` computed when the kepub is
  present, NULL-tolerant when not; bad/empty body → 400; another user's book →
  404.
- `test_annotations_edit_delete_endpoint.py` — PATCH mutates only color/note,
  position immutable; DELETE sets `hidden=True` and the row drops out of
  `_load_user_annotations` + `data.json`; idempotent re-delete; IDOR (user B
  can't touch user A's annotation_id) → 404.
- `test_annotations_create_csrf.py` — POST without token → 400/403; with token
  → ok.
- `test_annotations_webreader_hardcover_fanout.py` — with Hardcover annotation
  sync on, a created web highlight produces a `synced` sync_target (mocked
  client); with it off, no sync_target row.

Playwright (`tests/playwright/`, JPEG capture, **the user-flow gate**):
- Login → open `/read/<id>/epub` (served as kepub) → select a sentence →
  Save yellow highlight → screenshot overlay painted → reload → overlay still
  there (persisted + re-resolved) → click highlight → change to green + add a
  note → screenshot → delete → screenshot gone → confirm `data.json` count.
- Cross-check: the same highlight appears on the `/annotations/<book>` view
  page with `source: webreader`, and in the Markdown export.

## 4. Phase 2 — KOReader plugin annotation bridge (generic transport, Kobo first)

### 4.1 Server annotation API (device-agnostic), in the kosync package

New routes alongside the existing progress sync, reusing its auth + book
resolution verbatim (`authenticate_user()`, `is_koreader_sync_enabled()` gate,
`get_book_by_checksum(document)`), all `@csrf.exempt` (device clients):

```
GET /kosync/syncs/annotations/<document>   -> pull: annotations for the book the
                                              digest resolves to (server→device)
PUT /kosync/syncs/annotations              -> push: device-created/changed/deleted
                                              annotations (device→server)
```

These live in a new `cps/progress_syncing/protocols/koreader_annotations.py`
registered on the same `kosync` blueprint (keeps `kosync.py` from sprawling;
imports the shared helpers). `<document>` is the KOReader partial-MD5 digest;
`get_book_by_checksum` maps it → `book_id`, exactly as progress sync does, so
annotations converge on the same calibre book across formats/checksums.

**Pull** response — the portable annotation shape (device-kind-agnostic; the
plugin's provider maps it to KoboReader.sqlite fields):

```json
{ "document": "<digest>", "calibre_book_id": 42, "book_uuid": "<uuid>",
  "annotations": [
    { "annotation_id": "cwn-web-…", "highlighted_text": "…", "note_text": null,
      "color": "yellow", "content_id": "<uuid>!!chapter6.html",
      "start_kobospan": "kobo.4.1", "start_offset": 0,
      "end_kobospan": "kobo.4.2", "end_offset": 116,
      "context_string": "…", "chapter_progress": 0.41,
      "source": "webreader", "hidden": false, "last_synced": "…Z" } ] }
```

Only the current user's non-internal annotations for that book; includes
`hidden:true` rows so the device can delete locally (tombstone propagation).

**Push** request — same shape under `{"document":…, "annotations":[…]}`, each
carrying the device's `device_origin_id`. Server logic per row:
- Resolve book via digest. Upsert on `(user_id, annotation_id)` (the same
  race-safe path the dispatcher uses). New rows from the device land
  `source='koreader'` (or pass through `source='kobo'` when the plugin read a
  Nickel-authored bookmark out of KoboReader.sqlite — the plugin reports it).
- `hidden:true` in the payload → soft-delete (+ tombstone sync_targets), via
  the existing `dispatch_annotation_deletes` semantics.
- Record `device_origin_id` so the next pull can tell the plugin "you already
  have this one" and the plugin won't re-push a row the server gave it
  (feedback-loop guard, §4.4).
- Reuse `annotation_sync` so device-pushed highlights also fan out to Hardcover
  when enabled.

### 4.2 Plugin transport (`koreader/plugins/cwasync.koplugin`)

- `api.json` — add `pull_annotations` (`GET /syncs/annotations/:document`) and
  `push_annotations` (`PUT /syncs/annotations`) method specs.
- `CWASyncClient.lua` — add `pull_annotations(user, pass, document, cb)` and
  `push_annotations(user, pass, document, annotations, cb)`, mirroring the
  existing async-HTTP + Basic-auth `update_progress`/`get_progress` plumbing.
- `sync_logic.lua` — add pure, unit-testable functions: `diffAnnotations(local,
  remote)` → `{to_pull, to_push, to_delete}` keyed on `annotation_id`;
  `mergeAnnotation(local, remote)` → last-`last_synced`-wins per field (matches
  the parent doc §5 conflict rules). Pure tables in, pure tables out — no I/O —
  so the busted suite covers them fully.
- **Device-write provider seam.** A `device_annotations.lua` with a narrow
  interface — `read_all(document_ctx) -> list`, `apply(creates, updates,
  deletes)`, `available() -> bool` — and a first implementation
  `kobo_sqlite_provider.lua`. The plugin picks a provider at runtime
  (`available()`); on non-Kobo devices the Kobo provider returns false and
  annotation sync degrades to "server is source of truth, nothing to write
  locally" until a KOReader-native provider lands.

### 4.3 `KoboReader.sqlite` provider — safety first

The High-severity risk in the parent register ("plugin write corrupts the
device DB"). Mitigations, all enforced in `kobo_sqlite_provider.lua`:
- **Locate** `KoboReader.sqlite` at the device's `.kobo/KoboReader.sqlite`
  (Kobo-only path; `available()` is false if absent).
- **Back up first.** Copy to `KoboReader.sqlite.cwn-bak-<ts>` before the first
  write of a session; keep the last 3. A corrupt write is always recoverable by
  the user.
- **Reads** are plain `SELECT` on `Bookmark` (the schema in protocol-ref §10.1).
- **Writes** are `INSERT OR IGNORE` (idempotent on `BookmarkID`) inside a single
  transaction; never `UPDATE`/`DELETE` Nickel's own rows in the first cut —
  deletes are honored server-side and reflected as `hidden`, but we do **not**
  delete device rows until the round-trip is hardware-proven (deferred toggle).
- Synthesize the `Bookmark` row from the portable shape: `BookmarkID` = our
  `annotation_id`, `VolumeID` = book uuid, `ContentID`, `StartContainerPath` =
  `span#kobo\.X\.Y` (re-escape dots), `StartContainerChildIndex = -99`,
  offsets, `Text`, `Annotation` (note), `Color` = named→int (yellow0/red1/
  green2/blue3; other→0), `ContextString`, `Type='highlight'`, timestamps.
- Settings toggle (default **off**): "Sync highlights (experimental, Kobo
  only)" in the plugin menu, with a one-line "writes to your Kobo's database;
  a backup is made first" note. Opt-in until hardware-verified.

### 4.4 Conflict + feedback-loop handling

- **Identity**: `annotation_id` is the cross-system key (BookmarkID for Kobo
  rows, `cwn-web-*` for web rows). `(user_id, annotation_id)` uniqueness makes
  every upsert idempotent.
- **No echo**: the plugin records each row's `device_origin_id`; on the next
  cycle, a server row whose `device_origin_id` matches what the device already
  has is not re-applied, and a device row already known to the server is not
  re-pushed. Prevents the Nickel→server→Nickel loop.
- **Field conflicts**: last-`last_synced`-wins per field (`sync_logic.merge`).
  Position is immutable. Hidden propagates (a delete from any side wins).

### 4.5 Phase 2 tests

Automated (run in CI, must be green to reach the device gate):
- pytest `test_koreader_annotations_pull.py` / `_push.py` — auth required;
  digest→book resolution; pull returns only the user's rows incl. hidden;
  push upserts (`source='koreader'`), soft-deletes on `hidden`, records
  `device_origin_id`, Hardcover fan-out when enabled; malformed payload → 400;
  unknown digest → empty/!match handled.
- pytest `test_annotation_device_origin_migration.py` — the `ADD COLUMN`
  migration is idempotent (PRAGMA-guarded), no-ops when present, adds when
  absent (reproduces the v4.0.131 stale-inspector trap as a regression).
- busted `tests/sync_logic_test.lua` (extended) + a new
  `device_annotations_test.lua` — `diffAnnotations` / `mergeAnnotation` truth
  table (create/update/delete/no-echo/conflict); `kobo_sqlite_provider`
  field-mapping (named→int color, dot re-escaping, `-99` sentinel, `INSERT OR
  IGNORE` idempotency) against an in-memory SQLite fixture.

Manual, on hardware (**the Phase 2 completion gate** — operator runs once):
- New `notes/feat-annotation-koreader-bridge-device-verification.md`, mirroring
  the existing decouple checklist: install plugin on a Kobo running KOReader →
  create a highlight in the web reader → plugin pull → confirm a `Bookmark`
  row appears in `KoboReader.sqlite` → open the book in **Nickel** → highlight
  shows → create one on the device in KOReader → plugin push → appears in the
  web reader. Backup-file presence checked. DB integrity (`PRAGMA
  integrity_check`) clean before/after.

## 5. Risk register (delta over the parent doc)

| Risk | Sev | Mitigation |
|---|---|---|
| Web selection doesn't map to a koboSpan (non-kepub render) | Low | Save disabled w/ tooltip; reader always serves kepub for annotated books (#317) |
| Tampered create payload (text/offset mismatch, foreign book) | Low | Server validates ownership (404) + span text (warn-log divergence); offsets clamped |
| Plugin write corrupts `KoboReader.sqlite` | **High** | Backup-before-write; `INSERT OR IGNORE` only; no device deletes in v1; opt-in toggle; `integrity_check` in the checklist; **gated on real-device verification** |
| Feedback loop Nickel↔server↔Nickel | Med | `device_origin_id` echo-suppression + `annotation_id` idempotency |
| KOReader can't safely touch `KoboReader.sqlite` at all | Med | This is the protocol-ref §12 open unknown; the hardware gate answers it before we ship the device-write on by default |
| `device_origin_id` migration silently inert (the v4.0.130 trap) | Med | PRAGMA-guarded idempotent ADD COLUMN + regression test reproducing the stale-inspector failure |

## 6. Scope boundaries

In scope: §3 (Phase 1 full CRUD + reader UI + tests) and §4 (Phase 2 server
API + plugin transport + KoboReader.sqlite provider + automated tests + device
checklist), plus the one nullable column + its migration.

Out of scope (later, behind the seams built here): KOReader-native `.sdr`
provider (cross-engine xpointer mapping); device-side deletes of Nickel rows;
async background sync worker; sharing annotations between users; Readwise/Notion
targets. Edge 4 (direct server→Nickel) remains permanently out (protocol).

## 7. Acceptance criteria

Phase 1 done when: migration-free; unit + CSRF + Hardcover-fanout tests green;
Playwright proves select→save→reload-persist→edit→delete in a real browser;
web highlight shows on the view page + Markdown export with `source=webreader`;
container healthy, logs clean, CHANGES row with SHA+tag; i18n for any new
user-facing strings (pybabel extract → translate household locales → compile →
`test_translations_compile.py`).

Phase 2 done when: `ADD COLUMN` migration idempotent + regression-tested; pull/
push pytest green; busted Lua suite green; **and** the on-device
`KoboReader.sqlite` ↔ Nickel round-trip checklist passes on physical hardware
with `integrity_check` clean and a backup present. Until the hardware sweep
passes, Phase 2 is not complete and the device-write toggle ships **off**.

## 8. Implementation order

1. This spec approved + committed.
2. `writing-plans`: TDD-ordered plan.
3. Phase 1: endpoints (RED→GREEN) → reader UI → Playwright → i18n.
4. Phase 2: `device_origin_id` column + migration + regression test → server
   pull/push endpoints (RED→GREEN) → plugin `api.json`/client/sync_logic →
   `device_annotations` seam + `kobo_sqlite_provider` → busted tests.
5. Full enterprise verification (container rebuild, HTTP probes, log scan, live
   web-create flow, restart-idempotency) + CHANGES rows.
6. Operator runs the on-device Phase 2 checklist; flip the device-write toggle
   default only after it passes.
