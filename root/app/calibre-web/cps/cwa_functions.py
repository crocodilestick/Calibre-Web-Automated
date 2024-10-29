from flask import Blueprint, redirect, flash, url_for, request, Response
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
library_refresh = Blueprint('library_refresh', __name__)
convert_library = Blueprint('convert_library', __name__)
cwa_history = Blueprint('cwa_history', __name__)
cwa_check_status = Blueprint('cwa_check_status', __name__)
cwa_settings = Blueprint('cwa_settings', __name__)

# log = logger.create()


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
        if request.form['submit_button'] == "Submit":
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
        elif request.form['submit_button'] == "Apply Default Settings":
            cwa_db = CWA_DB()
            cwa_db.set_default_settings(force=True)
            cwa_settings = cwa_db.get_cwa_settings()

    elif request.method == 'GET':
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.cwa_settings

    return render_title_template("cwa_settings.html", title=_("CWA Settings"), page="cwa-settings",
                                    cwa_settings=cwa_settings)


@cwa_history.route("/cwa-history-show", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_history_show():
    cwa_db = CWA_DB()
    data, table_headers = cwa_db.enforce_show(paths=False, verbose=False, web_ui=True)
    data_p, table_headers_p = cwa_db.enforce_show(paths=True, verbose=False, web_ui=True)
    data_i, table_headers_i = cwa_db.get_import_history(verbose=False)
    data_c, table_headers_c = cwa_db.get_conversion_history(verbose=False)

    return render_title_template("cwa_history.html", title=_("Calibre-Web Automated Stats"), page="cwa-history",
                                    table_headers=table_headers, data=data,
                                    table_headers_p=table_headers_p, data_p=data_p,
                                    data_i=data_i, table_headers_i=table_headers_i,
                                    data_c=data_c, table_headers_c=table_headers_c)


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

from time import sleep

def flask_logger():
    subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/convert-library.py'])
    with open("/config/convert-library.log", 'r') as log_info:
        while True:
            data = log_info.read()
            yield data.encode()
            sleep(1)
            if "FIN" in data:
                break

@convert_library.route("/cwa-library-convert", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_library_convert():
    return Response(flask_logger(), mimetype="text/plain", content_type="text/event-stream")

# @convert_library.route("/convert-progress", methods=["GET"])
# @login_required_if_no_ano
# @admin_required
# def convert_progress():
#     # return render_title_template("cwa_convert_library.html", title=_("CWA Convert Library"), page="cwa-library-convert")
# def convert_progress():
#     return '''
#     <!DOCTYPE html>
#     <html lang="en">
#     <head>
#         <meta charset="UTF-8">
#         <meta name="viewport" content="width=device-width, initial-scale=1.0">
#         <title>Log Viewer</title>
#         <style>
#             body {
#                 font-family: Arial, sans-serif;
#                 background-color: #f4f4f4;
#                 margin: 0;
#                 padding: 20px;
#             }
#             #log {
#                 background: #fff;
#                 border: 1px solid #ccc;
#                 padding: 10px;
#                 height: 400px;
#                 overflow-y: scroll;
#                 font-family: monospace;
#                 white-space: pre-wrap;
#             }
#             .log-entry {
#                 margin-bottom: 5px;
#             }
#             .info {
#                 color: blue;
#             }
#             .warning {
#                 color: orange;
#             }
#             .error {
#                 color: red;
#             }
#         </style>
#     </head>
#     <body>
#         <h1>Log Viewer</h1>
#         <div id="log"></div>
#         <script>
#             const eventSource = new EventSource("/logs");
            
#             eventSource.onopen = function(event) {
#                 console.log("Connection to server opened.");
#             };

#             eventSource.onmessage = function(event) {
#                 console.log("Received message:", event.data); // Log incoming messages for debugging
#                 const logEntry = document.createElement("div");
#                 logEntry.className = "log-entry";
                
#                 if (event.data.includes("ERROR")) {
#                     logEntry.classList.add("error");
#                 } else if (event.data.includes("WARNING")) {
#                     logEntry.classList.add("warning");
#                 } else {
#                     logEntry.classList.add("info");
#                 }

#                 logEntry.textContent = event.data;
#                 document.getElementById("log").appendChild(logEntry);
#                 document.getElementById("log").scrollTop = document.getElementById("log").scrollHeight;
#             };

#             eventSource.onerror = function(event) {
#                 console.error("EventSource failed:", event);
#             };
#         </script>
#     </body>
#     </html>
#     '''