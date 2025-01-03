from flask import Blueprint, redirect, flash, url_for, request, Response
from flask_babel import gettext as _

from . import logger, config, constants, csrf
from .usermanagement import login_required_if_no_ano
from .admin import admin_required
from .render_template import render_title_template

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

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

switch_theme = Blueprint('switch_theme', __name__)
library_refresh = Blueprint('library_refresh', __name__)
convert_library = Blueprint('convert_library', __name__)
epub_fixer = Blueprint('epub_fixer', __name__)
cwa_history = Blueprint('cwa_history', __name__)
cwa_check_status = Blueprint('cwa_check_status', __name__)
cwa_settings = Blueprint('cwa_settings', __name__)

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                               CWA SWITCH THEME                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

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

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                             CWA LIBRARY REFRESH                            ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

@library_refresh.route("/cwa-library-refresh", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_library_refresh():
    flash(_("Library Refresh: Initialising Book Ingest System, please wait..."), category="cwa_refresh")
    result = subprocess.run(['python3', '/app/calibre-web-automated/scripts/ingest_processor.py', '/cwa-book-ingest'])
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
    ignorable_formats = ['azw', 'azw3', 'azw4', 'cbz',
                        'cbr', 'cb7', 'cbc', 'chm',
                        'djvu', 'docx', 'epub', 'fb2',
                        'fbz', 'html', 'htmlz', 'kepub', 'lit',
                        'lrf', 'mobi', 'odt', 'pdf',
                        'prc', 'pdb', 'pml', 'rb',
                        'rtf', 'snb', 'tcr', 'txt', 'txtz']
    target_formats = ['epub', 'azw3', 'kepub', 'mobi', 'pdf']
    boolean_settings = ["auto_backup_imports",
                        "auto_backup_conversions",
                        "auto_zip_backups",
                        "cwa_update_notifications",
                        "auto_convert",
                        "auto_metadata_enforcement",
                        "kindle_epub_fixer"]
    string_settings = ["auto_convert_target_format"]
    for format in ignorable_formats:
        string_settings.append(f"ignore_ingest_{format}")
        string_settings.append(f"ignore_convert_{format}")

    if request.method == 'POST':
        cwa_db = CWA_DB()
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
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.cwa_settings

    return render_title_template("cwa_settings.html", title=_("CWA Settings"), page="cwa-settings",
                                    cwa_settings=cwa_settings, ignorable_formats=ignorable_formats,
                                    target_formats=target_formats)

##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                               CWA SHOW HISTORY                             ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

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
                                    
@cwa_history.route("/cwa-history-show/full-enforcement", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_enforcement():
    cwa_db = CWA_DB()
    data, table_headers = cwa_db.enforce_show(paths=False, verbose=True, web_ui=True)
    return render_title_template("cwa_history_full.html", title=_("Calibre-Web Automated - Full Enforcement History"), page="cwa-history-full",
                                    table_headers=table_headers, data=data)

@cwa_history.route("/cwa-history-show/full-enforcement-path", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_enforcement_path():
    cwa_db = CWA_DB()
    data, table_headers = cwa_db.enforce_show(paths=True, verbose=True, web_ui=True)
    return render_title_template("cwa_history_full.html", title=_("Calibre-Web Automated - Full Enforcement History (Paths)"), page="cwa-history-full",
                                    table_headers=table_headers, data=data)

@cwa_history.route("/cwa-history-show/full-imports", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_imports():
    cwa_db = CWA_DB()
    data, table_headers = cwa_db.get_import_history(verbose=True)
    return render_title_template("cwa_history_full.html", title=_("Calibre-Web Automated - Full Import History"), page="cwa-history-full",
                                    table_headers=table_headers, data=data)

@cwa_history.route("/cwa-history-show/full-conversions", methods=["GET", "POST"])
@login_required_if_no_ano
@admin_required
def show_full_conversions():
    cwa_db = CWA_DB()
    data, table_headers = cwa_db.get_conversion_history(verbose=True)
    return render_title_template("cwa_history_full.html", title=_("Calibre-Web Automated - Full Conversion History"), page="cwa-history-full",
                                    table_headers=table_headers, data=data)

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
##                        CWA LIBRARY CONVERSION SERVICE                      ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

def convert_library_start(queue):
    cl_process = subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/convert_library.py'])
    queue.put(cl_process)

def get_tmp_conversion_dir() -> str:
    dirs_json_path = "/app/calibre-web-automated/dirs.json"
    dirs = {}
    with open(dirs_json_path, 'r') as f:
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
    with open("/config/convert-library.log", 'r') as log:
        if "CWA Convert Library Service - Run Ended: " in log.read():
            return True
        else:
            return False

def kill_convert_library(queue):
    trigger_file = Path(tempfile.gettempdir() + "/.kill_convert_library_trigger")
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
            with open("/config/convert-library.log", 'a') as f:
                f.write(f"\nCONVERT LIBRARY PROCESS TERMINATED BY USER AT {datetime.now()}")
            break
        elif is_convert_library_finished():
            break

@convert_library.route('/cwa-convert-library-overview', methods=["GET"])
def show_convert_library_page():
    return render_title_template('cwa_convert_library.html', title=_("Calibre-Web Automated - Convert Library"), page="cwa-library-convert",
                                target_format=CWA_DB().cwa_settings['auto_convert_target_format'].upper())

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
    statusList = {'status':status}
    return json.dumps(statusList)


##————————————————————————————————————————————————————————————————————————————##
##                                                                            ##
##                            CWA EPUB FIXER SERVICE                          ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

def epub_fixer_start(queue):
    ef_process = subprocess.Popen(['python3', '/app/calibre-web-automated/scripts/kindle_epub_fixer.py', '--all'])
    queue.put(ef_process)

# def get_tmp_conversion_dir() -> str:
#     dirs_json_path = "/app/calibre-web-automated/dirs.json"
#     dirs = {}
#     with open(dirs_json_path, 'r') as f:
#         dirs: dict[str, str] = json.load(f)
#     tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

#     return tmp_conversion_dir

# def empty_tmp_con_dir(tmp_conversion_dir) -> None:
#     try:
#         files = os.listdir(tmp_conversion_dir)
#         for file in files:
#             file_path = os.path.join(tmp_conversion_dir, file)
#             if os.path.isfile(file_path):
#                 os.remove(file_path)
#     except Exception as e:
#         print(f"[cwa-functions]: An error occurred while emptying {tmp_conversion_dir}. See the following error: {e}")

def is_epub_fixer_finished() -> bool:
    with open("/config/epub-fixer.log", 'r') as log:
        if "CWA Kindle EPUB Fixer Service - Run Ended: " in log.read():
            return True
        else:
            return False

def kill_epub_fixer(queue):
    trigger_file = Path(tempfile.gettempdir() + "/.kill_epub_fixer_trigger")
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
            # # Empty tmp conversion dir of half finished files
            # empty_tmp_con_dir(get_tmp_conversion_dir())
            # Remove the trigger file that triggered this block
            try:
                os.remove(trigger_file)
            except FileNotFoundError:
                ...
            with open("/config/convert-library.log", 'a') as f:
                f.write(f"\nCWA EPUB FIXER PROCESS TERMINATED BY USER AT {datetime.now()}")
            break
        elif is_epub_fixer_finished():
            break

@epub_fixer.route('/cwa-epub-fixer-overview', methods=["GET"])
def show_epub_fixer_page():
    return render_title_template('cwa_epub_fixer.html', title=_("Calibre-Web Automated - Send-to-Kindle EPUB Fixer Service"), page="cwa-epub-fixer")

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
    statusList = {'status':status}
    return json.dumps(statusList)