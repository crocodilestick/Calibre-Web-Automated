# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema tests for the decoupled annotation + annotation_sync_target tables.

See notes/2026-05-21-annotation-decouple-source-target-DESIGN.md.

The H1 migration tests live in test_kobo_annotation_sync_h1_schema.py and
remain untouched — they pin a migration that runs BEFORE this one. These
tests pin the post-decouple shape and behaviour.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def in_memory_session():
    """Fresh in-memory SQLite with the FULL post-decouple schema."""
    from cps import ub
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="t", email="t@example.com", role=0, password="x")
    s.add(user)
    s.commit()
    yield s, user, ub
    s.close()


def test_annotation_sync_target_model_exists():
    from cps import ub
    assert hasattr(ub, "AnnotationSyncTarget")
    assert ub.AnnotationSyncTarget.__tablename__ == "annotation_sync_target"


def test_annotation_sync_target_columns():
    from cps import ub
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
    s, user, ub = in_memory_session
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
    s, user, ub = in_memory_session
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


def test_annotation_model_renamed():
    from cps import ub
    assert hasattr(ub, "Annotation")
    assert ub.Annotation.__tablename__ == "annotation"


def test_annotation_drops_hardcover_columns():
    from cps import ub
    cols = {c.name for c in ub.Annotation.__table__.columns}
    assert "synced_to_hardcover" not in cols
    assert "hardcover_journal_id" not in cols


def test_annotation_source_validator():
    from cps import ub
    ann = ub.Annotation()
    ann.source = "kobo"
    ann.source = "webreader"
    ann.source = "koreader"
    ann.source = None
    with pytest.raises(ValueError):
        ann.source = "hardcover"
    with pytest.raises(ValueError):
        ann.source = "garbage"


def test_annotation_indexes_renamed():
    from cps import ub
    index_names = {i.name for i in ub.Annotation.__table__.indexes}
    assert "ix_annotation_user_annotation" in index_names
    assert "ix_annotation_user_book" in index_names
