# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask import Blueprint, redirect, flash, url_for, request, send_from_directory, abort, jsonify, current_app
from flask_babel import gettext as _, lazy_gettext as _l

from . import logger, config, constants, csrf, helper
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
from datetime import datetime, timedelta
import re
import shutil
import base64
from werkzeug.utils import secure_filename

from .web import cwa_get_num_books_in_library

import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB
from .services.background_scheduler import BackgroundScheduler, DateTrigger
from .services.worker import WorkerThread
from .tasks.database import TaskReconnectDatabase
from .tasks.auto_send import TaskAutoSend
from .tasks.ops import TaskConvertLibraryRun, TaskEpubFixerRun

switch_theme = Blueprint('switch_theme', __name__)
library_refresh = Blueprint('library_refresh', __name__)
convert_library = Blueprint('convert_library', __name__)
epub_fixer = Blueprint('epub_fixer', __name__)
cwa_stats = Blueprint('cwa_stats', __name__)
cwa_check_status = Blueprint('cwa_check_status', __name__)
cwa_settings = Blueprint('cwa_settings', __name__)
cwa_logs = Blueprint('cwa_logs', __name__)
profile_pictures = Blueprint('profile_pictures', __name__)
cwa_internal = Blueprint('cwa_internal', __name__)

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

def parse_metadata_providers_enabled(raw_value):
    """
    Parse the metadata_providers_enabled setting from various formats into a dict.
    
    Args:
        raw_value: The raw value from database/settings (str, dict, bytes, or None)
        
    Returns:
        dict: Provider ID to enabled status mapping. Empty dict on error.
    """
    import json
    
    try:
        # Handle None/null values
        if raw_value is None:
            return {}
            
        # Handle bytes (from some database drivers)
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode('utf-8', errors='ignore')
        
        # Handle string (most common case)
        if isinstance(raw_value, str):
            s = raw_value.strip()
            # Handle empty strings
            if not s:
                return {}
            # Strip surrounding single quotes if present from schema default
            if s.startswith("'") and s.endswith("'"):
                s = s[1:-1]
            # Handle empty string after quote stripping
            if not s:
                return {}
            data = json.loads(s)
            return data if isinstance(data, dict) else {}
        
        # Handle dict (already parsed)
        elif isinstance(raw_value, dict):
            return raw_value
        
        # Unknown type, return empty dict
        else:
            return {}
            
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}

def validate_and_cleanup_provider_enabled_map(enabled_map, available_provider_ids):
    """
    Validate and cleanup the provider enabled map.
    
    Args:
        enabled_map (dict): Current provider enabled map
        available_provider_ids (list): List of valid provider IDs
        
    Returns:
        dict: Cleaned up enabled map with only valid providers
    """
    if not isinstance(enabled_map, dict):
        return {}
    
    if not isinstance(available_provider_ids, (list, tuple, set)):
        return {}
    
    # Keep only valid provider IDs and boolean values
    cleaned_map = {}
    for provider_id, enabled in enabled_map.items():
        if (isinstance(provider_id, str) and 
            provider_id.strip() and  # Non-empty string
            provider_id in available_provider_ids):
            # Convert to boolean, handling various truthy/falsy values
            cleaned_map[provider_id] = bool(enabled)
    
    return cleaned_map

@switch_theme.route("/cwa-switch-theme", methods=["GET", "POST"])
@login_required_if_no_ano
def cwa_switch_theme():
    # Theme switching temporarily disabled for v4.0.0 frontend development
    flash(_("Theme switching is temporarily disabled until v4.0.0"), category="warning")
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
    
    # Original theme switching logic (disabled)
    # try:
    #     # current_user.theme may not exist for old sessions before migration; default to 1 (caliBlur)
    #     current = getattr(current_user, 'theme', 1)
    #     new_theme = 0 if current == 1 else 1
    #     from . import ub
    #     user = ub.session.query(ub.User).filter(ub.User.id == current_user.id).first()
    #     if user:
    #         user.theme = new_theme
    #         ub.session_commit()
    #     else:
    #         log.error("Theme switch: user not found in DB")
    # except Exception as e:
    #     log.error(f"Error switching theme: {e}")

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
##                           CWA INTERNAL ENDPOINTS                           ##
##                                                                            ##
##————————————————————————————————————————————————————————————————————————————##

@csrf.exempt
@cwa_internal.route('/cwa-internal/schedule-auto-send', methods=["POST"])
def cwa_internal_schedule_auto_send():
    """Schedule an Auto-Send task in the web process scheduler.

    Security: Limited to localhost callers (within container/host).
    Payload JSON: {book_id:int, user_id:int, delay_minutes:int, username:str, title:str}
    """
    try:
        # Basic origin check: allow only localhost
        remote = request.headers.get('X-Forwarded-For', request.remote_addr)
        if remote not in (None, '127.0.0.1', '::1'):
            abort(403)

        data = request.get_json(force=True, silent=True) or {}
        book_id = int(data.get('book_id'))
        user_id = int(data.get('user_id'))
        delay_minutes = int(data.get('delay_minutes', 5))
        delay_minutes = max(0, min(60, delay_minutes))
        username = data.get('username') or 'System'
        title = data.get('title') or 'Book'

        scheduler = BackgroundScheduler()
        if not scheduler:
            return jsonify({"error": "Scheduler unavailable"}), 503

        # Compute run time in both local and UTC for persistence
        run_at_local = datetime.now() + timedelta(minutes=delay_minutes)
        try:
            from datetime import timezone
            run_at_utc_iso = run_at_local.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        except Exception:
            run_at_utc_iso = run_at_local.isoformat()

        # Persist scheduled intent in cwa.db
        try:
            from cwa_db import CWA_DB
            db = CWA_DB()
            row_id = db.scheduled_add_autosend(book_id, user_id, run_at_utc_iso, username, title)
        except Exception as e:
            row_id = None
            log.error(f"Failed to record scheduled auto-send in cwa.db: {e}")

        task_message = f"Auto-sending '{title}' to user's eReader(s)"

        # Closure that marks dispatched and enqueues the task when the time arrives
        def _enqueue_autosend():
            should_enqueue = True
            try:
                if row_id is not None:
                    from cwa_db import CWA_DB
                    changed = CWA_DB().scheduled_mark_dispatched(int(row_id))
                    # Only enqueue if state actually moved to dispatched (i.e., was not cancelled)
                    should_enqueue = bool(changed)
            except Exception as e:
                log.error(f"Failed to mark scheduled auto-send dispatched: {e}")
            if should_enqueue:
                WorkerThread.add(username, TaskAutoSend(task_message, book_id, user_id, delay_minutes), hidden=False)

        # Defer task creation to scheduled time; shows in UI when enqueued
        job = scheduler.schedule(
            func=_enqueue_autosend,
            trigger=DateTrigger(run_date=run_at_local),
            name=f"Auto-send '{title}' to {username}"
        )

        # Persist scheduler job id for cancellation support
        try:
            if row_id is not None and job is not None:
                from cwa_db import CWA_DB
                CWA_DB().scheduled_update_job_id(int(row_id), str(job.id))
        except Exception as e:
            log.error(f"Failed to store scheduler job id for auto-send: {e}")

        return jsonify({"status": "scheduled", "run_at": run_at_local.isoformat(), "schedule_id": row_id}), 200
    except Exception as e:
        log.error(f"Internal auto-send schedule failed: {e}")
        return jsonify({"error": str(e)}), 400

@csrf.exempt
@cwa_internal.route('/cwa-internal/schedule-convert-library', methods=["POST"])
def cwa_internal_schedule_convert_library():
    """Schedule a Convert Library run in the web process scheduler.

    Security: Limited to localhost callers (within container/host).
    Payload JSON: {delay_minutes:int, username:str}
    """
    try:
        remote = request.headers.get('X-Forwarded-For', request.remote_addr)
        if remote not in (None, '127.0.0.1', '::1'):
            abort(403)

        data = request.get_json(force=True, silent=True) or {}
        delay_minutes = int(data.get('delay_minutes', 5))
        delay_minutes = max(0, min(60, delay_minutes))
        username = data.get('username') or 'System'

        scheduler = BackgroundScheduler()
        if not scheduler:
            return jsonify({"error": "Scheduler unavailable"}), 503

        run_at_local = datetime.now() + timedelta(minutes=delay_minutes)
        try:
            from datetime import timezone
            run_at_utc_iso = run_at_local.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        except Exception:
            run_at_utc_iso = run_at_local.isoformat()

        # Persist scheduled intent
        row_id = None
        try:
            db = CWA_DB()
            row_id = db.scheduled_add_job('convert_library', run_at_utc_iso, username=username, title='Convert Library')
        except Exception as e:
            log.error(f"Failed to record scheduled convert library in cwa.db: {e}")

        def _trigger_convert_library(sid=row_id, u=username):
            should_run = True
            try:
                if sid is not None:
                    should_run = bool(CWA_DB().scheduled_mark_dispatched(int(sid)))
            except Exception:
                pass
            if not should_run:
                return
            # Enqueue wrapper task so it shows in Tasks UI and triggers run internally
            WorkerThread.add(u, TaskConvertLibraryRun(), hidden=False)

        job = scheduler.schedule(func=_trigger_convert_library, trigger=DateTrigger(run_date=run_at_local), name=f"Convert Library (scheduled)")
        try:
            if row_id is not None and job is not None:
                CWA_DB().scheduled_update_job_id(int(row_id), str(job.id))
        except Exception:
            pass

        return jsonify({"status": "scheduled", "run_at": run_at_local.isoformat(), "schedule_id": row_id}), 200
    except Exception as e:
        log.error(f"Internal schedule-convert-library failed: {e}")
        return jsonify({"error": str(e)}), 400

@csrf.exempt
@cwa_internal.route('/cwa-internal/schedule-epub-fixer', methods=["POST"])
def cwa_internal_schedule_epub_fixer():
    """Schedule an EPUB Fixer run in the web process scheduler.

    Security: Limited to localhost callers (within container/host).
    Payload JSON: {delay_minutes:int, username:str}
    """
    try:
        remote = request.headers.get('X-Forwarded-For', request.remote_addr)
        if remote not in (None, '127.0.0.1', '::1'):
            abort(403)

        data = request.get_json(force=True, silent=True) or {}
        delay_minutes = int(data.get('delay_minutes', 5))
        delay_minutes = max(0, min(60, delay_minutes))
        username = data.get('username') or 'System'

        scheduler = BackgroundScheduler()
        if not scheduler:
            return jsonify({"error": "Scheduler unavailable"}), 503

        run_at_local = datetime.now() + timedelta(minutes=delay_minutes)
        try:
            from datetime import timezone
            run_at_utc_iso = run_at_local.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        except Exception:
            run_at_utc_iso = run_at_local.isoformat()

        row_id = None
        try:
            db = CWA_DB()
            row_id = db.scheduled_add_job('epub_fixer', run_at_utc_iso, username=username, title='EPUB Fixer')
        except Exception as e:
            log.error(f"Failed to record scheduled epub fixer in cwa.db: {e}")

        def _trigger_epub_fixer(sid=row_id, u=username):
            should_run = True
            try:
                if sid is not None:
                    should_run = bool(CWA_DB().scheduled_mark_dispatched(int(sid)))
            except Exception:
                pass
            if not should_run:
                return
            WorkerThread.add(u, TaskEpubFixerRun(), hidden=False)

        job = scheduler.schedule(func=_trigger_epub_fixer, trigger=DateTrigger(run_date=run_at_local), name=f"EPUB Fixer (scheduled)")
        try:
            if row_id is not None and job is not None:
                CWA_DB().scheduled_update_job_id(int(row_id), str(job.id))
        except Exception:
            pass

        return jsonify({"status": "scheduled", "run_at": run_at_local.isoformat(), "schedule_id": row_id}), 200
    except Exception as e:
        log.error(f"Internal schedule-epub-fixer failed: {e}")
        return jsonify({"error": str(e)}), 400

@csrf.exempt
@cwa_internal.route('/cwa-internal/reconnect-db', methods=["POST"])
def cwa_internal_reconnect_db():
    """Enqueue a database reconnect task in the web process.

    Security: Only accepts localhost callers.
    """
    try:
        remote = request.headers.get('X-Forwarded-For', request.remote_addr)
        if remote not in (None, '127.0.0.1', '::1'):
            abort(403)

        task = TaskReconnectDatabase()
        WorkerThread.add(None, task, hidden=True)
        return jsonify({"status": "enqueued"}), 200
    except Exception as e:
        log.error(f"Internal reconnect-db failed: {e}")
        return jsonify({"error": str(e)}), 400

@csrf.exempt
@cwa_stats.route('/cwa-scheduled/cancel', methods=["POST"])
@login_required_if_no_ano
@admin_required
def cwa_scheduled_cancel():
    """Cancel a pending scheduled auto-send by id.

    Payload JSON: {id:int}
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        sid = int(data.get('id'))
    except Exception:
        return jsonify({"error": "Invalid id"}), 400

    try:
        from cwa_db import CWA_DB
        db = CWA_DB()
        row = db.scheduled_get_by_id(sid)
        if not row:
            return jsonify({"error": "Not found"}), 404

        # Attempt to remove scheduled APScheduler job
        job_id = (row.get('scheduler_job_id') or '').strip()
        try:
            scheduler = BackgroundScheduler()
            if scheduler and job_id:
                scheduler.remove_job(job_id)
        except Exception:
            # Ignore removal errors (job may have already run or been removed)
            pass

        # Mark as cancelled regardless of job removal result
        db.scheduled_mark_cancelled(sid)
        return jsonify({"status": "cancelled", "id": sid}), 200
    except Exception as e:
        log.error(f"Error cancelling scheduled auto-send: {e}")
        return jsonify({"error": str(e)}), 500

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
                        'rtf', 'snb', 'tcr', 'txt', 'txtz',
                        'kfx', 'kfx-zip']
    target_formats = ['epub', 'azw3', 'kepub', 'mobi', 'pdf']
    automerge_options = ['ignore', 'overwrite', 'new_record']
    autoingest_options = ['ignore', 'overwrite', 'new_record']

    boolean_settings = []
    string_settings = []
    list_settings = []
    integer_settings = ['ingest_timeout_minutes', 'auto_send_delay_minutes']  # Special handling for integer settings
    json_settings = ['metadata_provider_hierarchy', 'metadata_providers_enabled', 'duplicate_format_priority']  # Special handling for JSON settings
    
    for setting in cwa_default_settings:
        if setting in integer_settings or setting in json_settings:
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
        string_settings.append(f"convert_retained_{format}")

    if request.method == 'POST':
        if request.form['submit_button'] == "Submit":
            result = {"auto_convert_ignored_formats":[], "auto_ingest_ignored_formats":[], "auto_convert_retained_formats":[]}
            # set boolean_settings
            for setting in boolean_settings:
                value = request.form.get(setting)
                if value is None:
                    value = 0
                else:
                    value = 1
                result |= {setting:value}
            # set string settings
            for setting in string_settings:
                value = request.form.get(setting)
                if setting[:14] == "ignore_convert":
                    if value is not None:
                        result["auto_convert_ignored_formats"].append(value)
                    continue
                elif setting[:13] == "ignore_ingest":
                    if value is not None:
                        result["auto_ingest_ignored_formats"].append(value)
                    continue
                elif setting.startswith("convert_retained"):
                    if value is not None:
                        result["auto_convert_retained_formats"].append(value)
                    continue
                elif setting == "auto_convert_target_format":
                    if value is None:
                        value = cwa_db.cwa_settings['auto_convert_target_format']
                    value = cwa_db.cwa_settings['auto_convert_target_format']

                result |= {setting:value}
            
            # Prevent ignoring of target format
            if result['auto_convert_target_format'] in result['auto_convert_ignored_formats']:
                result['auto_convert_ignored_formats'].remove(result['auto_convert_target_format'])
            if result['auto_convert_target_format'] in result['auto_ingest_ignored_formats']:
                result['auto_ingest_ignored_formats'].remove(result['auto_convert_target_format'])

            # Prevent retaining of ignored ingest formats (create a copy to avoid modification during iteration)
            for ignored_format in result['auto_ingest_ignored_formats'][:]:
                if ignored_format in result['auto_convert_retained_formats']:
                    result['auto_convert_retained_formats'].remove(ignored_format)

            # Force target format to be retained (ensure it's not already there to avoid duplicates)
            if result['auto_convert_target_format'] not in result['auto_convert_retained_formats']:
                result['auto_convert_retained_formats'].append(result['auto_convert_target_format'])

            # Handle integer settings
            for setting in integer_settings:
                value = request.form.get(setting)
                if value is not None:
                    try:
                        int_value = int(value)
                        # Validate timeout range
                        if setting == 'ingest_timeout_minutes':
                            int_value = max(5, min(120, int_value))  # Clamp between 5 and 120 minutes
                        elif setting == 'auto_send_delay_minutes':
                            int_value = max(1, min(60, int_value))  # Clamp between 1 and 60 minutes
                        result[setting] = int_value
                    except (ValueError, TypeError):
                        # Use current value if conversion fails
                        if setting == 'ingest_timeout_minutes':
                            result[setting] = cwa_db.cwa_settings.get(setting, 15)  # Default to 15 minutes
                        elif setting == 'auto_send_delay_minutes':
                            result[setting] = cwa_db.cwa_settings.get(setting, 5)  # Default to 5 minutes
                else:
                    if setting == 'ingest_timeout_minutes':
                        result[setting] = cwa_db.cwa_settings.get(setting, 15)  # Default to 15 minutes
                    elif setting == 'auto_send_delay_minutes':
                        result[setting] = cwa_db.cwa_settings.get(setting, 5)  # Default to 5 minutes

            # Handle JSON settings
            for setting in json_settings:
                value = request.form.get(setting)
                if value is not None:
                    try:
                        # Try to parse as JSON
                        import json
                        json_value = json.loads(value)
                        if setting == 'metadata_provider_hierarchy':
                            # Validate that it's a list of strings (provider IDs)
                            if isinstance(json_value, list) and all(isinstance(provider, str) for provider in json_value):
                                result[setting] = json.dumps(json_value)  # Store as JSON string
                            else:
                                # Use current value if validation fails
                                result[setting] = cwa_db.cwa_settings.get(setting, '["ibdb","google","dnb"]')
                        elif setting == 'metadata_providers_enabled':
                            # Validate dict mapping provider_id -> bool
                            if isinstance(json_value, dict):
                                # Just validate the basic structure - provider validation happens at runtime
                                cleaned_map = {}
                                for k, v in json_value.items():
                                    if isinstance(k, str) and isinstance(v, bool):
                                        cleaned_map[k] = v
                                result[setting] = json.dumps(cleaned_map)
                            else:
                                result[setting] = cwa_db.cwa_settings.get(setting, '{}')
                        else:
                            result[setting] = json.dumps(json_value)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        # Use current value if JSON parsing fails
                        if setting == 'metadata_provider_hierarchy':
                            result[setting] = cwa_db.cwa_settings.get(setting, '["ibdb","google","dnb"]')
                        elif setting == 'metadata_providers_enabled':
                            result[setting] = cwa_db.cwa_settings.get(setting, '{}')
                        else:
                            result[setting] = cwa_db.cwa_settings.get(setting, '[]')
                else:
                    # Use current value if not provided
                    if setting == 'metadata_provider_hierarchy':
                        result[setting] = cwa_db.cwa_settings.get(setting, '["ibdb","google","dnb"]')
                    elif setting == 'metadata_providers_enabled':
                        result[setting] = cwa_db.cwa_settings.get(setting, '{}')
                    else:
                        result[setting] = cwa_db.cwa_settings.get(setting, '[]')

            # DEBUGGING
            # with open("/config/post_request" ,"w") as f:
            #     for key in result.keys():
            #         if key == "auto_convert_ignored_formats" or key == "auto_ingest_ignored_formats":
            #             f.write(f"{key} - {', '.join(result[key])}\n")
            #         else:
            #             f.write(f"{key} - {result[key]}\n")

            # Save Kobo Sync Magic Shelves setting (stored in app.db, not cwa.db)
            config.config_kobo_sync_magic_shelves = 'config_kobo_sync_magic_shelves' in request.form
            config.save()

            cwa_db.update_cwa_settings(result)
            cwa_settings = cwa_db.get_cwa_settings()

        elif request.form['submit_button'] == "Apply Default Settings":
            cwa_db = CWA_DB()
            cwa_db.set_default_settings(force=True)
            cwa_settings = cwa_db.get_cwa_settings()

    elif request.method == 'GET':
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()

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
    from datetime import datetime, timedelta
    
    # Check which tab to show (default to user activity)
    active_tab = request.args.get('tab', 'activity')
    
    # Parse date range parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    days_param = request.args.get('days')
    
    # Initialize defaults
    date_range_label = None
    show_warning = False
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Handle 'all' as a special string value, otherwise parse as int
    if days_param == 'all':
        days = None  # None means all time
        date_range_label = "All Time"
    else:
        days = int(days_param) if days_param else None
    
    user_id = request.args.get('user_id', type=int)
    
    # Set default label if not set
    if not date_range_label:
        date_range_label = "Last 30 days"
    
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Calculate range in days
            range_days = (end_dt - start_dt).days
            
            # Show warning if range > 1 year
            if range_days > 365:
                show_warning = True
            
            date_range_label = f"{start_date} to {end_date}"
        except ValueError:
            # Invalid date format, fall back to 30 days
            start_date = None
            end_date = None
            days = 30
            date_range_label = "Last 30 days"
    elif days:
        if date_range_label != "All Time":
            date_range_label = f"Last {days} days"
        if days > 365:
            show_warning = True
    elif days is None and date_range_label != "All Time":
        # Default to 30 days if no parameters provided
        days = 30
        date_range_label = "Last 30 days"
    
    cwa_db = CWA_DB()
    
    # Get list of active users for dropdown
    active_users = cwa_db.get_active_users()
    
    # Get user activity dashboard stats with date range and optional user filter
    if start_date and end_date:
        dashboard_stats = cwa_db.get_dashboard_stats(start_date=start_date, end_date=end_date, user_id=user_id)
        hourly_heatmap = cwa_db.get_hourly_activity_heatmap(start_date=start_date, end_date=end_date, user_id=user_id)
        reading_velocity = cwa_db.get_reading_velocity(start_date=start_date, end_date=end_date, user_id=user_id)
        format_preferences = cwa_db.get_format_preferences(start_date=start_date, end_date=end_date, user_id=user_id)
        discovery_sources = cwa_db.get_discovery_sources(start_date=start_date, end_date=end_date, user_id=user_id)
        device_breakdown = cwa_db.get_device_breakdown(start_date=start_date, end_date=end_date, user_id=user_id)
        failed_logins = cwa_db.get_failed_logins(start_date=start_date, end_date=end_date)
    else:
        dashboard_stats = cwa_db.get_dashboard_stats(days=days, user_id=user_id)
        hourly_heatmap = cwa_db.get_hourly_activity_heatmap(days=days, user_id=user_id)
        reading_velocity = cwa_db.get_reading_velocity(days=days, user_id=user_id)
        format_preferences = cwa_db.get_format_preferences(days=days, user_id=user_id)
        discovery_sources = cwa_db.get_discovery_sources(days=days, user_id=user_id)
        device_breakdown = cwa_db.get_device_breakdown(days=days, user_id=user_id)
        failed_logins = cwa_db.get_failed_logins(days=days)
    
    # Get library stats (for Library tab)
    if start_date and end_date:
        library_growth = cwa_db.get_library_growth(start_date=start_date, end_date=end_date)
        library_formats = cwa_db.get_library_formats(start_date=start_date, end_date=end_date)
        conversion_stats = cwa_db.get_conversion_success_rate(start_date=start_date, end_date=end_date)
        books_added_stats = cwa_db.get_books_added_count(start_date=start_date, end_date=end_date)
    else:
        library_growth = cwa_db.get_library_growth(days=days)
        library_formats = cwa_db.get_library_formats(days=days)
        conversion_stats = cwa_db.get_conversion_success_rate(days=days)
        books_added_stats = cwa_db.get_books_added_count(days=days)
    
    # Get additional library stats (not time-dependent)
    series_completion = cwa_db.get_series_completion_stats(limit=10)
    publication_years = cwa_db.get_publication_year_distribution()
    most_fixed_books = cwa_db.get_most_fixed_books(limit=10)
    
    # Get Sprint 6 advanced library metrics
    if start_date and end_date:
        rating_statistics = cwa_db.get_rating_statistics(start_date=start_date, end_date=end_date)
    else:
        rating_statistics = cwa_db.get_rating_statistics(days=days)
    
    top_enforced_books = cwa_db.get_top_enforced_books(limit=10)
    import_source_flows = cwa_db.get_import_source_flows(limit=15)
    
    # Get Sprint 5 user activity enhancements
    if start_date and end_date:
        session_duration = cwa_db.get_session_duration_stats(start_date=start_date, end_date=end_date, user_id=user_id)
        search_success = cwa_db.get_search_success_rate(start_date=start_date, end_date=end_date, user_id=user_id)
        shelf_activity = cwa_db.get_shelf_activity_stats(start_date=start_date, end_date=end_date, user_id=user_id, limit=10)
        api_usage_breakdown = cwa_db.get_api_usage_breakdown(start_date=start_date, end_date=end_date, user_id=user_id)
        endpoint_frequency = cwa_db.get_endpoint_frequency_grouped(start_date=start_date, end_date=end_date, user_id=user_id, limit=20)
        api_timing = cwa_db.get_api_timing_heatmap(start_date=start_date, end_date=end_date, user_id=user_id)
    else:
        session_duration = cwa_db.get_session_duration_stats(days=days, user_id=user_id)
        search_success = cwa_db.get_search_success_rate(days=days, user_id=user_id)
        shelf_activity = cwa_db.get_shelf_activity_stats(days=days, user_id=user_id, limit=10)
        api_usage_breakdown = cwa_db.get_api_usage_breakdown(days=days, user_id=user_id)
        endpoint_frequency = cwa_db.get_endpoint_frequency_grouped(days=days, user_id=user_id, limit=20)
        api_timing = cwa_db.get_api_timing_heatmap(days=days, user_id=user_id)
    
    # Get system logs data
    data_enforcement = cwa_db.enforce_show(paths=False, verbose=False, web_ui=True)
    data_enforcement_with_paths = cwa_db.enforce_show(paths=True, verbose=False, web_ui=True)
    data_imports = cwa_db.get_import_history(verbose=False)
    data_conversions = cwa_db.get_conversion_history(verbose=False)
    data_epub_fixer = cwa_db.get_epub_fixer_history(fixes=False, verbose=False)
    data_epub_fixer_with_fixes = cwa_db.get_epub_fixer_history(fixes=True, verbose=False)

    return render_title_template("cwa_stats_tabs.html", title=_("Calibre-Web Automated Stats & Activity"),
                                page="cwa-stats",
                                active_tab=active_tab,
                                dashboard_stats=dashboard_stats,
                                hourly_heatmap=hourly_heatmap,
                                reading_velocity=reading_velocity,
                                format_preferences=format_preferences,
                                discovery_sources=discovery_sources,
                                device_breakdown=device_breakdown,
                                failed_logins=failed_logins,
                                session_duration=session_duration,
                                search_success=search_success,
                                shelf_activity=shelf_activity,
                                api_usage_breakdown=api_usage_breakdown,
                                endpoint_frequency=endpoint_frequency,
                                api_timing=api_timing,
                                library_growth=library_growth,
                                library_formats=library_formats,
                                conversion_stats=conversion_stats,
                                books_added_stats=books_added_stats,
                                series_completion=series_completion,
                                publication_years=publication_years,
                                most_fixed_books=most_fixed_books,
                                rating_statistics=rating_statistics,
                                top_enforced_books=top_enforced_books,
                                import_source_flows=import_source_flows,
                                date_range_label=date_range_label,
                                show_warning=show_warning,
                                start_date=start_date,
                                end_date=end_date,
                                days=days,
                                today=today,
                                is_admin=current_user.role_admin(),
                                active_users=active_users,
                                selected_user_id=user_id,
                                cwa_stats=get_cwa_stats(),
                                data_enforcement=data_enforcement, headers_enforcement=headers["enforcement"]["no_paths"], 
                                data_enforcement_with_paths=data_enforcement_with_paths, headers_enforcement_with_paths=headers["enforcement"]["with_paths"], 
                                data_imports=data_imports, headers_import=headers["imports"],
                                data_conversions=data_conversions, headers_conversion=headers["conversions"],
                                data_epub_fixer=data_epub_fixer, headers_epub_fixer=headers["epub_fixer"]["no_fixes"],
                                data_epub_fixer_with_fixes=data_epub_fixer_with_fixes, headers_epub_fixer_with_fixes=headers["epub_fixer"]["with_fixes"])


@cwa_stats.route("/cwa-stats-export-csv/<tab_name>", methods=["GET"])
@login_required_if_no_ano
@admin_required
def export_stats_csv(tab_name):
    """Export stats data as CSV for the specified tab."""
    import csv
    from io import StringIO
    from flask import make_response
    from datetime import datetime
    
    # Parse same filter parameters as main stats route
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    days_param = request.args.get('days')
    user_id = request.args.get('user_id', type=int)
    
    # Handle 'all' as special value
    if days_param == 'all':
        days = None
    else:
        days = int(days_param) if days_param else 30
    
    cwa_db = CWA_DB()
    output = StringIO()
    writer = csv.writer(output)
    
    try:
        if tab_name == 'activity':
            # User Activity Tab Export
            writer.writerow(['=== USER ACTIVITY STATISTICS ==='])
            writer.writerow([])
            
            # Dashboard stats
            if start_date and end_date:
                dashboard_stats = cwa_db.get_dashboard_stats(start_date=start_date, end_date=end_date, user_id=user_id)
            else:
                dashboard_stats = cwa_db.get_dashboard_stats(days=days, user_id=user_id)
            
            writer.writerow(['Metric', 'Value'])
            for key, value in dashboard_stats.get('totals', {}).items():
                writer.writerow([key, value])
            writer.writerow([])
            
            # Top users or most active days
            top_users = dashboard_stats.get('top_users', [])
            if user_id:
                writer.writerow(['=== MOST ACTIVE DAYS ==='])
                writer.writerow(['Date', 'Activity Count'])
                for day, count in top_users:
                    writer.writerow([day, count])
            else:
                writer.writerow(['=== TOP USERS ==='])
                writer.writerow(['User ID', 'Username', 'Event Count'])
                for uid, username, count in top_users:
                    writer.writerow([uid, username, count])
            writer.writerow([])
            
            # Format distribution
            writer.writerow(['=== FORMAT DISTRIBUTION ==='])
            writer.writerow(['Format', 'Download Count'])
            for format_name, count in dashboard_stats.get('format_distribution', []):
                writer.writerow([format_name, count])
            writer.writerow([])
            
            # Discovery sources
            writer.writerow(['=== DISCOVERY SOURCES ==='])
            writer.writerow(['Source', 'Access Count'])
            if start_date and end_date:
                discovery = cwa_db.get_discovery_sources(start_date=start_date, end_date=end_date, user_id=user_id)
            else:
                discovery = cwa_db.get_discovery_sources(days=days, user_id=user_id)
            for source, count in discovery:
                writer.writerow([source, count])
            writer.writerow([])
            
            # Device breakdown
            writer.writerow(['=== DEVICE BREAKDOWN ==='])
            writer.writerow(['Device', 'Access Count'])
            if start_date and end_date:
                devices = cwa_db.get_device_breakdown(start_date=start_date, end_date=end_date, user_id=user_id)
            else:
                devices = cwa_db.get_device_breakdown(days=days, user_id=user_id)
            for device, count in devices:
                writer.writerow([device, count])
            
        elif tab_name == 'library':
            # Library Stats Tab Export
            writer.writerow(['=== LIBRARY STATISTICS ==='])
            writer.writerow([])
            
            # Summary stats
            cwa_stats = get_cwa_stats()
            writer.writerow(['Total Books', cwa_stats['total_books']])
            if start_date and end_date:
                books_added = cwa_db.get_books_added_count(start_date=start_date, end_date=end_date)
                conversions = cwa_db.get_conversion_success_rate(start_date=start_date, end_date=end_date)
            else:
                books_added = cwa_db.get_books_added_count(days=days)
                conversions = cwa_db.get_conversion_success_rate(days=days)
            writer.writerow(['Books Added', books_added.get('total', 0)])
            writer.writerow(['Conversions', conversions.get('total', 0)])
            writer.writerow([])
            
            # Library growth
            writer.writerow(['=== LIBRARY GROWTH ==='])
            writer.writerow(['Date', 'Books Added'])
            if start_date and end_date:
                growth = cwa_db.get_library_growth(start_date=start_date, end_date=end_date)
            else:
                growth = cwa_db.get_library_growth(days=days)
            for date, count in growth:
                writer.writerow([date, count])
            writer.writerow([])
            
            # Format distribution
            writer.writerow(['=== FORMAT DISTRIBUTION ==='])
            writer.writerow(['Format', 'Book Count'])
            if start_date and end_date:
                formats = cwa_db.get_library_formats(start_date=start_date, end_date=end_date)
            else:
                formats = cwa_db.get_library_formats(days=days)
            for format_name, count in formats:
                writer.writerow([format_name, count])
            writer.writerow([])
            
            # Series completion
            writer.writerow(['=== SERIES STATISTICS ==='])
            writer.writerow(['Series Name', 'Book Count', 'Highest Index'])
            series = cwa_db.get_series_completion_stats(limit=50)
            for series_name, book_count, highest_index in series:
                writer.writerow([series_name, book_count, highest_index])
            writer.writerow([])
            
            # Rating statistics
            writer.writerow(['=== RATING STATISTICS ==='])
            if start_date and end_date:
                ratings = cwa_db.get_rating_statistics(start_date=start_date, end_date=end_date)
            else:
                ratings = cwa_db.get_rating_statistics(days=days)
            writer.writerow(['Average Rating', ratings.get('average_rating', 0)])
            writer.writerow(['Unrated Percentage', ratings.get('unrated_percentage', 0)])
            writer.writerow([])
            writer.writerow(['Stars', 'Book Count'])
            for stars, count in ratings.get('rating_distribution', []):
                writer.writerow([stars, count])
            writer.writerow([])
            
            # Top enforced books
            writer.writerow(['=== TOP ENFORCED BOOKS ==='])
            writer.writerow(['Book Title', 'Enforcement Count', 'Last Enforced'])
            top_enforced = cwa_db.get_top_enforced_books(limit=20)
            for book_id, title, count, last_enforced in top_enforced:
                writer.writerow([title, count, last_enforced])
            
        elif tab_name == 'api':
            # API Usage Tab Export
            writer.writerow(['=== API USAGE STATISTICS ==='])
            writer.writerow([])
            
            # API usage breakdown
            writer.writerow(['=== USAGE BREAKDOWN ==='])
            writer.writerow(['Category', 'Access Count'])
            if start_date and end_date:
                breakdown = cwa_db.get_api_usage_breakdown(start_date=start_date, end_date=end_date, user_id=user_id)
            else:
                breakdown = cwa_db.get_api_usage_breakdown(days=days, user_id=user_id)
            for category, count in breakdown:
                writer.writerow([category, count])
            writer.writerow([])
            
            # Endpoint frequency
            writer.writerow(['=== ENDPOINT ACCESS FREQUENCY ==='])
            writer.writerow(['Endpoint', 'Category', 'Access Count', 'Last Accessed'])
            if start_date and end_date:
                endpoints = cwa_db.get_endpoint_frequency_grouped(start_date=start_date, end_date=end_date, user_id=user_id, limit=50)
            else:
                endpoints = cwa_db.get_endpoint_frequency_grouped(days=days, user_id=user_id, limit=50)
            for endpoint, category, count, last_accessed in endpoints:
                writer.writerow([endpoint, category, count, last_accessed])
        
        else:
            # Unknown tab
            writer.writerow(['Error: Unknown tab name'])
        
        # Create response
        output.seek(0)
        csv_data = output.getvalue()
        response = make_response(csv_data)
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'cwa_stats_{tab_name}_{timestamp}.csv'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        log.error(f"Error generating CSV export for tab {tab_name}: {e}")
        import traceback
        traceback.print_exc()
        
        # Return error CSV
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Error generating export'])
        writer.writerow([str(e)])
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = 'attachment; filename="error.csv"'
        return response


@cwa_stats.route("/cwa-stats-debug", methods=["GET"])
@login_required_if_no_ano
@admin_required
def debug_stats_data():
    """Debug endpoint to inspect raw activity data and diagnose parsing issues."""
    try:
        cwa_db = CWA_DB()
        import json as json_module
        
        # Get sample of recent activity records WITHOUT json_extract to avoid errors
        cwa_db.cur.execute("""
            SELECT 
                timestamp,
                user_name,
                event_type,
                item_title,
                extra_data
            FROM cwa_user_activity
            WHERE event_type IN ('DOWNLOAD', 'READ', 'EMAIL', 'LOGIN')
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        
        records = []
        json_valid = 0
        json_invalid = 0
        
        for row in cwa_db.cur.fetchall():
            extra_data_raw = row[4]
            is_valid_json = False
            parsed_data = None
            error_msg = None
            
            # Try to parse as JSON
            if extra_data_raw:
                try:
                    parsed_data = json_module.loads(extra_data_raw)
                    is_valid_json = True
                    json_valid += 1
                except Exception as e:
                    is_valid_json = False
                    json_invalid += 1
                    error_msg = str(e)
            
            records.append({
                'timestamp': row[0],
                'user': row[1],
                'event': row[2],
                'item': row[3],
                'raw_extra_data': extra_data_raw,
                'is_valid_json': is_valid_json,
                'parsed_data': parsed_data,
                'parse_error': error_msg
            })
        
        # Get basic counts
        cwa_db.cur.execute("""
            SELECT 
                event_type,
                COUNT(*) as count,
                COUNT(extra_data) as with_extra_data
            FROM cwa_user_activity
            GROUP BY event_type
            ORDER BY count DESC
        """)
        
        event_counts = [{'event_type': row[0], 'total': row[1], 'with_extra_data': row[2]} 
                       for row in cwa_db.cur.fetchall()]
        
        # Try to get valid JSON count (might fail, that's okay)
        json_stats = {
            'valid_in_sample': json_valid,
            'invalid_in_sample': json_invalid,
            'sample_size': len(records)
        }
        
        return jsonify({
            'event_counts': event_counts,
            'json_stats': json_stats,
            'sample_records': records[:20]  # Only return first 20 to keep response size manageable
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@cwa_stats.route('/cwa-scheduled/upcoming', methods=["GET"])
@login_required_if_no_ano
@admin_required
def cwa_scheduled_upcoming():
    try:
        from cwa_db import CWA_DB
        db = CWA_DB()
        rows = db.scheduled_get_upcoming_autosend(limit=100)
        return jsonify({"items": rows}), 200
    except Exception as e:
        log.error(f"Error fetching upcoming scheduled sends: {e}")
        return jsonify({"items": []}), 200

@cwa_stats.route('/cwa-scheduled/upcoming-ops', methods=["GET"])
@login_required_if_no_ano
@admin_required
def cwa_scheduled_upcoming_ops():
    """Return upcoming scheduled operations (non auto-send), e.g., convert_library, epub_fixer."""
    try:
        db = CWA_DB()
        ops = []
        for jt in ('convert_library', 'epub_fixer'):
            ops.extend(db.scheduled_get_upcoming_by_type(jt, limit=100))
        # sort by time ascending
        ops.sort(key=lambda r: r.get('run_at_utc') or '')
        return jsonify({"items": ops}), 200
    except Exception as e:
        log.error(f"Error fetching upcoming scheduled ops: {e}")
        return jsonify({"items": []}), 200
                                    
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

@convert_library.route('/cwa-convert-library/schedule/<int:delay>', methods=["GET"])
@login_required_if_no_ano
@admin_required
def schedule_convert_library(delay: int):
    # Clamp delay to sane range
    delay = max(0, min(60, int(delay)))
    try:
        import requests
        username = getattr(current_user, 'name', 'System') or 'System'
        url = helper.get_internal_api_url("/cwa-internal/schedule-convert-library")
        resp = requests.post(url, json={"delay_minutes": delay, "username": username}, timeout=10, verify=False)
        if resp.ok:
            flash(_(f"Convert Library scheduled in {delay} minute(s)."), category="success")
        else:
            flash(_(f"Failed to schedule Convert Library: {resp.text}"), category="error")
    except Exception as e:
        flash(_(f"Failed to schedule Convert Library: {e}"), category="error")
    return redirect(url_for('convert_library.show_convert_library_page'))

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

@epub_fixer.route('/cwa-epub-fixer/schedule/<int:delay>', methods=["GET"])
@login_required_if_no_ano
@admin_required
def schedule_epub_fixer(delay: int):
    delay = max(0, min(60, int(delay)))
    try:
        import requests
        username = getattr(current_user, 'name', 'System') or 'System'
        url = helper.get_internal_api_url("/cwa-internal/schedule-epub-fixer")
        resp = requests.post(url, json={"delay_minutes": delay, "username": username}, timeout=10, verify=False)
        if resp.ok:
            flash(_(f"EPUB Fixer scheduled in {delay} minute(s)."), category="success")
        else:
            flash(_(f"Failed to schedule EPUB Fixer: {resp.text}"), category="error")
    except Exception as e:
        flash(_(f"Failed to schedule EPUB Fixer: {e}"), category="error")
    return redirect(url_for('epub_fixer.show_epub_fixer_page'))

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
            return redirect(url_for('profile_pictures.set_profile_picture'))

        # Validate Base64 image data format
        try:
            # Check if image_data starts with a valid data URI scheme
            if not image_data.startswith('data:image/'):
                flash(_("Invalid image data format. Must be a valid image."), category="error")
                log.warning(f"Invalid image data format from user: {username}")
                return redirect(url_for('profile_pictures.set_profile_picture'))
            
            # Verify it's a supported image type (PNG or JPEG)
            if not (image_data.startswith('data:image/png;base64,') or 
                    image_data.startswith('data:image/jpeg;base64,') or
                    image_data.startswith('data:image/jpg;base64,')):
                flash(_("Unsupported image type. Only PNG and JPEG are allowed."), category="error")
                log.warning(f"Unsupported image type from user: {username}")
                return redirect(url_for('profile_pictures.set_profile_picture'))
            
            # Extract and validate the Base64 portion
            if ';base64,' in image_data:
                base64_part = image_data.split(';base64,')[1]
                # Try to decode to verify it's valid Base64
                try:
                    decoded = base64.b64decode(base64_part, validate=True)
                    # Check size (limit to 500KB decoded)
                    if len(decoded) > 512000:
                        flash(_("Image is too large. Please use an image smaller than 500KB."), category="error")
                        log.warning(f"Image too large from user: {username}, size: {len(decoded)} bytes")
                        return redirect(url_for('profile_pictures.set_profile_picture'))
                except Exception as decode_error:
                    flash(_("Invalid Base64 image data."), category="error")
                    log.warning(f"Invalid Base64 data from user: {username}, error: {str(decode_error)}")
                    return redirect(url_for('profile_pictures.set_profile_picture'))
            else:
                flash(_("Invalid image data format."), category="error")
                log.warning(f"Invalid image data format (no base64 marker) from user: {username}")
                return redirect(url_for('profile_pictures.set_profile_picture'))
                
        except Exception as validation_error:
            flash(_("Error validating image data."), category="error")
            log.error(f"Image validation error: {str(validation_error)}")
            return redirect(url_for('profile_pictures.set_profile_picture'))

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
