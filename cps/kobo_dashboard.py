# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from . import db, ub, config, logger
from .magic_shelf import build_query_from_rules

log = logger.create()

def get_magic_shelf_book_ids_direct(shelf):
    """
    Ermittelt die IDs der Bücher eines Magic Shelves direkt über die Calibre-Datenbank.
    Umgeht den Cache, current_user-Abfragen und die Instanziierung von Buchobjekten.
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
    
    # 3. Sammlungen aggregieren (kobo_display == True)
    collections = []
    
    # a) Normale Regale
    normal_shelves = ub.session.query(ub.Shelf).filter_by(user_id=user.id, kobo_display=True).all()
    for shelf in normal_shelves:
        book_ids = {b.book_id for b in shelf.books}
        allowed_in_shelf = book_ids if allowed_book_ids is None else book_ids.intersection(allowed_book_ids)
        synced_in_shelf = book_ids.intersection(synced_book_ids)
        
        collections.append({
            "id": shelf.id,
            "uuid": shelf.uuid,
            "name": shelf.name,
            "type": "normal",
            "kobo_sync": shelf.kobo_sync,
            "total_books": len(book_ids),
            "allowed_books": len(allowed_in_shelf),
            "synced_books": len(synced_in_shelf)
        })
        
    # b) Magic Shelves
    magic_shelves = ub.session.query(ub.MagicShelf).filter_by(user_id=user.id, kobo_display=True).all()
    for shelf in magic_shelves:
        # Performante ID-Ermittlung
        book_ids = get_magic_shelf_book_ids_direct(shelf)
        
        allowed_in_shelf = book_ids if allowed_book_ids is None else book_ids.intersection(allowed_book_ids)
        synced_in_shelf = book_ids.intersection(synced_book_ids)
        
        collections.append({
            "id": shelf.id,
            "uuid": shelf.uuid,
            "name": shelf.name,
            "type": "magic",
            "kobo_sync": shelf.kobo_sync,
            "total_books": len(book_ids),
            "allowed_books": len(allowed_in_shelf),
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
            
        # Lokale Bücher vorhanden, aber keins davon sync-berechtigt (nur im Zwei-Säulen-Modus relevant)
        elif is_two_column_sync and col["allowed_books"] == 0:
            warnings.append({
                "type": "danger",
                "code": "NO_ALLOWED_BOOKS",
                "message": f"Sammlung '{col['name']}' enthält {col['total_books']} Bücher, aber keines davon darf auf den Kobo."
            })
            
        # Einige Bücher der Kollektion sind nicht sync-berechtigt (nur im Zwei-Säulen-Modus relevant)
        elif is_two_column_sync and col["allowed_books"] < col["total_books"]:
            warnings.append({
                "type": "warning",
                "code": "SOME_BOOKS_NOT_ALLOWED",
                "message": f"In Sammlung '{col['name']}' sind {col['total_books'] - col['allowed_books']} Bücher nicht für den Kobo freigegeben."
            })
            
    return {
        "is_two_column_sync": is_two_column_sync,
        "has_kobo_token": has_kobo_token,
        "collections": collections,
        "warnings": warnings,
        "allowed_book_count": 0 if allowed_book_ids is None else len(allowed_book_ids),
        "synced_book_count": len(synced_book_ids)
    }
