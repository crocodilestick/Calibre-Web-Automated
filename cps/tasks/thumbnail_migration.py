# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import shutil
from .. import logger, ub, fs, config_sql
from ..constants import CACHE_TYPE_THUMBNAILS

log = logger.create()

MIGRATION_VERSION_KEY = "thumbnail_flat_structure_migration"
MIGRATION_VERSION = "v1.0"

def get_migration_status():
    """Check if the thumbnail migration has already been completed."""
    try:
        session = ub.get_new_session_instance()
        try:
            # Check if migration marker exists in settings
            setting = session.query(ub.Settings).filter(
                ub.Settings.mail_server == MIGRATION_VERSION_KEY
            ).first()
            return setting.mail_server_type == MIGRATION_VERSION if setting else False
        finally:
            session.close()
    except Exception:
        return False

def set_migration_completed():
    """Mark the thumbnail migration as completed."""
    try:
        session = ub.get_new_session_instance()
        try:
            # Store migration marker in settings table
            setting = session.query(ub.Settings).filter(
                ub.Settings.mail_server == MIGRATION_VERSION_KEY
            ).first()
            
            if not setting:
                setting = ub.Settings()
                setting.mail_server = MIGRATION_VERSION_KEY
                session.add(setting)
            
            setting.mail_server_type = MIGRATION_VERSION
            session.commit()
        except Exception as ex:
            log.error(f"Failed to mark migration as completed: {ex}")
            session.rollback()
        finally:
            session.close()
    except Exception as ex:
        log.error(f"Failed to access database for migration marker: {ex}")

def migrate_thumbnail_structure():
    """
    One-time migration for existing CWA installations to move from
    subdirectory-based thumbnail storage to flat directory structure.
    
    This will:
    1. Clear all existing thumbnail database entries
    2. Remove old subdirectory structure 
    3. Trigger regeneration of all thumbnails in new format
    """
    try:
        cache = fs.FileSystem()
        thumbnails_dir = cache.get_cache_dir(CACHE_TYPE_THUMBNAILS)
        
        # Check if migration is needed (look for old subdirectories)
        migration_needed = False
        subdirs_found = []
        
        if os.path.exists(thumbnails_dir):
            for item in os.listdir(thumbnails_dir):
                item_path = os.path.join(thumbnails_dir, item)
                # Look for hex subdirectories (00, 01, ..., ff, bo, etc.)
                if (os.path.isdir(item_path) and 
                    len(item) == 2 and 
                    item not in ['.', '..']):
                    subdirs_found.append(item)
                    migration_needed = True
        
        if not migration_needed:
            log.info("Thumbnail migration: No old subdirectories found, skipping migration")
            return
            
        log.info(f"Thumbnail migration: Found {len(subdirs_found)} old subdirectories with legacy thumbnails")
        log.info("Thumbnail migration: Using lazy migration strategy - legacy thumbnails will be replaced on-demand")
        log.info("Thumbnail migration: Old subdirectories will be cleaned up automatically as thumbnails regenerate")
        
        # Note: We don't delete thumbnails immediately anymore.
        # The TaskGenerateCoverThumbnails.create_book_cover_thumbnails() method already
        # detects legacy thumbnails (via legacy_naming check) and migrates them on-demand.
        # This prevents mass regeneration on first page load after update.
        
        # Mark migration as completed so this only runs once
        set_migration_completed()
        
    except Exception as ex:
        log.error(f"Thumbnail migration: Failed with error: {ex}")

def check_and_migrate_thumbnails():
    """
    Check if thumbnail migration is needed and run it if so.
    This should be called during application startup.
    """
    try:
        # Skip if already migrated
        if get_migration_status():
            log.debug("Thumbnail migration: Already completed, skipping")
            return
            
        migrate_thumbnail_structure()
    except Exception as ex:
        log.error(f"Thumbnail migration check failed: {ex}")