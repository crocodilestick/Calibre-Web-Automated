# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for custom columns in the magic-shelf rule builder
(fork PR #387 by @8bitgentleman).

The rule builder's field picker was hardcoded to the built-in fields;
PR #387 adds the library's Calibre custom columns. Contract pinned here:

1. ``build_filter_from_rule`` recognizes ``custom_column_<N>`` ids and
   fails CLOSED — unknown column id, malformed suffix, invalid enum
   value, or unparseable date all return ``None`` (no filter, no crash,
   no fallthrough into the built-in FIELD_MAP path).
2. Server-side enum validation is the real gate (the template's
   ``<select>`` is just UX) — a value outside the column's enum set is
   rejected even though the request is attacker-shapeable JSON.
3. The empty/not-empty operators translate to relationship
   (non-)existence (``rel.any()`` / ``~rel.any()``), because a custom
   column with no row for the book IS the empty state.
4. The edit page embeds the columns as a JSON ``<script>`` island
   (``custom-columns-data``) rather than interpolating into executable
   JS, and ``_build_custom_columns_json`` excludes ``cc_exceptions``
   datatypes (composite/series) and columns marked for delete.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
class TestCustomColumnFilterFailsClosed:
    def test_malformed_suffix_returns_none(self):
        from cps.magic_shelf import build_filter_from_rule
        rule = {"id": "custom_column_evil", "operator": "equal", "value": "x"}
        assert build_filter_from_rule(rule) is None

    def test_unknown_column_id_returns_none(self):
        from cps import db
        from cps.magic_shelf import build_filter_from_rule
        with mock.patch.dict(db.cc_classes, {}, clear=True):
            rule = {"id": "custom_column_999", "operator": "equal", "value": "x"}
            assert build_filter_from_rule(rule) is None

    def test_invalid_enum_value_rejected_server_side(self):
        """The template renders a <select>, but the preview/save endpoints
        accept raw JSON — the server must reject out-of-set values."""
        from cps import db, magic_shelf

        fake_cc_class = mock.MagicMock()
        fake_rel = mock.MagicMock()
        fake_cc_col = mock.MagicMock()
        fake_cc_col.datatype = "enumeration"
        fake_cc_col.get_display_dict.return_value = {"enum_values": ["red", "blue"]}

        with mock.patch.dict(db.cc_classes, {7: fake_cc_class}, clear=False), \
             mock.patch.object(db.Books, "custom_column_7", fake_rel, create=True), \
             mock.patch("cps.calibre_db", create=True) as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            rule = {"id": "custom_column_7", "operator": "equal", "value": "green"}
            assert magic_shelf.build_filter_from_rule(rule) is None, (
                "enum value outside the column's set must be rejected"
            )

    def test_invalid_date_value_rejected(self):
        from cps import db, magic_shelf

        fake_cc_class = mock.MagicMock()
        fake_rel = mock.MagicMock()
        fake_cc_col = mock.MagicMock()
        fake_cc_col.datatype = "datetime"

        with mock.patch.dict(db.cc_classes, {3: fake_cc_class}, clear=False), \
             mock.patch.object(db.Books, "custom_column_3", fake_rel, create=True), \
             mock.patch("cps.calibre_db", create=True) as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            rule = {"id": "custom_column_3", "operator": "equal", "value": "not-a-date"}
            assert magic_shelf.build_filter_from_rule(rule) is None


@pytest.mark.unit
class TestCustomColumnFilterSemantics:
    def _patched(self, datatype="text", display=None):
        """Context: cc id 5 exists, Books.custom_column_5 is a mock rel."""
        from cps import db, magic_shelf
        fake_cc_class = mock.MagicMock()
        fake_rel = mock.MagicMock()
        fake_cc_col = mock.MagicMock()
        fake_cc_col.datatype = datatype
        if display is not None:
            fake_cc_col.get_display_dict.return_value = display
        patches = (
            mock.patch.dict(db.cc_classes, {5: fake_cc_class}, clear=False),
            mock.patch.object(db.Books, "custom_column_5", fake_rel, create=True),
            mock.patch("cps.calibre_db", create=True),
        )
        return patches, fake_rel, fake_cc_col

    def test_is_empty_means_no_relationship_row(self):
        from cps import magic_shelf
        patches, fake_rel, fake_cc_col = self._patched()
        with patches[0], patches[1], patches[2] as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            rule = {"id": "custom_column_5", "operator": "is_empty", "value": None}
            result = magic_shelf.build_filter_from_rule(rule)
            # is_empty -> ~rel.any(): the invert operator on the rel.any() mock
            fake_rel.any.assert_called_once_with()
            assert result == fake_rel.any.return_value.__invert__.return_value

    def test_is_not_empty_means_relationship_exists(self):
        from cps import magic_shelf
        patches, fake_rel, fake_cc_col = self._patched()
        with patches[0], patches[1], patches[2] as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            rule = {"id": "custom_column_5", "operator": "is_not_empty", "value": None}
            result = magic_shelf.build_filter_from_rule(rule)
            fake_rel.any.assert_called_once_with()
            assert result == fake_rel.any.return_value

    def test_enum_column_is_empty_not_killed_by_validation(self):
        """Regression (found in review of PR #387): with an enumeration
        column and operator is_empty, the value is None — enum validation
        used to reject None ('not in allowed') and return no filter at
        all, so 'is empty' rules on enum columns silently matched
        nothing. The validation must skip value-free operators."""
        from cps import magic_shelf
        patches, fake_rel, fake_cc_col = self._patched(
            datatype="enumeration", display={"enum_values": ["red", "blue"]}
        )
        with patches[0], patches[1], patches[2] as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            rule = {"id": "custom_column_5", "operator": "is_empty", "value": None}
            result = magic_shelf.build_filter_from_rule(rule)
            fake_rel.any.assert_called_once_with()
            assert result == fake_rel.any.return_value.__invert__.return_value

    def test_bool_string_value_is_coerced(self):
        """QueryBuilder radio inputs deliver '1'/'0' strings; the filter
        must compare the column against a real bool."""
        from cps import magic_shelf
        patches, fake_rel, fake_cc_col = self._patched(datatype="bool")
        captured = {}
        with patches[0], patches[1], patches[2] as fake_cdb:
            fake_cdb.session.get.return_value = fake_cc_col
            with mock.patch.dict(
                magic_shelf.OPERATOR_MAP,
                {"equal": lambda col, val: captured.setdefault("val", val) or mock.MagicMock()},
                clear=False,
            ):
                rule = {"id": "custom_column_5", "operator": "equal", "value": "1"}
                magic_shelf.build_filter_from_rule(rule)
        assert captured.get("val") is True


@pytest.mark.unit
class TestSourcePins:
    def test_web_excludes_deleted_and_exception_columns(self):
        from cps import web
        src = inspect.getsource(web._build_custom_columns_json)
        assert "cc_exceptions" in src, (
            "_build_custom_columns_json must exclude composite/series "
            "datatypes (db.cc_exceptions) — they aren't queryable"
        )
        assert "mark_for_delete" in src, (
            "columns marked for delete must not be offered in the builder"
        )

    def test_template_uses_json_script_island(self):
        tpl = (REPO_ROOT / "cps" / "templates" / "magic_shelf_edit.html").read_text(
            encoding="utf-8"
        )
        assert re.search(
            r'<script type="application/json" id="custom-columns-data">', tpl
        ), (
            "custom columns must be embedded as a JSON script island, not "
            "interpolated into executable JS (XSS-resistant: tojson escapes "
            "<, >, & as unicode escapes)"
        )
        assert "custom-columns-data" in tpl.split("JSON.parse")[1][:200], (
            "the JS must parse the island via JSON.parse(...textContent)"
        )

    def test_filter_branch_precedes_field_map(self):
        """The custom_column_ branch must run BEFORE the FIELD_MAP lookup
        so a hypothetical FIELD_MAP key collision can never shadow it."""
        from cps.magic_shelf import build_filter_from_rule
        src = inspect.getsource(build_filter_from_rule)
        assert src.index("custom_column_") < src.index("FIELD_MAP.get"), (
            "custom-column handling must precede the built-in FIELD_MAP path"
        )
