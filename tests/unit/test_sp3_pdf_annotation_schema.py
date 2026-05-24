# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sub-project (3) — polymorphic position columns + PDF data.json shape."""

from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine, text, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

from cps import ub


def test_annotation_has_position_type_column():
    cols = {c.name for c in ub.Annotation.__table__.columns}
    assert "position_type" in cols
    assert "pdf_page" in cols
    assert "pdf_quad_json" in cols
    assert "comic_page" in cols


def test_position_type_validator():
    ann = ub.Annotation()
    ann.position_type = "cfi"
    ann.position_type = "pdf_quad"
    ann.position_type = "comic_page"
    ann.position_type = None
    with pytest.raises(ValueError):
        ann.position_type = "garbage"


def test_polymorphic_migration_adds_columns():
    """The polymorphic-position migration is idempotent + additive."""
    engine = create_engine("sqlite:///:memory:")
    # Pre-state: 'annotation' table without the new columns.
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE annotation (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                annotation_id VARCHAR NOT NULL,
                book_id INTEGER NOT NULL,
                source VARCHAR,
                highlighted_text VARCHAR,
                hidden BOOLEAN DEFAULT 0
            )
        """))
    ub.migrate_annotation_polymorphic_position(engine, None)
    cols = {c["name"] for c in sa_inspect(engine).get_columns("annotation")}
    assert {"position_type", "pdf_page", "pdf_quad_json", "comic_page"}.issubset(cols)
    # Idempotency
    ub.migrate_annotation_polymorphic_position(engine, None)
    cols2 = {c["name"] for c in sa_inspect(engine).get_columns("annotation")}
    assert cols == cols2


def test_polymorphic_migration_no_op_on_fresh_install():
    """If 'annotation' table doesn't exist (pre-decouple), migration is no-op."""
    engine = create_engine("sqlite:///:memory:")
    ub.migrate_annotation_polymorphic_position(engine, None)
    assert "annotation" not in sa_inspect(engine).get_table_names()


def test_pdf_annotation_roundtrip():
    """A PDF-positioned annotation persists + reads back through the ORM."""
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="t", email="t@e.com", role=0, password="x")
    s.add(user); s.commit()
    quad = [[0.10, 0.20, 0.30, 0.05], [0.10, 0.25, 0.30, 0.05]]
    ann = ub.Annotation(
        user_id=user.id, annotation_id="pdf-1", book_id=1,
        source="webreader",
        highlighted_text="highlighted text on page 3",
        highlight_color="yellow",
        position_type="pdf_quad",
        pdf_page=3,
        pdf_quad_json=json.dumps(quad),
    )
    s.add(ann); s.commit()
    got = s.query(ub.Annotation).one()
    assert got.position_type == "pdf_quad"
    assert got.pdf_page == 3
    assert json.loads(got.pdf_quad_json) == quad


def test_comic_annotation_roundtrip():
    engine = create_engine("sqlite:///:memory:")
    ub.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    user = ub.User(name="t", email="t@e.com", role=0, password="x")
    s.add(user); s.commit()
    ann = ub.Annotation(
        user_id=user.id, annotation_id="cbr-1", book_id=1,
        source="webreader",
        highlighted_text=None,
        note_text="great splash page",
        highlight_color="blue",
        position_type="comic_page",
        comic_page=12,
    )
    s.add(ann); s.commit()
    got = s.query(ub.Annotation).one()
    assert got.position_type == "comic_page"
    assert got.comic_page == 12
    assert got.note_text == "great splash page"
