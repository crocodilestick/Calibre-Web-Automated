# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drop-in replacement for cps.services.hardcover.HardcoverClient for tests."""

from __future__ import annotations

from typing import Optional


class MockHardcoverClient:
    """Minimal subset of HardcoverClient used by HardcoverHandler.

    Configure via constructor or by mutating attributes between calls.
    Every call records into ``self.calls``.
    """

    def __init__(
        self,
        add_response: Optional[dict] = None,
        add_raises: Optional[Exception] = None,
        update_response: Optional[dict] = None,
        update_raises: Optional[Exception] = None,
        delete_response: Optional[int] = None,
        delete_raises: Optional[Exception] = None,
    ):
        self.add_response = add_response if add_response is not None else {"id": 42}
        self.add_raises = add_raises
        self.update_response = update_response if update_response is not None else {"id": 42}
        self.update_raises = update_raises
        self.delete_response = delete_response
        self.delete_raises = delete_raises
        self.calls = []

    def add_journal_entry(self, *args, **kwargs):
        self.calls.append(("add", args, kwargs))
        if self.add_raises:
            raise self.add_raises
        return self.add_response

    def update_journal_entry(self, *args, **kwargs):
        self.calls.append(("update", args, kwargs))
        if self.update_raises:
            raise self.update_raises
        return self.update_response

    def delete_journal_entry(self, journal_id):
        self.calls.append(("delete", journal_id))
        if self.delete_raises:
            raise self.delete_raises
        return self.delete_response if self.delete_response is not None else journal_id
