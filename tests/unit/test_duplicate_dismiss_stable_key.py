# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""D5 regression tests — dismissals keyed on the stable duplicate_key.

From the 2026-06 duplicate audit (notes/duplicate-detection-fix-plan.md §D5):
group_hash is an MD5 of the DISPLAY title/author of whichever book sorts
first in the group. A new ingest, a metadata edit, or a criteria change moved
that hash, so a prior dismissal stopped matching and the group resurfaced —
re-entering the destructive auto-resolve population. Two normalized groups
sharing a raw display title collided into one dismissal.

The fix keys dismissals on the SHA-256 ``duplicate_key`` the index already
groups by (carried through every scan path), keeps ``group_hash`` only for
the UI routes and pre-migration rows, and lazily backfills old rows.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
DUP_SRC = (REPO_ROOT / "cps" / "duplicates.py").read_text()
UB_SRC = (REPO_ROOT / "cps" / "ub.py").read_text()
IDX_SRC = (REPO_ROOT / "cps" / "duplicate_index.py").read_text()


@pytest.fixture(autouse=True)
def _isolate_sys_modules():
    """Restore sys.modules after the stub harness (see D8 test for why)."""
    saved = sys.modules.copy()
    yield
    for name in list(sys.modules):
        if name not in saved:
            del sys.modules[name]
    for name, module in saved.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module


def _harness():
    path = _HERE / "test_duplicate_delete_index_maintenance.py"
    spec = importlib.util.spec_from_file_location("_dup_stub_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Field:
    def __eq__(self, other):  # SQLAlchemy-style column comparison stub
        return ("eq", other)


class _DismissQuery:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


def _world_with_dismissals(rows):
    """Stubbed cps.duplicates with ub.session.query returning `rows`."""
    harness = _harness()
    module, _books, calls = harness._load_duplicates_module([])
    ub_stub = sys.modules["cps.ub"]
    ub_stub.DismissedDuplicateGroup = type(
        "DismissedDuplicateGroup", (),
        {"user_id": _Field(), "group_hash": _Field(), "duplicate_key": _Field()},
    )
    ub_stub.session = SimpleNamespace(
        query=lambda *a, **k: _DismissQuery(rows, calls),
        commit=lambda: calls.append("ub-commit"),
        rollback=lambda: calls.append("ub-rollback"),
    )
    return module, calls


def _group(title, group_hash, duplicate_key):
    return {"title": title, "author": "A", "count": 2, "books": [],
            "group_hash": group_hash, "duplicate_key": duplicate_key}


class TestD5DismissalSurvivesDisplayDrift:
    def test_key_match_filters_group_even_when_hash_drifted(self):
        # Dismissed when the group's display hash was OLDHASH; a new ingest
        # changed books[0] so the rebuilt group hashes to NEWHASH. The stable
        # duplicate_key is unchanged — the dismissal must still apply.
        row = SimpleNamespace(group_hash="OLDHASH", duplicate_key="KEY-1")
        module, _calls = _world_with_dismissals([row])
        groups = [_group("The Republic", "NEWHASH", "KEY-1")]
        out = module.filter_dismissed_groups(groups, user_id=7)
        assert out == [], (
            "a dismissed group resurfaced after display-data drift — the "
            "dismissal must match on duplicate_key, not the display hash (D5)"
        )


class TestD5NoCrossContamination:
    def test_same_display_hash_different_keys_do_not_collide(self):
        # Two distinct normalized groups whose newest books share a raw
        # display title produce the same MD5 hash. Dismissing one (keyed on
        # its duplicate_key) must NOT hide the other.
        row = SimpleNamespace(group_hash="SAMEHASH", duplicate_key="KEY-A")
        module, _calls = _world_with_dismissals([row])
        groups = [
            _group("Café", "SAMEHASH", "KEY-A"),
            _group("Café", "SAMEHASH", "KEY-B"),
        ]
        out = module.filter_dismissed_groups(groups, user_id=7)
        assert [g["duplicate_key"] for g in out] == ["KEY-B"], (
            "dismissing one group hid another group that shares its display "
            "hash — dismissals must be keyed on duplicate_key (D5)"
        )


class TestD5LegacyRowsBackfillAndStillMatch:
    def test_premigration_row_matches_by_hash_and_learns_the_key(self):
        # A row written before the migration has only group_hash. It must
        # still filter the matching group (transitional behavior) AND learn
        # that group's duplicate_key so future drift can't resurface it.
        row = SimpleNamespace(group_hash="H1", duplicate_key=None)
        module, calls = _world_with_dismissals([row])
        groups = [_group("Old Book", "H1", "KEY-9")]
        out = module.filter_dismissed_groups(groups, user_id=7)
        assert out == []
        assert row.duplicate_key == "KEY-9", (
            "pre-migration dismissal rows must be backfilled with the "
            "matching group's duplicate_key (D5 lazy backfill)"
        )
        assert "ub-commit" in calls, "the backfill must be persisted"


class TestD5KeyRotationRekeys:
    def test_normalization_bump_rekeys_dismissal_via_hash(self):
        # A NORMALIZATION_VERSION bump (D6) rotates every duplicate_key. A row
        # holding a stale v1 key must still match its group via the hash
        # fallback AND be re-keyed to the group's current key, so the
        # dismissal survives the index rebuild.
        row = SimpleNamespace(group_hash="H1", duplicate_key="V1-KEY")
        module, calls = _world_with_dismissals([row])
        groups = [_group("Old Book", "H1", "V2-KEY")]
        out = module.filter_dismissed_groups(groups, user_id=7)
        assert out == [], (
            "a dismissal stopped matching after the normalization-version "
            "rebuild rotated its duplicate_key (D5/D6 interaction)"
        )
        assert row.duplicate_key == "V2-KEY", "stale keys must be re-keyed"
        assert "ub-commit" in calls


class TestD5SourcePins:
    def test_dismiss_route_stores_duplicate_key(self):
        m = re.search(r"def dismiss_duplicate_group\(group_hash\):(.*?)\n@", DUP_SRC, re.S)
        assert m, "dismiss_duplicate_group not found"
        body = m.group(0)
        assert "_resolve_duplicate_key_for_hash" in body
        assert "duplicate_key=duplicate_key" in body, (
            "dismiss must store the stable duplicate_key on the row (D5)"
        )

    def test_undismiss_deletes_by_key_or_hash(self):
        m = re.search(r"def undismiss_duplicate_group\(group_hash\):(.*?)\n@", DUP_SRC, re.S)
        assert m, "undismiss_duplicate_group not found"
        body = m.group(0)
        assert "or_(" in body and "duplicate_key" in body, (
            "undismiss must delete by duplicate_key OR group_hash so drifted "
            "and pre-migration rows are both removable (D5)"
        )

    def test_index_group_carries_duplicate_key(self):
        m = re.search(r"def _group_from_books\(books, duplicate_key=None\):(.*?)\ndef ", IDX_SRC, re.S)
        assert m, "_group_from_books must accept duplicate_key (D5)"
        assert '"duplicate_key": duplicate_key' in m.group(1)
        assert "_group_from_books(books, duplicate_key=duplicate_key)" in IDX_SRC, (
            "get_duplicate_groups_from_index must pass the key it grouped by"
        )

    def test_legacy_paths_attach_stable_key(self):
        assert DUP_SRC.count("'duplicate_key': _stable_group_key(books)") >= 2, (
            "both legacy scan paths (SQL + Python) must attach the stable "
            "duplicate_key to their groups (D5)"
        )

    def test_model_and_migration(self):
        assert re.search(r"class DismissedDuplicateGroup\(Base\):.*?duplicate_key = Column", UB_SRC, re.S), (
            "DismissedDuplicateGroup must have a duplicate_key column (D5)"
        )
        assert "def migrate_dismissed_duplicate_groups_table" in UB_SRC
        assert "migrate_dismissed_duplicate_groups_table(engine, _session)" in UB_SRC, (
            "the migration must be registered in migrate_Database"
        )

    def test_single_dismiss_filter_implementation(self):
        # The two legacy inline copies of the dismissed-filter were divergence
        # bait — both paths must route through filter_dismissed_groups.
        assert DUP_SRC.count("DismissedDuplicateGroup.group_hash)\\") == 0, (
            "inline dismissed-hash queries must not reappear outside "
            "filter_dismissed_groups (single source of truth, D5)"
        )
