# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import render_template, g, abort, request, flash, current_app
from flask_babel import gettext as _
from flask_babel import get_locale
import polib
from werkzeug.local import LocalProxy
from .cw_login import current_user
from sqlalchemy.sql.expression import or_

from . import config, constants, logger, ub
from .ub import User

# CWA specific imports
from datetime import datetime
import os.path

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB


log = logger.create()

def get_sidebar_config(kwargs=None):
    kwargs = kwargs or []
    simple = bool([e for e in ['kindle', 'tolino', "kobo", "bookeen"]
                   if (e in request.headers.get('User-Agent', "").lower())])
    if 'content' in kwargs:
        content = kwargs['content']
        content = isinstance(content, (User, LocalProxy)) and not content.role_anonymous()
    else:
        content = 'conf' in kwargs
    sidebar = list()
    sidebar.append({"glyph": "glyphicon-book", "text": _('Books'), "link": 'web.index', "id": "new",
                    "visibility": constants.SIDEBAR_RECENT, 'public': True, "page": "root",
                    "show_text": _('Show recent books'), "config_show":False})
    sidebar.append({"glyph": "glyphicon-fire", "text": _('Hot Books'), "link": 'web.books_list', "id": "hot",
                    "visibility": constants.SIDEBAR_HOT, 'public': True, "page": "hot",
                    "show_text": _('Show Hot Books'), "config_show": True})
    if current_user.role_admin():
        sidebar.append({"glyph": "glyphicon-download", "text": _('Downloaded Books'), "link": 'web.download_list',
                        "id": "download", "visibility": constants.SIDEBAR_DOWNLOAD, 'public': (not current_user.is_anonymous),
                        "page": "download", "show_text": _('Show Downloaded Books'),
                        "config_show": content})
    else:
        sidebar.append({"glyph": "glyphicon-download", "text": _('Downloaded Books'), "link": 'web.books_list',
                        "id": "download", "visibility": constants.SIDEBAR_DOWNLOAD, 'public': (not current_user.is_anonymous),
                        "page": "download", "show_text": _('Show Downloaded Books'),
                        "config_show": content})
    sidebar.append(
        {"glyph": "glyphicon-star", "text": _('Top Rated Books'), "link": 'web.books_list', "id": "rated",
         "visibility": constants.SIDEBAR_BEST_RATED, 'public': True, "page": "rated",
         "show_text": _('Show Top Rated Books'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-eye-open", "text": _('Read Books'), "link": 'web.books_list', "id": "read",
                    "visibility": constants.SIDEBAR_READ_AND_UNREAD, 'public': (not current_user.is_anonymous),
                    "page": "read", "show_text": _('Show Read and Unread'), "config_show": content})
    sidebar.append(
        {"glyph": "glyphicon-eye-close", "text": _('Unread Books'), "link": 'web.books_list', "id": "unread",
         "visibility": constants.SIDEBAR_READ_AND_UNREAD, 'public': (not current_user.is_anonymous), "page": "unread",
         "show_text": _('Show unread'), "config_show": False})
    sidebar.append({"glyph": "glyphicon-random", "text": _('Discover'), "link": 'web.books_list', "id": "rand",
                    "visibility": constants.SIDEBAR_RANDOM, 'public': True, "page": "discover",
                    "show_text": _('Show Random Books'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-inbox", "text": _('Categories'), "link": 'web.category_list', "id": "cat",
                    "visibility": constants.SIDEBAR_CATEGORY, 'public': True, "page": "category",
                    "show_text": _('Show Category Section'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-bookmark", "text": _('Series'), "link": 'web.series_list', "id": "serie",
                    "visibility": constants.SIDEBAR_SERIES, 'public': True, "page": "series",
                    "show_text": _('Show Series Section'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-user", "text": _('Authors'), "link": 'web.author_list', "id": "author",
                    "visibility": constants.SIDEBAR_AUTHOR, 'public': True, "page": "author",
                    "show_text": _('Show Author Section'), "config_show": True})
    sidebar.append(
        {"glyph": "glyphicon-text-size", "text": _('Publishers'), "link": 'web.publisher_list', "id": "publisher",
         "visibility": constants.SIDEBAR_PUBLISHER, 'public': True, "page": "publisher",
         "show_text": _('Show Publisher Section'), "config_show":True})
    sidebar.append({"glyph": "glyphicon-flag", "text": _('Languages'), "link": 'web.language_overview', "id": "lang",
                    "visibility": constants.SIDEBAR_LANGUAGE, 'public': (current_user.filter_language() == 'all'),
                    "page": "language",
                    "show_text": _('Show Language Section'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-star-empty", "text": _('Ratings'), "link": 'web.ratings_list', "id": "rate",
                    "visibility": constants.SIDEBAR_RATING, 'public': True,
                    "page": "rating", "show_text": _('Show Ratings Section'), "config_show": True})
    sidebar.append({"glyph": "glyphicon-file", "text": _('File formats'), "link": 'web.formats_list', "id": "format",
                    "visibility": constants.SIDEBAR_FORMAT, 'public': True,
                    "page": "format", "show_text": _('Show File Formats Section'), "config_show": True})
    sidebar.append(
        {"glyph": "glyphicon-trash", "text": _('Archived Books'), "link": 'web.books_list', "id": "archived",
         "visibility": constants.SIDEBAR_ARCHIVED, 'public': (not current_user.is_anonymous), "page": "archived",
         "show_text": _('Show Archived Books'), "config_show": content})
    if not simple:
        sidebar.append(
            {"glyph": "glyphicon-th-list", "text": _('Books List'), "link": 'web.books_table', "id": "list",
             "visibility": constants.SIDEBAR_LIST, 'public': (not current_user.is_anonymous), "page": "list",
             "show_text": _('Show Books List'), "config_show": content})
    if current_user.role_admin() or current_user.role_edit():
        sidebar.append(
            {"glyph": "glyphicon-copy", "text": _('Duplicates'), "link": 'duplicates.show_duplicates', "id": "duplicates",
             "visibility": constants.SIDEBAR_DUPLICATES, 'public': (not current_user.is_anonymous), "page": "duplicates",
             "show_text": _('Show Duplicate Books'), "config_show": content})
    g.shelves_access = ub.session.query(ub.Shelf).filter(
        or_(ub.Shelf.is_public == 1, ub.Shelf.user_id == current_user.id)).order_by(ub.Shelf.name).all()

    return sidebar, simple

# Checks if an update for CWA is available, returning True if yes
def cwa_update_available() -> tuple[bool, str, str]:
    try:
        current_version = constants.INSTALLED_VERSION
        tag_name = constants.STABLE_VERSION

        if current_version == "V0.0.0" or tag_name == "V0.0.0":
            return False, "0.0.0", "0.0.0"

        return (tag_name != current_version), current_version, tag_name
    except Exception as e:
        print(f"[cwa-update-notification-service] Error checking for CWA updates: {e}", flush=True)
        return False, "0.0.0", "0.0.0"

# Gets the date the last cwa update notification was displayed
def get_cwa_last_notification() -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    if not os.path.isfile('/app/cwa_update_notice'):
        with open('/app/cwa_update_notice', 'w') as f:
            f.write(current_date)
        return "0001-01-01"
    else:
        with open('/app/cwa_update_notice', 'r') as f:
            last_notification = f.read()
    return last_notification

# Displays a notification to the user that an update for CWA is available, no matter which page they're on
# Currently set to only display once per calender day
def cwa_update_notification() -> None:
    db = CWA_DB()
    if db.cwa_settings['cwa_update_notifications']:
        current_date = datetime.now().strftime("%Y-%m-%d")
        cwa_last_notification = get_cwa_last_notification()
        
        if cwa_last_notification == current_date:
            return

        update_available, current_version, tag_name = cwa_update_available()
        if update_available:
            message = _(f"⚡🚨 CWA UPDATE AVAILABLE! 🚨⚡ Current - {current_version} | Newest - {tag_name} | To update, just re-pull the image! This message will only display once per day |")
            flash(_(message), category="cwa_update")
            print(f"[cwa-update-notification-service] {message}", flush=True)

        with open('/app/cwa_update_notice', 'w') as f:
            f.write(current_date)
        return
    else:
        return

# Notify users once about theme migration to caliBlur
def theme_migration_notification() -> None:
    notice_file = '/app/theme_migration_notice'
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # Check if notification already shown today
    if os.path.isfile(notice_file):
        try:
            with open(notice_file, 'r') as f:
                last_notification = f.read().strip()
                if last_notification == current_date:
                    return
        except Exception:
            pass
    
    # Show notification
    message = _("ℹ️ Your theme has been updated to caliBlur (Dark). Theme switching is temporarily disabled while we develop a new frontend for v5.0.0.")
    flash(message, category="theme_migration")
    
    # Mark as shown today
    try:
        with open(notice_file, 'w') as f:
            f.write(current_date)
    except Exception as e:
        print(f"[theme-migration-notification] Error writing notice file: {e}", flush=True)


# Checks if translations are missing for the current language
def translations_missing_notification() -> None:
    db = CWA_DB()
    if db.cwa_settings['contribute_translations_notifications']:
        lang = str(get_locale())
        # Skip English as it is the default language
        if lang == 'en':
            return
        po_path = f"cps/translations/{lang}/LC_MESSAGES/messages.po"
        current_date = datetime.now().strftime("%Y-%m-%d")
        notice_file = f"/app/cwa_translation_notice_{lang}"
        missing_count = 0
        if os.path.isfile(po_path):
            try:
                po = polib.pofile(po_path)
                missing_count = sum(1 for entry in po if not entry.msgstr.strip())
            except Exception as e:
                print(f"[translation-notification-service] Error reading {po_path}: {e}", flush=True)
        if missing_count > 0:
            if not os.path.isfile(notice_file):
                with open(notice_file, 'w') as f:
                    f.write(current_date)
                last_notification = "0001-01-01"
            else:
                with open(notice_file, 'r') as f:
                    last_notification = f.read().strip()
            if last_notification != current_date:
                message = _(f"🌐 Help improve CWA's {constants.LANGUAGE_NAMES.get(lang, lang)} translations! {missing_count} strings in your language need translation. ")
                flash(message, category="translation_missing")
                print(f"[translation-notification-service] {message}", flush=True)
                with open(notice_file, 'w') as f:
                    f.write(current_date)
        return
    else:
        return

# Returns the template for rendering and includes the instance name
def render_title_template(*args, **kwargs):
    sidebar, simple = get_sidebar_config(kwargs)
    try:
        magic_shelf_routes = {
            "render": 'web.render_magic_shelf' in current_app.view_functions,
            "create": 'web.create_magic_shelf' in current_app.view_functions,
        }
    except Exception:
        magic_shelf_routes = {"render": False, "create": False}
    if current_user.role_admin():
        try:
            cwa_update_notification()
        except Exception as e:
            print(f"[cwa-update-notification-service] The following error occurred when checking for available updates:\n{e}", flush=True)
    # Notify users about theme migration (once per day)
    try:
        theme_migration_notification()
    except Exception as e:
        print(f"[theme-migration-notification] Error showing theme migration notification: {e}", flush=True)
    # Notify any user if translations are missing for their language
    try:
        translations_missing_notification()
    except Exception as e:
        print(f"[translation-notification-service] The following error occurred when checking for missing translations:\n{e}", flush=True)
    duplicate_notification = {
        "enabled": False,
        "count": 0,
        "preview": [],
        "cached": False,
        "stale": False,
    }
    try:
        if current_user.is_authenticated and (current_user.role_admin() or current_user.role_edit()):
            cwa_db = CWA_DB()
            detection_enabled = cwa_db.cwa_settings.get('duplicate_detection_enabled', 1)
            notifications_enabled = bool(cwa_db.cwa_settings.get('duplicate_notifications_enabled', 1))
            if detection_enabled:
                cache_data = cwa_db.get_duplicate_cache()
                if cache_data and cache_data.get('duplicate_groups') is not None:
                    duplicate_groups = cache_data.get('duplicate_groups') or []
                    try:
                        dismissed_groups = ub.session.query(ub.DismissedDuplicateGroup.group_hash)\
                            .filter(ub.DismissedDuplicateGroup.user_id == current_user.id)\
                            .all()
                        dismissed_hashes = {row[0] for row in dismissed_groups}
                        if dismissed_hashes:
                            duplicate_groups = [
                                group for group in duplicate_groups
                                if group.get('group_hash') not in dismissed_hashes
                            ]
                    except Exception:
                        pass

                    preview = []
                    for group in duplicate_groups[:3]:
                        preview.append({
                            'title': group.get('title', ''),
                            'author': group.get('author', ''),
                            'count': group.get('count', 0),
                            'hash': group.get('group_hash', '')
                        })

                    duplicate_notification = {
                        "enabled": notifications_enabled,
                        "count": len(duplicate_groups),
                        "preview": preview,
                        "cached": True,
                        "stale": bool(cache_data.get('scan_pending')),
                    }
                else:
                    duplicate_notification = {
                        "enabled": notifications_enabled,
                        "count": 0,
                        "preview": [],
                        "cached": False,
                        "stale": True,
                    }
    except Exception as e:
        log.debug("[cwa-duplicates] Failed to build duplicate notification context: %s", str(e))
    try:
        return render_template(instance=config.config_calibre_web_title, sidebar=sidebar, simple=simple,
                       accept=config.config_upload_formats.split(','),
                       magic_shelf_routes=magic_shelf_routes,
                       duplicate_notification=duplicate_notification,
                       *args, **kwargs)
    except PermissionError:
        log.error("No permission to access {} file.".format(args[0]))
        abort(403)
