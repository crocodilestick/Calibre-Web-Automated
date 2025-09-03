# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint, redirect, flash, url_for, request, send_from_directory, abort, jsonify, current_app
from flask_babel import gettext as _, lazy_gettext as _l

from . import logger, config, constants, csrf
from .usermanagement import login_required_if_no_ano, user_login_required
from .admin import admin_required
from .render_template import render_title_template
from .cw_login import login_user, logout_user, current_user

import subprocess
import sqlite3
from pathlib import Path
from time import sleep

import json
from threading import Thread
import queue
import os
import tempfile
from datetime import datetime
import re
import shutil
from werkzeug.utils import secure_filename

from .web import cwa_get_num_books_in_library

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

switch_theme = Blueprint('switch_theme', __name__)
library_refresh = Blueprint('library_refresh', __name__)
convert_library = Blueprint('convert_library', __name__)
epub_fixer = Blueprint('epub_fixer', __name__)
cwa_stats = Blueprint('cwa_stats', __name__)
cwa_check_status = Blueprint('cwa_check_status', __name__)
cwa_settings = Blueprint('cwa_settings', __name__)
cwa_logs = Blueprint('cwa_logs', __name__)
profile_pictures = Blueprint('profile_pictures', __name__)

log = logger.create()

##——————————————————————————————GLOBAL VARIABLES——————————————————————————————##

# Folder where the log files are stored
LOG_ARCHIVE = "/config/log_archive"
DIRS_JSON = "/app/calibre-web-automated/dirs.json"

##———————————————————————————END OF GLOBAL VARIABLES——————————————————————————##

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                               CWA SWITCH THEME                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

@switch_theme.route("/cwa-switch-theme", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_switch_theme():
    # Switch theme for current user only
    try:
        # current_user.theme may not exist for old sessions before migration; default to 0
        current = getattr(current_user, 'theme', 0)
        new_theme = 0 if current == 1 else 1
        from . import ub
        user = ub.session.query(ub.User).filter(ub.User.id == current_user.id).first()
        if user:
            user.theme = new_theme
            ub.session_commit()
        else:
            log.error("Theme switch: user not found in DB")
    except Exception as e:
        log.error(f"Error switching theme: {e}")
    # Redirect back to the page user was on (fallback to index)
    target = request.referrer or url_for("web.index")
    # Basic safety: only allow same-host redirects
    try:
        from urllib.parse import urlparse
        ref_p = urlparse(target)
        if ref_p.netloc and ref_p.netloc != request.host:
            target = url_for("web.index")
    except Exception:
        target = url_for("web.index")
    return redirect(target, code=302)

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                             CWA LIBRARY REFRESH                            ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

def get_ingest_dir():
    with open(DIRS_JSON, 'r') as f:
        dirs = json.load(f)
        return dirs['ingest_folder']

def get_ingest_status():
    """Read the current ingest service status"""
    try:
        with open('/config/cwa_ingest_status', 'r') as f:
            status_line = f.read().strip()
            if ':' in status_line:
                parts = status_line.split(':')
                return {
                    'state': parts[0],
                    'filename': parts[1] if len(parts) > 1 else '',
                    'timestamp': parts[2] if len(parts) > 2 else '',
                    'detail': parts[3] if len(parts) > 3 else ''
                }
            else:
                return {'state': status_line, 'filename': '', 'timestamp': '', 'detail': ''}
    except (FileNotFoundError, IOError):
        return {'state': 'unknown', 'filename': '', 'timestamp': '', 'detail': ''}

def get_ingest_queue_size():
    """Get the number of files in the retry queue"""
    try:
        with open('/config/cwa_ingest_retry_queue', 'r') as f:
            return len([line for line in f if line.strip()])
    except (FileNotFoundError, IOError):
        return 0

def refresh_library(app):
    with app.app_context():  # Create app context for session
        ingest_dir = get_ingest_dir()
        result = subprocess.run(['python3', '/app/calibre-web-automated/scripts/ingest_processor.py', ingest_dir])
        return_code = result.returncode

        # Add empty list for messages in app context if a list doesn't already exist
        if "library_refresh_messages" not in current_app.config:
            current_app.config["library_refresh_messages"] = []

        if return_code == 2:
            message = _l("Library Refresh 🔄 The book ingest service is already running ✋ Please wait until it has finished before trying again ⌛")
        elif return_code == 0:
            message = _l("Library Refresh 🔄 Library refreshed & ingest process complete! ✅")
        else:
            message = _l("Library Refresh 🔄 An unexpected error occurred, check the logs ⛔")

        # Store lazy message objects (will be translated when converted to string)
        current_app.config["library_refresh_messages"].append(message)
        # Print result to docker log (force English by casting within temporary locale guard if desired)
        print(str(message).replace('Library Refresh 🔄', '[library-refresh]'), flush=True)

@csrf.exempt
@library_refresh.route("/cwa-library-refresh", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_library_refresh():
    print("[library-refresh] Library refresh manually triggered by user...", flush=True)
    app = current_app._get_current_object()  # Get actual app instance

    current_app.config["library_refresh_messages"] = []

    # Run refresh_library() in a background thread
    library_refresh_thread = Thread(target=refresh_library, args=(app,))
    library_refresh_thread.start()

    return jsonify({"message": _("Library Refresh 🔄 Checking for any books that may have been missed, please wait...")}), 200

@csrf.exempt
@library_refresh.route("/cwa-library-refresh/messages", methods=["GET"])
@login_required_if_no_ano
def get_library_refresh_messages():
    messages = current_app.config.get("library_refresh_messages", [])

    # Convert lazy messages to strings (translation occurs here)
    rendered = [str(m) for m in messages]

    # Clear messages after they have been retrieved
    current_app.config["library_refresh_messages"] = []

    return jsonify({"messages": rendered})

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                              CWA SETTINGS PAGE                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

@csrf.exempt
@cwa_settings.route("/cwa-settings", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def set_cwa_settings():
    cwa_db = CWA_DB()
    cwa_default_settings = cwa_db.cwa_default_settings
    cwa_settings = cwa_db.cwa_settings

    ignorable_formats = ['acsm', 'azw', 'azw3', 'azw4', 'cbz',
                        'cbr', 'cb7', 'cbc', 'chm',
                        'djvu', 'docx', 'epub', 'fb2',
                        'fbz', 'html', 'htmlz', 'kepub', 'lit',
                        'lrf', 'mobi', 'odt', 'pdf',
                        'prc', 'pdb', 'pml', 'rb',
                        'rtf', 'snb', 'tcr', 'txt', 'txtz']
    target_formats = ['epub', 'azw3', 'kepub', 'mobi', 'pdf']
    automerge_options = ['ignore', 'overwrite', 'new_record']
    autoingest_options = ['ignore', 'overwrite', 'new_record']

    boolean_settings = []
    string_settings = []
    list_settings = []
    integer_settings = ['ingest_timeout_minutes']  # Special handling for integer settings
    
    for setting in cwa_default_settings:
        if setting in integer_settings:
            continue  # Handle separately
        elif isinstance(cwa_default_settings[setting], int):
            boolean_settings.append(setting)
        elif isinstance(cwa_default_settings[setting], str) and cwa_default_settings[setting] != "":
            string_settings.append(setting)
        else:
            list_settings.append(setting)

    for format in ignorable_formats:
        string_settings.append(f"ignore_ingest_{format}")
        string_settings.append(f"ignore_convert_{format}")

    if request.method == 'POST':
        if request.form['submit_button'] == "Submit":
            result = {"auto_convert_ignored_formats":[], "auto_ingest_ignored_formats":[]}
            # set boolean_settings
            for setting in boolean_settings:
                value = request.form.get(setting)
                if value == None:
                    value = 0
                else:
                    value = 1
                result |= {setting:value}
            # set string settings
            for setting in string_settings:
                value = request.form.get(setting)
                if setting[:14] == "ignore_convert":
                    if value == None:
                        continue
                    else:
                        result["auto_convert_ignored_formats"].append(value)
                        continue
                elif setting[:13] == "ignore_ingest":
                    if value == None:
                        continue
                    else:
                        result["auto_ingest_ignored_formats"].append(value)
                        continue
                elif setting == "auto_convert_target_format" and value == None:
                    value = cwa_db.cwa_settings['auto_convert_target_format']

                result |= {setting:value}
            
            # Prevent ignoring of target format
            if result['auto_convert_target_format'] in result['auto_convert_ignored_formats']:
                result['auto_convert_ignored_formats'].remove(result['auto_convert_target_format'])
            if result['auto_convert_target_format'] in result['auto_ingest_ignored_formats']:
                result['auto_ingest_ignored_formats'].remove(result['auto_convert_target_format'])

            # Handle integer settings
            for setting in integer_settings:
                value = request.form.get(setting)
                if value is not None:
                    try:
                        int_value = int(value)
                        # Validate timeout range
                        if setting == 'ingest_timeout_minutes':
                            int_value = max(5, min(120, int_value))  # Clamp between 5 and 120 minutes
                        result[setting] = int_value
                    except (ValueError, TypeError):
                        # Use current value if conversion fails
                        result[setting] = cwa_db.cwa_settings.get(setting, 15)  # Default to 15 minutes
                else:
                    result[setting] = cwa_db.cwa_settings.get(setting, 15)  # Default to 15 minutes

            # DEBUGGING
            # with open("/config/post_request" ,"w") as f:
            #     for key in result.keys():
            #         if key == "auto_convert_ignored_formats" or key == "auto_ingest_ignored_formats":
            #             f.write(f"{key} - {', '.join(result[key])}\n")
            #         else:
            #             f.write(f"{key} - {result[key]}\n")

            cwa_db.update_cwa_settings(result)
            cwa_settings = cwa_db.get_cwa_settings()

        elif request.form['submit_button'] == "Apply Default Settings":
            cwa_db = CWA_DB()
            cwa_db.set_default_settings(force=True)
            cwa_settings = cwa_db.get_cwa_settings()

    elif request.method == 'GET':
        ...

    return render_title_template("cwa_settings.html", title=_("Calibre-Web Automated User Settings"), page="cwa-settings",
                                    cwa_settings=cwa_settings, ignorable_formats=ignorable_formats, target_formats=target_formats,
                                    automerge_options=automerge_options, autoingest_options=autoingest_options)

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                               CWA SHOW HISTORY                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

def get_cwa_stats() -> dict[str,int]:
    """Returns CWA stat totals as a dict (keys are table names except for total_books)"""
    cwa_db = CWA_DB()
    totals = cwa_db.get_stat_totals()
    totals["total_books"] = cwa_get_num_books_in_library() # from web.py

    return totals

### TABLE HEADERS
headers = {
    "enforcement":{
        "no_paths":[
            _("Timestamp"), _("Book ID"), _("Book Title"), _("Book Author"), _("Trigger Type")],
        "with_paths":[
            _("Timestamp"), _("Book ID"), _("Filepath")]
        },
    "epub_fixer":{
        "no_fixes":[
            _("Timestamp"), _("Filename"), _("Manual?"), _("No. Fixes"), _("Original Backed Up?")],
        "with_fixes":[
            _("Timestamp"), _("Filename"), _("Filepath"), _("Fixes Applied")]
        },
    "imports":[
        _("Timestamp"), _("Filename"), _("Original Backed Up?")],
    "conversions":[
        _("Timestamp"), _("Filename"), _("Original Format"), _("End Format"), _("Original Backed Up?")],
}

@cwa_stats.route("/cwa-stats-show", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def cwa_stats_show():
    cwa_db = CWA_DB()
    data_enforcement = cwa_db.enforce_show(paths=False, verbose=False, web_ui=True)
    data_enforcement_with_paths = cwa_db.enforce_show(paths=True, verbose=False, web_ui=True)
    data_imports = cwa_db.get_import_history(verbose=False)
    data_conversions = cwa_db.get_conversion_history(verbose=False)
    data_epub_fixer = cwa_db.get_epub_fixer_history(fixes=False, verbose=False)
    data_epub_fixer_with_fixes = cwa_db.get_epub_fixer_history(fixes=True, verbose=False)

    return render_title_template("cwa_stats.html", title=_("Calibre-Web Automated Sever Stats & Archive"), page="cwa-stats",
                                cwa_stats=get_cwa_stats(),
                                data_enforcement=data_enforcement, headers_enforcement=headers["enforcement"]["no_paths"], 
                                data_enforcement_with_paths=data_enforcement_with_paths,headers_enforcement_with_paths=headers["enforcement"]["with_paths"], 
                                data_imports=data_imports, headers_import=headers["imports"],
                                data_conversions=data_conversions, headers_conversion=headers["conversions"],
                                data_epub_fixer=data_epub_fixer, headers_epub_fixer=headers["epub_fixer"]["no_fixes"],
                                data_epub_fixer_with_fixes=data_epub_fixer_with_fixes, headers_epub_fixer_with_fixes=headers["epub_fixer"]["with_fixes"])
                                    
@cwa_stats.route("/cwa-stats-show/full-enforcement", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_enforcement():
    cwa_db = CWA_DB()
    data = cwa_db.enforce_show(paths=False, verbose=True, web_ui=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full Enforcement History"), page="cwa-stats-full",
                                    table_headers=headers["enforcement"]["no_paths"], data=data)

@cwa_stats.route("/cwa-stats-show/full-enforcement-with-paths", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_enforcement_path():
    cwa_db = CWA_DB()
    data = cwa_db.enforce_show(paths=True, verbose=True, web_ui=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full Enforcement History (w/ Paths)"), page="cwa-stats-full",
                                    table_headers=headers["enforcement"]["with_paths"], data=data)

@cwa_stats.route("/cwa-stats-show/full-imports", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_imports():
    cwa_db = CWA_DB()
    data = cwa_db.get_import_history(verbose=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full Import History"), page="cwa-stats-full",
                                    table_headers=headers["imports"], data=data)

@cwa_stats.route("/cwa-stats-show/full-conversions", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_conversions():
    cwa_db = CWA_DB()
    data = cwa_db.get_conversion_history(verbose=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full Conversion History"), page="cwa-stats-full",
                                    table_headers=headers["conversions"], data=data)

@cwa_stats.route("/cwa-stats-show/full-epub-fixer", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_epub_fixer():
    cwa_db = CWA_DB()
    data = cwa_db.get_epub_fixer_history(fixes=False, verbose=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full EPUB Fixer History (w/out Paths & Fixes)"), page="cwa-stats-full",
                                    table_headers=headers["epub_fixer"]["no_fixes"], data=data)

@cwa_stats.route("/cwa-stats-show/full-epub-fixer-with-paths-fixes", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_epub_fixer_with_paths_fixes():
    cwa_db = CWA_DB()
    data = cwa_db.get_epub_fixer_history(fixes=True, verbose=True)
    return render_title_template("cwa_stats_full.html", title=_("Calibre-Web Automated - Full EPUB Fixer History (w/ Paths & Fixes)"), page="cwa-stats-full",
                                    table_headers=headers["epub_fixer"]["with_fixes"], data=data)

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                               CWA CHECK STATUS                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

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

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                                 CWA LOGS                                   ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

@cwa_logs.route('/cwa-logs/download/<log_filename>')
def download_log(log_filename):
    try:
        # Secure the filename to prevent directory traversal (e.g., '..')
        safe_filename = secure_filename(log_filename)
        
        # Join the logs directory with the filename and get the absolute path
        file_path = os.path.abspath(os.path.join(LOG_ARCHIVE, safe_filename))
        
        # Check if the file path is within the allowed directory
        if not file_path.startswith(os.path.abspath(LOG_ARCHIVE)):
            abort(403)  # Forbidden if it's not within the logs directory

        # Check if the file exists
        if not os.path.exists(file_path):
            abort(404)  # Return a 404 if the file does not exist

        # Send the file as an attachment (to trigger a download)
        return send_from_directory(LOG_ARCHIVE, safe_filename, as_attachment=True)
    
    except Exception as e:
        # Handle any other errors
        abort(400)  # Bad request for malformed or unsafe file paths

@cwa_logs.route('/cwa-logs/read/<log_filename>')
def read_log(log_filename):
    try:
        # Secure the filename to prevent directory traversal (e.g., '..')
        safe_filename = secure_filename(log_filename)
        
        # Join the logs directory with the filename and get the absolute path
        file_path = os.path.abspath(os.path.join(LOG_ARCHIVE, safe_filename))
        
        # Check if the file path is within the allowed directory
        if not file_path.startswith(os.path.abspath(LOG_ARCHIVE)):
            abort(403)  # Forbidden if it's not within the logs directory

        # Check if the file exists
        if not os.path.exists(file_path):
            abort(404)  # Return a 404 if the file does not exist

        # Send the file as an attachment (to trigger a download)
        with open(file_path, 'r') as f:
            log = f.read()

        return render_title_template('cwa_read_log.html', title=_(f"Calibre-Web Automated - Log Archive - Read Log - {log_filename}"), page="cwa-log-read",
                                    log_filename=log_filename, log=log)
    
    except Exception as e:
        # Handle any other errors
        abort(400)  # Bad request for malformed or unsafe file paths

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                        CWA LIBRARY CONVERSION SERVICE                      ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

##————————————————————————SHARED VARIABLES & FUNCTIONS————————————————————————##

def extract_progress(log_content):
    """Analyses a log's given contents & returns the processes current progress as a dict"""
    # Regex to find all progress matches (e.g., "n/n")
    matches = re.findall(r'(\d+)/(\d+)', log_content)
    if matches:
        # Convert the matches to integers and take the last one
        current, total = map(int, matches[-1])
        return {"current": current, "total": total}
    return {"current": 0, "total": 0}

def archive_run_log(log_path):
    try:
        log_name = Path(log_path).stem + f"-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.log"
        shutil.copy2(log_path, f"{LOG_ARCHIVE}/{log_name}")
        print(f"[cwa-functions] Log '{log_path}' has been successfully archived as {log_name} in '{LOG_ARCHIVE}'")
    except Exception as e:
        print(f"[cwa-functions] The following error occurred when trying to back up {log_path} at {datetime.now()}:\n{e}")

def get_logs_from_archive(log_name) -> dict[str,str]:
    logs = {}
    logs_in_archive = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(LOG_ARCHIVE) for f in filenames]
    for log in logs_in_archive:
        if log_name in log:
            logs |= {os.path.basename(log):log}

    return logs

def get_log_dates(logs) -> dict[str,str]:
    log_dates = {}
    for log in logs:
        log_date, time = re.findall(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]+)+", log)[0]
        log_time = f"{time[:2]}:{time[2:4]}:{time[-2:]}"
        log_dates |= {log:{"date":log_date,
                            "time":log_time}}
    return log_dates

##———————————————————END OF SHARED VARIABLES & FUNCTIONS———————————————————————##

def convert_library_start(queue):
    cl_process = subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/convert_library.py'])
    queue.put(cl_process)

def get_tmp_conversion_dir() -> str:
    dirs = {}
    with open(DIRS_JSON, 'r') as f:
        dirs: dict[str, str] = json.load(f)
    tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

    return tmp_conversion_dir

def empty_tmp_con_dir(tmp_conversion_dir) -> None:
    try:
        files = os.listdir(tmp_conversion_dir)
        for file in files:
            file_path = os.path.join(tmp_conversion_dir, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        print(f"[cwa-functions]: An error occurred while emptying {tmp_conversion_dir}. See the following error: {e}")

def is_convert_library_finished() -> bool:
    log_path = "/config/convert-library.log"
    with open(log_path, 'r') as log:
        if "CWA Convert Library Service - Run Ended: " in log.read():
            return True
        else:
            return False

def kill_convert_library(queue):
    trigger_file = Path(tempfile.gettempdir() + "/.kill_convert_library_trigger")
    log_path = "/config/convert-library.log"
    while True:
        sleep(0.05) # Required to prevent high cpu usage
        if trigger_file.exists():
            # Kill the convert_library process
            cl_process = queue.get()
            cl_process.terminate()
            # Remove any potentially left over lock files
            try:
                os.remove(tempfile.gettempdir() + '/convert_library.lock')
            except FileNotFoundError:
                ...
            # Empty tmp conversion dir of half finished files
            empty_tmp_con_dir(get_tmp_conversion_dir())
            # Remove the trigger file that triggered this block
            try:
                os.remove(trigger_file)
            except FileNotFoundError:
                ...
            # Add string to log to notify user of successful cancellation and to stop the JS update script
            with open(log_path, 'a') as f:
                f.write(f"\nCONVERT LIBRARY PROCESS TERMINATED BY USER AT {datetime.now()}")
            # Add run log to log_archive
            archive_run_log(log_path)
            break
        elif is_convert_library_finished():
            archive_run_log(log_path)
            break

@convert_library.route('/cwa-convert-library-overview', methods=["GET"])
def show_convert_library_page():
    return render_title_template('cwa_convert_library.html', title=_("Calibre-Web Automated - Convert Library"), page="cwa-library-convert",
                                target_format=CWA_DB().cwa_settings['auto_convert_target_format'].upper())

@convert_library.route('/cwa-convert-library/log-archive', methods=["GET"])
def show_convert_library_logs():
    logs=get_logs_from_archive("convert-library")
    log_dates = get_log_dates(logs)
    return render_title_template('cwa_list_logs.html', title=_("Calibre-Web Automated - Convert Library"), page="cwa-library-convert-logs",
                                logs=logs, log_dates=log_dates)

@convert_library.route('/cwa-convert-library/download-current-log/<log_filename>')
def download_current_log(log_filename):
    log_filename = "convert-library.log"
    LOG_DIR = "/config"
    try:
        # Secure the filename to prevent directory traversal (e.g., '..')
        safe_filename = secure_filename(log_filename)
        
        # Join the logs directory with the filename and get the absolute path
        file_path = os.path.abspath(os.path.join(LOG_DIR, safe_filename))
        
        # Check if the file path is within the allowed directory
        if not file_path.startswith(os.path.abspath(LOG_DIR)):
            abort(403)  # Forbidden if it's not within the logs directory

        # Check if the file exists
        if not os.path.exists(file_path):
            abort(404)  # Return a 404 if the file does not exist

        # Send the file as an attachment (to trigger a download)
        return send_from_directory(LOG_DIR, safe_filename, as_attachment=True)
    
    except Exception as e:
        # Handle any other errors
        abort(400)  # Bad request for malformed or unsafe file paths

@convert_library.route('/cwa-convert-library-start', methods=["GET"])
def start_conversion():
    # Wipe conversion log from previous runs
    open('/config/convert-library.log', 'w').close()
    # Remove any left over kill file
    try:
        os.remove(tempfile.gettempdir() + "/.kill_convert_library_trigger")
    except FileNotFoundError:
        ...
    # Queue to share the subprocess reference
    process_queue = queue.Queue()
    # Create and start the subprocess thread
    cl_thread = Thread(target=convert_library_start, args=(process_queue,))
    cl_thread.start()
    # Create and start the kill thread
    cl_kill_thread = Thread(target=kill_convert_library, args=(process_queue,))
    cl_kill_thread.start()
    return redirect(url_for('convert_library.show_convert_library_page'))

@convert_library.route('/convert-library-cancel', methods=["GET"])
def cancel_convert_library():
    # Create kill trigger file
    open(tempfile.gettempdir() + "/.kill_convert_library_trigger", 'w').close()
    return redirect(url_for('convert_library.show_convert_library_page'))

@convert_library.route('/convert-library-status', methods=["GET"])
def get_status():
    with open("/config/convert-library.log", 'r') as f:
        status = f.read()
    progress = extract_progress(status)
    statusList = {'status':status,
                  'progress':progress}
    return json.dumps(statusList)


##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                            CWA EPUB FIXER SERVICE                          ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

def epub_fixer_start(queue):
    ef_process = subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/kindle_epub_fixer.py', '--all'])
    queue.put(ef_process)

def is_epub_fixer_finished() -> bool:
    log_path = "/config/epub-fixer.log"
    with open(log_path, 'r') as log:
        if "CWA Kindle EPUB Fixer Service - Run Ended: " in log.read():
            return True
        else:
            return False

def kill_epub_fixer(queue):
    trigger_file = Path(tempfile.gettempdir() + "/.kill_epub_fixer_trigger")
    log_path = "/config/epub-fixer.log"
    while True:
        sleep(0.05) # Required to prevent high cpu usage
        if trigger_file.exists():
            # Kill the epub_fixer process
            fl_process = queue.get()
            fl_process.terminate()
            # Remove any potentially left over lock files
            try:
                os.remove(tempfile.gettempdir() + '/kindle_epub_fixer.lock')
            except FileNotFoundError:
                ...
            # Remove the trigger file that triggered this block
            try:
                os.remove(trigger_file)
            except FileNotFoundError:
                ...
            # Add string to log to notify user of successful cancellation and to stop the JS update script
            with open(log_path, 'a') as f:
                f.write(f"\nCWA EPUB FIXER PROCESS TERMINATED BY USER AT {datetime.now()}")
            # Add run log to log_archive
            archive_run_log(log_path)
            break
        elif is_epub_fixer_finished():
            archive_run_log(log_path)
            break

@epub_fixer.route('/cwa-epub-fixer-overview', methods=["GET"])
def show_epub_fixer_page():
    return render_title_template('cwa_epub_fixer.html', title=_("Calibre-Web Automated - Send-to-Kindle EPUB Fixer Service"), page="cwa-epub-fixer")

@epub_fixer.route('/cwa-epub-fixer/log-archive', methods=["GET"])
def show_epub_fixer_logs():
    logs = get_logs_from_archive("epub-fixer")
    log_dates = get_log_dates(logs)
    return render_title_template('cwa_list_logs.html', title=_("Calibre-Web Automated - Send-to-Kindle EPUB Fixer Service"), page="cwa-epub-fixer-logs",
                                logs=logs, log_dates=log_dates)

@epub_fixer.route('/cwa-epub-fixer/download-current-log/<log_filename>')
def download_current_log(log_filename):
    log_filename = "epub-fixer.log"
    LOG_DIR = "/config"
    try:
        # Secure the filename to prevent directory traversal (e.g., '..')
        safe_filename = secure_filename(log_filename)
        
        # Join the logs directory with the filename and get the absolute path
        file_path = os.path.abspath(os.path.join(LOG_DIR, safe_filename))
        
        # Check if the file path is within the allowed directory
        if not file_path.startswith(os.path.abspath(LOG_DIR)):
            abort(403)  # Forbidden if it's not within the logs directory

        # Check if the file exists
        if not os.path.exists(file_path):
            abort(404)  # Return a 404 if the file does not exist

        # Send the file as an attachment (to trigger a download)
        return send_from_directory(LOG_DIR, safe_filename, as_attachment=True)
    
    except Exception as e:
        # Handle any other errors
        abort(400)  # Bad request for malformed or unsafe file paths

@epub_fixer.route('/cwa-epub-fixer-start', methods=["GET"])
def start_epub_fixer():
    # Wipe conversion log from previous runs
    open('/config/epub-fixer.log', 'w').close()
    # Remove any left over kill file
    try:
        os.remove(tempfile.gettempdir() + "/.kill_epub_fixer_trigger")
    except FileNotFoundError:
        ...
    # Queue to share the subprocess reference
    process_queue = queue.Queue()
    # Create and start the subprocess thread
    ef_thread = Thread(target=epub_fixer_start, args=(process_queue,))
    ef_thread.start()
    # Create and start the kill thread
    ef_kill_thread = Thread(target=kill_epub_fixer, args=(process_queue,))
    ef_kill_thread.start()
    return redirect(url_for('epub_fixer.show_epub_fixer_page'))

@epub_fixer.route('/epub-fixer-cancel', methods=["GET"])
def cancel_epub_fixer():
    # Create kill trigger file
    open(tempfile.gettempdir() + "/.kill_epub_fixer_trigger", 'w').close()
    return redirect(url_for('epub_fixer.show_epub_fixer_page'))

@epub_fixer.route('/epub-fixer-status', methods=["GET"])
def get_status():
    with open("/config/epub-fixer.log", 'r') as f:
        status = f.read()
    progress = extract_progress(status)
    statusList = {'status':status,
                  'progress':progress}
    return json.dumps(statusList)


# ################################### Profile Pictures ###################################################

@profile_pictures.route("/user_profiles.json")
@user_login_required
def user_profiles_json():
    try:
        json_path = "/config/user_profiles.json"
        with open(json_path, "r") as file:
            data = json.load(file)
        return jsonify(data)
    except Exception as e:
        log.error(f"Error reading user_profiles.json: {str(e)}")
        return jsonify({}), 500

@profile_pictures.route("/me/profile-picture", methods=["GET", "POST"])
@user_login_required
def set_profile_picture():
    log.debug("Accessed /me/profile-picture route.")

    # Check if the user is an admin
    if not current_user.role_admin():
        flash(_("You must be an admin to access this page."), category="error")
        log.warning(f"Unauthorized access attempt by user: {current_user.name}")
        return redirect(url_for('web.profile'))

    if request.method == "POST":
        log.debug("POST request received on profile_pictures page.")

        # Get the form data (username and image data)
        username = request.form.get("username")
        image_data = request.form.get("image_data")

        log.debug(f"Form data received - Username: {username}, Image Data Length: {len(image_data) if image_data else 'None'}")

        # Validate form fields
        if not username or not image_data:
            flash(_("Both username and image data are required."), category="error")
            log.warning("Form submission missing username or image_data.")
            return redirect(url_for('profile_pictures.setprofile_picture'))

        try:
            # Path to the JSON file
            json_path = "/config/user_profiles.json"
            log.debug(f"Opening JSON file at: {json_path}")

            # Read the existing data from the JSON file and update it
            with open(json_path, "r+") as file:
                user_data = json.load(file)
                user_data[username] = image_data  # Add new or update existing entry
                file.seek(0)  # Move to the start of the file for writing
                json.dump(user_data, file, indent=4)  # Write back the updated data
                file.truncate()  # Ensure there is no leftover content

            # Success feedback and logging
            flash(_("Profile picture updated successfully."), category="success")
            log.info(f"Profile picture updated for user: {username}")

        except Exception as e:
            # Error handling in case of an issue
            flash(f"Error: {str(e)}", category="error")
            log.error(f"Exception while updating profile picture JSON: {str(e)}")

        return redirect(url_for('profile_pictures.set_profile_picture'))

    # Handle the GET request and render the page
    log.debug("Rendering GET view for profile_pictures page.")
    return render_title_template("profile_pictures.html", 
                                title=_("CWA Profile Picture Management (WIP)"), 
                                page="profile-picture")