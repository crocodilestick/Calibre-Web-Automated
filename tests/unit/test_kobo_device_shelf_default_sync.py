# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test for B8 — device-created shelves default to
kobo_sync=False.

Symptom:
    When a user creates a shelf on their Kobo device (long-press a
    book in their library → "Create new collection"), the Kobo
    posts `POST /v1/library/tags` with the new collection name and
    items. ``HandleTagCreate`` constructs a fresh ``ub.Shelf`` row
    without passing ``kobo_sync=True``, so the column falls back to
    its default of ``False``. The shelf exists on the device and on
    the server, but the server never re-emits ``NewTag`` for it on
    subsequent syncs, so it never reconciles to a second Kobo on the
    same account and disappears on factory reset.

Root cause:
    ``cps/ub.py:Shelf.kobo_sync`` is ``Column(Boolean, default=False)``.
    Device-created shelves are by definition Kobo-managed; the
    constructor in ``HandleTagCreate`` must pass ``kobo_sync=True``
    explicitly.

Fix:
    Add ``kobo_sync=True`` to the ``ub.Shelf(...)`` call inside
    ``HandleTagCreate``. Users who don't want a device-created shelf
    to sync can untoggle the flag via the shelf-edit UI afterward.

These tests pin the fix at the source-text level so a future refactor
that drops the keyword silently re-introduces the bug.
"""

import inspect

import pytest


@pytest.mark.unit
class TestDeviceCreatedShelvesDefaultToKoboSync:
    """The shelf constructed in HandleTagCreate must set kobo_sync=True."""

    def test_handle_tag_create_passes_kobo_sync_true(self):
        from cps.kobo import HandleTagCreate
        src = inspect.getsource(HandleTagCreate)
        assert "kobo_sync=True" in src, (
            "HandleTagCreate must construct ub.Shelf(...) with "
            "kobo_sync=True. Device-created shelves are Kobo-managed "
            "by definition; without the explicit flag the column "
            "default of False makes the shelf invisible to subsequent "
            "syncs (B8)."
        )

    def test_handle_tag_create_constructs_shelf_with_kobo_sync(self):
        """The kobo_sync=True must be on the ub.Shelf(...) call inside
        the not-shelf branch — not somewhere unrelated."""
        from cps.kobo import HandleTagCreate
        src = inspect.getsource(HandleTagCreate)
        # The constructor call we care about is the one creating a
        # new shelf for the device. Pin the keyword to that call.
        assert "ub.Shelf(" in src, (
            "HandleTagCreate must still construct a ub.Shelf — the "
            "device-created shelf path was unexpectedly removed."
        )
        # Find the ub.Shelf(...) call and confirm kobo_sync=True is
        # within its argument list (single-line or multi-line).
        start = src.index("ub.Shelf(")
        # Walk forward to the matching close-paren accounting for
        # nesting (the user_id may itself reference a function call).
        depth = 0
        end = None
        for i, ch in enumerate(src[start:], start=start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        assert end is not None, (
            "Could not locate matching close-paren for ub.Shelf( in "
            "HandleTagCreate — test brittleness or refactor."
        )
        call_args = src[start:end + 1]
        assert "kobo_sync=True" in call_args, (
            "ub.Shelf(...) inside HandleTagCreate must include "
            "kobo_sync=True so device-created shelves are visible to "
            "subsequent syncs."
        )


@pytest.mark.unit
class TestColumnDefaultUnchanged:
    """We're not flipping the column default — the fix is at the
    callsite. Other shelf-creation paths (CW web UI) still default to
    kobo_sync=False, and only opt in when the user toggles the
    'sync this shelf to Kobo' switch in the shelf-edit form."""

    def test_shelf_kobo_sync_column_default_is_false(self):
        from cps.ub import Shelf
        col = Shelf.__table__.c.kobo_sync
        # SQLAlchemy stores the default as a ColumnDefault wrapping the
        # raw value.
        default = col.default
        assert default is not None, (
            "Shelf.kobo_sync must have a SQLAlchemy column default."
        )
        # The default argument we set is the literal False.
        assert default.arg is False, (
            "Shelf.kobo_sync column default must remain False so "
            "CW-UI-created shelves don't accidentally start syncing "
            "to Kobo without an explicit user opt-in. The B8 fix "
            "lives at the HandleTagCreate callsite, not the column."
        )
