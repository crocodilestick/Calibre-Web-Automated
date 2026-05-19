# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for the Kobo cont_sync paging signal (PR #248).

@ikerios captured a Kobo Forma (FW 4.45.23684) stuck in a sync loop after a
factory reset: ~3 sync requests/sec for 15+ hours against a 393-book
library, with logs showing 2 changed entries per request — well below
``SYNC_ITEM_LIMIT = 100`` — yet the server kept emitting
``x-kobo-sync: continue``.

Root cause in ``cps/kobo.py:HandleSyncRequest``: the books branch set
``cont_sync = bool(book_count)`` — True for any non-zero count — while the
reading-states branch seventeen lines below correctly used
``cont_sync |= bool(changed_reading_states.count() > SYNC_ITEM_LIMIT)``.
The Kobo protocol treats ``x-kobo-sync: continue`` as a paging signal
("more pages exist, keep your cursor pinned"), not a freshness signal.
When the current batch is exhaustive, emitting ``continue`` is a contract
violation: the firmware suppresses synctoken persistence, the device
re-requests with the same cursor, the server returns the same rows with
``continue``, and the loop self-perpetuates.

These tests source-pin that both cont_sync assignments in
``HandleSyncRequest`` use the same ``> SYNC_ITEM_LIMIT`` semantic — so a
future refactor can't silently drop the books-branch fix back to the
``bool(book_count)`` shape.

Complementary to fork #220's tests in ``test_kobo_bug_cluster_2026_05_17.py``,
which fixed the cursor-advance side (``BookShelf.date_added`` folded into
``new_books_last_modified``). PR #248 fixes the signal side. Both fixes
are required for the loop to terminate on ``else``-branch users.
"""

import inspect
import re
import sys
from pathlib import Path


def _handle_sync_request_source():
    """Pull ``HandleSyncRequest`` source via sys.modules so blueprint
    re-exports can't shadow the submodule attribute.

    Avoids ``from cps import kobo`` which can trigger Flask app boot and
    is fragile across pytest import modes.
    """
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "cps" / "kobo.py").read_text()
    return src


def _cont_sync_lines(src):
    """Return every line of source that assigns to ``cont_sync``.

    Books branch uses ``=`` (initial assignment); reading-states branch
    uses ``|=`` (aggregation). Matching to end-of-line dodges the nested-
    paren trap that ``[^)]+`` falls into (``bool(x.count() > LIMIT)`` has
    inner parens).
    """
    return re.findall(
        r"^[ \t]*cont_sync\s*(?:=|\|=)\s*[^\n]+$",
        src,
        re.MULTILINE,
    )


def test_books_branch_cont_sync_uses_sync_item_limit_compare():
    """The books-branch ``cont_sync`` assignment must compare against
    ``SYNC_ITEM_LIMIT`` — not simply ``bool(book_count)``.

    The broken shape is what stranded @ikerios's Forma at 3 req/sec for
    15 hours. Pin the corrected pattern by source so a refactor can't
    revert to the bug.
    """
    src = _handle_sync_request_source()
    lines = _cont_sync_lines(src)
    initial = [l for l in lines if re.match(r"^[ \t]*cont_sync\s*=\s", l)]
    assert initial, (
        "Expected a `cont_sync = ...` initial assignment in cps/kobo.py "
        "(books-branch paging signal). If the assignment shape changed, "
        "update this test — but keep the > SYNC_ITEM_LIMIT semantic."
    )
    line = initial[0]
    assert "SYNC_ITEM_LIMIT" in line, (
        f"The books-branch cont_sync assignment must reference "
        f"SYNC_ITEM_LIMIT (not just bool(book_count)). Current line: "
        f"{line!r}. Without the cap comparison, any non-zero book_count "
        f"emits 'x-kobo-sync: continue', the device suppresses synctoken "
        f"persistence, and the loop self-perpetuates."
    )
    assert ">" in line, (
        f"The books-branch cont_sync assignment must use the > comparison "
        f"with SYNC_ITEM_LIMIT (mirror the reading-states branch). "
        f"Current line: {line!r}"
    )


def test_reading_states_branch_cont_sync_uses_sync_item_limit_compare():
    """Defense-in-depth: the reading-states branch was already correct
    before PR #248 — pin it so a future refactor that "unifies" both
    branches doesn't accidentally regress this one too.
    """
    src = _handle_sync_request_source()
    lines = _cont_sync_lines(src)
    aggregations = [l for l in lines if re.match(r"^[ \t]*cont_sync\s*\|=", l)]
    assert aggregations, (
        "Expected a `cont_sync |= ...` aggregation in cps/kobo.py "
        "(reading-states branch). If the aggregation shape changed, "
        "update this test — but keep the > SYNC_ITEM_LIMIT semantic."
    )
    line = aggregations[0]
    assert "SYNC_ITEM_LIMIT" in line and ">" in line, (
        f"The reading-states cont_sync |= must compare against "
        f"SYNC_ITEM_LIMIT with the > operator. Current line: {line!r}"
    )


def test_both_count_based_cont_sync_assignments_use_same_pattern():
    """Both ``cont_sync (=|\\|=) bool(<count>)`` sites must use the same
    ``> SYNC_ITEM_LIMIT`` shape.

    There's a third ``cont_sync = True`` site downstream that's correctly
    guarded by an outer ``if len(pending_deletions) >= SYNC_ITEM_LIMIT``
    block (tombstone-pagination path) — that one doesn't need the inline
    comparison and is intentionally excluded from this pin.
    """
    src = _handle_sync_request_source()
    bool_lines = [
        l for l in _cont_sync_lines(src)
        if re.search(r"bool\s*\(", l)
    ]
    assert len(bool_lines) >= 2, (
        f"Expected at least two `cont_sync (=|\\|=) bool(...)` sites in "
        f"cps/kobo.py (books branch + reading-states branch); found "
        f"{len(bool_lines)}: {bool_lines}"
    )
    for m in bool_lines:
        assert "SYNC_ITEM_LIMIT" in m and ">" in m, (
            f"Every count-based cont_sync assignment must reference "
            f"SYNC_ITEM_LIMIT with the > operator (paging signal "
            f"semantics, not freshness). Offending line: {m!r}"
        )


def test_broken_pattern_bool_book_count_alone_is_gone():
    """The literal broken pattern ``bool(book_count)`` (alone, no
    comparison) must not appear in ``HandleSyncRequest``. Pinning the
    exact pre-fix string protects against a copy-paste revert.
    """
    src = _handle_sync_request_source()
    # Allow the variable name to appear in unrelated contexts. The check
    # is "bool(book_count) followed by close-paren and end-of-expression"
    # — the broken assignment shape exactly.
    assert not re.search(
        r"cont_sync\s*=\s*bool\(\s*book_count\s*\)",
        src,
    ), (
        "The pre-fix `cont_sync = bool(book_count)` pattern must not "
        "reappear. It treats any non-zero count as 'more pages exist', "
        "which the Kobo firmware honors by pinning the synctoken — "
        "infinite sync loop. Use `bool(book_count > SYNC_ITEM_LIMIT)` "
        "to mirror the reading-states branch."
    )
