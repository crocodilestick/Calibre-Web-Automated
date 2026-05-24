# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers on Annotation that traverse the sync_targets relationship."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from cps import ub


@pytest.fixture
def session_with_ann():
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(text("PRAGMA foreign_keys=ON"))
    user = ub.User(name="t", email="t@example.com", role=0, password="x")
    s.add(user); s.commit()
    ann = ub.Annotation(user_id=user.id, annotation_id="abc", book_id=1, source="kobo")
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
    assert got is not None and got.status == "synced"


def test_is_synced_to_true_only_when_status_synced(session_with_ann):
    s, ann = session_with_ann
    assert ann.is_synced_to("hardcover") is False
    st = ub.AnnotationSyncTarget(
        annotation_id=ann.id, target="hardcover", status="failed",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    s.add(st); s.commit(); s.refresh(ann)
    assert ann.is_synced_to("hardcover") is False
    st.status = "synced"; s.commit(); s.refresh(ann)
    assert ann.is_synced_to("hardcover") is True
    st.status = "tombstone"; s.commit(); s.refresh(ann)
    assert ann.is_synced_to("hardcover") is False


def test_helpers_tolerate_empty_sync_targets(session_with_ann):
    _, ann = session_with_ann
    assert ann.sync_target("hardcover") is None
    assert ann.is_synced_to("hardcover") is False
