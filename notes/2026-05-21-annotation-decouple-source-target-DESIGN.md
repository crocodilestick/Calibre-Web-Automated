# Annotation: decouple origin from sync destination (sub-project 1)

Status: approved — implementation in progress
Author: new-usemame
Date: 2026-05-21
Parent: notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md (H1 phase work)
Project tracker: this is sub-project (1) of a 4-part annotation hardening effort.

## 1. Problem

The `kobo_annotation_sync` table conflates origin and destination on its `source`
column. Pre-H1 the table was Hardcover-sync-state bookkeeping. H1 (2026-05-18,
3 days before this spec) added position columns + a `source` field intended to
track origin (`kobo` / `webreader` / `koreader`), but the H1 migration backfilled
`source='hardcover'` on pre-H1 rows and the live PATCH writer in
`cps/readingservices.py:462` continues to write `source='hardcover'` for any
Kobo-origin annotation pushed through the Hardcover pipeline.

This blocks four follow-on sub-projects:

| Sub-project | Why blocked |
|---|---|
| (2) Live Kobo capture independent of Hardcover | Can't write origin='kobo' without conflicting with the Hardcover-as-source convention |
| (3) PDF annotation overlay | Web-reader-native highlights need origin='webreader' — schema must be source-clean |
| (4) CBR/CBZ overlay | Same as (3) |
| Future Readwise / Notion / Obsidian targets | No clean place to record "synced to X" without another ALTER TABLE per target |

## 2. Decision

Decouple origin from destination via an expand-contract refactor in one
migration. Concretely:

1. Rename `kobo_annotation_sync` → `annotation` (the table is no longer
   Kobo-specific; the name has been a known smell since the H1 work).
2. Rename `KoboAnnotationSync` → `Annotation` in Python.
3. Pull `synced_to_hardcover` + `hardcover_journal_id` columns OFF the
   annotation table.
4. Add a new `annotation_sync_target` table — one row per (annotation, target)
   destination, with a status state machine.
5. Fix the source bug: `source='hardcover'` → `source='kobo'` on all existing
   rows.
6. Refactor the Hardcover push logic from `cps/readingservices.py` into a
   dedicated handler module (`cps/services/annotation_sync/hardcover.py`)
   so future targets plug in as new files, not edits to a sprawling PATCH
   handler.

## 3. Architecture

### 3.1 Data model

#### `annotation` table (renamed + columns dropped)

```python
class Annotation(Base):
    __tablename__ = 'annotation'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    annotation_id = Column(String, nullable=False)   # origin's stable ID
    book_id = Column(Integer, nullable=False)
    source = Column(String, nullable=True)           # 'kobo' | 'webreader' | 'koreader'

    # Content
    highlighted_text = Column(String, nullable=True)
    highlight_color = Column(String, nullable=True)
    note_text = Column(String, nullable=True)

    # Position (Kobo-native; cfi_range is canonical web-reader form)
    content_id = Column(String, nullable=True)
    start_container_path = Column(Text, nullable=True)
    start_container_child_index = Column(Integer, nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_container_path = Column(Text, nullable=True)
    end_container_child_index = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    context_string = Column(Text, nullable=True)
    chapter_progress = Column(Float, nullable=True)
    cfi_range = Column(String, nullable=True)

    # Lifecycle
    hidden = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_synced = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sync_targets = relationship(
        "AnnotationSyncTarget",
        backref="annotation",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index('ix_annotation_user_annotation', 'user_id', 'annotation_id'),
        Index('ix_annotation_user_book', 'user_id', 'book_id'),
    )

    @validates('source')
    def _validate_source(self, _key, value):
        if value is not None and value not in {'kobo', 'webreader', 'koreader'}:
            raise ValueError(f"invalid source: {value!r}")
        return value

    def sync_target(self, target_name: str) -> Optional['AnnotationSyncTarget']:
        for st in self.sync_targets:
            if st.target == target_name:
                return st
        return None

    def is_synced_to(self, target_name: str) -> bool:
        st = self.sync_target(target_name)
        return st is not None and st.status == 'synced'
```

Columns REMOVED from the annotation table:
- `synced_to_hardcover` (moved to AnnotationSyncTarget.status)
- `hardcover_journal_id` (moved to AnnotationSyncTarget.target_record_id)

#### `annotation_sync_target` table (new)

```python
class AnnotationSyncTarget(Base):
    __tablename__ = 'annotation_sync_target'

    id = Column(Integer, primary_key=True, autoincrement=True)
    annotation_id = Column(
        Integer, ForeignKey('annotation.id', ondelete='CASCADE'), nullable=False,
    )
    target = Column(String, nullable=False)
    target_record_id = Column(String, nullable=True)
    status = Column(String, nullable=False)
    error_message = Column(Text, nullable=True)
    last_attempt = Column(DateTime, nullable=True)
    last_synced = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint('annotation_id', 'target', name='uq_ast_annotation_target'),
        Index('ix_ast_target_status', 'target', 'status'),
    )
```

#### Status state machine

```
            INITIAL  (no row in annotation_sync_target)
               |
               | dispatch_annotation_sync()
               v
       +-------+-------+-----+
       v       v       v     v
   pending  synced  failed  tombstone(*)
                                       (* INITIAL→tombstone never; tombstone only
                                          reached from synced/failed via delete)

   States:
     pending    — row exists, push not yet attempted (sub-project 2+ async worker)
     synced     — most recent push OK; target_record_id + last_synced set
     failed     — most recent push failed; error_message set; retry on next PATCH
     tombstone  — user deleted; remote deletion confirmed; terminal

   Transitions:
     INITIAL → synced     (push() returned status=synced)
     INITIAL → failed     (push() returned status=failed)
     failed → synced      (retry succeeded)
     failed → failed      (retry failed; error_message updated)
     synced → synced      (re-push after annotation update)
     synced/failed → tombstone   (delete() returned status=tombstone)
     tombstone → *        NEVER
```

### 3.2 Code structure

```
cps/
  ub.py                            # Annotation + AnnotationSyncTarget models;
                                   # migrate_annotation_decouple_source_target()
  readingservices.py               # thin orchestrator: calls annotation_sync.dispatch_*
  annotations.py                   # import path: ub.KoboAnnotationSync → ub.Annotation
  admin.py                         # wipe-list string update
  services/
    annotation_backup.py           # class rename; bump schema_version 1→2
    annotation_sync/               # NEW
      __init__.py                  # dispatch_annotation_sync, dispatch_annotation_deletes,
                                   #   register_handler, available_targets
      base.py                      # AnnotationSyncTargetHandler ABC + SyncResult dataclass
      hardcover.py                 # HardcoverHandler (extracted from readingservices.py)
```

### 3.3 Handler abstraction

```python
@dataclass(frozen=True)
class SyncResult:
    status: str                          # 'synced' | 'failed' | 'tombstone'
    target_record_id: Optional[str]
    error_message: Optional[str] = None


class AnnotationSyncTargetHandler(ABC):
    target_name: str

    @abstractmethod
    def is_enabled(self, user) -> bool: ...

    @abstractmethod
    def push(self, annotation, book, user) -> SyncResult: ...

    @abstractmethod
    def delete(self, sync_target, user) -> SyncResult: ...
```

Handlers are stateless: they receive ORM objects, make remote calls, return
results. The dispatcher owns DB persistence; handlers never write.

### 3.4 Dispatcher behaviour

`dispatch_annotation_sync(payload_annotations, book, user)`:

For each annotation in `payload_annotations`:
1. UPSERT `Annotation` row keyed on `(user_id, annotation_id)` with
   `source='kobo'`. This dispatcher is the **Kobo PATCH path** specifically —
   it's called from `readingservices.py:handle_annotations` which only
   receives Kobo-origin annotations. Webreader/koreader payloads will go
   through their own future entry points (sub-projects 3 + future KOReader
   work) and pass their own `source` value. UPSERT uses SQLite's
   `INSERT ... ON CONFLICT (user_id, annotation_id) DO UPDATE` so concurrent
   PATCH requests for the same annotation_id are race-safe at the SQL level,
   not just at the application level.
2. For each registered handler where `handler.is_enabled(user)`:
   a. Call `handler.push(annotation, book, user)`.
   b. UPSERT an `AnnotationSyncTarget` row keyed on `(annotation_id, target)`
      with the result.
3. Commit.

`dispatch_annotation_deletes(deleted_ids, user)`:

For each `annotation_id` in `deleted_ids`:
1. Look up the `Annotation` row.
2. For each `AnnotationSyncTarget` on it where `status != 'tombstone'`:
   a. Find the matching registered handler.
   b. Call `handler.delete(sync_target, user)`.
   c. UPDATE the sync_target row with the result.
3. Commit.

## 4. Migration

Single function `migrate_annotation_decouple_source_target(engine, session)` in
`cps/ub.py`. Called from `migrate_Database()` after the existing H1 migration.
Wrapped in `engine.begin()` for transactional atomicity.

### Steps (idempotent, transactional)

```
0. Pre-check: 'annotation' table exists AND lacks synced_to_hardcover col?
   YES → no-op return.
   NO + kobo_annotation_sync absent → fresh install, no-op return.

1. CREATE TABLE annotation_sync_target IF NOT EXISTS, with indexes.

2. INSERT INTO annotation_sync_target (annotation_id, target, target_record_id,
                                       status, last_synced, last_attempt,
                                       created_at, updated_at)
   SELECT id, 'hardcover', CAST(hardcover_journal_id AS VARCHAR),
          'synced', last_synced, last_synced, last_synced, last_synced
   FROM kobo_annotation_sync
   WHERE synced_to_hardcover = 1
     AND NOT EXISTS (SELECT 1 FROM annotation_sync_target ast
                     WHERE ast.annotation_id = kobo_annotation_sync.id
                       AND ast.target = 'hardcover');

3. UPDATE kobo_annotation_sync SET source='kobo' WHERE source='hardcover';

4. Sanity check:
   pre_count := SELECT COUNT(*) FROM kobo_annotation_sync WHERE synced_to_hardcover=1
   new_count := SELECT COUNT(*) FROM annotation_sync_target WHERE target='hardcover'
   IF pre_count != new_count RAISE → transaction rolls back, DB unchanged.

5. ALTER TABLE kobo_annotation_sync RENAME TO annotation.

6. DROP INDEX ix_kobo_annotation_sync_user_annotation;
   DROP INDEX ix_kobo_annotation_sync_user_book;
   CREATE INDEX ix_annotation_user_annotation ON annotation (user_id, annotation_id);
   CREATE INDEX ix_annotation_user_book        ON annotation (user_id, book_id);

7. ALTER TABLE annotation DROP COLUMN synced_to_hardcover;
   ALTER TABLE annotation DROP COLUMN hardcover_journal_id;

   (Requires SQLite >= 3.35, available on the lsio ubuntu:noble base.)
```

### Migration timing

`migrate_Database()` is called from `cps/__init__.py` during application init,
before the Flask app starts accepting requests. There is no in-flight user
traffic during the migration window, so we don't need to worry about
concurrent writes to `kobo_annotation_sync` while the rename + drop is
executing.

### Why no expand-contract or rollback script

The affected surface is 3 days old (H1 shipped 2026-05-18). The pre-existing
annotation-backup safety net (v4.0.81, also 3 days old) snapshots every
annotation row to disk on every INSERT/UPDATE — if migration somehow corrupts
data, restore is mechanical.

Plus: the migration is transactional, the sanity check at step 4 refuses to
proceed if backfill row counts disagree, and the test suite (see §6.1) bit-
exactly fingerprints content preservation.

### Annotation-backup snapshot format

`cps/services/annotation_backup.py` writes `/config/annotation-backups/<user>/
<book>/<iso>.json.gz` files. The on-disk payload bumps from `schema_version:
1` → `schema_version: 2`. v2 readers (the restore endpoint, future) handle
both versions:

- v1 payload: no `source` field → default to `'kobo'` on restore.
- v2 payload: explicit `source` field; restore uses as-is.

## 5. Error handling

### 5.1 Failure modes + responses

| Failure | Detection | Response |
|---|---|---|
| Hardcover API timeout | `requests.exceptions.Timeout` | `SyncResult(status='failed', error_message=...)`, `log.warning`, retried on next PATCH |
| Hardcover 4xx | non-2xx response | `SyncResult(status='failed', error_message=<body>)`, `log.error`, retried on next PATCH |
| Hardcover 5xx | non-2xx response | same as 4xx |
| Hardcover delete 404 | HTTP 404 | `SyncResult(status='tombstone', error_message='already deleted on remote')` — idempotent delete closes the existing TODO at readingservices.py:472-474 |
| DB write fails after Hardcover succeeded | `IntegrityError` / `OperationalError` | log.error with `target_record_id` for reconcile; next push attempt returns same target_record_id (Hardcover deduplicates) and UPSERT completes |
| Concurrent PATCH for same annotation | `IntegrityError` on `uq_ast_annotation_target` | dispatcher catches, re-queries existing row, updates it; UPSERT semantics |
| Migration partial failure | any exception in steps 1-7 | transactional rollback, DB stays pre-migration, container retries on next boot |
| Sanity check fails | step 4 counts mismatch | raises, transactional rollback, container won't proceed; operator investigates |

### 5.2 Hardcover-side race closure

The existing TODO at `readingservices.py:472-474` (Hardcover write succeeded
but DB write failed → duplicate journal entry on retry) is closed by:

- **Push**: include `external_id = "cwn:annotation:<annotation_id>"` in the
  Hardcover request body. Hardcover treats existing external_id as upsert,
  returning the existing record's ID rather than creating a duplicate. Open
  question: verify Hardcover's API actually supports `external_id`
  deduplication. Fallback if not: persist target_record_id BEFORE returning
  from handler.push(), then subsequent calls PATCH against the recorded ID.
- **Delete**: 404 from Hardcover is treated as success (already deleted
  remotely). Handler returns `status=tombstone`. Idempotent re-run is a no-op.

### 5.3 Observability

Every state transition logs a structured field:

```python
log.info(
    "annotation_sync: %s",
    {
        "event": "transition",
        "annotation_id": ann.id,
        "annotation_origin": ann.source,
        "target": target_name,
        "from_status": prior_status,
        "to_status": new_status,
        "user_id": user.id,
        "error_message": result.error_message,
    },
)
```

No new external telemetry. The `error_message` column on
`annotation_sync_target` is the operator surface — future admin UI can
`SELECT … WHERE status='failed' ORDER BY updated_at DESC LIMIT 50`.

## 6. Test plan

Total: ~68 automated tests + 1 manual Kobo-device checklist (45 unit + 10
integration + 5 docker + 8 playwright).

### 6.1 Unit (~45 tests, `tests/unit/`, CI Job 1)

| File | Pins | Count |
|---|---|---|
| `test_annotation_schema.py` (renamed from `test_kobo_annotation_sync_h1_schema.py`) | columns, indexes, source validator, UniqueConstraint, FK CASCADE | 8 |
| `test_annotation_sync_helpers.py` | `sync_target()`, `is_synced_to()` model helpers | 4 |
| `test_annotation_decouple_migration.py` | each of the 8 steps + full-flow on H1 fixture + full-flow on pre-H1 fixture + idempotency + partial-failure rollback | 14 |
| `test_annotation_migration_preservation.py` | bit-exact SHA-256 preservation across 100-row populated DB | 3 |
| `test_hardcover_handler.py` | push 200/4xx/5xx, delete 200/404, idempotent push | 6 |
| `test_annotation_sync_dispatcher.py` | UPSERT, concurrent race handling, tombstone terminal, delete-flow transitions | 7 |
| `test_annotation_backup_v2.py` | schema_version=2 in new snapshots, v1 snapshots restore correctly | 3 |

### 6.2 Integration (~10 tests, `tests/integration/`, CI Job 2)

| File | Pins | Count |
|---|---|---|
| `test_annotation_patch_lifecycle.py` | full PATCH flow, mocked Hardcover, real SQLite, backup hook fires | 6 |
| `test_annotation_handler_registration.py` | register_handler, available_targets, disabled-handler skip | 4 |

### 6.3 Docker (~5 tests, `tests/docker/`, manual + scheduled)

| File | Pins | Count |
|---|---|---|
| `test_migration_on_boot.py` | empty / H1-populated / already-migrated DBs on container boot | 3 |
| `test_pre_migration_upgrade_e2e.py` | mount populated pre-decouple SQLite, container migrates, HTTP probe works | 2 |

### 6.4 Playwright (~8 tests with JPEG capture, `tests/playwright/` — new dir)

| Step | Capture | Asserted |
|---|---|---|
| 1. Login as test user | `01-login.jpeg` | logged-in state, no error toast |
| 2. Navigate to /annotations/import | `02-import-form.jpeg` | form visible, CSRF token present |
| 3. Upload synthetic KoboReader.sqlite | `03-import-result.jpeg` | result counts: imported=3, skipped_hidden=1, skipped_orphan=2 |
| 4. Navigate to /annotations/<book_id> | `04-annotations-view.jpeg` | 3 blockquotes, color-coded, sorted by chapter_progress |
| 5. Click Export Markdown | `05-markdown-download.jpeg` | browser download bar visible |
| 6. Open /read/<id>/epub | `06-reader-with-overlays.jpeg` | yellow/red/green overlays on text |
| 7. Open Annotations sidebar | `07-reader-sidebar.jpeg` | 3 entries listed |
| 8. Click sidebar entry | `08-reader-jumped-to-cfi.jpeg` | reader scrolled to CFI |

### 6.5 Manual Kobo device verification

One-shot checklist saved to `notes/feat-annotation-decouple-kobo-verification.md`:

1. Configure Kobo to point at cwn-local (DNS override on test wifi).
2. Hardcover disabled → make highlight → sync → `SELECT source FROM annotation` → 'kobo'; no sync_target rows.
3. Enable Hardcover + token → sync again → `SELECT status FROM annotation_sync_target` → 'synced'.
4. Verify Hardcover.app shows the journal entry.
5. Delete highlight on Kobo → sync → status → 'tombstone'; Hardcover journal entry gone.
6. Re-create highlight on Kobo → sync → new `Annotation` row (different annotation_id); tombstoned row stays tombstoned.

### 6.6 Fixtures

- **Reused**: `tests/fixtures/kobo_reader_sqlite.py`, `tests/fixtures/kepub_fixture.py`.
- **New**: `tests/fixtures/annotation_pre_decouple_db.py` — populated pre-decouple SQLite with mixed `synced_to_hardcover` rows and `source='hardcover'` rows.
- **New**: `tests/fixtures/mock_hardcover_client.py` — drop-in HardcoverClient with controllable response codes.

## 7. Scope boundaries

### In scope (this PR)
- Schema rename + new sync_target table + migration
- Source-value bug fix + backfill of legacy `source='hardcover'` rows
- Handler abstraction + Hardcover handler extracted from readingservices.py
- All tests in §6.

### Out of scope (deferred to future sub-projects)
| Item | Goes in |
|---|---|
| Live Kobo capture independent of Hardcover (always-persist Annotation row regardless of any sync target) | Sub-project (2) |
| PDF annotation overlay (introduces `position_type` column for non-CFI positions) | Sub-project (3) |
| CBR/CBZ overlay (rides on (3)'s polymorphic position machinery) | Sub-project (4) |
| Web-reader-native highlight creation (CFI-from-selection JS + POST endpoint) | Sub-project (3) |
| Readwise / Notion / Obsidian handlers | future per-target PRs |
| Async sync worker for `pending` rows | future PR if Hardcover becomes a latency hotspot |
| Tombstone propagation from `hidden=TRUE` | future PR if users explicitly want it |
| Admin UI surface for `error_message` / sync health | future PR |

## 8. Open questions

1. **Hardcover `external_id` support**: implementation will verify this against
   `cps/services/hardcover.py` before writing the idempotency path. If
   Hardcover doesn't support external_id deduplication, fall back to
   "record target_record_id from first push, PATCH against it thereafter."
   This is mentioned in §5.2 as the explicit fallback.

2. **`source` NOT NULL constraint**: keeping `source` SQL-nullable; ORM
   `@validates` enforces the value set at write time. SQLite table-rebuild
   would be required for a SQL-level NOT NULL, which isn't justified by the
   marginal safety gain when the only writers are our own ORM code.

## 9. Implementation order

1. Spec written + committed (this file).
2. `writing-plans` skill: structured implementation plan with TDD ordering.
3. Migration code + step-isolated unit tests (RED→GREEN per step).
4. Model rename + helper methods + schema validator + tests.
5. Handler abstraction + Hardcover handler extraction + unit tests.
6. Dispatcher + integration tests.
7. readingservices.py PATCH handler refactored to orchestrator + integration tests.
8. annotations.py import path: rename only.
9. annotation_backup.py: rename + schema_version=2 + tests.
10. admin.py wipe-list update.
11. Docker tests: build image, run with various DB states.
12. Playwright tests: build out + JPEG capture.
13. Manual Kobo verification (operator).
14. Verification checklist per CLAUDE.md "Enterprise verification standard":
    - Container healthy
    - HTTP probes for key endpoints return 200
    - Logs show no errors during migration
    - Migration runs once, idempotent re-run is no-op
    - Bit-exact preservation fingerprint test passes
15. PR opened with full evidence: test counts, screenshots, log excerpts.
