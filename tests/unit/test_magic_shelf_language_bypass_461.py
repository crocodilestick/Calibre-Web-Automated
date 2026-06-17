# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for fork issue #461 (reporter @chloeroform).

Symptom: a book the user is actively reading (KOSync/Kobo-synced,
read_status == STATUS_IN_PROGRESS) is missing from the "Currently
Reading" magic shelf, while another in-progress book on the same
account appears. The reporter saw it split along EPUB-vs-PDF lines.

Root cause (confirmed on real cwn-local data, see
notes/461-magic-shelf-koreader-design.md): read-path asymmetry. The
magic-shelf query applies CalibreDB.common_filters, which includes the
per-user *language* browse filter
(Books.languages.any(lang_code == user.filter_language())) whenever the
user's default_language is not "all". A book with no language metadata
(UI-uploaded PDFs routinely have none) fails that clause and is dropped
from the shelf — but the book-detail page reads KOReader progress
WITHOUT common_filters, so it still shows the book as in-progress. The
EPUB carried 'eng' and survived the clause; the PDF carried no language
and did not.

Fix: progress-driven shelves (any rule set referencing read_status) are
activity-driven, not browse-driven. A book the user demonstrably has
reading activity on must not be hidden by a language *browse preference*.
So when a magic shelf's rule set references read_status, the query passes
return_all_languages=True to common_filters — skipping ONLY the language
clause while archived/hidden/denied-tags/restricted-column stay enforced.

These tests pin two things:

1. rules_reference_read_status() correctly detects a read_status rule in
   the system templates and in nested AND/OR rule groups, and correctly
   returns False for browse-only rule sets (so language filtering is NOT
   bypassed for non-progress custom shelves). This is the gate that
   decides whether the language bypass fires — pure function, fully
   exercised here.

2. build_book_query_for_magic_shelf threads that gate into
   common_filters(return_all_languages=...). Source/AST-pinned because the
   function reaches into ub.session, db.CalibreDB(init=True) and
   current_user at runtime and is awkward to invoke without full app init
   (same precedent as test_magic_shelf_currently_reading.py). If a future
   edit drops the bypass, the no-language in-progress book silently
   disappears from the shelf again and this pin fires.
"""

import ast
import inspect

import pytest


@pytest.mark.unit
class TestRulesReferenceReadStatus:
    """Pure-function tests for the language-bypass decision gate."""

    def test_currently_reading_template_detected(self):
        from cps.magic_shelf import SYSTEM_SHELF_TEMPLATES, rules_reference_read_status

        rules = SYSTEM_SHELF_TEMPLATES['currently_reading']['rules']
        assert rules_reference_read_status(rules) is True, (
            "The 'Currently Reading' preset filters on read_status, so the "
            "shelf query must bypass the per-user language browse filter "
            "(return_all_languages=True). #461."
        )

    def test_yet_to_read_and_finished_templates_detected(self):
        from cps.magic_shelf import SYSTEM_SHELF_TEMPLATES, rules_reference_read_status

        for key in ('yet_to_read',):
            assert rules_reference_read_status(
                SYSTEM_SHELF_TEMPLATES[key]['rules']
            ) is True, f"{key} filters on read_status and must bypass language."

        # Any template whose rules reference read_status must be detected.
        for key, tmpl in SYSTEM_SHELF_TEMPLATES.items():
            refs = _raw_rules_reference_field(tmpl.get('rules'), 'read_status')
            assert rules_reference_read_status(tmpl['rules']) == refs, (
                f"Detection disagrees with rule contents for template {key!r}."
            )

    def test_browse_only_rules_not_detected(self):
        """A custom shelf that filters on language/rating but NOT read_status
        must keep language filtering (return False)."""
        from cps.magic_shelf import rules_reference_read_status

        browse_rules = {
            'condition': 'AND',
            'rules': [
                {'id': 'rating', 'field': 'rating', 'operator': 'greater', 'value': 3},
                {'id': 'has_cover', 'field': 'has_cover', 'operator': 'equal', 'value': 1},
            ],
        }
        assert rules_reference_read_status(browse_rules) is False

    def test_nested_group_detected(self):
        """A read_status rule nested inside an OR sub-group must be detected."""
        from cps.magic_shelf import rules_reference_read_status

        nested = {
            'condition': 'AND',
            'rules': [
                {'id': 'rating', 'field': 'rating', 'operator': 'greater', 'value': 3},
                {
                    'condition': 'OR',
                    'rules': [
                        {'id': 'has_cover', 'field': 'has_cover', 'operator': 'equal', 'value': 1},
                        {'id': 'read_status', 'field': 'read_status', 'operator': 'equal', 'value': 2},
                    ],
                },
            ],
        }
        assert rules_reference_read_status(nested) is True

    def test_field_key_alias_detected(self):
        """build_filter_from_rule keys off rule['id']; templates also carry
        'field'. Either spelling of read_status must trigger the bypass."""
        from cps.magic_shelf import rules_reference_read_status

        only_field = {'condition': 'AND', 'rules': [
            {'field': 'read_status', 'operator': 'equal', 'value': 2}]}
        only_id = {'condition': 'AND', 'rules': [
            {'id': 'read_status', 'operator': 'equal', 'value': 2}]}
        assert rules_reference_read_status(only_field) is True
        assert rules_reference_read_status(only_id) is True

    def test_empty_or_missing_rules_not_detected(self):
        from cps.magic_shelf import rules_reference_read_status

        assert rules_reference_read_status(None) is False
        assert rules_reference_read_status({}) is False
        assert rules_reference_read_status({'condition': 'AND', 'rules': []}) is False


def _raw_rules_reference_field(rules_json, field):
    """Independent reference implementation for cross-checking detection."""
    if not rules_json or not rules_json.get('rules'):
        return False
    for rule in rules_json.get('rules', []):
        if 'condition' in rule:
            if _raw_rules_reference_field(rule, field):
                return True
        elif rule.get('id') == field or rule.get('field') == field:
            return True
    return False


@pytest.mark.unit
class TestQuerySiteThreadsLanguageBypass:
    """AST-pin: the shelf query must derive return_all_languages from the
    read_status gate. Pinned at source level because the function needs full
    app init (ub.session, db.CalibreDB, current_user) to run."""

    def _query_fn_source(self):
        from cps.magic_shelf import build_book_query_for_magic_shelf
        return inspect.getsource(build_book_query_for_magic_shelf)

    def test_calls_detection_gate(self):
        src = self._query_fn_source()
        assert 'rules_reference_read_status' in src, (
            "build_book_query_for_magic_shelf must consult "
            "rules_reference_read_status to decide whether to bypass the "
            "language browse filter for progress-driven shelves. #461."
        )

    def test_common_filters_receives_return_all_languages(self):
        """The common_filters call in the shelf query must pass
        return_all_languages as a (non-constant) keyword argument so a
        progress shelf can skip the language clause."""
        src = self._query_fn_source()
        # Module-level function source is already valid top-level code; parse
        # it directly (cleandoc would strip body indentation and break it).
        tree = ast.parse(src)

        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # match `<something>.common_filters(...)`
            if isinstance(func, ast.Attribute) and func.attr == 'common_filters':
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                assert 'return_all_languages' in kw, (
                    "common_filters in the magic-shelf query must receive a "
                    "return_all_languages keyword (#461)."
                )
                val = kw['return_all_languages']
                # Must NOT be hardcoded True/False — it has to be derived from
                # the rule set so browse-only shelves keep language filtering.
                is_constant = isinstance(val, ast.Constant) and isinstance(val.value, bool)
                assert not is_constant, (
                    "return_all_languages must be computed from the rule set "
                    "(read_status gate), not hardcoded — browse-only custom "
                    "shelves must still filter by language."
                )
                found.append(node)

        assert found, "No common_filters(...) call found in the shelf query."
