from flask import Blueprint, redirect, flash, url_for, request
from flask_babel import gettext as _

from . import logger, config, constants, csrf
from .usermanagement import login_required_if_no_ano
from .admin import admin_required
from .render_template import render_title_template

import subprocess
import sqlite3

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

switch_theme = Blueprint('switch_theme', __name__)
library_ingest = Blueprint('library_ingest', __name__)
convert_library = Blueprint('convert_library', __name__)
cwa_history = Blueprint('cwa_history', __name__)
cwa_check_status = Blueprint('cwa_check_status', __name__)
cwa_settings = Blueprint('cwa_settings', __name__)

log = logger.create()


@switch_theme.route("/cwa-switch-theme", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_switch_theme():
    con = sqlite3.connect("/config/app.db")
    cur = con.cursor()
    current_theme = cur.execute('SELECT config_theme FROM settings;').fetchone()[0]

    if current_theme == 1:
        new_theme = 0
    else:
        new_theme = 1

    to_save = {"config_theme":new_theme}

    config.set_from_dictionary(to_save, "config_theme", int)
    config.config_default_role = constants.selected_roles(to_save)
    config.config_default_role &= ~constants.ROLE_ANONYMOUS

    config.config_default_show = sum(int(k[5:]) for k in to_save if k.startswith('show_'))
    if "Show_detail_random" in to_save:
        config.config_default_show |= constants.DETAIL_RANDOM

    config.save()
    return redirect("/", code=302)


@library_ingest.route("/cwa-library-ingest", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_library_ingest():
    flash(_("Library Refresh: Initialising Book Ingest System, please wait..."), category="cwa_refresh")
    result = subprocess.run(['python3', '/app/calibre-web-automated/scripts/ingest-processor.py', '/cwa-book-ingest'])
    return_code = result.returncode

    # if return_code == 100:
    #     flash(_(f"Library Refresh: Ingest process complete. New books ingested."), category="cwa_refresh")
    if return_code == 2:
        flash(_("Library Refresh: The book ingest service is already running, please wait until it has finished before trying again."), category="cwa_refresh")
    elif return_code == 0:
        flash(_("Library Refresh: Library refreshed & ingest process complete."), category="cwa_refresh")
    else:
        flash(_("Library Refresh: An unexpected error occurred, check the logs."), category="cwa_refresh")

    return redirect("/", code=302)


@csrf.exempt
@cwa_settings.route("/cwa-settings", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def set_cwa_settings():
    if request.method == 'POST':

        settings = ["auto_backup_imports",
                    "auto_backup_conversions",
                    "auto_zip_backups",
                    "cwa_update_notifications",
                    "robotic_reading"]

        result = {}
        for setting in settings:
            value = request.form.get(setting)
            if value == None:
                value = 0
            else:
                value = 1
            result |= {setting:value}

        cwa_db = CWA_DB()
        cwa_db.update_cwa_settings(result)
        cwa_settings = cwa_db.get_cwa_settings()

    elif request.method == 'GET':
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.cwa_settings

    return render_title_template("cwa_settings.html", title=_("CWA Settings"), page="cwa-settings",
                                    cwa_settings=cwa_settings)

# Coming Soon
@convert_library.route("/cwa-library-convert", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_library_convert():
    flash(_("Library Convert: Running, please wait..."), category="refresh-cwa")
    subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/convert-library.py'])
    return redirect(url_for('admin.view_logfile'))

# Coming Soon
@cwa_history.route("/cwa-history-show", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_history_show():
    ...


@cwa_check_status.route("/cwa-check-monitoring", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_flash_status():
    result = subprocess.run(['/app/calibre-web-automated/scripts/check-cwa-services.sh'])
    services_status = result.returncode

    match services_status:
        case 0:
            flash(_("✅ All Monitoring Services are running as intended! 👍"), category="cwa_refresh")
        case 1:
            flash(_("🔴 The Ingest Service is running but the Metadata Change Detector is not"), category="cwa_refresh")
        case 2:
            flash(_("🔴 The Metadata Change Detector is running but the Ingest Service is not"), category="cwa_refresh")
        case 3:
            flash(_("⛔ Neither the Ingest Service or the Metadata Change Detector are running"), category="cwa_refresh")
        case _:
            flash(_("An Error has occurred"), category="cwa_refresh")

    return redirect(url_for('admin.admin'))