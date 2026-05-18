# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests pinning the "Currently Reading" magic-shelf preset
added in fork PR #233 (backport of upstream CWA #1201 by @Sheol27).

The fix introduces a third built-in read_status value (2 =
STATUS_IN_PROGRESS) so users can build a magic shelf that surfaces
books KOSync/Kobo has marked in-progress. Before the fix, the
QueryBuilder treated read_status as a boolean (0/1 only), and
build_filter_from_rule only resolved the unread/finished branches —
in-progress would silently fall through to "finished" matching.

Three invariants this test pins:

1. SYSTEM_SHELF_TEMPLATES has a 'currently_reading' entry whose only
   rule matches read_status == STATUS_IN_PROGRESS (value 2). If a
   future edit removes the template or changes the value to 0/1, the
   preset stops surfacing in-progress books and the test fires.

2. The 'yet_to_read' preset's icon was swapped from 📖 to 📚 so it
   doesn't collide with the new currently_reading 📖. If someone
   reverts that without thinking, both presets render with the same
   icon and the UI becomes ambiguous.

3. build_filter_from_rule's read_status fallback (the no-custom-column
   path) handles all three statuses — STATUS_IN_PROGRESS, STATUS_FINISHED,
   STATUS_UNREAD — and the STATUS_IN_PROGRESS branch issues a query
   filtered on STATUS_IN_PROGRESS, not STATUS_FINISHED. Source-pinned
   because the function reaches into ub.session at runtime and is
   awkward to invoke from a unit test without full app init.
"""

import inspect

import pytest


@pytest.mark.unit
class TestCurrentlyReadingTemplate:
    def test_template_exists_with_in_progress_rule(self):
        from cps.magic_shelf import SYSTEM_SHELF_TEMPLATES

        assert 'currently_reading' in SYSTEM_SHELF_TEMPLATES, (
            "SYSTEM_SHELF_TEMPLATES must expose a 'currently_reading' "
            "preset so users can build a magic shelf that surfaces "
            "in-progress (KOSync/Kobo-synced) books."
        )

        tmpl = SYSTEM_SHELF_TEMPLATES['currently_reading']
        assert tmpl['name'] == 'Currently Reading'
        rules = tmpl['rules']['rules']
        assert len(rules) == 1, (
            "currently_reading should be a single-rule preset — "
            "read_status == STATUS_IN_PROGRESS — not a compound filter."
        )
        rule = rules[0]
        assert rule['id'] == 'read_status'
        assert rule['field'] == 'read_status'
        assert rule['operator'] == 'equal'
        assert rule['value'] == 2, (
            "currently_reading must match value 2 (STATUS_IN_PROGRESS). "
            "Values 0/1 would re-bind it to unread/finished and the "
            "preset would silently match the wrong books."
        )

    def test_in_progress_value_matches_ub_constant(self):
        """Cross-pin: the literal 2 in the template must equal
        ub.ReadBook.STATUS_IN_PROGRESS. If someone renumbers the
        ReadBook status constants, this test catches the silent drift
        before the preset starts matching the wrong rows."""
        from cps import ub
        from cps.magic_shelf import SYSTEM_SHELF_TEMPLATES

        rule = SYSTEM_SHELF_TEMPLATES['currently_reading']['rules']['rules'][0]
        assert rule['value'] == ub.ReadBook.STATUS_IN_PROGRESS

    def test_yet_to_read_icon_avoids_collision(self):
        """yet_to_read was 📖 in plain calibre-web; the backport
        swapped it to 📚 so the new currently_reading preset could
        own 📖. If a future edit reverts this without re-checking
        currently_reading, both presets render with the same emoji."""
        from cps.magic_shelf import SYSTEM_SHELF_TEMPLATES

        yet_icon = SYSTEM_SHELF_TEMPLATES['yet_to_read']['icon']
        cur_icon = SYSTEM_SHELF_TEMPLATES['currently_reading']['icon']
        assert yet_icon != cur_icon, (
            "yet_to_read and currently_reading must use distinct icons "
            "so the magic-shelf picker is unambiguous. yet_to_read "
            "should be 📚; currently_reading should be 📖."
        )
        assert yet_icon == '📚'
        assert cur_icon == '📖'


@pytest.mark.unit
class TestBuildFilterFromRuleHandlesThreeStatuses:
    def test_in_progress_branch_filters_on_status_in_progress(self):
        """The no-custom-column fallback in build_filter_from_rule
        must dispatch on int(value) and query ReadBook with
        STATUS_IN_PROGRESS when value == 2. Before the backport, the
        function only knew STATUS_FINISHED — in-progress books would
        be classified as finished. Source-pin because the function
        depends on ub.session at runtime."""
        from cps.magic_shelf import build_filter_from_rule

        src = inspect.getsource(build_filter_from_rule)
        assert "ub.ReadBook.STATUS_IN_PROGRESS" in src, (
            "build_filter_from_rule must reference STATUS_IN_PROGRESS "
            "by name in its built-in fallback so the read_status==2 "
            "preset resolves to the correct ReadBook query."
        )
        # The STATUS_IN_PROGRESS branch must run its own query (not
        # share with the STATUS_FINISHED branch). Pin that there are
        # at least two distinct ReadBook.read_status comparisons in
        # the fallback — one IN_PROGRESS, one FINISHED.
        assert src.count("ub.ReadBook.read_status == ub.ReadBook.STATUS_IN_PROGRESS") >= 1
        assert src.count("ub.ReadBook.read_status == ub.ReadBook.STATUS_FINISHED") >= 1

    def test_status_value_parsed_as_int_not_bool(self):
        """The pre-backport code did `is_checking_read = (int(value) == 1)`
        which collapsed all non-1 values to the unread branch. The
        backport must parse status_value as int and dispatch on its
        actual numeric value, not coerce to bool."""
        from cps.magic_shelf import build_filter_from_rule

        src = inspect.getsource(build_filter_from_rule)
        assert "status_value = int(value)" in src, (
            "build_filter_from_rule must parse the rule value as a "
            "true integer (status_value = int(value)) so 0/1/2 each "
            "dispatch to their own branch. The pre-fix `is_checking_"
            "read = (int(value) == 1)` shape collapsed 2 to False."
        )
        assert "is_checking_read = (int(value) == 1)" not in src, (
            "build_filter_from_rule must not retain the boolean-coerce "
            "shape; that path silently misroutes STATUS_IN_PROGRESS."
        )

    def test_unread_branch_uses_complement_of_finished_set(self):
        """The unread branch must NOT issue a query for ReadBook rows
        with STATUS_UNREAD (such rows often don't exist — the default
        is "no ReadBook row at all"). It must build the unread set as
        the complement of STATUS_FINISHED book ids, mirroring how the
        original pre-backport code worked. If a future edit changes
        the unread branch to filter on STATUS_UNREAD directly, users
        with no ReadBook rows would see an empty unread shelf."""
        from cps.magic_shelf import build_filter_from_rule

        src = inspect.getsource(build_filter_from_rule)
        # The unread branch must emit ~db.Books.id.in_(...) when
        # status_value == STATUS_UNREAD. Pin the operator usage.
        assert "~db.Books.id.in_(matching_book_ids)" in src, (
            "Unread must be expressed as the negation of the finished "
            "set (~db.Books.id.in_(matching_book_ids)). Direct "
            "STATUS_UNREAD filtering would miss users whose default "
            "state is no ReadBook row."
        )


@pytest.mark.unit
class TestQueryBuilderTemplateExposesThreeRadioValues:
    """The Jinja template for magic-shelf edit ships the QueryBuilder
    field definition for read_status. It must declare the type as
    'integer' (not 'boolean') and expose all three radio values
    (0/1/2). If a future edit reverts to boolean or drops the
    "Currently Reading" radio, users can no longer create the preset
    through the UI even though the Python side still supports it."""

    def test_template_declares_integer_radio_with_three_values(self):
        import pathlib

        template_path = pathlib.Path(__file__).resolve().parents[2] / "cps" / "templates" / "magic_shelf_edit.html"
        content = template_path.read_text(encoding="utf-8")
        assert "type: 'integer'" in content, (
            "The QueryBuilder read_status field must declare "
            "type: 'integer' so all three values (0=Unread, "
            "1=Read, 2=Currently Reading) are valid. 'boolean' "
            "collapses to 0/1 only."
        )
        # All three radio values must be present in the QueryBuilder
        # values map for read_status. Order can vary (Unread/CR/Read
        # is the backport order); only presence matters.
        assert "'Currently Reading'" in content
        assert "'Unread'" in content
        assert "'Read'" in content
