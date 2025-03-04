# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2018-2020 OzzieIsaacs
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

from flask import render_template, g, abort, request, flash
from flask_babel import gettext as _
from werkzeug.local import LocalProxy
from .cw_login import current_user
from sqlalchemy.sql.expression import or_

from . import config, constants, logger, ub
from .ub import User

# CWA specific imports
import requests
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
    g.shelves_access = ub.session.query(ub.Shelf).filter(
        or_(ub.Shelf.is_public == 1, ub.Shelf.user_id == current_user.id)).order_by(ub.Shelf.name).all()

    return sidebar, simple

# Checks if an update for CWA is available, returning True if yes
def cwa_update_available() -> tuple[bool, str, str]:
    with open("/app/CWA_RELEASE", 'r') as f:
        current_version = f.read().strip()
    response = requests.get("https://api.github.com/repos/crocodilestick/calibre-web-automated/releases/latest")
    tag_name = response.json().get('tag_name', current_version)
    return (tag_name != current_version), current_version, tag_name

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
            message = f"⚡🚨 CWA UPDATE AVAILABLE! 🚨⚡ Current - {current_version} | Newest - {tag_name} | To update, just re-pull the image! This message will only display once per day |"
            flash(_(message), category="cwa_update")
            print(f"[cwa-update-notification-service] {message}", flush=True)

        with open('/app/cwa_update_notice', 'w') as f:
            f.write(current_date)
        return
    else:
        return


# Returns the template for rendering and includes the instance name
def render_title_template(*args, **kwargs):
    sidebar, simple = get_sidebar_config(kwargs)
    if current_user.role_admin():
        try:
            cwa_update_notification()
        except Exception as e:
            print(f"[cwa-update-notification-service] The following error occurred when checking for available updates:\n{e}", flush=True)
    try:
        return render_template(instance=config.config_calibre_web_title, sidebar=sidebar, simple=simple,
                               accept=config.config_upload_formats.split(','),
                               *args, **kwargs)
    except PermissionError:
        log.error("No permission to access {} file.".format(args[0]))
        abort(403)
