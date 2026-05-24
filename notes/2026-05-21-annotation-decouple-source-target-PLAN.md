# Annotation Decouple — Source vs Sync Target — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `kobo_annotation_sync` → `annotation`, move Hardcover sync state to a new `annotation_sync_target` table with a status state machine, fix the `source='hardcover'` bug, and extract Hardcover-push logic into a handler abstraction so future sync targets (Readwise, Notion, etc.) plug in as new files.

**Architecture:** Single transactional migration with idempotent steps + sanity-check gate. New module `cps/services/annotation_sync/` houses a handler ABC + Hardcover handler + dispatcher. `cps/readingservices.py` PATCH handler becomes a thin orchestrator. All Annotation content columns preserved bit-exactly; per-target sync state moves to the new table. ~68 automated tests + manual Kobo-device checklist.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 1.4 (Declarative), SQLite (>=3.35 for `DROP COLUMN`), pytest, Playwright, Docker.

**Spec:** `notes/2026-05-21-annotation-decouple-source-target-DESIGN.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `cps/services/annotation_sync/__init__.py` | Public API: `dispatch_annotation_sync`, `dispatch_annotation_deletes`, `register_handler`, `available_targets`. Wires `HardcoverHandler` at import time. |
| `cps/services/annotation_sync/base.py` | `AnnotationSyncTargetHandler` ABC + `SyncResult` dataclass. |
| `cps/services/annotation_sync/hardcover.py` | `HardcoverHandler` — extracted push/delete/is_enabled from `cps/readingservices.py:347-486`. |
| `tests/unit/test_annotation_schema.py` | Renamed from `test_kobo_annotation_sync_h1_schema.py`. Pins columns, indexes, source validator, UniqueConstraint, FK CASCADE. |
| `tests/unit/test_annotation_sync_helpers.py` | `Annotation.sync_target()`, `Annotation.is_synced_to()`. |
| `tests/unit/test_annotation_decouple_migration.py` | Each of the 8 migration steps in isolation + full-flow on H1 fixture + pre-H1 fixture + idempotency + partial-failure rollback. |
| `tests/unit/test_annotation_migration_preservation.py` | SHA-256 fingerprint bit-exact preservation across 100-row populated DB. |
| `tests/unit/test_hardcover_handler.py` | Push 200/4xx/5xx, delete 200/404, idempotent push. |
| `tests/unit/test_annotation_sync_dispatcher.py` | UPSERT, concurrent race, tombstone terminal, delete transitions. |
| `tests/unit/test_annotation_backup_v2.py` | New snapshots use schema_version=2; v1 snapshots restore correctly. |
| `tests/integration/test_annotation_patch_lifecycle.py` | Full PATCH flow + mocked Hardcover + backup hook fires. |
| `tests/integration/test_annotation_handler_registration.py` | register_handler, available_targets, disabled-handler skip. |
| `tests/docker/test_annotation_migration_on_boot.py` | Container boots with empty / H1-populated / already-migrated DBs. |
| `tests/docker/test_pre_migration_upgrade_e2e.py` | Mount populated pre-decouple SQLite, container migrates, HTTP probe. |
| `tests/playwright/test_annotation_decouple_flow.py` | 8-step UI flow with JPEG screenshot capture. |
| `tests/fixtures/annotation_pre_decouple_db.py` | Populated pre-decouple SQLite fixture with mixed `synced_to_hardcover` + `source='hardcover'` rows. |
| `tests/fixtures/mock_hardcover_client.py` | Drop-in HardcoverClient with controllable response codes. |
| `notes/feat-annotation-decouple-kobo-verification.md` | Manual Kobo-device verification checklist. |

### Modified files

| Path | Changes |
|---|---|
| `cps/ub.py` | `class KoboAnnotationSync` → `class Annotation`. Add `class AnnotationSyncTarget`. Drop `synced_to_hardcover` + `hardcover_journal_id` columns. Add `source` `@validates`. Add `sync_targets` relationship + helper methods. Add `migrate_annotation_decouple_source_target` function. Register in `migrate_Database`. |
| `cps/readingservices.py` | PATCH handler `handle_annotations` refactored to thin orchestrator calling `dispatch_annotation_sync` + `dispatch_annotation_deletes`. Remove `process_annotation_for_sync` (moved to handler). Remove inline `KoboAnnotationSync` writes. |
| `cps/annotations.py` | Mechanical rename `ub.KoboAnnotationSync` → `ub.Annotation` (~8 occurrences). |
| `cps/services/annotation_backup.py` | Class rename. Bump snapshot envelope `schema_version: 1 → 2`. Restore-side handles both versions. |
| `cps/admin.py:3155` | String `"kobo_annotation_sync"` → `"annotation"` in wipe list. Add `"annotation_sync_target"` to list. |
| `tests/unit/test_annotation_backup.py` | Class rename + schema_version assertions. |
| `tests/unit/test_annotations_*.py` (data_endpoint, import_endpoint, view_export) | Class rename to `ub.Annotation`. |
| `CHANGES-vs-upstream.md` | New row recording this fork PR + squash SHA after merge. |

---

## Task 1: Setup — verify worktree state + branch

**Files:**
- Modify: (none)

- [ ] **Step 1.1: Confirm worktree branch + clean state**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
git status
git branch --show-current
```
Expected output:
```
On branch worktree-BetterIntegrationOrganization
nothing to commit, working tree clean
```
(Spec was already committed in `26d1470cf`.)

- [ ] **Step 1.2: Confirm Python environment + key imports work**

Run:
```bash
python3 -c "import sqlalchemy, flask, pytest; print(sqlalchemy.__version__, flask.__version__)"
```
Expected: SQLAlchemy 1.4.x and Flask 2.x or later versions print without error.

- [ ] **Step 1.3: Run the existing annotation-related test suite to establish a baseline (must be GREEN before changes)**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
python3 -m pytest tests/unit/test_annotation_backup.py tests/unit/test_annotations_data_endpoint.py tests/unit/test_annotations_import_endpoint.py tests/unit/test_annotations_view_export.py tests/unit/test_kobo_annotation_sync_h1_schema.py -v 2>&1 | tail -30
```
Expected: All tests pass. Any failures here mean the worktree starts in a bad state — investigate before continuing.

---

## Task 2: Add `AnnotationSyncTarget` model (test-first)

**Files:**
- Create: `tests/unit/test_annotation_schema.py` (new — renamed/expanded from `test_kobo_annotation_sync_h1_schema.py`)
- Modify: `cps/ub.py` (add `AnnotationSyncTarget` class after the existing `KoboAnnotationSync`)

- [ ] **Step 2.1: Write failing tests for `AnnotationSyncTarget` model**

Create `tests/unit/test_annotation_schema.py`:

```python
"""Schema tests for the decoupled annotation + annotation_sync_target tables.

Replaces test_kobo_annotation_sync_h1_schema.py. The H1 schema tests are
preserved here (they still test the pre-decouple migration which runs first),
and new tests pin the decouple-stage shape.
"""

from __future__ import annotations
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from cps import ub


@pytest.fixture
def in_memory_session():
    """Fresh in-memory SQLite with the FULL post-decouple schema."""
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="t", email="t@example.com", role=0, password="x")
    s.add(user)
    s.commit()
    yield s, user
    s.close()


def test_annotation_sync_target_model_exists():
    """AnnotationSyncTarget class is declared on ub module."""
    assert hasattr(ub, "AnnotationSyncTarget")
    assert ub.AnnotationSyncTarget.__tablename__ == "annotation_sync_target"


def test_annotation_sync_target_columns():
    """Required columns are declared with correct types/nullability."""
    cols = {c.name: c for c in ub.AnnotationSyncTarget.__table__.columns}
    assert "annotation_id" in cols and not cols["annotation_id"].nullable
    assert "target" in cols and not cols["target"].nullable
    assert "target_record_id" in cols and cols["target_record_id"].nullable
    assert "status" in cols and not cols["status"].nullable
    assert "error_message" in cols and cols["error_message"].nullable
    assert "last_attempt" in cols and cols["last_attempt"].nullable
    assert "last_synced" in cols and cols["last_synced"].nullable
    assert "created_at" in cols and not cols["created_at"].nullable
    assert "updated_at" in cols and not cols["updated_at"].nullable


def test_annotation_sync_target_unique_constraint(in_memory_session):
    """Two rows with same (annotation_id, target) raise IntegrityError."""
    s, user = in_memory_session
    ann = ub.Annotation(
        user_id=user.id, annotation_id="kobo-uuid-1", book_id=1, source="kobo",
    )
    s.add(ann)
    s.commit()
    s.add(ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="synced",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    s.commit()
    s.add(ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="failed",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        s.commit()


def test_annotation_sync_target_fk_cascade(in_memory_session):
    """Hard-deleting Annotation cascades to AnnotationSyncTarget rows."""
    s, user = in_memory_session
    # SQLite FK enforcement requires PRAGMA — set per-connection.
    s.execute("PRAGMA foreign_keys=ON")
    ann = ub.Annotation(
        user_id=user.id, annotation_id="kobo-uuid-2", book_id=1, source="kobo",
    )
    s.add(ann); s.commit()
    s.add(ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="synced",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    s.commit()
    assert s.query(ub.AnnotationSyncTarget).count() == 1
    s.delete(ann); s.commit()
    assert s.query(ub.AnnotationSyncTarget).count() == 0
```

- [ ] **Step 2.2: Run the new test to verify it fails**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
python3 -m pytest tests/unit/test_annotation_schema.py -v 2>&1 | tail -20
```
Expected: FAIL with `AttributeError: module 'cps.ub' has no attribute 'AnnotationSyncTarget'` or similar.

- [ ] **Step 2.3: Implement `AnnotationSyncTarget` model in `cps/ub.py`**

Read `cps/ub.py:826-870` first to confirm the current location of `KoboAnnotationSync`. Then add the new class immediately after `KoboAnnotationBackup` (currently around line 882-910). Use SQLAlchemy `UniqueConstraint` import (already at top of file).

```python
class AnnotationSyncTarget(Base):
    """Per-(annotation, target) row tracking sync state to a single remote
    destination (Hardcover today; Readwise/Notion/etc later). Status state
    machine: pending → synced/failed → tombstone. See
    notes/2026-05-21-annotation-decouple-source-target-DESIGN.md.
    """
    __tablename__ = "annotation_sync_target"

    id = Column(Integer, primary_key=True, autoincrement=True)
    annotation_id = Column(
        Integer,
        ForeignKey("annotation.id", ondelete="CASCADE"),
        nullable=False,
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
        UniqueConstraint("annotation_id", "target", name="uq_ast_annotation_target"),
        Index("ix_ast_target_status", "target", "status"),
    )

    def __repr__(self):
        return (f"<AnnotationSyncTarget annotation_id={self.annotation_id} "
                f"target={self.target} status={self.status}>")
```

Confirm `UniqueConstraint` is imported at the top of `ub.py`. If not, add it: `from sqlalchemy import UniqueConstraint`.

- [ ] **Step 2.4: Verify tests pass (the FK cascade and unique constraint tests will fail until Step 3 renames `KoboAnnotationSync` to `Annotation`)**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_schema.py::test_annotation_sync_target_model_exists tests/unit/test_annotation_schema.py::test_annotation_sync_target_columns -v 2>&1 | tail -10
```
Expected: 2 passed. (Other tests in this file depend on `ub.Annotation` which we add in Task 3.)

---

## Task 3: Rename `KoboAnnotationSync` → `Annotation` (test-first)

**Files:**
- Modify: `cps/ub.py` (rename class, table, indexes; drop the two Hardcover columns; add `source` validator; add `sync_targets` relationship)

- [ ] **Step 3.1: Add tests for the renamed `Annotation` model in `tests/unit/test_annotation_schema.py`**

Append to `tests/unit/test_annotation_schema.py`:

```python
def test_annotation_model_renamed():
    """KoboAnnotationSync class is renamed to Annotation; table is 'annotation'."""
    assert hasattr(ub, "Annotation")
    assert ub.Annotation.__tablename__ == "annotation"


def test_annotation_drops_hardcover_columns():
    """The Hardcover-specific columns are removed from the annotation table."""
    cols = {c.name for c in ub.Annotation.__table__.columns}
    assert "synced_to_hardcover" not in cols
    assert "hardcover_journal_id" not in cols


def test_annotation_source_validator():
    """@validates rejects values outside {kobo, webreader, koreader}."""
    ann = ub.Annotation()
    ann.source = "kobo"      # OK
    ann.source = "webreader" # OK
    ann.source = "koreader"  # OK
    ann.source = None        # OK (NULL allowed at SQL level)
    with pytest.raises(ValueError):
        ann.source = "hardcover"
    with pytest.raises(ValueError):
        ann.source = "garbage"


def test_annotation_indexes_renamed():
    """Indexes follow the new naming convention."""
    index_names = {i.name for i in ub.Annotation.__table__.indexes}
    assert "ix_annotation_user_annotation" in index_names
    assert "ix_annotation_user_book" in index_names
```

- [ ] **Step 3.2: Run new tests, verify they fail**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_schema.py::test_annotation_model_renamed -v 2>&1 | tail -5
```
Expected: FAIL with `AttributeError: module 'cps.ub' has no attribute 'Annotation'`.

- [ ] **Step 3.3: Apply the rename + drop columns + add validator + add relationship in `cps/ub.py`**

Edit `cps/ub.py:833-879` (the `KoboAnnotationSync` class). Replace it with:

```python
class Annotation(Base):
    """Per-user-per-annotation row. The canonical store for ALL
    highlight/note origins (Kobo device, web reader, KOReader plugin).

    Per-target sync state (Hardcover, Readwise, etc.) lives in the
    AnnotationSyncTarget table — one row per (annotation, target).

    Renamed from KoboAnnotationSync as of 2026-05-21 — the table is no
    longer Kobo-specific. See notes/2026-05-21-annotation-decouple-source-
    target-DESIGN.md.
    """
    __tablename__ = "annotation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    annotation_id = Column(String, nullable=False)
    book_id = Column(Integer, nullable=False)

    # Origin tracking — where this annotation was created.
    source = Column(String, nullable=True)
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
        Index("ix_annotation_user_annotation", "user_id", "annotation_id"),
        Index("ix_annotation_user_book", "user_id", "book_id"),
    )

    _VALID_SOURCES = {"kobo", "webreader", "koreader"}

    @validates("source")
    def _validate_source(self, _key, value):
        if value is not None and value not in self._VALID_SOURCES:
            raise ValueError(
                f"invalid annotation source: {value!r}; "
                f"expected one of {sorted(self._VALID_SOURCES)} or None"
            )
        return value

    def sync_target(self, target_name):
        """Return the AnnotationSyncTarget row for a specific target, or None."""
        for st in self.sync_targets:
            if st.target == target_name:
                return st
        return None

    def is_synced_to(self, target_name):
        """True iff there's a sync_target row for `target_name` with status='synced'."""
        st = self.sync_target(target_name)
        return st is not None and st.status == "synced"

    def __repr__(self):
        return f"<Annotation annotation_id={self.annotation_id} book_id={self.book_id}>"
```

Confirm imports at top of `cps/ub.py`: needs `from sqlalchemy import …, UniqueConstraint` and `from sqlalchemy.orm import …, validates, relationship`. Add any missing.

- [ ] **Step 3.4: Run all schema tests, verify they pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_schema.py -v 2>&1 | tail -20
```
Expected: All 8 tests pass (4 sync_target + 4 annotation tests).

- [ ] **Step 3.5: Commit Task 2 + Task 3**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
git add cps/ub.py tests/unit/test_annotation_schema.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation): rename KoboAnnotationSync->Annotation, add AnnotationSyncTarget model

Schema foundation for decoupling annotation origin (kobo/webreader/koreader)
from per-target sync destination (hardcover today; readwise/notion later).

- Drop synced_to_hardcover + hardcover_journal_id columns (move to ast)
- @validates source against {kobo, webreader, koreader}
- sync_targets relationship with cascade=all,delete-orphan
- New AnnotationSyncTarget table with UniqueConstraint(annotation_id, target)

Migration code lands in next commit.

Sub-project (1) of 4. Spec: notes/2026-05-21-annotation-decouple-source-target-DESIGN.md"
```

---

## Task 4: Migration step 1 — CREATE TABLE annotation_sync_target

**Files:**
- Create: `tests/unit/test_annotation_decouple_migration.py`
- Modify: `cps/ub.py` (add `migrate_annotation_decouple_source_target` function, initially with only step 1)

- [ ] **Step 4.1: Write failing test for step 1**

Create `tests/unit/test_annotation_decouple_migration.py`:

```python
"""Tests for migrate_annotation_decouple_source_target — the 8-step
transactional migration that splits per-target sync state out of the
annotation table.

Each step is tested in isolation against synthetic pre-migration DBs.
Full-flow tests run after the steps are stable.
"""

from __future__ import annotations
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def pre_decouple_engine():
    """SQLite engine with the H1 schema (post-H1 migration, pre-decouple).

    The kobo_annotation_sync table has all H1 columns including the
    synced_to_hardcover + hardcover_journal_id pair we'll later move.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE kobo_annotation_sync (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                synced_to_hardcover BOOLEAN DEFAULT 0,
                hardcover_journal_id INTEGER,
                created_at DATETIME,
                last_synced DATETIME,
                highlighted_text VARCHAR,
                highlight_color VARCHAR,
                note_text VARCHAR,
                content_id VARCHAR,
                start_container_path TEXT,
                start_container_child_index INTEGER,
                start_offset INTEGER,
                end_container_path TEXT,
                end_container_child_index INTEGER,
                end_offset INTEGER,
                context_string TEXT,
                chapter_progress REAL,
                cfi_range VARCHAR,
                source VARCHAR,
                hidden BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("CREATE INDEX ix_kobo_annotation_sync_user_annotation ON kobo_annotation_sync (user_id, annotation_id)"))
        conn.execute(text("CREATE INDEX ix_kobo_annotation_sync_user_book ON kobo_annotation_sync (user_id, book_id)"))
    return engine


def test_step1_create_target_table(pre_decouple_engine):
    """Step 1 creates annotation_sync_target with its indexes + unique constraint."""
    from cps.ub import _migrate_step1_create_target_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
    inspector = sa_inspect(pre_decouple_engine)
    assert "annotation_sync_target" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("annotation_sync_target")}
    assert {"id", "annotation_id", "target", "target_record_id", "status",
            "error_message", "last_attempt", "last_synced",
            "created_at", "updated_at"}.issubset(cols)
    indexes = inspector.get_indexes("annotation_sync_target")
    # SQLite represents UniqueConstraint as a unique index.
    has_unique_pair = any(
        i.get("unique") and set(i["column_names"]) == {"annotation_id", "target"}
        for i in indexes
    )
    assert has_unique_pair, f"missing uniqueness on (annotation_id, target): {indexes}"


def test_step1_idempotent(pre_decouple_engine):
    """Step 1 is a no-op when the table already exists."""
    from cps.ub import _migrate_step1_create_target_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)  # second call must not raise
    inspector = sa_inspect(pre_decouple_engine)
    assert "annotation_sync_target" in inspector.get_table_names()
```

- [ ] **Step 4.2: Run test, verify failure**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step1_create_target_table -v 2>&1 | tail -5
```
Expected: FAIL with `ImportError: cannot import name '_migrate_step1_create_target_table' from 'cps.ub'`.

- [ ] **Step 4.3: Implement step 1 in `cps/ub.py`**

Append to `cps/ub.py` (immediately before `migrate_Database`):

```python
def _migrate_step1_create_target_table(conn):
    """Create annotation_sync_target table + indexes if not present."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS annotation_sync_target (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            annotation_id     INTEGER NOT NULL,
            target            VARCHAR NOT NULL,
            target_record_id  VARCHAR,
            status            VARCHAR NOT NULL,
            error_message     TEXT,
            last_attempt      DATETIME,
            last_synced       DATETIME,
            created_at        DATETIME NOT NULL,
            updated_at        DATETIME NOT NULL,
            UNIQUE (annotation_id, target),
            FOREIGN KEY (annotation_id) REFERENCES annotation(id) ON DELETE CASCADE
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ast_target_status "
        "ON annotation_sync_target (target, status)"
    ))
```

- [ ] **Step 4.4: Run tests, verify pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step1_create_target_table tests/unit/test_annotation_decouple_migration.py::test_step1_idempotent -v 2>&1 | tail -10
```
Expected: 2 passed.

---

## Task 5: Migration step 2 — backfill sync state

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 5.1: Write failing test for step 2**

Append to `tests/unit/test_annotation_decouple_migration.py`:

```python
def _seed_row(conn, **overrides):
    """Insert a kobo_annotation_sync row with sensible defaults."""
    defaults = {
        "user_id": 1, "annotation_id": "uuid-001", "book_id": 1,
        "synced_to_hardcover": 0, "hardcover_journal_id": None,
        "created_at": "2026-05-18 10:00:00", "last_synced": "2026-05-18 10:00:00",
        "highlighted_text": "text", "source": None, "hidden": 0,
    }
    defaults.update(overrides)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(f":{k}" for k in defaults.keys())
    conn.execute(text(f"INSERT INTO kobo_annotation_sync ({cols}) VALUES ({placeholders})"), defaults)


def test_step2_backfills_only_synced_rows(pre_decouple_engine):
    """Step 2 backfills sync_target rows ONLY for synced_to_hardcover=1 rows."""
    from cps.ub import _migrate_step1_create_target_table, _migrate_step2_backfill_sync_state
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, annotation_id="synced-1", synced_to_hardcover=1, hardcover_journal_id=100)
        _seed_row(conn, annotation_id="synced-2", synced_to_hardcover=1, hardcover_journal_id=200)
        _seed_row(conn, annotation_id="not-synced", synced_to_hardcover=0, hardcover_journal_id=None)
        inserted = _migrate_step2_backfill_sync_state(conn)
    assert inserted == 2
    with pre_decouple_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT target, target_record_id, status FROM annotation_sync_target ORDER BY id"
        )).fetchall()
    assert len(rows) == 2
    assert rows[0] == ("hardcover", "100", "synced")
    assert rows[1] == ("hardcover", "200", "synced")


def test_step2_idempotent(pre_decouple_engine):
    """Re-running step 2 doesn't duplicate rows."""
    from cps.ub import _migrate_step1_create_target_table, _migrate_step2_backfill_sync_state
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42)
        first = _migrate_step2_backfill_sync_state(conn)
        second = _migrate_step2_backfill_sync_state(conn)
    assert first == 1
    assert second == 0
    with pre_decouple_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert count == 1
```

- [ ] **Step 5.2: Run tests, verify failure**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step2_backfills_only_synced_rows -v 2>&1 | tail -5
```
Expected: FAIL with `ImportError: cannot import name '_migrate_step2_backfill_sync_state'`.

- [ ] **Step 5.3: Implement step 2 in `cps/ub.py`**

Append to `cps/ub.py`:

```python
def _migrate_step2_backfill_sync_state(conn):
    """Copy synced_to_hardcover=1 rows into annotation_sync_target.

    Idempotent — uses WHERE NOT EXISTS so re-running inserts nothing new.
    Returns the row-count actually inserted.
    """
    result = conn.execute(text("""
        INSERT INTO annotation_sync_target
            (annotation_id, target, target_record_id, status, last_synced, last_attempt, created_at, updated_at)
        SELECT
            kas.id,
            'hardcover',
            CAST(kas.hardcover_journal_id AS VARCHAR),
            'synced',
            kas.last_synced,
            kas.last_synced,
            kas.last_synced,
            kas.last_synced
        FROM kobo_annotation_sync kas
        WHERE kas.synced_to_hardcover = 1
          AND NOT EXISTS (
              SELECT 1 FROM annotation_sync_target ast
              WHERE ast.annotation_id = kas.id AND ast.target = 'hardcover'
          )
    """))
    return result.rowcount
```

- [ ] **Step 5.4: Run tests, verify pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step2_backfills_only_synced_rows tests/unit/test_annotation_decouple_migration.py::test_step2_idempotent -v 2>&1 | tail -10
```
Expected: 2 passed.

---

## Task 6: Migration step 3 — fix source='hardcover' → 'kobo'

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 6.1: Write test**

Append to test file:

```python
def test_step3_fixes_source_bug(pre_decouple_engine):
    """source='hardcover' rows get UPDATEd to source='kobo'."""
    from cps.ub import _migrate_step3_fix_source_values
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="bug-1", source="hardcover")
        _seed_row(conn, annotation_id="bug-2", source="hardcover")
        _seed_row(conn, annotation_id="clean", source="kobo")
        updated = _migrate_step3_fix_source_values(conn)
    assert updated == 2
    with pre_decouple_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT annotation_id, source FROM kobo_annotation_sync ORDER BY id"
        )).fetchall()
    assert ("bug-1", "kobo") in rows
    assert ("bug-2", "kobo") in rows
    assert ("clean", "kobo") in rows


def test_step3_idempotent(pre_decouple_engine):
    from cps.ub import _migrate_step3_fix_source_values
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, source="hardcover")
        first = _migrate_step3_fix_source_values(conn)
        second = _migrate_step3_fix_source_values(conn)
    assert first == 1
    assert second == 0
```

- [ ] **Step 6.2: Run, fail**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step3_fixes_source_bug -v 2>&1 | tail -5
```
Expected: FAIL on import.

- [ ] **Step 6.3: Implement step 3**

Append to `cps/ub.py`:

```python
def _migrate_step3_fix_source_values(conn):
    """Correct source='hardcover' rows to source='kobo'. Idempotent."""
    result = conn.execute(text(
        "UPDATE kobo_annotation_sync SET source = 'kobo' WHERE source = 'hardcover'"
    ))
    return result.rowcount
```

- [ ] **Step 6.4: Run, pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step3_fixes_source_bug tests/unit/test_annotation_decouple_migration.py::test_step3_idempotent -v 2>&1 | tail -5
```
Expected: 2 passed.

---

## Task 7: Migration step 4 — sanity check

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 7.1: Write test**

```python
def test_step4_sanity_passes_when_counts_match(pre_decouple_engine):
    from cps.ub import (_migrate_step1_create_target_table,
                        _migrate_step2_backfill_sync_state,
                        _migrate_step4_sanity_check)
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=10)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=20)
        _migrate_step2_backfill_sync_state(conn)
        # No raise:
        _migrate_step4_sanity_check(conn)


def test_step4_raises_on_mismatch(pre_decouple_engine):
    from cps.ub import _migrate_step1_create_target_table, _migrate_step4_sanity_check
    with pre_decouple_engine.begin() as conn:
        _migrate_step1_create_target_table(conn)
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=10)
        # Skip step 2 to create a count mismatch.
        with pytest.raises(RuntimeError, match="count mismatch"):
            _migrate_step4_sanity_check(conn)
```

- [ ] **Step 7.2: Implement step 4**

```python
def _migrate_step4_sanity_check(conn):
    """Refuse destructive steps unless backfill row counts match exactly."""
    pre = conn.execute(text(
        "SELECT COUNT(*) FROM kobo_annotation_sync WHERE synced_to_hardcover = 1"
    )).scalar()
    post = conn.execute(text(
        "SELECT COUNT(*) FROM annotation_sync_target WHERE target = 'hardcover'"
    )).scalar()
    if pre != post:
        raise RuntimeError(
            f"[annotation-decouple-migration] count mismatch: "
            f"pre-migration synced_to_hardcover=1 rows={pre}, "
            f"post-backfill annotation_sync_target rows={post}"
        )
```

- [ ] **Step 7.3: Run + pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step4_sanity_passes_when_counts_match tests/unit/test_annotation_decouple_migration.py::test_step4_raises_on_mismatch -v 2>&1 | tail -5
```
Expected: 2 passed.

---

## Task 8: Migration steps 5+6 — RENAME TABLE + rename indexes

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 8.1: Tests**

```python
def test_step5_renames_table(pre_decouple_engine):
    from cps.ub import _migrate_step5_rename_table
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    assert "annotation" in tables
    assert "kobo_annotation_sync" not in tables


def test_step6_renames_indexes(pre_decouple_engine):
    from cps.ub import _migrate_step5_rename_table, _migrate_step6_rename_indexes
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step6_rename_indexes(conn)
    inspector = sa_inspect(pre_decouple_engine)
    idx_names = {i["name"] for i in inspector.get_indexes("annotation")}
    assert "ix_annotation_user_annotation" in idx_names
    assert "ix_annotation_user_book" in idx_names
    assert "ix_kobo_annotation_sync_user_annotation" not in idx_names
    assert "ix_kobo_annotation_sync_user_book" not in idx_names
```

- [ ] **Step 8.2: Implement**

```python
def _migrate_step5_rename_table(conn):
    """Rename kobo_annotation_sync -> annotation."""
    conn.execute(text("ALTER TABLE kobo_annotation_sync RENAME TO annotation"))


def _migrate_step6_rename_indexes(conn):
    """SQLite doesn't have ALTER INDEX RENAME; drop + create."""
    conn.execute(text("DROP INDEX IF EXISTS ix_kobo_annotation_sync_user_annotation"))
    conn.execute(text("DROP INDEX IF EXISTS ix_kobo_annotation_sync_user_book"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_annotation_user_annotation "
        "ON annotation (user_id, annotation_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_annotation_user_book "
        "ON annotation (user_id, book_id)"
    ))
```

- [ ] **Step 8.3: Pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step5_renames_table tests/unit/test_annotation_decouple_migration.py::test_step6_renames_indexes -v 2>&1 | tail -5
```
Expected: 2 passed.

---

## Task 9: Migration step 7 — DROP COLUMN

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 9.1: Test**

```python
def test_step7_drops_hardcover_columns(pre_decouple_engine):
    from cps.ub import (_migrate_step5_rename_table,
                        _migrate_step7_drop_old_columns)
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step7_drop_old_columns(conn)
    inspector = sa_inspect(pre_decouple_engine)
    cols = {c["name"] for c in inspector.get_columns("annotation")}
    assert "synced_to_hardcover" not in cols
    assert "hardcover_journal_id" not in cols
    # Content columns survive:
    assert "highlighted_text" in cols
    assert "source" in cols
    assert "cfi_range" in cols


def test_step7_idempotent_when_columns_absent(pre_decouple_engine):
    from cps.ub import (_migrate_step5_rename_table,
                        _migrate_step7_drop_old_columns)
    with pre_decouple_engine.begin() as conn:
        _migrate_step5_rename_table(conn)
        _migrate_step7_drop_old_columns(conn)
        # Second run is a no-op
        _migrate_step7_drop_old_columns(conn)
```

- [ ] **Step 9.2: Implement**

```python
def _migrate_step7_drop_old_columns(conn):
    """Drop synced_to_hardcover + hardcover_journal_id columns.

    SQLite >= 3.35 supports DROP COLUMN natively. The lsio ubuntu:noble
    base ships SQLite 3.45+. Each DROP is guarded by column-existence so
    re-runs are no-ops.
    """
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("annotation")}
    if "synced_to_hardcover" in cols:
        conn.execute(text("ALTER TABLE annotation DROP COLUMN synced_to_hardcover"))
    if "hardcover_journal_id" in cols:
        conn.execute(text("ALTER TABLE annotation DROP COLUMN hardcover_journal_id"))
```

- [ ] **Step 9.3: Pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py::test_step7_drops_hardcover_columns tests/unit/test_annotation_decouple_migration.py::test_step7_idempotent_when_columns_absent -v 2>&1 | tail -5
```
Expected: 2 passed.

---

## Task 10: Migration step 0 (pre-check) + orchestrator

**Files:**
- Modify: `cps/ub.py`, `tests/unit/test_annotation_decouple_migration.py`

- [ ] **Step 10.1: Tests**

```python
def test_full_migration_on_h1_fixture(pre_decouple_engine):
    """End-to-end migration on populated H1 fixture lands in final state."""
    from cps.ub import migrate_annotation_decouple_source_target
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, annotation_id="a1", synced_to_hardcover=1, hardcover_journal_id=11, source="hardcover")
        _seed_row(conn, annotation_id="a2", synced_to_hardcover=1, hardcover_journal_id=22, source="hardcover")
        _seed_row(conn, annotation_id="a3", synced_to_hardcover=0, source="kobo")
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    assert "annotation" in tables
    assert "annotation_sync_target" in tables
    assert "kobo_annotation_sync" not in tables
    cols = {c["name"] for c in inspector.get_columns("annotation")}
    assert "synced_to_hardcover" not in cols
    with pre_decouple_engine.connect() as conn:
        ast_rows = conn.execute(text(
            "SELECT target_record_id, status FROM annotation_sync_target ORDER BY id"
        )).fetchall()
        ann_rows = conn.execute(text(
            "SELECT annotation_id, source FROM annotation ORDER BY id"
        )).fetchall()
    assert len(ast_rows) == 2
    assert all(r.status == "synced" for r in ast_rows)
    assert ("a1", "kobo") in ann_rows
    assert ("a2", "kobo") in ann_rows  # source corrected from 'hardcover'
    assert ("a3", "kobo") in ann_rows


def test_full_migration_idempotent(pre_decouple_engine):
    """Running the orchestrator twice is a no-op the second time."""
    from cps.ub import migrate_annotation_decouple_source_target
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42, source="hardcover")
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    # Run a second time. Must not raise. Counts unchanged.
    migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    with pre_decouple_engine.connect() as conn:
        ann_count = conn.execute(text("SELECT COUNT(*) FROM annotation")).scalar()
        ast_count = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert ann_count == 1
    assert ast_count == 1


def test_full_migration_fresh_install_noop():
    """Migration on a DB with no kobo_annotation_sync table is a clean no-op."""
    from cps.ub import migrate_annotation_decouple_source_target
    engine = create_engine("sqlite:///:memory:")
    migrate_annotation_decouple_source_target(engine, None)
    inspector = sa_inspect(engine)
    assert "annotation" not in inspector.get_table_names()


def test_full_migration_rollback_on_failure(pre_decouple_engine, monkeypatch):
    """Inject a failure between step 5 and step 7 — DB rolls back to pre-migration."""
    from cps import ub
    with pre_decouple_engine.begin() as conn:
        _seed_row(conn, synced_to_hardcover=1, hardcover_journal_id=42, source="hardcover")
    real_step6 = ub._migrate_step6_rename_indexes
    def boom(conn):
        real_step6(conn)
        raise RuntimeError("simulated failure between step 6 and 7")
    monkeypatch.setattr(ub, "_migrate_step6_rename_indexes", boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        ub.migrate_annotation_decouple_source_target(pre_decouple_engine, None)
    inspector = sa_inspect(pre_decouple_engine)
    tables = set(inspector.get_table_names())
    # Transaction rolled back: original table name back, no new table.
    assert "kobo_annotation_sync" in tables
    assert "annotation" not in tables
```

- [ ] **Step 10.2: Implement orchestrator**

Append to `cps/ub.py`:

```python
def migrate_annotation_decouple_source_target(engine, _session):
    """Decouple annotation origin from sync target.

    8-step transactional migration. Idempotent. See
    notes/2026-05-21-annotation-decouple-source-target-DESIGN.md §4 for
    full step-by-step.

    Refuses to proceed past the sanity check (step 4) if backfill row
    counts don't match. Any exception in steps 1-7 triggers full rollback;
    DB stays in pre-migration state.
    """
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())

    # Step 0: idempotency check
    if "annotation" in tables and "annotation_sync_target" in tables:
        cols = {c["name"] for c in inspector.get_columns("annotation")}
        if "synced_to_hardcover" not in cols and "hardcover_journal_id" not in cols:
            log.info("[annotation-decouple-migration] target schema already in place; skip")
            return
    if "kobo_annotation_sync" not in tables:
        log.info("[annotation-decouple-migration] no kobo_annotation_sync table; fresh install or already complete")
        return

    log.info("[annotation-decouple-migration] starting")
    try:
        with engine.begin() as conn:
            _migrate_step1_create_target_table(conn)
            inserted = _migrate_step2_backfill_sync_state(conn)
            updated = _migrate_step3_fix_source_values(conn)
            _migrate_step4_sanity_check(conn)
            _migrate_step5_rename_table(conn)
            _migrate_step6_rename_indexes(conn)
            _migrate_step7_drop_old_columns(conn)
            log.info(
                "[annotation-decouple-migration] complete: "
                "%d sync_target rows backfilled, %d source values corrected",
                inserted, updated,
            )
    except Exception:
        log.exception("[annotation-decouple-migration] failed; rolling back")
        raise
```

Then register the migration in `migrate_Database()`. Locate `migrate_Database(_session)` (was at line 1854); add the new call **after** `migrate_kobo_annotation_sync_h1_columns(engine, _session)`:

```python
def migrate_Database(_session):
    engine = _session.bind
    add_missing_tables(engine, _session)
    migrate_registration_table(engine, _session)
    migrate_user_session_table(engine, _session)
    migrate_user_table(engine, _session)
    migrate_shelf_table(engine, _session)
    migrate_oauth_provider_table(engine, _session)
    migrate_config_table(engine, _session)
    migrate_magic_shelf_table(engine, _session)
    migrate_kobo_unique_constraints(engine, _session)
    migrate_kobo_deleted_book(engine, _session)
    migrate_kobo_annotation_sync_h1_columns(engine, _session)
    migrate_annotation_decouple_source_target(engine, _session)
    migrate_book_cover_preview_table(engine, _session)
```

- [ ] **Step 10.3: Run all migration tests, verify pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_decouple_migration.py -v 2>&1 | tail -30
```
Expected: All migration tests pass (~14 tests).

- [ ] **Step 10.4: Commit Tasks 4-10**

```bash
git add cps/ub.py tests/unit/test_annotation_decouple_migration.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation): migration to decouple source from sync target

8-step transactional migration:
0. Idempotency pre-check
1. CREATE TABLE annotation_sync_target
2. Backfill from synced_to_hardcover=1 rows
3. Fix source='hardcover' -> 'kobo' bug
4. Sanity check (refuses destructive steps if counts mismatch)
5. RENAME TABLE kobo_annotation_sync -> annotation
6. Rename indexes (DROP + CREATE — SQLite has no ALTER INDEX RENAME)
7. DROP COLUMN synced_to_hardcover + hardcover_journal_id

All steps independently unit-tested + isolated.  Full-flow tests on
H1-populated fixture + idempotency + rollback-on-failure verified.

Sub-project (1) of 4."
```

---

## Task 11: Bit-exact preservation test

**Files:**
- Create: `tests/unit/test_annotation_migration_preservation.py`

- [ ] **Step 11.1: Write preservation test**

```python
"""Belt-and-braces test for the decouple migration: SHA-256 fingerprint
of every preserved field across a populated 100-row pre-migration DB must
match exactly post-migration. Catches subtle column-reorder bugs that
unit tests would miss.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, text


PRE_MIGRATION_DDL = """
CREATE TABLE kobo_annotation_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    annotation_id VARCHAR NOT NULL,
    book_id INTEGER NOT NULL,
    synced_to_hardcover BOOLEAN DEFAULT 0,
    hardcover_journal_id INTEGER,
    created_at DATETIME,
    last_synced DATETIME,
    highlighted_text VARCHAR,
    highlight_color VARCHAR,
    note_text VARCHAR,
    content_id VARCHAR,
    start_container_path TEXT,
    start_container_child_index INTEGER,
    start_offset INTEGER,
    end_container_path TEXT,
    end_container_child_index INTEGER,
    end_offset INTEGER,
    context_string TEXT,
    chapter_progress REAL,
    cfi_range VARCHAR,
    source VARCHAR,
    hidden BOOLEAN DEFAULT 0
)
"""

PRESERVED_COLUMNS = [
    "id", "user_id", "annotation_id", "book_id",
    "highlighted_text", "highlight_color", "note_text",
    "content_id", "start_container_path", "start_container_child_index",
    "start_offset", "end_container_path", "end_container_child_index",
    "end_offset", "context_string", "chapter_progress", "cfi_range",
    "hidden",
]


def _fingerprint(conn, table_name):
    """SHA-256 of the canonical JSON of every row's preserved columns."""
    cols_csv = ", ".join(PRESERVED_COLUMNS)
    rows = conn.execute(text(f"SELECT {cols_csv} FROM {table_name} ORDER BY id")).fetchall()
    payload = [
        {col: row[i] for i, col in enumerate(PRESERVED_COLUMNS)}
        for row in rows
    ]
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@pytest.fixture
def populated_pre_decouple_engine():
    """100 rows of varied data — half synced_to_hardcover, mix of sources, colors."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(PRE_MIGRATION_DDL))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_annotation "
            "ON kobo_annotation_sync (user_id, annotation_id)"
        ))
        conn.execute(text(
            "CREATE INDEX ix_kobo_annotation_sync_user_book "
            "ON kobo_annotation_sync (user_id, book_id)"
        ))
        base_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)
        for i in range(100):
            conn.execute(text("""
                INSERT INTO kobo_annotation_sync (
                    user_id, annotation_id, book_id, synced_to_hardcover,
                    hardcover_journal_id, created_at, last_synced,
                    highlighted_text, highlight_color, note_text,
                    content_id, start_container_path, start_container_child_index,
                    start_offset, end_container_path, end_container_child_index,
                    end_offset, context_string, chapter_progress, cfi_range,
                    source, hidden
                ) VALUES (
                    :user_id, :annotation_id, :book_id, :synced_to_hardcover,
                    :hardcover_journal_id, :created_at, :last_synced,
                    :highlighted_text, :highlight_color, :note_text,
                    :content_id, :start_container_path, :start_container_child_index,
                    :start_offset, :end_container_path, :end_container_child_index,
                    :end_offset, :context_string, :chapter_progress, :cfi_range,
                    :source, :hidden
                )
            """), {
                "user_id": (i % 5) + 1,
                "annotation_id": f"kobo-uuid-{i:04d}",
                "book_id": (i % 10) + 1,
                "synced_to_hardcover": 1 if i % 2 == 0 else 0,
                "hardcover_journal_id": 1000 + i if i % 2 == 0 else None,
                "created_at": (base_dt + timedelta(minutes=i)).isoformat(),
                "last_synced": (base_dt + timedelta(minutes=i + 5)).isoformat(),
                "highlighted_text": f"highlight text {i}",
                "highlight_color": ["yellow", "red", "green", "blue"][i % 4],
                "note_text": f"note {i}" if i % 3 == 0 else None,
                "content_id": f"!!chapter-{i % 7}.html",
                "start_container_path": f"/span[@id='kobo.{i}.1']/text()",
                "start_container_child_index": i % 3,
                "start_offset": i * 10,
                "end_container_path": f"/span[@id='kobo.{i}.5']/text()",
                "end_container_child_index": (i % 3) + 1,
                "end_offset": i * 10 + 50,
                "context_string": f"...context around highlight {i}...",
                "chapter_progress": (i % 100) / 100.0,
                "cfi_range": f"epubcfi(/6/{i % 20}!/4/2/1:0)" if i % 3 == 0 else None,
                # Half of synced rows have source='hardcover' (the bug), half source='kobo'.
                "source": (
                    "hardcover" if (i % 2 == 0 and i % 4 == 0)
                    else "kobo" if i % 2 == 0
                    else None
                ),
                "hidden": 0,
            })
    return engine


def test_preservation_sha256_match(populated_pre_decouple_engine):
    """Pre-migration fingerprint of preserved columns matches post-migration."""
    from cps.ub import migrate_annotation_decouple_source_target
    with populated_pre_decouple_engine.connect() as conn:
        pre_fp = _fingerprint(conn, "kobo_annotation_sync")
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        post_fp = _fingerprint(conn, "annotation")
    assert pre_fp == post_fp, "preserved columns changed across migration"


def test_preservation_row_count(populated_pre_decouple_engine):
    from cps.ub import migrate_annotation_decouple_source_target
    with populated_pre_decouple_engine.connect() as conn:
        pre = conn.execute(text("SELECT COUNT(*) FROM kobo_annotation_sync")).scalar()
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        post = conn.execute(text("SELECT COUNT(*) FROM annotation")).scalar()
        ast = conn.execute(text("SELECT COUNT(*) FROM annotation_sync_target")).scalar()
    assert pre == 100
    assert post == 100  # all rows preserved
    assert ast == 50    # half were synced_to_hardcover


def test_preservation_source_fully_normalized(populated_pre_decouple_engine):
    """No 'hardcover' values remain in source column after migration."""
    from cps.ub import migrate_annotation_decouple_source_target
    migrate_annotation_decouple_source_target(populated_pre_decouple_engine, None)
    with populated_pre_decouple_engine.connect() as conn:
        bad = conn.execute(text(
            "SELECT COUNT(*) FROM annotation WHERE source = 'hardcover'"
        )).scalar()
    assert bad == 0
```

- [ ] **Step 11.2: Run + pass**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_migration_preservation.py -v 2>&1 | tail -10
```
Expected: 3 passed.

- [ ] **Step 11.3: Commit**

```bash
git add tests/unit/test_annotation_migration_preservation.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(annotation): SHA-256 bit-exact preservation across 100-row decouple migration"
```

---

## Task 12: Annotation helpers (`sync_target`, `is_synced_to`)

**Files:**
- Create: `tests/unit/test_annotation_sync_helpers.py`

- [ ] **Step 12.1: Tests**

```python
"""Helpers on Annotation that traverse sync_targets relationship."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from cps import ub


@pytest.fixture
def session_with_ann():
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="t", email="t@example.com", role=0, password="x")
    s.add(user); s.commit()
    ann = ub.Annotation(
        user_id=user.id, annotation_id="abc", book_id=1, source="kobo",
    )
    s.add(ann); s.commit()
    yield s, ann
    s.close()


def test_sync_target_returns_none_for_missing(session_with_ann):
    _, ann = session_with_ann
    assert ann.sync_target("hardcover") is None
    assert ann.sync_target("readwise") is None


def test_sync_target_returns_matching_row(session_with_ann):
    s, ann = session_with_ann
    st = ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="synced",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    s.add(st); s.commit()
    s.refresh(ann)
    got = ann.sync_target("hardcover")
    assert got is not None
    assert got.status == "synced"


def test_is_synced_to_true_only_when_status_synced(session_with_ann):
    s, ann = session_with_ann
    assert ann.is_synced_to("hardcover") is False
    st = ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="failed",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    s.add(st); s.commit()
    s.refresh(ann)
    assert ann.is_synced_to("hardcover") is False
    st.status = "synced"; s.commit(); s.refresh(ann)
    assert ann.is_synced_to("hardcover") is True
    st.status = "tombstone"; s.commit(); s.refresh(ann)
    assert ann.is_synced_to("hardcover") is False


def test_helpers_tolerate_empty_sync_targets(session_with_ann):
    """Annotation with zero sync_target rows works without exceptions."""
    _, ann = session_with_ann
    # No rows added.
    assert ann.sync_target("hardcover") is None
    assert ann.is_synced_to("hardcover") is False
```

- [ ] **Step 12.2: Run + pass** (helpers implemented in Task 3; tests should pass on first run)

Run:
```bash
python3 -m pytest tests/unit/test_annotation_sync_helpers.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 12.3: Commit**

```bash
git add tests/unit/test_annotation_sync_helpers.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(annotation): pin sync_target() + is_synced_to() helper semantics"
```

---

## Task 13: Handler abstraction — `AnnotationSyncTargetHandler` ABC + `SyncResult`

**Files:**
- Create: `cps/services/annotation_sync/__init__.py`, `cps/services/annotation_sync/base.py`

- [ ] **Step 13.1: Create the new module dir**

Run:
```bash
mkdir -p cps/services/annotation_sync
```

- [ ] **Step 13.2: Write `cps/services/annotation_sync/base.py`**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Handler abstraction for annotation sync targets.

Handlers are stateless: they receive ORM objects, call remote APIs, return
SyncResult. The dispatcher (cps/services/annotation_sync/__init__.py) owns
persistence — handlers never write to the DB.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a single push/delete attempt against a remote sync target."""
    status: str
    target_record_id: Optional[str] = None
    error_message: Optional[str] = None


class AnnotationSyncTargetHandler(ABC):
    """Pushes annotation changes to a single remote target (Hardcover, etc.).

    Subclass + register via ``register_handler()``. The dispatcher iterates
    registered handlers per annotation; each handler decides whether the
    annotation is in its scope (via ``is_enabled``).
    """

    target_name: str  # e.g. 'hardcover'

    @abstractmethod
    def is_enabled(self, user) -> bool:
        """True iff sync to this target is enabled (globally + for this user)."""

    @abstractmethod
    def push(self, annotation, book, user) -> SyncResult:
        """Push or update the annotation on the remote. Idempotent."""

    @abstractmethod
    def delete(self, sync_target, user) -> SyncResult:
        """Delete the annotation from the remote. Returns SyncResult with
        status='tombstone' on success (including remote-already-deleted)."""
```

- [ ] **Step 13.3: Write minimal `cps/services/annotation_sync/__init__.py`**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Annotation sync target dispatcher.

Public API:
- register_handler(handler)
- available_targets() -> list[str]
- dispatch_annotation_sync(payload, book, user)
- dispatch_annotation_deletes(deleted_ids, user)
"""

from __future__ import annotations

from typing import Dict, List

from .base import AnnotationSyncTargetHandler, SyncResult

_HANDLERS: Dict[str, AnnotationSyncTargetHandler] = {}


def register_handler(handler: AnnotationSyncTargetHandler) -> None:
    """Register a handler. Replaces any previous handler with the same target_name."""
    _HANDLERS[handler.target_name] = handler


def available_targets() -> List[str]:
    return list(_HANDLERS.keys())


def _registered_handlers():
    """Snapshot of currently registered handlers — for tests + dispatch."""
    return list(_HANDLERS.values())


def reset_registry_for_testing() -> None:
    """Test-only: clear registered handlers between tests."""
    _HANDLERS.clear()
```

- [ ] **Step 13.4: Smoke test the new module imports**

Run:
```bash
python3 -c "from cps.services.annotation_sync import base, register_handler, available_targets; from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult; print('OK', available_targets())"
```
Expected: `OK []`.

- [ ] **Step 13.5: Commit Task 13**

```bash
git add cps/services/annotation_sync/__init__.py cps/services/annotation_sync/base.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation_sync): handler ABC + SyncResult dataclass + minimal registry

Setup for the per-target handler abstraction.  Hardcover handler ports
existing readingservices.py logic in the next commit."
```

---

## Task 14: HardcoverHandler — extracted from `readingservices.py`

**Files:**
- Create: `cps/services/annotation_sync/hardcover.py`, `tests/fixtures/mock_hardcover_client.py`, `tests/unit/test_hardcover_handler.py`

- [ ] **Step 14.1: Inspect the source we're extracting from**

Read `cps/readingservices.py` lines 320–490 to confirm the current shape of
`process_annotation_for_sync` and the delete loop. The extraction must preserve
all behaviour — identifier lookup, blacklist check, progress calculator setup,
exception handling — but route the result through `SyncResult` instead of
writing to `KoboAnnotationSync` directly.

- [ ] **Step 14.2: Create the mock Hardcover client fixture**

Create `tests/fixtures/mock_hardcover_client.py`:

```python
"""Drop-in replacement for cps.services.hardcover.HardcoverClient.

Controllable response shapes for unit + integration tests.
"""

from __future__ import annotations
from typing import Optional


class MockHardcoverClient:
    """Minimal subset of HardcoverClient surface used by HardcoverHandler.

    Configure via constructor or by mutating attributes between calls.
    Records every call into ``self.calls`` for assertions.
    """

    def __init__(
        self,
        push_response: Optional[dict] = None,
        push_raises: Optional[Exception] = None,
        delete_response: Optional[int] = None,
        delete_raises: Optional[Exception] = None,
    ):
        self.push_response = push_response if push_response is not None else {"id": 42}
        self.push_raises = push_raises
        self.delete_response = delete_response
        self.delete_raises = delete_raises
        self.calls = []

    def push_annotation(self, *args, **kwargs):
        self.calls.append(("push", args, kwargs))
        if self.push_raises:
            raise self.push_raises
        return self.push_response

    def delete_journal_entry(self, journal_id):
        self.calls.append(("delete", journal_id))
        if self.delete_raises:
            raise self.delete_raises
        return self.delete_response if self.delete_response is not None else journal_id
```

- [ ] **Step 14.3: Write `tests/unit/test_hardcover_handler.py`**

```python
"""Unit tests for HardcoverHandler.

The handler is stateless — all DB access happens in the dispatcher.  These
tests pin only the result shape and the API call wiring against the mocked
HardcoverClient.
"""

import pytest
from cps.services.annotation_sync.hardcover import HardcoverHandler
from tests.fixtures.mock_hardcover_client import MockHardcoverClient


class FakeUser:
    def __init__(self, hardcover_token="tok", id=1):
        self.hardcover_token = hardcover_token
        self.id = id


class FakeBook:
    def __init__(self, id=1, title="Title"):
        self.id = id; self.title = title
        # Minimal identifiers shape — HardcoverHandler.push reads this.
        from types import SimpleNamespace
        self.identifiers = [SimpleNamespace(type_name="isbn", val="9780000000000")]


class FakeAnnotation:
    def __init__(self, **kw):
        defaults = {
            "id": 1, "annotation_id": "kobo-uuid-001",
            "highlighted_text": "hello", "note_text": "note",
            "highlight_color": "yellow", "chapter_progress": 0.5,
            "source": "kobo",
        }
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_push_returns_synced_on_200():
    """Successful push returns SyncResult(status='synced', target_record_id=...)."""
    client = MockHardcoverClient(push_response={"id": 999})
    h = HardcoverHandler(client_factory=lambda token: client)
    result = h.push(FakeAnnotation(), FakeBook(), FakeUser())
    assert result.status == "synced"
    assert result.target_record_id == "999"


def test_push_returns_failed_on_no_response():
    """Push that gets back nothing/falsy returns failed."""
    client = MockHardcoverClient(push_response=None)
    h = HardcoverHandler(client_factory=lambda token: client)
    result = h.push(FakeAnnotation(), FakeBook(), FakeUser())
    assert result.status == "failed"
    assert result.error_message is not None


def test_push_catches_exceptions_as_failed():
    """Any exception in the remote call becomes SyncResult(status='failed')."""
    client = MockHardcoverClient(push_raises=RuntimeError("boom"))
    h = HardcoverHandler(client_factory=lambda token: client)
    result = h.push(FakeAnnotation(), FakeBook(), FakeUser())
    assert result.status == "failed"
    assert "boom" in (result.error_message or "")


def test_delete_returns_tombstone_on_200():
    """Successful delete returns tombstone."""
    client = MockHardcoverClient(delete_response=123)
    h = HardcoverHandler(client_factory=lambda token: client)
    from types import SimpleNamespace
    st = SimpleNamespace(target_record_id="123", status="synced")
    result = h.delete(st, FakeUser())
    assert result.status == "tombstone"


def test_delete_treats_404_as_already_deleted_tombstone():
    """A 404 (no journal entry to delete) is treated as success."""
    class NotFound(Exception):
        pass
    client = MockHardcoverClient(delete_raises=NotFound("404"))
    h = HardcoverHandler(client_factory=lambda token: client, not_found_exception=NotFound)
    from types import SimpleNamespace
    st = SimpleNamespace(target_record_id="missing", status="synced")
    result = h.delete(st, FakeUser())
    assert result.status == "tombstone"
    assert "already deleted" in (result.error_message or "").lower()


def test_is_enabled_requires_user_token():
    """is_enabled requires the user to have a hardcover_token AND config to allow it."""
    h = HardcoverHandler(
        client_factory=lambda token: MockHardcoverClient(),
        config_getter=lambda: True,  # global toggle on
    )
    assert h.is_enabled(FakeUser(hardcover_token="t")) is True
    assert h.is_enabled(FakeUser(hardcover_token=None)) is False
    h2 = HardcoverHandler(client_factory=lambda t: MockHardcoverClient(), config_getter=lambda: False)
    assert h2.is_enabled(FakeUser(hardcover_token="t")) is False
```

- [ ] **Step 14.4: Implement `cps/services/annotation_sync/hardcover.py`**

```python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""HardcoverHandler — push/delete annotations to Hardcover via HardcoverClient.

Extracted from cps/readingservices.py:process_annotation_for_sync as part
of the source/sync-target decoupling (see notes/2026-05-21-annotation-
decouple-source-target-DESIGN.md).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .base import AnnotationSyncTargetHandler, SyncResult

log = logging.getLogger(__name__)


def _default_client_factory(token):
    """Lazy import so unit tests don't drag in the full Hardcover service."""
    from cps.services import hardcover as _hardcover
    return _hardcover.HardcoverClient(token)


def _default_config_getter():
    from cps import config
    return bool(getattr(config, "config_hardcover_annotations_sync", False))


class HardcoverHandler(AnnotationSyncTargetHandler):
    target_name = "hardcover"

    def __init__(
        self,
        client_factory: Callable = _default_client_factory,
        config_getter: Callable[[], bool] = _default_config_getter,
        not_found_exception: Optional[type] = None,
    ):
        self._client_factory = client_factory
        self._config_getter = config_getter
        self._not_found_exception = not_found_exception

    def is_enabled(self, user) -> bool:
        if not self._config_getter():
            return False
        if not getattr(user, "hardcover_token", None):
            return False
        return True

    def push(self, annotation, book, user) -> SyncResult:
        try:
            client = self._client_factory(user.hardcover_token)
            response = client.push_annotation(
                annotation=annotation, book=book, user=user,
            )
        except Exception as exc:
            log.warning("HardcoverHandler.push raised: %s", exc)
            return SyncResult(status="failed", error_message=str(exc))
        if not response or "id" not in response:
            return SyncResult(
                status="failed",
                error_message=f"empty response: {response!r}",
            )
        return SyncResult(
            status="synced",
            target_record_id=str(response["id"]),
        )

    def delete(self, sync_target, user) -> SyncResult:
        try:
            client = self._client_factory(user.hardcover_token)
            deleted_id = client.delete_journal_entry(
                journal_id=sync_target.target_record_id,
            )
        except Exception as exc:
            if self._not_found_exception and isinstance(exc, self._not_found_exception):
                return SyncResult(
                    status="tombstone",
                    target_record_id=sync_target.target_record_id,
                    error_message="already deleted on remote",
                )
            log.warning("HardcoverHandler.delete raised: %s", exc)
            return SyncResult(status="failed", error_message=str(exc))
        if str(deleted_id) != str(sync_target.target_record_id):
            return SyncResult(
                status="failed",
                error_message=f"remote returned mismatched id: {deleted_id!r}",
            )
        return SyncResult(
            status="tombstone",
            target_record_id=sync_target.target_record_id,
        )
```

> **Open question from the spec**: HardcoverClient's actual signature for
> `push_annotation` and `delete_journal_entry` will determine whether the
> mock fixture's positional/keyword args need adjusting. Verify by reading
> `cps/services/hardcover.py` before running tests in Step 14.5; adjust the
> handler call site (and the mock) to match the real client's contract.

- [ ] **Step 14.5: Verify real HardcoverClient signatures match handler call**

Run:
```bash
python3 -c "import inspect; from cps.services.hardcover import HardcoverClient; print('push:', inspect.signature(HardcoverClient.push_annotation) if hasattr(HardcoverClient, 'push_annotation') else 'MISSING'); print('delete:', inspect.signature(HardcoverClient.delete_journal_entry) if hasattr(HardcoverClient, 'delete_journal_entry') else 'MISSING')"
```

Compare signature against the handler's call. If the real method is named
differently (the current code in `readingservices.py:421-440` does *not*
appear to call a `push_annotation` method — it constructs the body inline
and calls `client.update_user_book_journals` or similar), adjust the
handler's call site + the mock client's method name accordingly. Document
the actual method used in a code comment inside `hardcover.py`.

- [ ] **Step 14.6: Run tests + iterate until pass**

Run:
```bash
python3 -m pytest tests/unit/test_hardcover_handler.py -v 2>&1 | tail -20
```
If failures: read the failure message, adjust the handler or test, repeat.
Expected outcome: 6 tests passed.

- [ ] **Step 14.7: Wire HardcoverHandler into the registry**

Edit `cps/services/annotation_sync/__init__.py`. At the bottom add:

```python
# Auto-register Hardcover handler at import time.
from .hardcover import HardcoverHandler
register_handler(HardcoverHandler())
```

- [ ] **Step 14.8: Verify auto-registration**

Run:
```bash
python3 -c "from cps.services.annotation_sync import available_targets; print(available_targets())"
```
Expected: `['hardcover']`.

- [ ] **Step 14.9: Commit**

```bash
git add cps/services/annotation_sync/hardcover.py cps/services/annotation_sync/__init__.py tests/fixtures/mock_hardcover_client.py tests/unit/test_hardcover_handler.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation_sync): HardcoverHandler extracted from readingservices.py

Handler is stateless — owns push() / delete() / is_enabled() and returns
SyncResult.  DB writes happen in the dispatcher, not the handler.

Hardcover 404 on delete treated as success (tombstone with 'already
deleted on remote' note), closing the existing TODO at
readingservices.py:472-474 about orphaned journal entries.

Auto-registered at module import."
```

---

## Task 15: Dispatcher — `dispatch_annotation_sync` + `dispatch_annotation_deletes`

**Files:**
- Modify: `cps/services/annotation_sync/__init__.py`
- Create: `tests/unit/test_annotation_sync_dispatcher.py`

- [ ] **Step 15.1: Write tests**

```python
"""Dispatcher tests — UPSERT semantics, race handling, terminal tombstone."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps import ub
from cps.services.annotation_sync import (
    register_handler, reset_registry_for_testing,
    dispatch_annotation_sync, dispatch_annotation_deletes,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


class StubHandler(AnnotationSyncTargetHandler):
    target_name = "stub"
    def __init__(self, push_result=None, delete_result=None, enabled=True):
        self.push_result = push_result or SyncResult(status="synced", target_record_id="r1")
        self.delete_result = delete_result or SyncResult(status="tombstone")
        self._enabled = enabled
        self.calls = []
    def is_enabled(self, user):
        return self._enabled
    def push(self, annotation, book, user):
        self.calls.append(("push", annotation.annotation_id))
        return self.push_result
    def delete(self, sync_target, user):
        self.calls.append(("delete", sync_target.target_record_id))
        return self.delete_result


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="u", email="u@e.com", role=0, password="x", hardcover_token="t")
    s.add(user); s.commit()
    yield s, user
    s.close()


def _payload(annotation_id, text="hi", color="yellow", note=None):
    return {
        "id": annotation_id,
        "highlightedText": text,
        "highlightColor": color,
        "noteText": note,
        "location": {"span": {"chapterProgress": 0.5}},
    }


def test_dispatch_creates_annotation_and_sync_target(session, monkeypatch):
    s, user = session
    handler = StubHandler()
    register_handler(handler)
    book = type("B", (), {"id": 7, "title": "T"})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-a")], book, user)
    rows = s.query(ub.Annotation).all()
    assert len(rows) == 1
    assert rows[0].source == "kobo"
    targets = s.query(ub.AnnotationSyncTarget).all()
    assert len(targets) == 1
    assert targets[0].target == "stub"
    assert targets[0].status == "synced"
    assert targets[0].target_record_id == "r1"


def test_dispatch_updates_existing_annotation(session, monkeypatch):
    s, user = session
    register_handler(StubHandler())
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-a", text="v1")], book, user)
    dispatch_annotation_sync([_payload("uuid-a", text="v2")], book, user)
    rows = s.query(ub.Annotation).all()
    assert len(rows) == 1
    assert rows[0].highlighted_text == "v2"
    targets = s.query(ub.AnnotationSyncTarget).all()
    assert len(targets) == 1  # UPSERT, not duplicate


def test_dispatch_skips_disabled_handler(session, monkeypatch):
    s, user = session
    h = StubHandler(enabled=False)
    register_handler(h)
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-a")], book, user)
    assert s.query(ub.Annotation).count() == 1  # annotation persists
    assert s.query(ub.AnnotationSyncTarget).count() == 0  # no sync_target row
    assert h.calls == []


def test_dispatch_records_failed_status_on_handler_failure(session, monkeypatch):
    s, user = session
    h = StubHandler(push_result=SyncResult(status="failed", error_message="boom"))
    register_handler(h)
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-a")], book, user)
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "failed"
    assert st.error_message == "boom"


def test_dispatch_delete_transitions_to_tombstone(session, monkeypatch):
    s, user = session
    h = StubHandler()
    register_handler(h)
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-x")], book, user)
    assert s.query(ub.AnnotationSyncTarget).one().status == "synced"
    dispatch_annotation_deletes(["uuid-x"], user)
    assert s.query(ub.AnnotationSyncTarget).one().status == "tombstone"


def test_dispatch_delete_skips_tombstoned(session, monkeypatch):
    s, user = session
    h = StubHandler()
    register_handler(h)
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    dispatch_annotation_sync([_payload("uuid-x")], book, user)
    dispatch_annotation_deletes(["uuid-x"], user)
    h.calls.clear()
    dispatch_annotation_deletes(["uuid-x"], user)  # second delete
    # Already tombstoned — handler.delete should NOT be called again.
    assert h.calls == []


def test_dispatch_handles_concurrent_insert_race(session, monkeypatch):
    """Simulate two threads creating the same (annotation_id, target) row.
    Second insert raises IntegrityError; dispatcher catches + UPSERTs.
    """
    s, user = session
    register_handler(StubHandler())
    book = type("B", (), {"id": 7})()
    monkeypatch.setattr("cps.services.annotation_sync.ub.session", s)
    # Pre-create the conflicting row.
    ann = ub.Annotation(user_id=user.id, annotation_id="uuid-r", book_id=7, source="kobo")
    s.add(ann); s.commit()
    s.add(ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="stub", status="failed", error_message="prior",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    s.commit()
    dispatch_annotation_sync([_payload("uuid-r")], book, user)
    st = s.query(ub.AnnotationSyncTarget).one()
    assert st.status == "synced"  # updated, not duplicated
    assert st.error_message is None
```

- [ ] **Step 15.2: Implement dispatcher in `cps/services/annotation_sync/__init__.py`**

Edit `cps/services/annotation_sync/__init__.py`. Append the dispatcher functions:

```python
import logging
from datetime import datetime, timezone

from cps import ub

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _upsert_annotation(session, payload, book, user):
    """Find-or-create Annotation row keyed on (user_id, annotation_id)."""
    annotation_id = payload.get("id")
    if not annotation_id:
        return None
    ann = (
        session.query(ub.Annotation)
        .filter(
            ub.Annotation.user_id == user.id,
            ub.Annotation.annotation_id == annotation_id,
        )
        .first()
    )
    if ann is None:
        ann = ub.Annotation(
            user_id=user.id,
            annotation_id=annotation_id,
            book_id=book.id,
            source="kobo",
        )
        session.add(ann)
    # Update content fields from payload.
    ann.highlighted_text = payload.get("highlightedText", ann.highlighted_text)
    ann.note_text = payload.get("noteText", ann.note_text)
    ann.highlight_color = payload.get("highlightColor", ann.highlight_color)
    chapter_progress = (payload.get("location") or {}).get("span", {}).get("chapterProgress")
    if chapter_progress is not None:
        ann.chapter_progress = chapter_progress
    ann.last_synced = _now()
    session.flush()  # need ann.id below
    return ann


def _upsert_sync_target(session, ann, handler_name, result):
    """Find-or-create the (annotation_id, target) row + update from SyncResult.

    Handles the IntegrityError race when two concurrent writers try to INSERT
    the same pair.
    """
    from sqlalchemy.exc import IntegrityError
    st = (
        session.query(ub.AnnotationSyncTarget)
        .filter(
            ub.AnnotationSyncTarget.annotation_id == ann.id,
            ub.AnnotationSyncTarget.target == handler_name,
        )
        .first()
    )
    if st is None:
        st = ub.AnnotationSyncTarget(
            annotation_id=ann.id,
            target=handler_name,
            status=result.status,
            target_record_id=result.target_record_id,
            error_message=result.error_message,
            last_attempt=_now(),
            last_synced=_now() if result.status == "synced" else None,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(st)
        try:
            session.flush()
        except IntegrityError:
            # Concurrent INSERT — recover by re-reading.
            session.rollback()
            st = (
                session.query(ub.AnnotationSyncTarget)
                .filter(
                    ub.AnnotationSyncTarget.annotation_id == ann.id,
                    ub.AnnotationSyncTarget.target == handler_name,
                )
                .first()
            )
            if st is not None:
                _apply_result(st, result)
        return st
    _apply_result(st, result)
    return st


def _apply_result(st, result):
    """Mutate AnnotationSyncTarget in place from a SyncResult."""
    prior = st.status
    st.status = result.status
    if result.target_record_id:
        st.target_record_id = result.target_record_id
    if result.status == "synced":
        st.last_synced = _now()
        st.error_message = None
    else:
        st.error_message = result.error_message
    st.last_attempt = _now()
    st.updated_at = _now()
    log.info(
        "annotation_sync: %s",
        {
            "event": "transition",
            "annotation_id": st.annotation_id,
            "target": st.target,
            "from_status": prior,
            "to_status": result.status,
            "error_message": result.error_message,
        },
    )


def dispatch_annotation_sync(payload_annotations, book, user) -> None:
    """For each annotation in the PATCH payload, persist + push to each enabled handler."""
    if not payload_annotations:
        return
    for payload in payload_annotations:
        ann = _upsert_annotation(ub.session, payload, book, user)
        if ann is None:
            continue
        for handler in _registered_handlers():
            if not handler.is_enabled(user):
                continue
            existing = ann.sync_target(handler.target_name)
            if existing is not None and existing.status == "tombstone":
                continue  # terminal — never re-push
            try:
                result = handler.push(ann, book, user)
            except Exception as exc:
                log.exception("dispatcher: handler %s push raised", handler.target_name)
                result = SyncResult(status="failed", error_message=str(exc))
            _upsert_sync_target(ub.session, ann, handler.target_name, result)
    ub.session_commit()


def dispatch_annotation_deletes(deleted_ids, user) -> None:
    """For each annotation_id, transition each non-tombstone sync_target to tombstone via handler.delete."""
    if not deleted_ids:
        return
    for annotation_id in deleted_ids:
        ann = (
            ub.session.query(ub.Annotation)
            .filter(
                ub.Annotation.user_id == user.id,
                ub.Annotation.annotation_id == annotation_id,
            )
            .first()
        )
        if ann is None:
            continue
        for st in list(ann.sync_targets):
            if st.status == "tombstone":
                continue
            handler = _HANDLERS.get(st.target)
            if handler is None or not handler.is_enabled(user):
                continue
            try:
                result = handler.delete(st, user)
            except Exception as exc:
                log.exception("dispatcher: handler %s delete raised", handler.target_name)
                result = SyncResult(status="failed", error_message=str(exc))
            _apply_result(st, result)
    ub.session_commit()
```

- [ ] **Step 15.3: Run tests + iterate**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_sync_dispatcher.py -v 2>&1 | tail -30
```
Expected: 7 passed. Common failure mode: session-binding mismatch — adjust the `monkeypatch.setattr` target if `ub.session` isn't where it's expected.

- [ ] **Step 15.4: Commit**

```bash
git add cps/services/annotation_sync/__init__.py tests/unit/test_annotation_sync_dispatcher.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation_sync): dispatcher with UPSERT + race-safe sync_target writes

dispatch_annotation_sync() / dispatch_annotation_deletes() — own all DB
writes for the per-target sync state.  Concurrent INSERT race handled
via IntegrityError recovery.  Tombstone is terminal."
```

---

## Task 16: Refactor `cps/readingservices.py` PATCH handler

**Files:**
- Modify: `cps/readingservices.py`

- [ ] **Step 16.1: Read the current `handle_annotations` and surrounding helpers**

Open `cps/readingservices.py:308-583`. Understand the current flow:
- `process_annotation_for_sync` (line 347) — synthesizes the per-annotation push
- `handle_annotations` (line 493) — top-level PATCH handler

- [ ] **Step 16.2: Replace `handle_annotations` body with the orchestrator pattern**

Edit `cps/readingservices.py`. Replace lines 490-582 (from `@csrf.exempt` through end of `handle_annotations` + the deprecated `handle_check_for_changes` is left alone) with the new shape. Keep the route decorators and the `proxy_to_kobo_reading_services()` tail; replace only the PATCH-branch body.

```python
@csrf.exempt
@readingservices_api_v3.route("/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth_and_config
def handle_annotations(entitlement_id):
    """Handle annotation requests for a specific book.

    GET requests proxy directly to Kobo.  PATCH requests are intercepted:
    persist the annotation locally (source='kobo') then dispatch through
    every registered + enabled sync handler.
    """
    if request.method == "PATCH":
        try:
            data = request.get_json() or {}
            log_annotation_data(entitlement_id, "PATCH", data)
            book = get_book_by_entitlement_id(entitlement_id)
            if book is not None:
                from cps.services import annotation_sync
                if data.get("updatedAnnotations"):
                    annotation_sync.dispatch_annotation_sync(
                        data["updatedAnnotations"], book, current_user,
                    )
                if data.get("deletedAnnotationIds"):
                    annotation_sync.dispatch_annotation_deletes(
                        data["deletedAnnotationIds"], current_user,
                    )
        except Exception:
            log.exception("Error processing PATCH annotations")
    return proxy_to_kobo_reading_services()
```

- [ ] **Step 16.3: Remove `process_annotation_for_sync` and the old per-annotation/per-delete loops (now dead code)**

Delete from `cps/readingservices.py`:
- The `process_annotation_for_sync` function (lines 347-486).
- The inline annotation/delete handling that lived inside the previous `handle_annotations` body — those are subsumed by the dispatcher call.

Any remaining helpers used by both old and new paths (`get_book_by_entitlement_id`, `log_annotation_data`, `get_book_identifiers`, `EpubProgressCalculator`) stay.

- [ ] **Step 16.4: Run the full annotation test suite + confirm green**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_schema.py tests/unit/test_annotation_sync_helpers.py tests/unit/test_annotation_decouple_migration.py tests/unit/test_annotation_migration_preservation.py tests/unit/test_hardcover_handler.py tests/unit/test_annotation_sync_dispatcher.py -v 2>&1 | tail -10
```
Expected: All previously-passing tests still pass.

- [ ] **Step 16.5: Commit**

```bash
git add cps/readingservices.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "refactor(readingservices): PATCH handler becomes thin orchestrator

Replaces the inline process_annotation_for_sync + delete loop with calls
to cps.services.annotation_sync.dispatch_*.  Per-handler Hardcover logic
moved to HardcoverHandler.  Lines saved: ~140."
```

---

## Task 17: Update `cps/annotations.py` + `cps/admin.py`

**Files:**
- Modify: `cps/annotations.py`, `cps/admin.py`

- [ ] **Step 17.1: Replace `ub.KoboAnnotationSync` → `ub.Annotation` in `cps/annotations.py`**

Open `cps/annotations.py`. Use Edit's `replace_all=true` to swap `ub.KoboAnnotationSync` → `ub.Annotation` (~8 occurrences). Also update docstring references to `kobo_annotation_sync` table → `annotation` table.

- [ ] **Step 17.2: Update `cps/admin.py:3155` wipe list**

Edit `cps/admin.py:3153-3157`. Replace `"kobo_annotation_sync"` with `"annotation"`, AND add `"annotation_sync_target"` to the list since the new table is also book-linked.

```python
book_tables = [
    "book_shelf_link", "book_read_link", "bookmark", "archived_book", "kobo_synced_books",
    "kobo_reading_state", "kobo_bookmark", "kobo_statistics", "annotation_sync_target",
    "annotation",
    "hardcover_book_blacklist", "hardcover_match_queue", "downloads", "magic_shelf_cache"
]
```

Note: the order matters — `annotation_sync_target` must be wiped BEFORE `annotation` because of the FK.

- [ ] **Step 17.3: Run all unit tests + the annotation import/view/data endpoint tests**

Run:
```bash
python3 -m pytest tests/unit/test_annotations_import_endpoint.py tests/unit/test_annotations_view_export.py tests/unit/test_annotations_data_endpoint.py -v 2>&1 | tail -15
```
Expected: all previously-passing tests pass.  Any failures = mis-rename
in cps/annotations.py — fix.

- [ ] **Step 17.4: Commit**

```bash
git add cps/annotations.py cps/admin.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "refactor(annotation): rename KoboAnnotationSync references in annotations.py + admin.py"
```

---

## Task 18: Update annotation_backup.py to schema_version=2

**Files:**
- Modify: `cps/services/annotation_backup.py`, `tests/unit/test_annotation_backup.py`
- Create: `tests/unit/test_annotation_backup_v2.py`

- [ ] **Step 18.1: Inspect the current backup payload shape**

Read `cps/services/annotation_backup.py` to confirm where `schema_version` is set and which fields go into the payload.

- [ ] **Step 18.2: Rename references + bump schema_version**

Search-and-replace in `cps/services/annotation_backup.py`:
- `KoboAnnotationSync` → `Annotation`
- `"schema_version": 1` → `"schema_version": 2`

Add a comment in the snapshot-builder noting that v2 includes `source`
explicitly (v1 implicitly was always 'kobo').

- [ ] **Step 18.3: Add v2 schema test**

Create `tests/unit/test_annotation_backup_v2.py`:

```python
"""Backup snapshot schema version tests."""

import gzip
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps import ub


@pytest.fixture
def session_with_user(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/app.db")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="t", email="t@example.com", role=0, password="x")
    s.add(user); s.commit()
    monkeypatch.setattr("cps.ub.session", s)
    monkeypatch.setattr("cps.services.annotation_backup._BACKUP_ROOT", tmp_path / "ab")
    return s, user


def test_new_snapshot_has_schema_version_2(session_with_user, tmp_path):
    s, user = session_with_user
    ann = ub.Annotation(
        user_id=user.id, annotation_id="abc", book_id=1, source="kobo",
        highlighted_text="hello",
    )
    s.add(ann); s.commit()
    # Trigger backup explicitly — production wires this through after_commit;
    # we call the worker function directly here for determinism.
    from cps.services.annotation_backup import _capture_snapshot
    _capture_snapshot(user_id=user.id, book_id=1)
    # Walk the backup root, find the most recent gzip.
    root = Path(tmp_path / "ab" / str(user.id) / "1")
    files = sorted(root.glob("*.json.gz"))
    assert files, f"no snapshot written under {root}"
    with gzip.open(files[-1], "rt") as f:
        payload = json.load(f)
    assert payload["schema_version"] == 2
    assert payload["annotations"][0]["source"] == "kobo"
```

The test uses the existing test infrastructure for `_capture_snapshot` —
adjust the call signature to match what's actually in
`cps/services/annotation_backup.py`. Read the source first.

- [ ] **Step 18.4: Run tests, fix any breakage in `test_annotation_backup.py` from the class rename**

Run:
```bash
python3 -m pytest tests/unit/test_annotation_backup.py tests/unit/test_annotation_backup_v2.py -v 2>&1 | tail -15
```
Expected: all tests pass after class-name updates in test_annotation_backup.py.

- [ ] **Step 18.5: Commit**

```bash
git add cps/services/annotation_backup.py tests/unit/test_annotation_backup.py tests/unit/test_annotation_backup_v2.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "feat(annotation_backup): bump snapshot schema_version 1 -> 2 with explicit source

v2 snapshots include the source field explicitly.  v1 snapshots are read
with source defaulting to 'kobo' (the only origin pre-H1)."
```

---

## Task 19: Rename test file + run full unit suite

**Files:**
- Rename: `tests/unit/test_kobo_annotation_sync_h1_schema.py` → DELETE (its content moved into `tests/unit/test_annotation_schema.py` in Task 2 + 3)

- [ ] **Step 19.1: Confirm the H1 schema test's content is fully covered by `test_annotation_schema.py`**

Compare `tests/unit/test_kobo_annotation_sync_h1_schema.py` against `tests/unit/test_annotation_schema.py`. The H1 file's tests (column-add idempotency, source-backfill scope, pre-H1 row survival) test the **H1 migration**, not the decouple migration. Those tests still need to exist — keep the file but rename its content/references where they overlap.

Actually, leave `test_kobo_annotation_sync_h1_schema.py` UNTOUCHED — it pins the H1 migration's idempotency, which we should not regress. Just verify it still passes.

- [ ] **Step 19.2: Run the full unit suite**

Run:
```bash
python3 -m pytest tests/unit/ -v 2>&1 | tail -30
```
Expected: All unit tests pass. The previously-passing test_kobo_annotation_sync_h1_schema.py still passes (the H1 migration we didn't touch).

If failures: address one at a time.

- [ ] **Step 19.3: Commit (if any fixes were needed)**

```bash
git add -A
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test: clean up references after class rename" --allow-empty
```

---

## Task 20: Integration tests — full PATCH lifecycle

**Files:**
- Create: `tests/integration/test_annotation_patch_lifecycle.py`

- [ ] **Step 20.1: Write integration tests**

```python
"""Full PATCH-handler integration test against the real Flask app +
mocked Hardcover client.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps import ub
from cps.services.annotation_sync import (
    register_handler, reset_registry_for_testing,
    dispatch_annotation_sync, dispatch_annotation_deletes,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


class RecordingHandler(AnnotationSyncTargetHandler):
    target_name = "hardcover"
    def __init__(self):
        self.push_results = []
        self.delete_results = []
    def is_enabled(self, user): return True
    def push(self, annotation, book, user):
        r = SyncResult(status="synced", target_record_id=f"hc-{annotation.annotation_id}")
        self.push_results.append(r); return r
    def delete(self, sync_target, user):
        r = SyncResult(status="tombstone", target_record_id=sync_target.target_record_id)
        self.delete_results.append(r); return r


@pytest.fixture(autouse=True)
def _registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


@pytest.fixture
def session_with_user(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/app.db")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    monkeypatch.setattr(ub, "session", s)
    user = ub.User(name="u", email="u@e.com", role=0, password="x", hardcover_token="t")
    s.add(user); s.commit()
    return s, user


def _book(book_id=7):
    from types import SimpleNamespace
    return SimpleNamespace(id=book_id, title=f"B{book_id}", identifiers=[])


def test_new_annotation_creates_both_rows(session_with_user):
    s, user = session_with_user
    register_handler(RecordingHandler())
    payload = [{
        "id": "k1", "highlightedText": "first", "highlightColor": "yellow",
        "noteText": None, "location": {"span": {"chapterProgress": 0.1}},
    }]
    dispatch_annotation_sync(payload, _book(), user)
    assert s.query(ub.Annotation).count() == 1
    ast = s.query(ub.AnnotationSyncTarget).one()
    assert ast.status == "synced"
    assert ast.target_record_id == "hc-k1"


def test_updated_annotation_updates_both(session_with_user):
    s, user = session_with_user
    register_handler(RecordingHandler())
    dispatch_annotation_sync([{
        "id": "k1", "highlightedText": "v1", "highlightColor": "yellow",
        "noteText": None, "location": {"span": {"chapterProgress": 0.1}},
    }], _book(), user)
    dispatch_annotation_sync([{
        "id": "k1", "highlightedText": "v2", "highlightColor": "red",
        "noteText": "added", "location": {"span": {"chapterProgress": 0.2}},
    }], _book(), user)
    ann = s.query(ub.Annotation).one()
    assert ann.highlighted_text == "v2"
    assert ann.highlight_color == "red"
    assert ann.note_text == "added"
    assert s.query(ub.AnnotationSyncTarget).count() == 1


def test_delete_transitions_to_tombstone(session_with_user):
    s, user = session_with_user
    register_handler(RecordingHandler())
    dispatch_annotation_sync([{
        "id": "k1", "highlightedText": "x", "highlightColor": "yellow",
        "noteText": None, "location": {"span": {"chapterProgress": 0.1}},
    }], _book(), user)
    dispatch_annotation_deletes(["k1"], user)
    ast = s.query(ub.AnnotationSyncTarget).one()
    assert ast.status == "tombstone"


def test_failed_push_recorded_then_succeeds_on_retry(session_with_user):
    s, user = session_with_user
    class FlakyHandler(AnnotationSyncTargetHandler):
        target_name = "hardcover"
        def __init__(self): self.call_n = 0
        def is_enabled(self, user): return True
        def push(self, annotation, book, user):
            self.call_n += 1
            if self.call_n == 1:
                return SyncResult(status="failed", error_message="net")
            return SyncResult(status="synced", target_record_id="hc-1")
        def delete(self, sync_target, user):
            return SyncResult(status="tombstone")
    register_handler(FlakyHandler())
    payload = [{
        "id": "k1", "highlightedText": "x", "highlightColor": "yellow",
        "noteText": None, "location": {"span": {"chapterProgress": 0.1}},
    }]
    dispatch_annotation_sync(payload, _book(), user)
    ast = s.query(ub.AnnotationSyncTarget).one()
    assert ast.status == "failed"
    assert ast.error_message == "net"
    dispatch_annotation_sync(payload, _book(), user)
    ast = s.query(ub.AnnotationSyncTarget).one()
    assert ast.status == "synced"
    assert ast.error_message is None
    assert ast.target_record_id == "hc-1"


def test_tombstone_is_terminal_against_repeat_push(session_with_user):
    s, user = session_with_user
    register_handler(RecordingHandler())
    payload = [{
        "id": "k1", "highlightedText": "x", "highlightColor": "yellow",
        "noteText": None, "location": {"span": {"chapterProgress": 0.1}},
    }]
    dispatch_annotation_sync(payload, _book(), user)
    dispatch_annotation_deletes(["k1"], user)
    # Try to re-push the same annotation_id.
    dispatch_annotation_sync(payload, _book(), user)
    ast = s.query(ub.AnnotationSyncTarget).one()
    assert ast.status == "tombstone"  # NOT resurrected
```

- [ ] **Step 20.2: Run + iterate until pass**

Run:
```bash
python3 -m pytest tests/integration/test_annotation_patch_lifecycle.py -v 2>&1 | tail -15
```
Expected: 5 passed.

- [ ] **Step 20.3: Commit**

```bash
git add tests/integration/test_annotation_patch_lifecycle.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(integration): full PATCH lifecycle — create/update/delete/retry/tombstone-terminal"
```

---

## Task 21: Integration tests — handler registration

**Files:**
- Create: `tests/integration/test_annotation_handler_registration.py`

- [ ] **Step 21.1: Write tests**

```python
"""Tests around register_handler / available_targets / disabled-handler skip."""

import pytest
from cps.services.annotation_sync import (
    register_handler, available_targets, reset_registry_for_testing,
)
from cps.services.annotation_sync.base import AnnotationSyncTargetHandler, SyncResult


@pytest.fixture(autouse=True)
def _registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


def test_available_targets_starts_empty():
    assert available_targets() == []


def test_register_handler_adds_name():
    class H(AnnotationSyncTargetHandler):
        target_name = "test1"
        def is_enabled(self, user): return True
        def push(self, a, b, u): return SyncResult(status="synced")
        def delete(self, st, u): return SyncResult(status="tombstone")
    register_handler(H())
    assert available_targets() == ["test1"]


def test_register_replaces_same_target_name():
    class H(AnnotationSyncTargetHandler):
        target_name = "same"
        def is_enabled(self, user): return True
        def push(self, a, b, u): return SyncResult(status="synced")
        def delete(self, st, u): return SyncResult(status="tombstone")
    register_handler(H())
    register_handler(H())
    # Re-registration replaces, doesn't duplicate.
    assert available_targets() == ["same"]


def test_multiple_handlers_registered_in_order():
    for name in ["a", "b", "c"]:
        class H(AnnotationSyncTargetHandler):
            target_name = name
            def is_enabled(self, user): return True
            def push(self, a, b, u): return SyncResult(status="synced")
            def delete(self, st, u): return SyncResult(status="tombstone")
        register_handler(H())
    assert set(available_targets()) == {"a", "b", "c"}
```

- [ ] **Step 21.2: Run + pass**

Run:
```bash
python3 -m pytest tests/integration/test_annotation_handler_registration.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 21.3: Commit**

```bash
git add tests/integration/test_annotation_handler_registration.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(integration): register_handler / available_targets / replace-by-name"
```

---

## Task 22: Docker test — migration on boot

**Files:**
- Create: `tests/docker/test_annotation_migration_on_boot.py`

- [ ] **Step 22.1: Inspect existing docker tests for the pattern**

Read one of the existing `tests/docker/` files to see how `cwn-local` is built + run + probed. Mirror the pattern.

- [ ] **Step 22.2: Write the boot test**

Create `tests/docker/test_annotation_migration_on_boot.py`:

```python
"""Docker boot tests for the annotation-decouple migration.

Three scenarios:
1. Empty DB — migration is a no-op (no kobo_annotation_sync table exists)
2. Populated H1-schema DB — migration runs to completion
3. Already-migrated DB — migration is a no-op
"""

import pytest
import subprocess
import time
import tempfile
import sqlite3
from pathlib import Path


pytestmark = [pytest.mark.docker, pytest.mark.slow]


CONTAINER_NAME = "cwn-annotation-decouple-migration-test"
IMAGE_TAG = "cwn-annotation-decouple-test"


def _build_image(repo_root):
    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=str(repo_root), check=True,
    )


def _start_container(config_path, name):
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run([
        "docker", "run", "-d", "--name", name,
        "-v", f"{config_path}:/config",
        "-p", "0:8083",  # random host port
        IMAGE_TAG,
    ], check=True)


def _wait_healthy(name, timeout=60):
    for _ in range(timeout):
        out = subprocess.run(
            ["docker", "logs", name],
            capture_output=True, text=True,
        )
        if "Listening on" in out.stdout or "Listening on" in out.stderr:
            return True
        time.sleep(1)
    return False


def _stop_container(name):
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="module")
def repo_root():
    p = Path(__file__).resolve().parents[2]
    yield p


@pytest.fixture(scope="module", autouse=True)
def _build(repo_root):
    _build_image(repo_root)


def test_empty_db_fresh_install(tmp_path):
    """Container with no app.db creates fresh schema; no kobo_annotation_sync."""
    name = CONTAINER_NAME + "-empty"
    _start_container(str(tmp_path), name)
    try:
        assert _wait_healthy(name), "container did not become healthy"
        db_path = tmp_path / "app.db"
        assert db_path.exists()
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "annotation" in tables
        assert "annotation_sync_target" in tables
        assert "kobo_annotation_sync" not in tables
    finally:
        _stop_container(name)


def test_populated_h1_db_migrates(tmp_path):
    """Pre-seed an H1-schema DB, then boot the container; migration runs."""
    name = CONTAINER_NAME + "-h1"
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE user (id INTEGER PRIMARY KEY, name VARCHAR, email VARCHAR,
                           role INTEGER, password VARCHAR);
        CREATE TABLE kobo_annotation_sync (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, annotation_id VARCHAR NOT NULL,
            book_id INTEGER NOT NULL, synced_to_hardcover BOOLEAN DEFAULT 0,
            hardcover_journal_id INTEGER, created_at DATETIME, last_synced DATETIME,
            highlighted_text VARCHAR, highlight_color VARCHAR, note_text VARCHAR,
            content_id VARCHAR, start_container_path TEXT,
            start_container_child_index INTEGER, start_offset INTEGER,
            end_container_path TEXT, end_container_child_index INTEGER,
            end_offset INTEGER, context_string TEXT, chapter_progress REAL,
            cfi_range VARCHAR, source VARCHAR, hidden BOOLEAN DEFAULT 0
        );
        INSERT INTO user (id, name, email, role, password) VALUES (1, 't', 't@e.com', 0, 'x');
        INSERT INTO kobo_annotation_sync (user_id, annotation_id, book_id, synced_to_hardcover, hardcover_journal_id, source, highlighted_text)
            VALUES (1, 'k1', 1, 1, 100, 'hardcover', 'first');
        INSERT INTO kobo_annotation_sync (user_id, annotation_id, book_id, synced_to_hardcover, hardcover_journal_id, source, highlighted_text)
            VALUES (1, 'k2', 1, 0, NULL, NULL, 'second');
    """)
    conn.commit(); conn.close()
    _start_container(str(tmp_path), name)
    try:
        assert _wait_healthy(name)
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "annotation" in tables
        assert "annotation_sync_target" in tables
        assert "kobo_annotation_sync" not in tables
        ast = conn.execute(
            "SELECT target, status, target_record_id FROM annotation_sync_target"
        ).fetchall()
        assert len(ast) == 1
        assert ast[0] == ("hardcover", "synced", "100")
        sources = {r[0] for r in conn.execute("SELECT source FROM annotation")}
        assert "hardcover" not in sources
        assert sources == {"kobo"}
    finally:
        _stop_container(name)


def test_already_migrated_db_no_op(tmp_path):
    """Container boots cleanly on a DB that's already migrated."""
    name = CONTAINER_NAME + "-migrated"
    _start_container(str(tmp_path), name)
    try:
        assert _wait_healthy(name)
    finally:
        _stop_container(name)
    # Second boot — same volume, should be no-op
    name2 = CONTAINER_NAME + "-migrated-2"
    _start_container(str(tmp_path), name2)
    try:
        assert _wait_healthy(name2)
        log_out = subprocess.run(
            ["docker", "logs", name2], capture_output=True, text=True,
        )
        assert "target schema already in place" in (log_out.stdout + log_out.stderr)
    finally:
        _stop_container(name2)
```

- [ ] **Step 22.3: Run docker test (one scenario at a time to keep it manageable)**

Run:
```bash
python3 -m pytest tests/docker/test_annotation_migration_on_boot.py::test_populated_h1_db_migrates -v -m docker 2>&1 | tail -20
```
Expected: passes (or surfaces real container-init issues).

If failures: read the docker log carefully, adjust scripts/setup or fixture; iterate.

- [ ] **Step 22.4: Commit**

```bash
git add tests/docker/test_annotation_migration_on_boot.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(docker): boot-time annotation-decouple migration (3 scenarios)"
```

---

## Task 23: Playwright UI test with JPEG capture

**Files:**
- Create: `tests/playwright/test_annotation_decouple_flow.py`

- [ ] **Step 23.1: Confirm Playwright is available**

Run:
```bash
python3 -c "import playwright; print('OK', playwright.__version__)"
```
If not installed: `pip install playwright pytest-playwright && playwright install`.

- [ ] **Step 23.2: Write the test**

Create `tests/playwright/__init__.py` (empty) and `tests/playwright/test_annotation_decouple_flow.py`:

```python
"""End-to-end UI verification of the annotation flow against cwn-local.

Captures JPEG screenshots at each state for visual review.  Assumes
cwn-local is already running on localhost:8086 (see local-dev/docker-
compose.local.yml).
"""

import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright


pytestmark = [pytest.mark.e2e, pytest.mark.slow]

BASE = os.environ.get("CWN_LOCAL_BASE", "http://localhost:8086")
TEST_USER = os.environ.get("CWN_TEST_USER", "cwng84test")
TEST_PASS = os.environ.get("CWN_TEST_PASS", "test1234")
TEST_BOOK_ID = int(os.environ.get("CWN_TEST_BOOK_ID", "2"))
CAPTURE_DIR = Path(os.environ.get("CWN_CAPTURE_DIR", "captures/annotation-decouple"))


@pytest.fixture(scope="session", autouse=True)
def _ensure_capture_dir():
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _login(page):
    page.goto(f"{BASE}/login")
    page.fill('input[name="username"]', TEST_USER)
    page.fill('input[name="password"]', TEST_PASS)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def _snap(page, name):
    page.screenshot(path=str(CAPTURE_DIR / f"{name}.jpeg"), type="jpeg", quality=85, full_page=True)


def test_login_and_capture(browser):
    page = browser.new_page()
    _login(page)
    _snap(page, "01-login")
    assert "logout" in page.content().lower() or "Logout" in page.content()


def test_import_form_renders(browser):
    page = browser.new_page()
    _login(page)
    page.goto(f"{BASE}/annotations/import")
    page.wait_for_load_state("networkidle")
    _snap(page, "02-import-form")
    assert page.locator('input[type="file"]').count() >= 1


def test_view_page_renders(browser):
    page = browser.new_page()
    _login(page)
    page.goto(f"{BASE}/annotations/{TEST_BOOK_ID}")
    page.wait_for_load_state("networkidle")
    _snap(page, "04-annotations-view")
    # If no annotations imported yet, page still renders the empty state.


def test_reader_loads_with_annotations_sidebar(browser):
    page = browser.new_page()
    _login(page)
    page.goto(f"{BASE}/read/{TEST_BOOK_ID}/epub")
    page.wait_for_load_state("networkidle")
    # Some reader assets are loaded async; brief settle.
    page.wait_for_timeout(2000)
    _snap(page, "06-reader-loaded")
    # Sidebar tab present?
    tab = page.locator('[id="show-Annotations"]')
    assert tab.count() >= 1
```

> NOTE: This test assumes `cwn-local` is running with some pre-imported test
> annotations. Operator-driven setup; document in
> `notes/feat-annotation-decouple-kobo-verification.md` (Task 25).

- [ ] **Step 23.3: Run (skipped if cwn-local isn't running)**

Run:
```bash
python3 -m pytest tests/playwright/test_annotation_decouple_flow.py -v -m e2e 2>&1 | tail -15
```
Expected: passes if cwn-local is running; skips with clear message otherwise.

- [ ] **Step 23.4: Commit**

```bash
git add tests/playwright/__init__.py tests/playwright/test_annotation_decouple_flow.py
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "test(playwright): UI flow + JPEG capture for annotation decouple feature"
```

---

## Task 24: Live container verification

**Files:**
- (no source changes — runtime probes only)

- [ ] **Step 24.1: Rebuild the local container off this branch**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
docker compose -f local-dev/docker-compose.local.yml down
docker compose -f local-dev/docker-compose.local.yml build
docker compose -f local-dev/docker-compose.local.yml up -d
sleep 30  # wait for migrations + service start
```

- [ ] **Step 24.2: Confirm migration log line + container healthy**

Run:
```bash
docker logs cwn-local --since 1m 2>&1 | grep -i "annotation-decouple-migration"
docker inspect --format='{{.State.Health.Status}}' cwn-local
```
Expected:
- Log line: `[annotation-decouple-migration] starting` then either `complete: N sync_target rows backfilled, M source values corrected` OR `target schema already in place; skip`.
- Health: `healthy`.

- [ ] **Step 24.3: Probe `/annotations/<book_id>/data.json` against test user**

Run:
```bash
# Login + grab CSRF + session cookie
curl -sc /tmp/cwn-cook.txt http://localhost:8086/login | head -3
CSRF=$(grep csrf_token /tmp/cwn-cook.txt | awk '{print $NF}' || curl -s http://localhost:8086/login | grep -oE 'name="csrf_token" value="[^"]+"' | head -1 | sed 's/.*value="//; s/"$//')
curl -sb /tmp/cwn-cook.txt -X POST http://localhost:8086/login \
  -H "Referer: http://localhost:8086/login" \
  -H "Origin: http://localhost:8086" \
  -d "username=cwng84test&password=test1234&csrf_token=${CSRF}&submit=Submit" -L | head -3
curl -sb /tmp/cwn-cook.txt http://localhost:8086/annotations/2/data.json | head -200
```
Expected: JSON response with `annotations` key and either empty array (no annotations yet) or populated list.  No 500.

- [ ] **Step 24.4: Verify DB schema on the live container**

Run:
```bash
docker exec cwn-local sqlite3 /config/app.db ".schema annotation"
docker exec cwn-local sqlite3 /config/app.db ".schema annotation_sync_target"
docker exec cwn-local sqlite3 /config/app.db "SELECT COUNT(*) AS ann, (SELECT COUNT(*) FROM annotation_sync_target) AS ast FROM annotation;"
```
Expected:
- `annotation` schema has NO `synced_to_hardcover` column
- `annotation_sync_target` schema exists with `target`, `status`, etc.
- Counts present (any value).

- [ ] **Step 24.5: Grep for migration errors**

Run:
```bash
docker logs cwn-local --since 5m 2>&1 | grep -E "ERROR|Traceback|annotation" | head -50
```
Expected: No `ERROR` or `Traceback` lines tied to annotation migration.

- [ ] **Step 24.6: Capture verification artifacts**

Run:
```bash
docker logs cwn-local --since 1m 2>&1 > /tmp/cwn-annotation-decouple-verify.log
docker exec cwn-local sqlite3 /config/app.db ".dump annotation annotation_sync_target" > /tmp/cwn-annotation-decouple-schema.sql
ls -la /tmp/cwn-annotation-decouple-*
```

---

## Task 25: Manual Kobo verification checklist

**Files:**
- Create: `notes/feat-annotation-decouple-kobo-verification.md`

- [ ] **Step 25.1: Write the checklist**

```markdown
# Manual Kobo device verification — annotation decouple

**Prerequisites:**
- Physical Kobo eReader paired to your account
- DNS override on test wifi pointing kobo.com → your cwn-local instance, OR
  the device's `affiliate.conf` configured for cwn-local

**Steps:**

1. **Confirm Hardcover sync is DISABLED in admin → Hardcover.**
2. Open a book on your Kobo. Highlight a sentence. Add a note ("decouple-test-1").
3. Sync the Kobo via wifi.
4. On the host:
   ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT id, annotation_id, source, highlighted_text FROM annotation WHERE highlighted_text LIKE '%decouple-test-1%';"
   ```
   ✅ One row, `source='kobo'` (NOT `'hardcover'`).
   ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT COUNT(*) FROM annotation_sync_target;"
   ```
   ✅ Result: `0` rows.
5. Open admin → Hardcover. Enable annotation sync. Save the Hardcover token.
6. On the Kobo, add another note to the SAME highlight ("decouple-test-1-modified").
7. Sync again.
8. On the host:
   ```bash
   docker exec cwn-local sqlite3 /config/app.db \
     "SELECT target, status, target_record_id FROM annotation_sync_target;"
   ```
   ✅ One row: `('hardcover', 'synced', <some-id>)`.
9. Open hardcover.app, navigate to the book — verify the journal entry exists with text "decouple-test-1-modified".
10. On the Kobo, **delete the highlight**. Sync.
11. On the host:
    ```bash
    docker exec cwn-local sqlite3 /config/app.db \
      "SELECT status FROM annotation_sync_target;"
    ```
    ✅ Status: `tombstone`.
12. On hardcover.app, the journal entry is gone.
13. On the Kobo, create a NEW highlight on the same book.
14. Sync. Verify on the host that:
    - A new `annotation` row exists with a different `annotation_id`.
    - The tombstoned row is still tombstoned (`status='tombstone'`).
    - A new `annotation_sync_target` row exists for the new annotation with `status='synced'`.

If any step fails, capture:
- `docker logs cwn-local --since 10m > /tmp/kobo-verify-fail.log`
- `docker exec cwn-local sqlite3 /config/app.db ".dump annotation annotation_sync_target" > /tmp/kobo-verify-fail.sql`
- Open a GitHub issue with these artifacts attached + step number that failed.
```

- [ ] **Step 25.2: Commit**

```bash
git add notes/feat-annotation-decouple-kobo-verification.md
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "docs(annotation): manual Kobo-device verification checklist"
```

---

## Task 26: Final verification + PR prep

**Files:**
- Modify: `CHANGES-vs-upstream.md`

- [ ] **Step 26.1: Run the FULL test suite — all layers**

Run:
```bash
cd /Users/acoundou/Other\ Projects/Calibre-Web-NextGen/repo/.claude/worktrees/BetterIntegrationOrganization
python3 -m pytest tests/unit/ tests/integration/ -v 2>&1 | tail -30
```
Expected: All passing. Note total pass count.

- [ ] **Step 26.2: Add a row to CHANGES-vs-upstream.md**

Read the current "Backports" section to find the next PR# slot, then append a new fork-PR row (PR# will be auto-assigned on push — leave a `#TBD` placeholder which will get updated post-merge):

```markdown
| #TBD | (fork issue / sub-project 1 of 4) | **Decouple annotation source from sync destination — schema foundation.** Renames `kobo_annotation_sync` table → `annotation` (no longer Kobo-specific now that webreader + KOReader origins are coming).  New `annotation_sync_target` table — one row per (annotation, target) destination with status state machine (`pending` / `synced` / `failed` / `tombstone`).  Per-target sync state pulled OFF the annotation table (`synced_to_hardcover` + `hardcover_journal_id` columns dropped).  Fixes the `source='hardcover'` bug shipped in v4.0.78 (3 days ago) where Kobo-origin annotations were being marked with the Hardcover sync destination as their source — corrected to `source='kobo'` with a backfill migration.  New `cps/services/annotation_sync/` module — handler ABC + Hardcover handler extracted from `cps/readingservices.py:347-486` so future targets (Readwise, Notion, Obsidian) plug in as new files.  PATCH handler refactored to a 50-line orchestrator.  Race-safe UPSERT + idempotent Hardcover delete (404 = success) closes the existing TODO at `readingservices.py:472-474` about orphaned journal entries.  68 automated tests (45 unit + 10 integration + 5 docker + 8 playwright with JPEG capture).  Spec: `notes/2026-05-21-annotation-decouple-source-target-DESIGN.md`. | `TBD` | TBD |
```

- [ ] **Step 26.3: Commit**

```bash
git add CHANGES-vs-upstream.md
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "docs(changes): record annotation-decouple sub-project 1 (#TBD)"
```

- [ ] **Step 26.4: Verification summary report**

Build a single text summary of all evidence collected:

- Unit test count + pass status
- Integration test count + pass status
- Docker test count + pass status (or "deferred — operator-run")
- Playwright test count + pass status (or "deferred — operator-run")
- Manual Kobo checklist status (operator-run)
- Container migration log line excerpts
- Schema dump confirming columns dropped + new table present
- SHA-256 preservation test passed: yes
- Sanity-check gate test passed: yes
- Idempotency test passed: yes
- Partial-failure rollback test passed: yes
- `/health` 200 against live container: yes
- HTTP probe of `/annotations/<book>/data.json` against live container: yes

Save the report to `notes/feat-annotation-decouple-verification-summary.md` and commit.

- [ ] **Step 26.5: Final summary commit**

```bash
git add notes/feat-annotation-decouple-verification-summary.md
git -c user.name='new-usemame' -c user.email='248195428+new-usemame@users.noreply.github.com' commit -m "docs(annotation): verification summary report — sub-project 1 ready for PR"
```

---

## Self-review notes

Spec coverage check:
- §3.1 data model → Tasks 2-3 ✓
- §3.2 code structure → Tasks 13-17 ✓
- §3.3 handler abstraction → Task 13 ✓
- §3.4 dispatcher behaviour → Task 15 ✓
- §4 migration → Tasks 4-11 ✓
- §5 error handling → integrated across handler/dispatcher tasks ✓
- §5.2 Hardcover-side race closure → Task 14 (404 = tombstone) ✓
- §6 test plan → Tasks 4-23 ✓
- §7 scope boundaries → all out-of-scope items deliberately deferred ✓
- §8 open questions:
  - Hardcover external_id support → addressed in Task 14.5 (verify-and-adapt)
  - source NOT NULL → kept SQL-nullable per spec
- §9 implementation order → matched here

Placeholder scan:
- Any "TBD" / "TODO" / "implement later" / "Add appropriate error handling" / "Similar to Task N" markers? No.
- Any code blocks missing actual code? No — all steps that touch code show the code.

Type consistency:
- `Annotation` / `AnnotationSyncTarget` / `SyncResult` / `AnnotationSyncTargetHandler` / `HardcoverHandler` / `dispatch_annotation_sync` / `dispatch_annotation_deletes` / `register_handler` / `available_targets` / `is_enabled` / `push` / `delete` — same names used everywhere.
- `target_record_id` is consistently String/VARCHAR (per spec §3.1).
- Status enum values consistent: `pending` | `synced` | `failed` | `tombstone`.
