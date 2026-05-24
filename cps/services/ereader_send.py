# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for the multi-recipient "Send to eReader" flow.

Fork #276 (@magdalar): an admin who manages a household's eReaders can send a
single book to *other* users' kindle_mail addresses without including any of
their own. In that case the book was relayed, not obtained by the sender, so it
must not be recorded as the sender's own download — otherwise the admin's
download history / "hot books" stats get polluted with books they only passed
along.
"""

from __future__ import annotations


def _split_addresses(raw: str | None) -> set[str]:
    """Normalise a comma-separated address string to trimmed, lowercased addresses."""
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def send_includes_own_address(own_kindle_mail: str | None, selected_emails: str | None) -> bool:
    """Return True if the send targeted at least one of the sender's own addresses.

    A multi-recipient send should record a self-download only when the sender
    included one of their own configured eReader addresses. Relaying a book
    solely to other users' eReaders is not a self-download.

    Args:
        own_kindle_mail: the sender's configured kindle_mail (may be comma-separated, may be None).
        selected_emails: the comma-separated set of addresses the book was actually sent to.

    Returns:
        True if any own address appears in the selected set (case-insensitive,
        whitespace-trimmed); False otherwise, including when the sender has no
        own address configured.
    """
    own = _split_addresses(own_kindle_mail)
    if not own:
        return False
    return bool(own & _split_addresses(selected_emails))
