# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for the built-in PDF reader persistence models."""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

from cps import ub, web


@pytest.mark.unit
def test_existing_app_db_receives_pdf_reader_tables(tmp_path):
    """The normal startup create_all call must upgrade an existing app.db."""
    app_db = tmp_path / "app.db"
    with sqlite3.connect(app_db) as connection:
        connection.execute("CREATE TABLE existing_settings (id INTEGER PRIMARY KEY)")

    engine = create_engine("sqlite:///{}".format(app_db), echo=False)
    ub.Base.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())
    assert "existing_settings" in table_names
    assert "pdf_reader_state" in table_names
    assert "pdf_reader_note" in table_names

    unique_constraints = inspect(engine).get_unique_constraints("pdf_reader_state")
    assert any(
        set(constraint["column_names"]) == {"user_id", "book_id"}
        for constraint in unique_constraints
    )


@pytest.mark.unit
@pytest.mark.parametrize("scale", ["0", "0.09", "10.01", "100"])
def test_reader_state_rejects_zoom_outside_pdfjs_bounds(scale):
    with pytest.raises(ValueError, match="Invalid scale"):
        web._validated_pdf_reader_state({"scale_value": scale})


@pytest.mark.unit
@pytest.mark.parametrize("scale", ["0.1", "1", "1.5", "10", "page-width"])
def test_reader_state_accepts_pdfjs_zoom_values(scale):
    assert web._validated_pdf_reader_state({"scale_value": scale}) == {"scale_value": scale}
