# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Behaviour-pinning tests for fork issue #312 (@uschi1) — "Mark as read
koreader".

The user-facing promise we made on that thread: when KOReader syncs a book
that has reached the end (~99% or more), this build sets the book's **Read**
checkmark for that user automatically, with no toggle. Partway through, the
book shows as *Reading*; at 0% it is *Unread*.

That promise is implemented by ``update_book_read_status`` in the kosync
protocol handler, called from the ``/kosync/syncs/progress`` PUT path once the
synced document is matched to a Calibre ``book_id``. The existing integration
tests in ``tests/integration/test_kosync_update_read_status.py`` send progress
to documents that do **not** resolve to a library book, so ``book_id`` is
``None`` and ``update_book_read_status`` is never invoked — they assert only
the HTTP 200 and the stored percentage, never the resulting ``ReadBook``
status. The checkmark behaviour itself was therefore unpinned: a threshold
drift (``>= 99`` → ``> 99``), an inverted status mapping, or dropping the call
site entirely would all have shipped green.

These tests pin the contract directly against a real in-memory ``ub`` session
(no mocks of the query chain) and source-pin the call site so a future refactor
can't silently strip the auto-mark-read wiring.
"""

import ast
import inspect
import pathlib
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO = pathlib.Path(__file__).resolve().parents[2]

USER_ID = 7
BOOK_ID = 101


def _kosync_module():
    """Return the kosync *module* (not the re-exported Blueprint).

    ``cps.progress_syncing.protocols.__init__`` does ``from .kosync import
    kosync``, binding the Blueprint object as ``protocols.kosync`` and shadowing
    the submodule attribute. The module itself is still in ``sys.modules``.
    """
    import cps.progress_syncing.protocols.kosync  # noqa: F401 — populate sys.modules
    return sys.modules["cps.progress_syncing.protocols.kosync"]


class _FakeUser:
    """``update_book_read_status`` only reads ``user.id``."""

    def __init__(self, user_id):
        self.id = user_id


@pytest.fixture
def session(monkeypatch):
    # Some suites stub cps.*, flask, sqlalchemy… into sys.modules and don't
    # restore — evict the affected families so we import the real ones.
    if "cps.ub" in sys.modules and not hasattr(sys.modules["cps.ub"], "Base"):
        stubbed = {"cps", "cwa_db", "flask", "flask_babel", "flask_dance",
                   "sqlalchemy", "werkzeug"}
        for name in [m for m in list(sys.modules) if m.split(".")[0] in stubbed]:
            sys.modules.pop(name, None)
    from cps import ub

    engine = create_engine("sqlite:///:memory:", future=True)
    ub.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # The function uses the module-global ``ub.session``; point it at our
    # in-memory session so the real query/insert path runs.
    monkeypatch.setattr(ub, "session", s)
    # Default config: no Calibre custom read-column designated, so the checkmark
    # is the standard ub.ReadBook one (exactly @uschi1's setup). This skips the
    # _mark_custom_read_column branch, which would need a reflected metadata.db.
    mod = _kosync_module()
    monkeypatch.setattr(mod.config, "config_read_column", 0, raising=False)
    yield s
    s.close()


def _read_status(ub, user_id, book_id):
    row = (ub.session.query(ub.ReadBook)
           .filter(ub.ReadBook.user_id == user_id,
                   ub.ReadBook.book_id == book_id)
           .first())
    return row.read_status if row else None


# ---------------------------------------------------------------------------
# Threshold → status contract (the #312 promise)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("percentage, expected_attr", [
    (100.0, "STATUS_FINISHED"),
    (99.5, "STATUS_FINISHED"),
    (99.0, "STATUS_FINISHED"),    # inclusive lower bound for "finished"
    (98.9, "STATUS_IN_PROGRESS"), # just below → still reading, NOT finished
    (50.0, "STATUS_IN_PROGRESS"),
    (1.0, "STATUS_IN_PROGRESS"),
    (0.0, "STATUS_UNREAD"),
])
def test_percentage_maps_to_read_status(session, percentage, expected_attr):
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    update_book_read_status(_FakeUser(USER_ID), BOOK_ID, percentage)
    ub.session.commit()

    expected = getattr(ub.ReadBook, expected_attr)
    assert _read_status(ub, USER_ID, BOOK_ID) == expected, (
        f"{percentage}% should map to {expected_attr} ({expected})"
    )


def test_99_is_finished_but_98_9_is_not(session):
    """The exact boundary that decides whether @uschi1's checkmark ticks."""
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    update_book_read_status(_FakeUser(USER_ID), 201, 98.9)
    update_book_read_status(_FakeUser(USER_ID), 202, 99.0)
    ub.session.commit()

    assert _read_status(ub, USER_ID, 201) == ub.ReadBook.STATUS_IN_PROGRESS
    assert _read_status(ub, USER_ID, 202) == ub.ReadBook.STATUS_FINISHED


def test_creates_readbook_row_on_first_sync(session):
    """A book the user has never opened in the web UI still gets a row — the
    whole point of #312 (finishing on-device, never touching the web reader)."""
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    assert _read_status(ub, USER_ID, BOOK_ID) is None  # nothing pre-existing
    update_book_read_status(_FakeUser(USER_ID), BOOK_ID, 100.0)
    ub.session.commit()
    assert _read_status(ub, USER_ID, BOOK_ID) == ub.ReadBook.STATUS_FINISHED


def test_progress_then_finish_transitions_to_finished(session):
    """Mid-book sync marks Reading; a later end-of-book sync flips to Read."""
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    update_book_read_status(_FakeUser(USER_ID), BOOK_ID, 40.0)
    ub.session.commit()
    assert _read_status(ub, USER_ID, BOOK_ID) == ub.ReadBook.STATUS_IN_PROGRESS

    update_book_read_status(_FakeUser(USER_ID), BOOK_ID, 99.0)
    ub.session.commit()
    assert _read_status(ub, USER_ID, BOOK_ID) == ub.ReadBook.STATUS_FINISHED


def test_times_started_reading_increments_on_unread_to_in_progress(session):
    """Starting a book bumps times_started_reading; jumping a new row straight
    to FINISHED does not (Kobo/CWA convention preserved)."""
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    # New row created directly at FINISHED → counter stays 0.
    update_book_read_status(_FakeUser(USER_ID), 301, 100.0)
    ub.session.commit()
    row = (ub.session.query(ub.ReadBook)
           .filter(ub.ReadBook.user_id == USER_ID, ub.ReadBook.book_id == 301)
           .first())
    assert row.times_started_reading == 0

    # New row created at IN_PROGRESS → counter is 1.
    update_book_read_status(_FakeUser(USER_ID), 302, 30.0)
    ub.session.commit()
    row = (ub.session.query(ub.ReadBook)
           .filter(ub.ReadBook.user_id == USER_ID, ub.ReadBook.book_id == 302)
           .first())
    assert row.times_started_reading == 1


def test_status_scoped_per_user(session):
    """One user finishing a book must not flip another user's status."""
    from cps import ub
    update_book_read_status = _kosync_module().update_book_read_status

    update_book_read_status(_FakeUser(1), BOOK_ID, 100.0)
    update_book_read_status(_FakeUser(2), BOOK_ID, 10.0)
    ub.session.commit()

    assert _read_status(ub, 1, BOOK_ID) == ub.ReadBook.STATUS_FINISHED
    assert _read_status(ub, 2, BOOK_ID) == ub.ReadBook.STATUS_IN_PROGRESS


# ---------------------------------------------------------------------------
# Call-site wiring — the promise only holds if the push handler invokes it
# ---------------------------------------------------------------------------

def test_progress_push_calls_update_book_read_status_when_book_matched():
    """Source-pin: the kosync progress handler must call
    ``update_book_read_status`` guarded by a truthy ``book_id``. If a refactor
    drops this call (or stops guarding on the match), the auto-mark-read promise
    silently breaks while every HTTP-level test stays green — exactly the gap
    this file closes."""
    mod = _kosync_module()
    src = inspect.getsource(mod)
    tree = ast.parse(src)

    calls_under_book_id_guard = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # `if book_id:` — name or attribute access truthiness check
            test = node.test
            guards_on_book_id = (
                (isinstance(test, ast.Name) and test.id == "book_id")
            )
            if not guards_on_book_id:
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "update_book_read_status"):
                    calls_under_book_id_guard.append(inner)

    assert calls_under_book_id_guard, (
        "expected update_book_read_status(...) to be called inside an "
        "`if book_id:` guard in the kosync progress handler — the #312 "
        "auto-mark-read wiring is missing or no longer gated on a library match"
    )
