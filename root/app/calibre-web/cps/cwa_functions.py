from flask import Blueprint, redirect, flash, url_for
from flask_babel import gettext as _

from . import logger, config, constants
from .usermanagement import login_required_if_no_ano
from .admin import admin_required

import os

switch_theme = Blueprint('switch_theme', __name__)
library_refresh = Blueprint('library_refresh', __name__)
convert_library = Blueprint('convert_library', __name__)
cwa_history = Blueprint('cwa_history', __name__)
cwa_check_monitoring = Blueprint('cwa_check_monitoring', __name__)

log = logger.create()

import sqlite3

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


@library_refresh.route("/cwa-library-refresh", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_library_refresh():
    flash(_("Library Refresh: Initialising Book Ingest System, please wait..."), category="cwa_refresh")
    return_code = os.system('python3 /app/calibre-web-automated/scripts/new-book-processor.py "/cwa-book-ingest"')
    return_val = os.WEXITSTATUS(return_code)

    if return_val > 100:
        flash(_(f"Library Refresh: Ingest process complete. {return_val - 100} new books ingested."), category="cwa_refresh")
    elif return_val == 2:
        flash(_("Library Refersh: The book ingest service is already running, please wait until it has finished before trying again."), category="cwa_refresh")
#    elif return_val == 0:
#        flash(_("Manually starting ingest proces"), category="info")
    elif return_val == 0:
        flash(_("Library Refresh: Ingest process complete. No new books ingested."), category="cwa_refresh")
    else:
        flash(_("Library Refresh: An unexpected error occured, check the logs."), category="cwa_refresh")

    return redirect("/", code=302)

# Coming Soon
@convert_library.route("/cwa-library-convert", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_library_convert():
    flash(_("Library Convert: Running, please wait..."), category="refresh-cwa")
    os.system('python3 /app/calibre-web-automated/scripts/convert-library.py -k')
    return redirect(url_for('admin.view_logfile'))

# Coming Soon
@cwa_history.route("/cwa-history-show", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_history_show():
    ...

# Coming Soon
@cwa_check_monitoring.route("/cwa-check-monitoring", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_check_monitoring_services():
    ...
