# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""B3 regression tests: orphan book on device after CW delete.

Companion fix to the B1/B2/B4 cluster shipped in v4.0.70. Closes the
last bug in the 2026-05-17 MITM-captured cluster — books deleted from
CW persisted on the device because no DeletedEntitlement was ever
emitted to the Kobo sync response (no UUID retained after the row went
away).

Design:
- New ub.KoboDeletedBook tombstone table — (user_id, book_uuid,
  deleted_at) snapshot at delete time.
- editbooks.delete_whole_book calls kobo_sync_status.record_book_deletion
  BEFORE deleting metadata, capturing UUID for every user with a
  matching kobo_synced_books row.
- HandleSyncRequest emits DeletedEntitlement for tombstones with
  deleted_at > sync_token.archive_last_modified, advances cursor past
  them so each device sees each tombstone exactly once.
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Source-pinned: the wiring exists where we expect it
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestB3SourceWiring:
    """The fix has three distinct surfaces; any one missing breaks the
    full pipeline. Source-pin all three so a refactor can't silently
    strip part of it."""

    def test_kobo_deleted_book_model_defined(self):
        """Model must exist with the (user_id, book_uuid, deleted_at)
        contract the sync emit + tombstone-capture logic both depend on."""
        from cps.ub import KoboDeletedBook
        assert KoboDeletedBook.__tablename__ == "kobo_deleted_book"
        cols = {c.name for c in KoboDeletedBook.__table__.columns}
        assert {"id", "user_id", "book_uuid", "deleted_at"} <= cols, (
            f"KoboDeletedBook missing required columns. Got: {cols}"
        )
        # UNIQUE on (user_id, book_uuid) is the dedupe contract that
        # record_book_deletion relies on for idempotency.
        from sqlalchemy import UniqueConstraint
        uc_names = {
            c.name for c in KoboDeletedBook.__table__.constraints
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_kobo_deleted_book_user_uuid" in uc_names, (
            "UniqueConstraint on (user_id, book_uuid) missing — "
            "record_book_deletion relies on it for idempotency."
        )

    def test_migration_runs_from_migrate_database(self):
        from cps.ub import migrate_Database
        src = inspect.getsource(migrate_Database)
        assert "migrate_kobo_deleted_book" in src, (
            "migrate_kobo_deleted_book must be called from migrate_Database "
            "so existing installs get the table on upgrade."
        )

    def test_record_book_deletion_helper_exists(self):
        from cps.kobo_sync_status import record_book_deletion
        sig = inspect.signature(record_book_deletion)
        assert "book_id" in sig.parameters
        assert "book_uuid" in sig.parameters, (
            "record_book_deletion must take book_uuid — the UUID can't "
            "be recovered after the metadata row is gone."
        )

    def test_delete_whole_book_calls_record_book_deletion(self):
        from cps.editbooks import delete_whole_book
        src = inspect.getsource(delete_whole_book)
        assert "record_book_deletion" in src, (
            "delete_whole_book must call kobo_sync_status."
            "record_book_deletion BEFORE removing the metadata row — "
            "otherwise the UUID is lost and no DeletedEntitlement can "
            "be emitted, leaving the book on every synced device "
            "forever (B3)."
        )

    def test_handle_sync_emits_deleted_entitlement(self):
        from cps.kobo import HandleSyncRequest
        src = inspect.getsource(HandleSyncRequest)
        assert "DeletedEntitlement" in src, (
            "HandleSyncRequest must emit DeletedEntitlement for "
            "kobo_deleted_book rows — that's the device-side signal "
            "to archive the local copy."
        )
        assert "KoboDeletedBook" in src, (
            "HandleSyncRequest must query KoboDeletedBook (the "
            "tombstone table) to find books to emit DeletedEntitlement "
            "for."
        )

    def test_handle_sync_uses_device_cursor_not_local_watermark(self):
        """The filter must compare against sync_token.archive_last_modified
        (the device's cursor), not new_archived_last_modified — the
        latter has already been advanced by any ArchivedBook row, which
        would mask legitimate tombstones whose deleted_at lies between
        the cursor and the new local watermark."""
        from cps.kobo import HandleSyncRequest
        src = inspect.getsource(HandleSyncRequest)
        assert (
            "sync_token.archive_last_modified" in src
            and "KoboDeletedBook.deleted_at" in src
        ), (
            "HandleSyncRequest must filter KoboDeletedBook by "
            "sync_token.archive_last_modified (the device cursor), "
            "not the local new_archived_last_modified variable."
        )


# ---------------------------------------------------------------------------
# Behavioral: real SQLite stack, record + emit roundtrip
# ---------------------------------------------------------------------------


@pytest.fixture
def kobo_b3_stack(tmp_path, monkeypatch):
    """Minimal ub-side DB + a stub current_user. Tests the
    record_book_deletion ↔ KoboDeletedBook persistence path end to end."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, scoped_session
    from cps import ub

    db_path = tmp_path / "b3.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    ub.Base.metadata.create_all(engine)
    Session = scoped_session(sessionmaker(bind=engine, future=True))
    session = Session()
    monkeypatch.setattr(ub, "session", session, raising=False)

    # Two users — proves the helper covers all affected users, not just
    # the current request's user (a deleted book affects everyone who
    # had it synced).
    users = []
    for name in ("u_a", "u_b", "u_c"):
        u = ub.User()
        u.name = name
        u.email = f"{name}@example.invalid"
        u.role = 0
        u.locale = "en"
        u.default_language = "all"
        u.allowed_tags = ""
        u.denied_tags = ""
        u.allowed_column_value = ""
        u.denied_column_value = ""
        u.sidebar_view = 0
        u.password = "x"
        u.kobo_only_shelves_sync = False
        session.add(u)
        users.append(u)
    session.commit()

    yield {"session": session, "users": users, "ub": ub}
    Session.remove()


@pytest.mark.unit
class TestB3RecordBookDeletion:
    def test_creates_tombstone_for_each_synced_user(self, kobo_b3_stack):
        from cps import kobo_sync_status
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a, u_b, u_c = kobo_b3_stack["users"]

        # u_a and u_b had book 42 synced; u_c did not.
        session.add(ub.KoboSyncedBooks(user_id=u_a.id, book_id=42))
        session.add(ub.KoboSyncedBooks(user_id=u_b.id, book_id=42))
        session.commit()

        kobo_sync_status.record_book_deletion(42, "abc-uuid-42", session=session)

        tombs = session.query(ub.KoboDeletedBook).filter_by(book_uuid="abc-uuid-42").all()
        affected_users = sorted([t.user_id for t in tombs])
        assert affected_users == sorted([u_a.id, u_b.id]), (
            "Tombstone must be created for u_a and u_b (had the book "
            "synced) but not u_c (did not). "
            f"Got affected_users={affected_users}"
        )

        # KoboSyncedBooks rows for this book are cleared.
        remaining_synced = session.query(ub.KoboSyncedBooks).filter_by(book_id=42).count()
        assert remaining_synced == 0, (
            "KoboSyncedBooks rows for the deleted book must be cleared "
            "after recording the deletion — the two-way deletion logic "
            "in HandleSyncRequest would otherwise trip over a stale row."
        )

    def test_idempotent_on_double_invocation(self, kobo_b3_stack):
        """If delete_whole_book runs twice for the same UUID (e.g. retry
        path), the UNIQUE(user_id, book_uuid) constraint must coalesce
        — no duplicate tombstone, no exception."""
        from cps import kobo_sync_status
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a = kobo_b3_stack["users"][0]

        session.add(ub.KoboSyncedBooks(user_id=u_a.id, book_id=100))
        session.commit()

        kobo_sync_status.record_book_deletion(100, "uuid-100", session=session)
        # Re-add the synced row to simulate a hypothetical re-run scenario
        session.add(ub.KoboSyncedBooks(user_id=u_a.id, book_id=100))
        session.commit()
        kobo_sync_status.record_book_deletion(100, "uuid-100", session=session)

        tombs = session.query(ub.KoboDeletedBook).filter_by(book_uuid="uuid-100").count()
        assert tombs == 1, (
            f"Double-invocation must coalesce via UNIQUE; got {tombs} "
            f"rows for the same (user, uuid) pair."
        )

    def test_noop_when_book_uuid_missing(self, kobo_b3_stack):
        """Defensive: if upstream changes mean book.uuid is None at
        delete time, we silently no-op rather than write garbage rows
        the sync handler would emit as DeletedEntitlement for a null
        UUID (device-side error)."""
        from cps import kobo_sync_status
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a = kobo_b3_stack["users"][0]

        session.add(ub.KoboSyncedBooks(user_id=u_a.id, book_id=99))
        session.commit()

        kobo_sync_status.record_book_deletion(99, None, session=session)
        kobo_sync_status.record_book_deletion(99, "", session=session)

        tombs = session.query(ub.KoboDeletedBook).count()
        assert tombs == 0, (
            f"Tombstone with null/empty UUID must not be written. "
            f"Got {tombs} rows."
        )

    def test_noop_when_no_users_had_book_synced(self, kobo_b3_stack):
        """If a book is deleted but no user ever synced it to a Kobo,
        no tombstone is needed — kobo_deleted_book stays empty."""
        from cps import kobo_sync_status
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]

        # No KoboSyncedBooks rows for book 200
        kobo_sync_status.record_book_deletion(200, "uuid-200", session=session)

        tombs = session.query(ub.KoboDeletedBook).count()
        assert tombs == 0


# ---------------------------------------------------------------------------
# Behavioral: sync emission picks up tombstones, advances cursor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestB3SyncEmission:
    def test_tombstone_emit_logic_picks_up_pending_rows(self, kobo_b3_stack):
        """Direct test of the query+emit shape used in HandleSyncRequest's
        DeletedEntitlement block. Builds a few tombstones, simulates the
        device's cursor, asserts only newer-than-cursor rows surface and
        the response payload matches the Kobo DeletedEntitlement schema."""
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a = kobo_b3_stack["users"][0]

        t0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=1)
        t2 = t0 + timedelta(hours=2)
        t3 = t0 + timedelta(hours=3)

        # Tombstones at t1, t2, t3. Device's cursor was at t1 (saw t1).
        session.add(ub.KoboDeletedBook(user_id=u_a.id, book_uuid="uuid-1", deleted_at=t1))
        session.add(ub.KoboDeletedBook(user_id=u_a.id, book_uuid="uuid-2", deleted_at=t2))
        session.add(ub.KoboDeletedBook(user_id=u_a.id, book_uuid="uuid-3", deleted_at=t3))
        session.commit()

        cursor_archive_lm = t1  # device saw t1 last
        SYNC_ITEM_LIMIT = 100

        pending = (
            session.query(ub.KoboDeletedBook)
            .filter(ub.KoboDeletedBook.user_id == u_a.id)
            .filter(ub.KoboDeletedBook.deleted_at > cursor_archive_lm)
            .order_by(ub.KoboDeletedBook.deleted_at)
            .limit(SYNC_ITEM_LIMIT)
            .all()
        )

        sync_results = []
        new_archived_last_modified = cursor_archive_lm
        for tombstone in pending:
            sync_results.append({
                "DeletedEntitlement": {
                    "BookEntitlement": {
                        "Id": tombstone.book_uuid,
                        "RevisionId": tombstone.book_uuid,
                        "CrossRevisionId": tombstone.book_uuid,
                    }
                }
            })
            ta = tombstone.deleted_at
            if hasattr(ta, "replace") and getattr(ta, "tzinfo", None) is not None:
                ta = ta.replace(tzinfo=None)
            if isinstance(new_archived_last_modified, datetime):
                if new_archived_last_modified.tzinfo is not None:
                    new_archived_last_modified = new_archived_last_modified.replace(tzinfo=None)
            new_archived_last_modified = max(ta, new_archived_last_modified)

        assert len(sync_results) == 2, (
            f"Expected 2 tombstones past cursor (uuid-2, uuid-3); "
            f"got {len(sync_results)}: {sync_results}"
        )
        uuids = [r["DeletedEntitlement"]["BookEntitlement"]["RevisionId"]
                 for r in sync_results]
        assert uuids == ["uuid-2", "uuid-3"], (
            f"Tombstones must emit in deleted_at order; got {uuids}"
        )

        # Cursor advances past the newest emitted tombstone.
        expected = t3.replace(tzinfo=None) if t3.tzinfo else t3
        assert new_archived_last_modified == expected, (
            f"Cursor must advance to t3 ({expected}); "
            f"got {new_archived_last_modified}"
        )

    def test_second_sync_does_not_re_emit_tombstones(self, kobo_b3_stack):
        """Once a device's cursor has advanced past a tombstone, the
        next sync from that device must not re-emit it (idempotent
        per device-cycle, like every other sync element)."""
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a = kobo_b3_stack["users"][0]

        t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        session.add(ub.KoboDeletedBook(user_id=u_a.id, book_uuid="uuid-X", deleted_at=t0))
        session.commit()

        # First sync: cursor at min, tombstone at t0 — should emit.
        cursor_1 = datetime.min
        rows_1 = (
            session.query(ub.KoboDeletedBook)
            .filter(ub.KoboDeletedBook.user_id == u_a.id)
            .filter(ub.KoboDeletedBook.deleted_at > cursor_1)
            .all()
        )
        assert len(rows_1) == 1

        # Cursor advances to t0.
        cursor_2 = t0
        rows_2 = (
            session.query(ub.KoboDeletedBook)
            .filter(ub.KoboDeletedBook.user_id == u_a.id)
            .filter(ub.KoboDeletedBook.deleted_at > cursor_2)
            .all()
        )
        assert len(rows_2) == 0, (
            f"Second sync must not re-emit already-seen tombstones; "
            f"got {len(rows_2)}: {[(r.book_uuid, r.deleted_at) for r in rows_2]}"
        )

    def test_user_isolation_no_cross_user_leak(self, kobo_b3_stack):
        """Tombstone for u_a must NEVER appear in u_b's sync response.
        kobo_deleted_book is user-keyed; the query must filter by
        current_user.id."""
        ub = kobo_b3_stack["ub"]
        session = kobo_b3_stack["session"]
        u_a, u_b, _ = kobo_b3_stack["users"]

        t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        session.add(ub.KoboDeletedBook(user_id=u_a.id, book_uuid="uuid-a", deleted_at=t0))
        session.add(ub.KoboDeletedBook(user_id=u_b.id, book_uuid="uuid-b", deleted_at=t0))
        session.commit()

        for u in (u_a, u_b):
            rows = (
                session.query(ub.KoboDeletedBook)
                .filter(ub.KoboDeletedBook.user_id == u.id)
                .all()
            )
            uuids = sorted([r.book_uuid for r in rows])
            expected = ["uuid-a"] if u is u_a else ["uuid-b"]
            assert uuids == expected, (
                f"User {u.name} saw {uuids}, expected {expected} — "
                f"cross-user tombstone leak."
            )


# ---------------------------------------------------------------------------
# Migration: table creation, idempotency
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestB3Migration:
    def test_migration_creates_table(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine, inspect as sa_inspect
        from sqlalchemy.orm import sessionmaker
        from cps import ub, constants

        # Point CONFIG_DIR at tmp_path so the marker file lands in
        # a hermetic location.
        monkeypatch.setattr(constants, "CONFIG_DIR", str(tmp_path), raising=False)

        db_path = tmp_path / "mig.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        # Create only ONE table to simulate a partial migration state
        # — the migration must add kobo_deleted_book even though the
        # rest of the schema isn't there yet.
        ub.User.__table__.create(engine, checkfirst=True)

        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        ub.migrate_kobo_deleted_book(engine, session)

        inspector = sa_inspect(engine)
        assert "kobo_deleted_book" in inspector.get_table_names(), (
            "migrate_kobo_deleted_book must create the table when it "
            "doesn't exist."
        )

        # Marker file is written so repeated runs are no-ops.
        import os
        marker_path = os.path.join(str(tmp_path), ".cwa_migrations", "kobo_deleted_book_v1")
        assert os.path.isfile(marker_path), (
            f"Migration marker file missing at {marker_path} — "
            f"second run would re-execute DDL unnecessarily."
        )

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        """Second run with marker present must be a no-op (no exception,
        no DDL re-issued)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from cps import ub, constants

        monkeypatch.setattr(constants, "CONFIG_DIR", str(tmp_path), raising=False)

        db_path = tmp_path / "mig2.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        ub.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, future=True)
        session = Session()

        ub.migrate_kobo_deleted_book(engine, session)
        # Second run — must not raise
        ub.migrate_kobo_deleted_book(engine, session)
