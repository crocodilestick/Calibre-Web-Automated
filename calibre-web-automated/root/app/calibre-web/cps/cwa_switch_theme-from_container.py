from flask import Blueprint, redirect
from flask_babel import gettext as _

from . import logger, config, constants
from .usermanagement import login_required_if_no_ano

switch_theme = Blueprint('switch_theme', __name__)

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