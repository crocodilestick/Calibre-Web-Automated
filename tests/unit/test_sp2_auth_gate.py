# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sub-project (2) — the auth gate must NOT short-circuit on Hardcover-off.

Pre-(2): requires_reading_services_auth_and_config bailed early when
config_hardcover_annotations_sync was False — the dispatcher never ran,
so live Kobo annotations were never captured locally unless Hardcover was on.

Post-(2): the gate only short-circuits on Kobo-sync-off or unauthenticated.
The Hardcover-specific decision is moved into the dispatcher's per-handler
is_enabled check.
"""

from __future__ import annotations
import inspect

from cps import readingservices


def test_auth_gate_source_no_longer_references_hardcover_annotations_sync():
    """The decorator's body must not reference config_hardcover_annotations_sync."""
    src = inspect.getsource(readingservices.requires_reading_services_auth_and_config)
    assert "config_hardcover_annotations_sync" not in src, (
        "Sub-project (2) regression: the auth gate is back to gating on Hardcover. "
        "Move that check into the dispatcher's per-handler is_enabled() instead."
    )


def test_auth_gate_still_checks_kobo_sync():
    """We still gate on Kobo sync being on AND user authenticated."""
    src = inspect.getsource(readingservices.requires_reading_services_auth_and_config)
    assert "config_kobo_sync" in src
    assert "is_authenticated" in src
