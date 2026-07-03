# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from . import db, ub, config, logger
from .magic_shelf import build_query_from_rules

log = logger.create()

KOBO_EXCLUSION_SHELF_NAME = "Kobo: Ausgeschlossen"


def get_magic_shelf_book_ids_direct(shelf):
    """
    Ermittelt die IDs der Bücher eines Magic Shelves direkt über die Calibre-Datenbank.
    Umgeht den Magic-Shelf-Cache sowie die Instanziierung von Buchobjekten, nutzt jedoch
    über cdb.common_filters() weiterhin den current_user-Kontext für Sprach- und Tag-Rechtefilter.
    """
    if not shelf.rules:
        return set()

    try:
        cdb = db.CalibreDB(init=True)
        query_filter = build_query_from_rules(shelf.rules, user_id=shelf.user_id, is_public=bool(shelf.is_public))
        if query_filter is None:
            log.warning(f"Failed to build query filter for magic shelf {shelf.id}")
            return set()

        query = cdb.session.query(db.Books).filter(query_filter)
        query = query.filter(cdb.common_filters())

        all_ids_tuples = query.with_entities(db.Books.id).all()
        return {x[0] for x in all_ids_tuples}
    except Exception as e:
        log.error(f"Failed to fetch book IDs for magic shelf {shelf.id}: {str(e)}")
        return set()


def get_kobo_excluded_books(user_id):
    excluded_rows = (
        ub.session.query(ub.BookShelf.book_id)
        .join(ub.Shelf, ub.BookShelf.shelf == ub.Shelf.id)
        .filter(ub.Shelf.user_id == user_id, ub.Shelf.name == KOBO_EXCLUSION_SHELF_NAME)
        .all()
    )
    excluded_ids = sorted({row.book_id for row in excluded_rows})
    if not excluded_ids:
        return []

    try:
        cdb = db.CalibreDB(init=True)
        books = (
            cdb.session.query(db.Books)
            .filter(db.Books.id.in_(excluded_ids))
            .filter(cdb.common_filters(allow_show_archived=True))
            .order_by(db.Books.sort)
            .all()
        )
        titles_by_id = {book.id: book.title for book in books}
    except Exception as e:
        log.error(f"Failed to fetch excluded Kobo book metadata: {str(e)}")
        titles_by_id = {}

    return [
        {
            "id": book_id,
            "title": titles_by_id.get(book_id, f"Book #{book_id}")
        }
        for book_id in excluded_ids
    ]


def get_kobo_allowed_books_for_dashboard(allowed_book_ids):
    if not allowed_book_ids:
        return []

    try:
        cdb = db.CalibreDB(init=True)
        books = (
            cdb.session.query(db.Books)
            .filter(db.Books.id.in_(allowed_book_ids))
            .filter(cdb.common_filters(allow_show_archived=True))
            .order_by(db.Books.sort)
            .all()
        )
    except Exception as e:
        log.error(f"Failed to fetch allowed Kobo book metadata: {str(e)}")
        return [
            {
                "id": book_id,
                "title": f"Book #{book_id}"
            }
            for book_id in sorted(allowed_book_ids)
        ]

    return [
        {
            "id": book.id,
            "title": book.title
        }
        for book in books
    ]


def get_kobo_dashboard_data(user):
    """
    Aggregiert alle relevanten Kobo-Konfigurationsdaten, Sammlungen und Warnungen für das Dashboard.
    """
    # 1. Berechtigungen und globale Flags prüfen
    has_download_role = user.role_download()
    has_kobo_token = ub.session.query(ub.RemoteAuthToken).filter_by(user_id=user.id, token_type=1).first() is not None
    is_two_column_sync = (user.kobo_only_shelves_sync == 1)
    magic_shelves_enabled = config.config_kobo_sync_magic_shelves

    # 2. Sync-erlaubte Bücher ermitteln (Lazy-Import zur Zirkularimport-Vermeidung)
    from .kobo import get_kobo_allowed_book_ids
    allowed_book_ids = get_kobo_allowed_book_ids(user.id)

    # Tatsächlich synchronisierte Buch-IDs
    synced_book_ids = {b.book_id for b in ub.session.query(ub.KoboSyncedBooks.book_id).filter_by(user_id=user.id).all()}
    excluded_books = get_kobo_excluded_books(user.id)
    excluded_book_ids = {book["id"] for book in excluded_books}
    allowed_books = [] if allowed_book_ids is None else get_kobo_allowed_books_for_dashboard(allowed_book_ids)

    # 3. Sammlungen aggregieren (kobo_display == True)
    collections = []

    # a) Normale Regale
    normal_shelves = ub.session.query(ub.Shelf).filter_by(user_id=user.id, kobo_display=True).all()
    for shelf in normal_shelves:
        book_ids = {b.book_id for b in shelf.books}
        allowed_in_shelf = book_ids if allowed_book_ids is None else book_ids.intersection(allowed_book_ids)
        synced_in_shelf = book_ids.intersection(synced_book_ids)
        blocked_in_shelf = book_ids.intersection(excluded_book_ids) if is_two_column_sync else set()

        collections.append({
            "id": shelf.id,
            "uuid": shelf.uuid,
            "name": shelf.name,
            "type": "normal",
            "kobo_sync": shelf.kobo_sync,
            "total_books": len(book_ids),
            "allowed_books": len(allowed_in_shelf),
            "blocked_books": len(blocked_in_shelf),
            "synced_books": len(synced_in_shelf)
        })

    # b) Magic Shelves
    magic_shelves = ub.session.query(ub.MagicShelf).filter_by(user_id=user.id, kobo_display=True).all()
    for shelf in magic_shelves:
        # Performante ID-Ermittlung
        book_ids = get_magic_shelf_book_ids_direct(shelf)

        allowed_in_shelf = book_ids if allowed_book_ids is None else book_ids.intersection(allowed_book_ids)
        synced_in_shelf = book_ids.intersection(synced_book_ids)
        blocked_in_shelf = book_ids.intersection(excluded_book_ids) if is_two_column_sync else set()

        collections.append({
            "id": shelf.id,
            "uuid": shelf.uuid,
            "name": shelf.name,
            "type": "magic",
            "kobo_sync": shelf.kobo_sync,
            "total_books": len(book_ids),
            "allowed_books": len(allowed_in_shelf),
            "blocked_books": len(blocked_in_shelf),
            "synced_books": len(synced_in_shelf)
        })

    # 4. Warnungen berechnen
    warnings = []

    if not has_download_role:
        warnings.append({
            "type": "danger",
            "code": "MISSING_DOWNLOAD_ROLE",
            "message": "Benutzer hat keine Download-Berechtigung. Kobo-Sync wird fehlschlagen."
        })

    if not is_two_column_sync:
        warnings.append({
            "type": "warning",
            "code": "FULL_SYNC_MODE",
            "message": "Vollständige Synchronisation ist aktiv. Alle Bücher der Bibliothek werden auf den Kobo übertragen."
        })

    for col in collections:
        # Prüfen auf Magic-Shelf Deaktivierung
        if col["type"] == "magic" and not magic_shelves_enabled:
            warnings.append({
                "type": "warning",
                "code": "MAGIC_SHELVES_DISABLED",
                "message": f"Automatische Sammlung '{col['name']}' wird nicht synchronisiert, da Kobo-Magic-Shelves global deaktiviert sind."
            })

        # 1000er Cap bei Magic Shelves
        if col["type"] == "magic" and col["total_books"] > 1000:
            warnings.append({
                "type": "info",
                "code": "MAGIC_SHELF_LIMIT",
                "message": f"Kollektion '{col['name']}' enthält {col['total_books']} Bücher. Kobo synchronisiert maximal 1000."
            })

        # Leere Sammlung (keine Bücher zugeordnet) -> "leer/prüfen" (Info statt danger)
        if col["total_books"] == 0:
            warnings.append({
                "type": "info",
                "code": "EMPTY_COLLECTION",
                "message": f"Sammlung '{col['name']}' ist leer (keine Bücher zugeordnet)."
            })

        elif is_two_column_sync and col["blocked_books"] > 0:
            warnings.append({
                "type": "warning",
                "code": "BLOCKED_BOOKS_IN_COLLECTION",
                "message": f"In Sammlung '{col['name']}' sind {col['blocked_books']} Bücher als Nicht auf Kobo markiert."
            })

        # Lokale Bücher vorhanden, aber keins davon sync-berechtigt (nur im Zwei-Säulen-Modus relevant)
        unselected_books = col["total_books"] - col["allowed_books"] - col["blocked_books"]
        if is_two_column_sync and col["total_books"] > 0 and col["allowed_books"] == 0 and unselected_books > 0:
            warnings.append({
                "type": "danger",
                "code": "NO_ALLOWED_BOOKS",
                "message": f"Sammlung '{col['name']}' enthält {col['total_books']} Bücher, aber keines davon ist für Kobo ausgewählt."
            })

        # Einige Bücher der Kollektion sind nicht sync-berechtigt (nur im Zwei-Säulen-Modus relevant)
        elif is_two_column_sync and unselected_books > 0:
            warnings.append({
                "type": "warning",
                "code": "SOME_BOOKS_NOT_ALLOWED",
                "message": f"In Sammlung '{col['name']}' sind {unselected_books} Bücher nicht für Kobo ausgewählt."
            })

    return {
        "is_two_column_sync": is_two_column_sync,
        "has_kobo_token": has_kobo_token,
        "collections": collections,
        "warnings": warnings,
        "allowed_books": allowed_books,
        "excluded_books": excluded_books,
        "allowed_book_count": 0 if allowed_book_ids is None else len(allowed_book_ids),
        "excluded_book_count": len(excluded_books),
        "synced_book_count": len(synced_book_ids)
    }
