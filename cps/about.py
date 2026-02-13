# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
import platform
import sqlite3
import importlib
from collections import OrderedDict

import flask
from flask import redirect, url_for
from flask_babel import gettext as _

from . import db, calibre_db, converter, uploader, dep_check
from .render_template import render_title_template
from .usermanagement import user_login_required


about = flask.Blueprint('about', __name__)

modules = dict()
req = dep_check.load_dependencies(False)
opt = dep_check.load_dependencies(True)
for i in (req + opt):
    modules[i[1]] = i[0]
modules['Jinja2'] = importlib.metadata.version("jinja2")
if sys.version_info < (3, 12):
    modules['pySqlite'] = sqlite3.version
modules['SQLite'] = sqlite3.sqlite_version
sorted_modules = OrderedDict((sorted(modules.items(), key=lambda x: x[0].casefold())))


def collect_stats():
    try:
        with open("/app/CWA_RELEASE", "r") as f:
            cwa_version = f.read()
    except Exception:
        cwa_version = "Unknown"

    _VERSIONS = {'Calibre-Web Automated': cwa_version}
    _VERSIONS.update(OrderedDict(
        Python=sys.version,
        Platform='{0[0]} {0[2]} {0[3]} {0[4]} {0[5]}'.format(platform.uname()),
    ))
    _VERSIONS['Unrar'] = converter.get_unrar_version()
    _VERSIONS['Ebook converter'] = converter.get_calibre_version()
    _VERSIONS['Kepubify'] = converter.get_kepubify_version()
    _VERSIONS.update(uploader.get_magick_version())
    _VERSIONS.update(sorted_modules)
    return _VERSIONS


@about.route("/package-versions")
@user_login_required
def package_versions():
    counter = calibre_db.session.query(db.Books).count()
    authors = calibre_db.session.query(db.Authors).count()
    categories = calibre_db.session.query(db.Tags).count()
    series = calibre_db.session.query(db.Series).count()
    return render_title_template('stats.html', bookcounter=counter, authorcounter=authors, versions=collect_stats(),
                                 categorycounter=categories, seriecounter=series, title=_("Statistics"), page="stat")


@about.route("/stats")
@user_login_required
def stats():
    return redirect(url_for('cwa_stats.cwa_stats_show'), code=301)
