# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Hardcover ↔ KoReader integration.

Registers a KoSync progress listener that forwards reading progress to
Hardcover.  Keeps all Hardcover-specific logic *outside* the KoSync plugin.

Usage (called once at app startup):
    from .hardcover_koreader import register_hardcover_koreader_sync
    register_hardcover_koreader_sync()
"""

from . import calibre_db, config, logger, ub
from .services import hardcover

log = logger.create()


def _on_koreader_progress(user: ub.User, book_id: int, percentage: float) -> None:
    """Push KoReader reading progress to Hardcover.

    Called by the KoSync progress-listener mechanism whenever a KoReader
    device pushes progress that was successfully matched to a Calibre book.

    All exceptions are caught and logged so that Hardcover issues never
    prevent KoReader from syncing progress.

    Args:
        user: The authenticated CWA user.
        book_id: The Calibre library book ID.
        percentage: Reading progress as a percentage (0-100).
    """
    if not config.config_hardcover_sync or not bool(hardcover):
        return

    # Check if book is blacklisted from reading progress syncing
    try:
        book_blacklist = ub.session.query(ub.HardcoverBookBlacklist).filter(
            ub.HardcoverBookBlacklist.book_id == book_id
        ).first()

        if book_blacklist and book_blacklist.blacklist_reading_progress:
            log.debug(f"Skipping Hardcover reading progress sync for book {book_id} - blacklisted")
            return
    except Exception as e:
        log.error(f"Failed to check Hardcover blacklist for book {book_id}: {e}")
        # Continue anyway — better to sync than to silently skip

    # Check the user has a Hardcover token
    if not getattr(user, "hardcover_token", None):
        log.debug(f"User {user.name} has no Hardcover token, skipping Hardcover progress sync")
        return

    try:
        hardcover_client = hardcover.HardcoverClient(user.hardcover_token)
    except hardcover.MissingHardcoverToken:
        log.info(
            f"User {user.name} has no Hardcover token, "
            "not syncing reading progress to Hardcover"
        )
        return
    except Exception as e:
        log.error(f"Failed to create Hardcover client for user {user.name}: {e}")
        return

    # Fetch the book from Calibre to get its identifiers
    try:
        book = calibre_db.get_book(book_id)
    except Exception as e:
        log.error(f"Failed to fetch book {book_id} from Calibre DB for Hardcover sync: {e}")
        return

    if not book:
        log.debug(f"Book {book_id} not found in Calibre DB, cannot sync to Hardcover")
        return

    try:
        hardcover_client.update_reading_progress(book.identifiers, percentage)
        log.info(
            f"Synced KoReader reading progress to Hardcover: user={user.name}, "
            f"book={book_id}, progress={percentage:.1f}%"
        )
    except Exception as e:
        log.error(f"Failed to sync KoReader reading progress for book {book_id} to Hardcover: {e}")


def register_hardcover_koreader_sync() -> None:
    """Register the Hardcover listener with KoSync.

    Safe to call even when Hardcover is not available — the listener will
    short-circuit on each invocation if the feature is disabled.
    """
    from .progress_syncing.protocols.kosync import register_progress_listener

    register_progress_listener(_on_koreader_progress)
    log.info("Registered Hardcover integration with KoSync progress listener")
