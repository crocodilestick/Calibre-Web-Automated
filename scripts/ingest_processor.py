# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import sqlite3
import fcntl
import threading
from pathlib import Path

from cwa_db import CWA_DB
from kindle_epub_fixer import EPUBFixer
import audiobook
import requests

# Optional: enable GDrive sync and auto-send by importing cps modules when available
_GDRIVE_AVAILABLE = False
_CPS_AVAILABLE = False
_gdriveutils = None
_cps_config = None
fetch_and_apply_metadata = None
TaskAutoSend = None
WorkerThread = None
_ub = None

# Debounced duplicate scan timer
_duplicate_scan_timer = None
_duplicate_scan_lock = threading.Lock()

class ProcessLock:
    """Robust process lock using both file locking and PID tracking"""

    def __init__(self, lock_name="ingest_processor"):
        self.lock_name = lock_name
        self.lock_path = os.path.join(tempfile.gettempdir(), f"{lock_name}.lock")
        self.lock_file = None
        self.acquired = False

    def acquire(self, timeout=5):
        """Acquire the lock with timeout. Returns True if successful, False if another process has it."""
        try:
            # Try to open/create the lock file
            self.lock_file = open(self.lock_path, 'w+')

            # Try to acquire an exclusive lock with timeout
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                    # Successfully acquired lock, write our PID
                    self.lock_file.seek(0)
                    self.lock_file.write(str(os.getpid()))
                    self.lock_file.flush()
                    self.lock_file.truncate()  # Truncate at current position to remove any leftover data

                    self.acquired = True
                    print(f"[ingest-processor] Lock acquired successfully (PID: {os.getpid()})")
                    return True

                except (IOError, OSError):
                    # Lock is held by another process
                    # Check if the holding process is still alive
                    if self._check_stale_lock():
                        continue  # Try again as we cleaned up a stale lock
                    time.sleep(0.1)  # Brief wait before retry

            # Timeout reached
            holding_pid = self._get_holding_pid()
            print(f"[ingest-processor] CANCELLING... ingest-processor initiated but is already running (PID: {holding_pid})")
            self.release()
            return False

        except Exception as e:
            print(f"[ingest-processor] Error acquiring lock: {e}")
            self.release()
            return False

    def _get_holding_pid(self):
        """Get the PID of the process holding the lock"""
        try:
            if self.lock_file:
                self.lock_file.seek(0)
                pid_str = self.lock_file.read().strip()
                return int(pid_str) if pid_str.isdigit() else "unknown"
        except:
            pass
        return "unknown"

    def _check_stale_lock(self):
        """Check if the lock is stale (holding process no longer exists) and clean it up"""
        try:
            if not self.lock_file:
                return False

            self.lock_file.seek(0)
            pid_str = self.lock_file.read().strip()

            if not pid_str.isdigit():
                print("[ingest-processor] Lock file contains invalid PID, treating as stale")
                return self._cleanup_stale_lock()

            holding_pid = int(pid_str)

            # Check if process is still running
            try:
                os.kill(holding_pid, 0)  # Signal 0 just checks if process exists
                return False  # Process is still running
            except ProcessLookupError:
                # Process doesn't exist, lock is stale
                print(f"[ingest-processor] Detected stale lock from non-existent process {holding_pid}, cleaning up")
                return self._cleanup_stale_lock()
            except PermissionError:
                # Process exists but we can't signal it (different user), assume it's running
                return False

        except Exception as e:
            print(f"[ingest-processor] Error checking stale lock: {e}")
            return False

    def _cleanup_stale_lock(self):
        """Clean up a stale lock file"""
        try:
            if self.lock_file:
                try:
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                except (OSError, IOError):
                    # We might not have had the lock in the first place
                    pass
                self.lock_file.close()
                self.lock_file = None

            # Remove the lock file
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
                print(f"[ingest-processor] Cleaned up stale lock file: {self.lock_path}")

            return True
        except Exception as e:
            print(f"[ingest-processor] Error cleaning up stale lock: {e}")
            return False

    def release(self):
        """Release the lock"""
        if self.acquired and self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                self.lock_file = None

                # Remove lock file
                if os.path.exists(self.lock_path):
                    os.remove(self.lock_path)

                self.acquired = False
                print(f"[ingest-processor] Lock released (PID: {os.getpid()})")
            except Exception as e:
                print(f"[ingest-processor] Error releasing lock: {e}")
        elif self.lock_file:
            # Clean up even if we didn't successfully acquire
            try:
                self.lock_file.close()
                self.lock_file = None
            except:
                pass

# Global lock instance
process_lock = ProcessLock()

def cleanup_lock():
    """Cleanup function for atexit"""
    process_lock.release()

# Register cleanup function
atexit.register(cleanup_lock)


def get_app_db_path() -> str:
    """Resolve app.db path consistently with the main app config."""
    app_db_path = os.environ.get("CWA_APP_DB_PATH")
    if app_db_path:
        return app_db_path
    base_path = os.environ.get("CALIBRE_DBPATH", "/config")
    if base_path.endswith(".db"):
        if os.path.basename(base_path) != "app.db":
            return os.path.join(os.path.dirname(base_path), "app.db")
        return base_path
    return os.path.join(base_path, "app.db")


def _load_cps_settings_from_app_db() -> None:
    """Load minimal CPS settings needed for GDrive + internal HTTPS handling."""
    if not _cps_config:
        return
    try:
        app_db_path = get_app_db_path()
        with sqlite3.connect(app_db_path, timeout=30) as con:
            cur = con.cursor()
            row = cur.execute(
                "SELECT config_use_google_drive, config_google_drive_folder, "
                "config_calibre_dir, config_certfile, config_keyfile "
                "FROM settings LIMIT 1"
            ).fetchone()
            if not row:
                return

            _cps_config.config_use_google_drive = bool(row[0]) if row[0] is not None else False
            _cps_config.config_google_drive_folder = row[1]
            if row[2]:
                _cps_config.config_calibre_dir = row[2]
            if row[3]:
                _cps_config.config_certfile = row[3]
            if row[4]:
                _cps_config.config_keyfile = row[4]
    except Exception as e:
        print(f"[ingest-processor] WARN: Could not read CPS settings from app.db ({app_db_path}): {e}", flush=True)

try:
    # Ensure project root is on sys.path to import cps
    cps_path = os.path.dirname(os.path.dirname(__file__))
    if cps_path not in sys.path:
        sys.path.append(cps_path)

    # Import GDrive functionality
    try:
        from cps import gdriveutils as _gdriveutils, config as _cps_config
        _GDRIVE_AVAILABLE = True
        print("[ingest-processor] GDrive functionality available", flush=True)
        _load_cps_settings_from_app_db()
    except (ImportError, TypeError, AttributeError) as e:
        print(f"[ingest-processor] GDrive functionality not available: {e}", flush=True)
        _gdriveutils = None
        _cps_config = None
        _GDRIVE_AVAILABLE = False

    # Import auto-send and metadata functionality
    try:
        from cps.metadata_helper import fetch_and_apply_metadata
        from cps.tasks.auto_send import TaskAutoSend
        from cps.services.worker import WorkerThread
        from cps import ub as _ub
        from cps.calibre_init import init_calibre_db_from_app_db
        init_calibre_db_from_app_db(get_app_db_path())
        _CPS_AVAILABLE = True
        print("[ingest-processor] Auto-send and metadata functionality available", flush=True)
    except ImportError as e:
        print(f"[ingest-processor] Auto-send/metadata functionality not available: {e}", flush=True)
        fetch_and_apply_metadata = None
        TaskAutoSend = None
        WorkerThread = None
        _ub = None
        _CPS_AVAILABLE = False

except Exception as e:
    print(f"[ingest-processor] WARN: Unexpected error during CPS path setup: {e}", flush=True)
    # Only disable if there's a fundamental path/import issue
    if '_GDRIVE_AVAILABLE' not in locals():
        _GDRIVE_AVAILABLE = False
    if '_CPS_AVAILABLE' not in locals():
        _CPS_AVAILABLE = False

def gdrive_sync_if_enabled():
    """Sync Calibre library to Google Drive if enabled in app config."""
    if _GDRIVE_AVAILABLE and getattr(_cps_config, "config_use_google_drive", False):
        try:
            _gdriveutils.updateGdriveCalibreFromLocal()
            print("[ingest-processor] GDrive sync completed.", flush=True)
        except Exception as e:
            print(f"[ingest-processor] WARN: GDrive sync failed: {e}", flush=True)

# Acquire process lock to prevent concurrent execution
if not process_lock.acquire(timeout=10):
    sys.exit(2)

# Ensure processed backups directory structure exists so backups never crash on missing folders
try:
    _processed_root = "/config/processed_books"
    os.makedirs(_processed_root, exist_ok=True)
    for _name in ("converted", "imported", "fixed_originals", "failed"):
        os.makedirs(os.path.join(_processed_root, _name), exist_ok=True)
except Exception as e:
    print(f"[ingest-processor] WARN: Could not ensure processed_books directories: {e}", flush=True)

# Generates dictionary of available backup directories and their paths
try:
    backup_destinations = {
            entry.name: entry.path
            for entry in os.scandir("/config/processed_books")
            if entry.is_dir()
        }
except FileNotFoundError:
    # Fallback for test environments where /config might not exist
    backup_destinations = {}
except Exception as e:
    print(f"[ingest-processor] WARN: Could not scan processed_books: {e}", flush=True)
    backup_destinations = {}

def get_internal_api_url(path):
    """Construct internal API URL, respecting SSL configuration"""
    port = os.getenv('CWA_PORT_OVERRIDE', '8083').strip()
    if not port.isdigit():
        port = '8083'
    
    protocol = "http"
    certfile = None
    keyfile = None
    if _cps_config:
        certfile = getattr(_cps_config, "config_certfile", None)
        keyfile = getattr(_cps_config, "config_keyfile", None)
    if not certfile and not keyfile:
        try:
            app_db_path = get_app_db_path()
            with sqlite3.connect(app_db_path, timeout=30) as con:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT config_certfile, config_keyfile FROM settings LIMIT 1"
                ).fetchone()
                if row:
                    certfile, keyfile = row[0], row[1]
        except Exception as e:
            print(f"[ingest-processor] WARN: Could not read TLS settings from app.db ({app_db_path}): {e}", flush=True)

    if certfile and keyfile and os.path.isfile(certfile) and os.path.isfile(keyfile):
        protocol = "https"
            
    if not path.startswith("/"):
        path = "/" + path
        
    return f"{protocol}://127.0.0.1:{port}{path}"


def get_internal_api_headers():
    """Provide headers that satisfy localhost-only internal endpoint checks."""
    return {"X-Forwarded-For": "127.0.0.1"}

class NewBookProcessor:
    def __init__(self, filepath: str):
        # Settings / DB
        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

        # Core ingest settings
        self.auto_convert_on = self.cwa_settings['auto_convert']
        self.target_format = self.cwa_settings['auto_convert_target_format']
        self.ingest_ignored_formats = self.cwa_settings['auto_ingest_ignored_formats']
        if isinstance(self.ingest_ignored_formats, str):
            self.ingest_ignored_formats = [self.ingest_ignored_formats]

        # Add known temporary / partial extensions
        for tmp_ext in ("crdownload", "download", "part", "uploading", "temp"):
            if tmp_ext not in self.ingest_ignored_formats:
                self.ingest_ignored_formats.append(tmp_ext)

        self.convert_ignored_formats = self.cwa_settings['auto_convert_ignored_formats']
        self.convert_retained_formats = self.cwa_settings.get('auto_convert_retained_formats', [])
        if isinstance(self.convert_retained_formats, str):
            self.convert_retained_formats = self.convert_retained_formats.split(',') if self.convert_retained_formats else []
        self.is_kindle_epub_fixer = self.cwa_settings['kindle_epub_fixer']

        # Formats
        self.supported_book_formats = {
            'acsm','azw','azw3','azw4','cbz','cbr','cb7','cbc','chm','djvu','docx','epub','fb2','fbz','html','htmlz','kepub','kfx','kfx-zip','lit','lrf','mobi','odt','pdf','prc','pdb','pml','rb','rtf','snb','tcr','txtz','txt'
        }
        self.hierarchy_of_success = {
            'epub','kepub','lit','mobi','azw','azw3','fb2','fbz','azw4','prc','odt','lrf','pdb','cbz','pml','rb','cbr','cb7','cbc','chm','djvu','snb','tcr','pdf','docx','rtf','html','htmlz','txtz','txt'
        }
        self.supported_audiobook_formats = {'m4b', 'm4a', 'mp4'}

        # Directories
        self.ingest_folder, self.library_dir, self.tmp_conversion_dir = self.get_dirs("/app/calibre-web-automated/dirs.json")
        self.ingest_folder = os.path.normpath(self.ingest_folder)
        # Ensure library_dir is consistent with the main app's config
        app_db_path = get_app_db_path()
        with sqlite3.connect(app_db_path, timeout=30) as con:
            cur = con.cursor()
            try:
                db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
                if db_path:
                    self.library_dir = db_path
            except Exception as e:
                print(f"[ingest-processor] WARN: Could not read config_calibre_dir from app.db ({app_db_path}), using default. Error: {e}", flush=True)

        Path(self.tmp_conversion_dir).mkdir(exist_ok=True)
        self.staging_dir = os.path.join(self.tmp_conversion_dir, "staging")
        Path(self.staging_dir).mkdir(exist_ok=True)

        # Current file
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.can_convert, self.input_format = self.can_convert_check()
        # Determine if the file is already in the desired target format using normalized extensions
        self.is_target_format = (self.input_format.lower() == str(self.target_format).lower())

        # Calibre environment
        self.calibre_env = os.environ.copy()
        self.calibre_env["HOME"] = "/config"  # Enable plugins under /config

        self.metadata_db = os.path.join(self.library_dir, "metadata.db")
        # Split library support
        self.split_library = self.get_split_library()
        if self.split_library:
            self.calibre_env['CALIBRE_OVERRIDE_DATABASE_PATH'] = self.metadata_db
            self.library_dir = self.split_library["split_path"]

        # Track the last added Calibre book id(s) from calibredb output
        self.last_added_book_id: int | None = None
        self.last_added_book_ids: list[int] = []
        self._title_sort_regex = self._get_title_sort_regex()

    @staticmethod
    def _get_title_sort_regex() -> str:
        default_regex = (
            r'^(A|The|An|Der|Die|Das|Den|Ein|Eine|Einen|Dem|Des|Einem|Eines|Le|La|Les|L\'|Un|Une)\s+'
        )
        try:
            app_db_path = get_app_db_path()
            with sqlite3.connect(app_db_path, timeout=30) as con:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT config_title_regex FROM settings LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    return row[0]
        except Exception as e:
            print(f"[ingest-processor] WARN: Could not read config_title_regex from app.db ({app_db_path}): {e}", flush=True)
        return default_regex

    @staticmethod
    def _parse_added_book_ids(output: str) -> list[int]:
        """Parse calibredb stdout for the 'Added/Merged/Updated book ids: X[, Y, ...]' line and return IDs.

        Handles variations like 'Added book id: 4' or 'Merged book ids: 4, 5'.
        """
        try:
            import re
            m = re.search(r"(?:Added|Merged|Updated) book id[s]?:\s*([0-9,\s]+)", output, flags=re.IGNORECASE)
            if not m:
                return []
            nums = m.group(1)
            ids = [int(x.strip()) for x in nums.split(',') if x.strip().isdigit()]
            return ids
        except Exception:
            return []

    def _fallback_last_added_book_id(self) -> None:
        """Fallback to the most recently modified book when calibredb output lacks IDs."""
        if self.last_added_book_id is not None:
            return
        try:
            with sqlite3.connect(self.metadata_db, timeout=30) as con:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT id FROM books ORDER BY last_modified DESC LIMIT 1"
                ).fetchone()
                if row:
                    self.last_added_book_id = int(row[0])
                    self.last_added_book_ids = [self.last_added_book_id]
                    print(
                        "[ingest-processor] WARN: Could not parse calibredb output; using most recently modified book ID.",
                        flush=True,
                    )
        except Exception as e:
            print(f"[ingest-processor] WARN: Failed to infer book ID after import: {e}", flush=True)

    def _register_title_sort_function(self, connection: sqlite3.Connection) -> bool:
        """Register title_sort SQL function on a raw SQLite connection."""
        try:
            import re
            title_pat = re.compile(self._title_sort_regex, re.IGNORECASE)

            def _title_sort(title):
                if title is None:
                    title = ""
                match = title_pat.search(title)
                if match:
                    prep = match.group(1)
                    title = title[len(prep):] + ', ' + prep
                return " ".join(str(title).split())

            connection.create_function("title_sort", 1, _title_sort)
            return True
        except Exception as e:
            print(f"[ingest-processor] WARN: Could not register title_sort function: {e}", flush=True)
            return False
    def get_split_library(self) -> dict[str, str] | None:
        """Checks whether or not the user has split library enabled. Returns None if they don't and the path of the Split Library location if True."""
        app_db_path = get_app_db_path()
        with sqlite3.connect(app_db_path, timeout=30) as con:
            cur = con.cursor()
            split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

            if split_library:
                split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
                db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
                return {
                    "split_path": split_path,
                    "db_path": db_path,
                }
            else:
                return None


    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/"
        library_dir = f"{dirs['calibre_library_dir']}/"
        tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

        return ingest_folder, library_dir, tmp_conversion_dir


    def can_convert_check(self) -> tuple[bool, str]:
        """When the current filepath isn't of the target format, this function will check if the file is able to be converted to the target format,
        returning a can_convert bool with the answer"""
        can_convert = False
        input_format = Path(self.filepath).suffix[1:].lower()
        if input_format in self.supported_book_formats:
            can_convert = True
        return can_convert, input_format

    def is_supported_audiobook(self) -> bool:
        input_format = Path(self.filepath).suffix[1:].lower()
        if input_format in self.supported_audiobook_formats:
            return True
        else:
            return False

    def backup(self, input_file, backup_type):
        output_path = None
        try:
            output_path = backup_destinations.get(backup_type)
            if not output_path:
                raise KeyError(f"No backup destination for type '{backup_type}'")
            # Ensure destination directory exists
            os.makedirs(output_path, exist_ok=True)
            destination = shutil.copy(input_file, output_path)
            os.utime(destination, None)
        except Exception as e:
            # Never let backups crash ingest; just log the problem
            print(f"[ingest-processor]: ERROR - Failed to backup '{input_file}' to '{output_path}': {e}")


    def convert_book(self, end_format=None) -> tuple[bool, str]:
        """Uses the following terminal command to convert the books provided using the calibre converter tool:\n\n--- ebook-convert myfile.input_format myfile.output_format\n\nAnd then saves the resulting files to the calibre-web import folder."""
        print(f"[ingest-processor]: Starting conversion process for {self.filename}...", flush=True)
        print(f"[ingest-processor]: Converting file from {self.input_format} to {self.target_format} format...\n", flush=True)
        print(f"\n[ingest-processor]: START_CON: Converting {self.filename}...\n", flush=True)

        if end_format == None:
            end_format = self.target_format # If end_format isn't given, the file is converted to the target format specified in the CWA Settings page

        original_filepath = Path(self.filepath)
        target_filepath = f"{self.tmp_conversion_dir}{original_filepath.stem}.{end_format}"
        try:
            t_convert_book_start = time.time()
            subprocess.run(['ebook-convert', self.filepath, target_filepath], env=self.calibre_env, check=True)
            t_convert_book_end = time.time()
            time_book_conversion = t_convert_book_end - t_convert_book_start
            print(f"\n[ingest-processor]: END_CON: Conversion of {self.filename} complete in {time_book_conversion:.2f} seconds.\n", flush=True)

            if self.cwa_settings['auto_backup_conversions']:
                self.backup(self.filepath, backup_type="converted")

            self.db.conversion_add_entry(original_filepath.stem,
                                        self.input_format,
                                        self.target_format,
                                        str(self.cwa_settings["auto_backup_conversions"]))

            return True, target_filepath

        except subprocess.CalledProcessError as e:
            print(f"\n[ingest-processor]: CON_ERROR: {self.filename} could not be converted to {end_format} due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}", flush=True)
            self.backup(self.filepath, backup_type="failed")
            return False, ""


    # Kepubify can only convert EPUBs to Kepubs
    def convert_to_kepub(self) -> tuple[bool,str]:
        """Kepubify is limited in that it can only convert from epubs. To get around this, CWA will automatically convert other
        supported formats to epub using the Calibre's conversion tools & then use Kepubify to produce your desired kepubs. Obviously multi-step conversions aren't ideal
        so if you notice issues with your converted files, bare in mind starting with epubs will ensure the best possible results"""
        if self.input_format == "epub":
            print(f"[ingest-processor]: File in epub format, converting directly to kepub...", flush=True)
            converted_filepath = self.filepath
            convert_successful = True
        else:
            print("\n[ingest-processor]: *** NOTICE TO USER: Kepubify is limited in that it can only convert from epubs. To get around this, CWA will automatically convert other"
            "supported formats to epub using the Calibre's conversion tools & then use Kepubify to produce your desired kepubs. Obviously multi-step conversions aren't ideal"
            "so if you notice issues with your converted files, bare in mind starting with epubs will ensure the best possible results***\n", flush=True)
            convert_successful, converted_filepath = self.convert_book(end_format="epub") # type: ignore

        if convert_successful:
            converted_filepath = Path(converted_filepath)
            target_filepath = f"{self.tmp_conversion_dir}{converted_filepath.stem}.kepub"
            try:
                subprocess.run(['kepubify', '--inplace', '--calibre', '--output', self.tmp_conversion_dir, converted_filepath], check=True)
                if self.cwa_settings['auto_backup_conversions']:
                    self.backup(self.filepath, backup_type="converted")

                self.db.conversion_add_entry(converted_filepath.stem,
                                            self.input_format,
                                            self.target_format,
                                            str(self.cwa_settings["auto_backup_conversions"]))

                return True, target_filepath

            except subprocess.CalledProcessError as e:
                print(f"[ingest-processor]: CON_ERROR: {self.filename} could not be converted to kepub due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}", flush=True)
                self.backup(converted_filepath, backup_type="failed")
                return False, ""
            except Exception as e:
                print(f"[ingest-processor] ingest-processor ran into the following error:\n{e}", flush=True)
        else:
            print(f"[ingest-processor]: An error occurred when converting the original {self.input_format} to epub. Cancelling kepub conversion...", flush=True)
            return False, ""


    def delete_current_file(self) -> None:
        """Deletes file just processed from ingest folder"""
        try:
            ext = Path(self.filename).suffix.replace('.', '')
            if ext in self.ingest_ignored_formats or self.filename.endswith(".cwa.json") or self.filename.endswith(".cwa.failed.json"):
                print(f"[ingest-processor] Skipping delete for ignored/temporary file: {self.filename}", flush=True)
                return
            if os.path.exists(self.filepath):
                os.remove(self.filepath) # Removes processed file
            else:
                # Likely a transient/temporary file (.uploading) that was renamed before we processed cleanup
                print(f"[ingest-processor] Skipping delete; file already gone: {self.filepath}", flush=True)
                return

            parent_dir = os.path.dirname(self.filepath)
            # Only attempt folder cleanup if parent still exists and isn't the ingest root
            if os.path.isdir(parent_dir) and os.path.exists(parent_dir):
                try:
                    if os.path.exists(self.ingest_folder) and os.path.normpath(parent_dir) != self.ingest_folder:
                        subprocess.run(["find", parent_dir, "-type", "d", "-empty", "-delete"], check=False)
                except Exception as e:
                    print(f"[ingest-processor] WARN: Failed pruning empty folders for {parent_dir}: {e}", flush=True)
        except Exception as e:
            print(f"[ingest-processor] WARN: Failed to delete processed file {self.filepath}: {e}", flush=True)

    def is_file_in_use(self, timeout: float = None) -> bool:
        """Wait until the file is no longer in use (write handle is closed) or timeout is reached.
        Returns True if file is ready, False if timed out or file vanished."""

        # Use configured timeout from CWA settings (default 15 minutes if not configured)
        if timeout is None:
            timeout_minutes = self.cwa_settings.get('ingest_timeout_minutes', 15)
            timeout = timeout_minutes * 60  # Convert to seconds

        start = time.time()
        while time.time() - start < timeout:
            if not os.path.exists(self.filepath):
                return False
            try:
                # lsof '-F f' gets file access mode; we check for 'w' (write).
                # Add timeout to prevent hanging (issue #654)
                result = subprocess.run(['lsof', '-F', 'f', '--', self.filepath],
                                      capture_output=True, text=True, timeout=10)
                if 'w' not in result.stdout:
                    return True # Not in use for writing
            except subprocess.TimeoutExpired:
                print("[ingest-processor] WARN: lsof command timed out. Assuming file is not in use.", flush=True)
                return True  # If lsof hangs, assume file is ready to avoid indefinite wait
            except FileNotFoundError:
                print("[ingest-processor] WARN: 'lsof' command not found. Cannot reliably check if file is in use. Proceeding with caution.", flush=True)
                return True # Fallback for systems without lsof
            except Exception as e:
                print(f"[ingest-processor] WARN: Error checking file usage with lsof: {e}", flush=True)
                # On error, wait and retry to be safe
            time.sleep(1)
        return False # Timeout reached



    def add_book_to_library(self, book_path:str, text: bool=True, format: str="text" ) -> None:
        # If kindle-epub-fixer is on, run it first and import the *fixed* file.
        if self.target_format == "epub" and self.is_kindle_epub_fixer:
            fixed_epub_path = Path(self.tmp_conversion_dir) / os.path.basename(book_path)
            self.run_kindle_epub_fixer(book_path, dest=self.tmp_conversion_dir)
            try:
                # Use the fixed path only if the fixer succeeded and created a non-empty file
                if fixed_epub_path.exists() and fixed_epub_path.stat().st_size > 0:
                    book_path = str(fixed_epub_path)
                else:
                    print(f"[ingest-processor] WARN: Kindle EPUB fixer did not produce a valid output file. Importing original.", flush=True)
            except OSError as e:
                if e.errno == 36: # Filename too long
                    print(f"[ingest-processor] Skipping file due to OS path length error: {book_path}", flush=True)
                    return
                else:
                    print(f"[ingest-processor] An error occurred while checking the fixed EPUB path on {book_path}:\n{e}", flush=True)
                    raise

        # Capture the current max(timestamp) in Calibre DB so we can detect rows whose last_modified was bumped by an overwrite
        pre_import_max_timestamp = None
        if self.cwa_settings.get('auto_ingest_automerge') == 'overwrite':
            try:
                with sqlite3.connect(self.metadata_db, timeout=30) as con:
                    cur = con.cursor()
                    pre_import_max_timestamp = cur.execute('SELECT MAX(timestamp) FROM books').fetchone()[0]
            except Exception as e:
                print(f"[ingest-processor] WARN: Could not read pre-import max timestamp: {e}", flush=True)

        print("[ingest-processor]: Importing new book to CWA...")
        source_path = Path(book_path)
        if not source_path.exists() or source_path.stat().st_size == 0:
            print(f"[ingest-processor] ERROR: Import file is missing or empty, skipping: {book_path}", flush=True)
            self.backup(self.filepath, backup_type="failed") # Backup original file
            return

        # Stage file for import
        staged_path = Path(self.staging_dir) / source_path.name
        try:
            shutil.copy2(source_path, staged_path)
        except Exception as e:
            print(f"[ingest-processor] ERROR: Failed to stage file for import: {e}", flush=True)
            self.backup(self.filepath, backup_type="failed")
            return

        try:
            if text:
                result = subprocess.run([
                    "calibredb", "add", str(staged_path), "--automerge", self.cwa_settings['auto_ingest_automerge'], f"--library-path={self.library_dir}"
                ], env=self.calibre_env, check=True, capture_output=True, text=True)
                added_ids = self._parse_added_book_ids((result.stdout or '') + '\n' + (result.stderr or ''))
                if added_ids:
                    self.last_added_book_ids = added_ids
                    self.last_added_book_id = added_ids[-1]
                else:
                    self._fallback_last_added_book_id()
            else:  # audiobook path
                meta = audiobook.get_audio_file_info(str(staged_path), format, os.path.basename(str(staged_path)), False)

                # Coalesce metadata to safe strings
                _title = str(meta[2]) if meta[2] else Path(staged_path).stem
                _authors = str(meta[3]) if meta[3] else ""
                _tags = str(meta[6]) if meta[6] else ""
                _series = str(meta[7]) if meta[7] else ""
                _series_index = str(meta[8]) if meta[8] is not None and meta[8] != "" else None
                _languages = str(meta[9]) if meta[9] else ""
                _cover = meta[4] if meta[4] and isinstance(meta[4], str) else None

                add_command = [
                    "calibredb", "add", str(staged_path), "--automerge", self.cwa_settings['auto_ingest_automerge'],
                    f"--library-path={self.library_dir}",
                ]
                if _title:
                    add_command.extend(["--title", _title])
                if _authors:
                    add_command.extend(["--authors", _authors])
                if _tags:
                    add_command.extend(["--tags", _tags])
                if _series:
                    add_command.extend(["--series", _series])
                if _series_index:
                    add_command.extend(["--series-index", str(_series_index)])
                if _languages:
                    add_command.extend(["--languages", _languages])
                if _cover and os.path.exists(_cover):
                    add_command.extend(["--cover", _cover])

                # Add identifiers if present; expect entries like "isbn:12345"
                try:
                    identifiers_list = meta[12] if isinstance(meta[12], (list, tuple)) else []
                except Exception:
                    identifiers_list = []
                for ident in identifiers_list:
                    if isinstance(ident, str) and ":" in ident and ident.strip():
                        add_command.extend(["--identifier", ident.strip()])

                result = subprocess.run(add_command, env=self.calibre_env, check=True, capture_output=True, text=True)
                added_ids = self._parse_added_book_ids((result.stdout or '') + '\n' + (result.stderr or ''))
                if added_ids:
                    self.last_added_book_ids = added_ids
                    self.last_added_book_id = added_ids[-1]
                else:
                    self._fallback_last_added_book_id()
            print(f"[ingest-processor] Added {staged_path.stem} to Calibre database", flush=True)

            if self.cwa_settings['auto_backup_imports']:
                self.backup(str(staged_path), backup_type="imported")

            self.db.import_add_entry(staged_path.stem,
                                    str(self.cwa_settings["auto_backup_imports"]))

            # Optional post-import GDrive sync
            gdrive_sync_if_enabled()

            # Fetch metadata if enabled, prefer exact book id from calibredb
            if self.last_added_book_id is not None:
                self.fetch_metadata_if_enabled(book_id=self.last_added_book_id)
            else:
                self.fetch_metadata_if_enabled(staged_path.stem)

            # Trigger auto-send for users who have it enabled
            if self.last_added_book_id is not None:
                self.trigger_auto_send_if_enabled(book_id=self.last_added_book_id, book_path=book_path)
            else:
                self.trigger_auto_send_if_enabled(staged_path.stem, book_path)

            # CRITICAL FIX: Refresh Calibre-Web's database session to make new books visible
            # This solves the issue where multiple books don't appear until container restart
            self.refresh_cwa_session()

            # Invalidate duplicate cache since a new book was added
            self.invalidate_duplicate_cache()

            # Debounced duplicate scan (after import)
            self.schedule_debounced_duplicate_scan()

            # Generate KOReader sync checksums for the imported book
            if self.last_added_book_id is not None:
                self.generate_book_checksums(staged_path.stem, book_id=self.last_added_book_id)
            else:
                self.generate_book_checksums(staged_path.stem)

            # If we overwrote an existing book, Calibre does not bump books.timestamp, only last_modified.
            # Update timestamp to last_modified for any rows changed by this import so sorting by 'new' reflects overwrites.
            if self.cwa_settings.get('auto_ingest_automerge') == 'overwrite':
                try:
                    with sqlite3.connect(self.metadata_db, timeout=30) as con:
                        cur = con.cursor()
                        if not self._register_title_sort_function(con):
                            print("[ingest-processor] INFO: Skipping timestamp adjust (title_sort SQL function unavailable).", flush=True)
                            return
                        # pre_import_max_timestamp may be None (empty library) -> update all rows where timestamp < last_modified
                        if pre_import_max_timestamp is None:
                            cur.execute('UPDATE books SET timestamp = last_modified WHERE timestamp < last_modified')
                        else:
                            cur.execute('UPDATE books SET timestamp = last_modified WHERE last_modified > ? AND timestamp < last_modified', (pre_import_max_timestamp,))
                        affected = cur.rowcount
                        if affected:
                            print(f"[ingest-processor] INFO: Updated timestamp for {affected} overwritten book(s) to reflect latest import.", flush=True)
                except Exception as e:
                    print(f"[ingest-processor] WARN: Failed to adjust timestamps after overwrite import: {e}", flush=True)

        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor] {staged_path.stem} was not able to be added to the Calibre Library due to the following error:\nCALIBREDB EXIT/ERROR CODE: {e.returncode}\n{e.stderr}", flush=True)
            self.backup(str(staged_path), backup_type="failed")
        except Exception as e:
            print(f"[ingest-processor] ingest-processor ran into the following error:\n{e}", flush=True)
        finally:
            if staged_path.exists():
                os.remove(staged_path)

    def _validate_book_exists(self, book_id: int) -> bool:
        """Check if a book with the given ID exists in the Calibre library"""
        try:
            with sqlite3.connect(self.metadata_db, timeout=30) as con:
                cur = con.cursor()
                row = cur.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
                return row is not None
        except Exception as e:
            print(f"[ingest-processor] ERROR: Failed to validate book_id {book_id}: {e}", flush=True)
            return False

    def add_format_to_book(self, book_id:int, book_path:str) -> None:
        """Attach a new format file to an existing Calibre book using calibredb add_format"""
        source_path = Path(book_path)
        if not source_path.exists() or source_path.stat().st_size == 0:
            print(f"[ingest-processor] ERROR: Source file for add_format is missing or empty, skipping: {book_path}", flush=True)
            self.backup(self.filepath, backup_type="failed") # Backup original file
            return

        # Validate that the book exists before attempting to add format
        if not self._validate_book_exists(book_id):
            print(f"[ingest-processor] ERROR: Book ID {book_id} not found in library, cannot add format: {os.path.basename(book_path)}", flush=True)
            self.backup(self.filepath, backup_type="failed")
            return

        # Stage file for import
        staged_path = Path(self.staging_dir) / source_path.name
        try:
            shutil.copy2(source_path, staged_path)
        except Exception as e:
            print(f"[ingest-processor] ERROR: Failed to stage file for add_format: {e}", flush=True)
            self.backup(self.filepath, backup_type="failed")
            return

        try:
            result = subprocess.run([
                "calibredb", "add_format", str(book_id), str(staged_path), f"--library-path={self.library_dir}"
            ], env=self.calibre_env, check=True, capture_output=True, text=True)
            print(f"[ingest-processor] Added new format for book id {book_id}: {os.path.basename(str(staged_path))}", flush=True)
            if self.cwa_settings['auto_backup_imports']:
                self.backup(str(staged_path), backup_type="imported")
            # Optional post-add-format GDrive sync
            gdrive_sync_if_enabled()
        except subprocess.CalledProcessError as e:
            stderr_output = e.stderr if e.stderr else "No error details available"
            print(f"[ingest-processor] Failed to add format for book id {book_id}: {os.path.basename(str(staged_path))}\nCALIBREDB EXIT/ERROR CODE: {e.returncode}\nError details: {stderr_output}", flush=True)
            self.backup(str(staged_path), backup_type="failed")
        except Exception as e:
            print(f"[ingest-processor] Unexpected error while adding format for book id {book_id}: {e}", flush=True)
        finally:
            if staged_path.exists():
                os.remove(staged_path)


    def run_kindle_epub_fixer(self, filepath:str, dest=None) -> None:
        try:
            EPUBFixer().process(input_path=filepath, output_path=dest)
            print(f"[ingest-processor] {os.path.basename(filepath)} successfully processed with the cwa-kindle-epub-fixer!")
        except Exception as e:
            print(f"[ingest-processor] An error occurred while processing {os.path.basename(filepath)} with the kindle-epub-fixer. See the following error:\n{e}")


    def fetch_metadata_if_enabled(self, book_title: str | None = None, book_id: int | None = None) -> None:
        """Fetch and apply metadata for newly ingested books if enabled"""
        if not _CPS_AVAILABLE:
            print("[ingest-processor] CPS modules not available, skipping metadata fetch", flush=True)
            return

        if fetch_and_apply_metadata is None:
            print("[ingest-processor] Metadata helper not available, skipping metadata fetch", flush=True)
            return

        try:
            with sqlite3.connect(self.metadata_db, timeout=30) as con:
                cur = con.cursor()
                if book_id is not None:
                    cur.execute("SELECT id, title FROM books WHERE id = ?", (int(book_id),))
                else:
                    # Fallback: most recently added book
                    cur.execute("SELECT id, title FROM books ORDER BY timestamp DESC LIMIT 1")
                result = cur.fetchone()

            if not result:
                print(f"[ingest-processor] Could not find book ID for metadata fetch: {book_title}", flush=True)
                return
                
            book_id = int(result[0])
            actual_title = result[1]

            print(f"[ingest-processor] Attempting to fetch metadata for: {actual_title}", flush=True)

            # Fetch and apply metadata (now admin-controlled only)
            if fetch_and_apply_metadata(book_id):
                print(f"[ingest-processor] Successfully fetched and applied metadata for: {actual_title}", flush=True)
            else:
                print(f"[ingest-processor] No metadata improvements found for: {actual_title}", flush=True)

        except Exception as e:
            print(f"[ingest-processor] Error fetching metadata: {e}", flush=True)


    def trigger_auto_send_if_enabled(self, book_title: str | None = None, book_path: str | None = None, book_id: int | None = None) -> None:
        """Trigger auto-send for users who have it enabled"""
        if not _CPS_AVAILABLE:
            print("[ingest-processor] CPS modules not available, skipping auto-send", flush=True)
            return

        if TaskAutoSend is None or WorkerThread is None:
            print("[ingest-processor] Auto-send functionality not available, skipping auto-send", flush=True)
            return

        try:
            with sqlite3.connect(self.metadata_db, timeout=30) as con:
                cur = con.cursor()
                if book_id is not None:
                    cur.execute("SELECT id, title FROM books WHERE id = ?", (int(book_id),))
                else:
                    cur.execute("SELECT id, title FROM books ORDER BY timestamp DESC LIMIT 1")
                result = cur.fetchone()

            if not result:
                print(f"[ingest-processor] Could not find book ID for auto-send: {book_title}", flush=True)
                return
                
            book_id = int(result[0])
            actual_title = result[1]

            # Get users with auto-send enabled
            app_db_path = get_app_db_path()
            with sqlite3.connect(app_db_path, timeout=30) as con:
                cur = con.cursor()
                cur.execute("""
                    SELECT id, name, kindle_mail
                    FROM user
                    WHERE auto_send_enabled = 1
                    AND kindle_mail IS NOT NULL
                    AND kindle_mail != ''
                """)
                auto_send_users = cur.fetchall()

            if not auto_send_users:
                print(f"[ingest-processor] No users with auto-send enabled found", flush=True)
                return
                
            # Queue or schedule auto-send tasks for each user
            for user_id, username, kindle_mail in auto_send_users:
                try:
                    delay_minutes = self.cwa_settings.get('auto_send_delay_minutes', 5)

                    # Prefer to schedule in the long-lived web process so it shows in UI
                    scheduled_via_api = False
                    try:
                        url = get_internal_api_url("/cwa-internal/schedule-auto-send")
                        payload = {
                            'book_id': int(book_id),
                            'user_id': int(user_id),
                            'delay_minutes': int(delay_minutes) if isinstance(delay_minutes, (int, float, str)) else 5,
                            'username': username,
                            'title': actual_title,
                        }
                        resp = requests.post(
                            url,
                            json=payload,
                            headers=get_internal_api_headers(),
                            timeout=5,
                            verify=False,
                        )
                        if resp.status_code == 200:
                            try:
                                run_at = resp.json().get('run_at', 'soon')
                            except Exception:
                                run_at = 'soon'
                            print(f"[ingest-processor] Scheduled auto-send at {run_at} for '{actual_title}' to user {username} ({kindle_mail}) via web process", flush=True)
                            scheduled_via_api = True
                        else:
                            print(f"[ingest-processor] WARN: Web scheduling returned {resp.status_code}, falling back to immediate queue", flush=True)
                    except Exception as api_err:
                        print(f"[ingest-processor] WARN: Failed to schedule via web API: {api_err}. Falling back to immediate queue.", flush=True)

                    if not scheduled_via_api:
                        # Fallback: queue immediately in this process (task does not sleep)
                        task_message = f"Auto-sending '{actual_title}' to {username}'s eReader(s)"
                        task = TaskAutoSend(task_message, book_id, user_id, delay_minutes)
                        WorkerThread.add(username, task)
                        print(f"[ingest-processor] Queued auto-send immediately for '{actual_title}' to user {username} ({kindle_mail})", flush=True)
                except Exception as e:
                    print(f"[ingest-processor] Error queuing auto-send for user {username}: {e}", flush=True)

        except Exception as e:
            print(f"[ingest-processor] Error in auto-send trigger: {e}", flush=True)


    def generate_book_checksums(self, book_title: str, book_id: int | None = None) -> None:
        """Generate and store partial MD5 checksums for all formats of a newly imported book

        This creates KOReader-compatible checksums that allow reading progress to sync
        between KOReader devices and Calibre-Web.

        Args:
            book_title: Title of the book (used to find the book in Calibre database)
            book_id: Optional ID of the book (more reliable than title lookup)
        """
        try:
            import sqlite3
            # Import the centralized partial MD5 calculation function
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from cps.progress_syncing.checksums import calculate_koreader_partial_md5, store_checksum, CHECKSUM_VERSION

            calibre_db_path = os.path.join(self.library_dir, 'metadata.db')

            with sqlite3.connect(calibre_db_path, timeout=30) as con:
                cur = con.cursor()

                book_row = None
                if book_id is not None:
                    # Find by ID (preferred)
                    book_row = cur.execute(
                        'SELECT id, path FROM books WHERE id = ?',
                        (book_id,)
                    ).fetchone()

                if not book_row:
                    # Fallback: Find the book ID by title (most recently added if multiple matches)
                    book_row = cur.execute(
                        'SELECT id, path FROM books WHERE title = ? ORDER BY timestamp DESC LIMIT 1',
                        (book_title,)
                    ).fetchone()

                if not book_row:
                    print(f"[ingest-processor] Could not find book '{book_title}' (ID: {book_id}) in database for checksum generation", flush=True)
                    return

                book_id, book_path = book_row

                # Get all formats for this book
                formats = cur.execute(
                    'SELECT format, name FROM data WHERE book = ?',
                    (book_id,)
                ).fetchall()

                if not formats:
                    print(f"[ingest-processor] No formats found for book ID {book_id}", flush=True)
                    return

                print(f"[ingest-processor] Generating KOReader sync checksums v{CHECKSUM_VERSION} for book ID {book_id}...", flush=True)

                for format_ext, format_name in formats:
                    # Construct full file path
                    file_path = os.path.join(self.library_dir, book_path, f"{format_name}.{format_ext.lower()}")

                    if not os.path.exists(file_path):
                        print(f"[ingest-processor] WARN: File not found: {file_path}", flush=True)
                        continue

                    # Generate partial MD5 checksum using centralized function
                    checksum = calculate_koreader_partial_md5(file_path)

                    if checksum:
                        # Store using centralized manager function
                        success = store_checksum(
                            book_id=book_id,
                            book_format=format_ext.upper(),
                            checksum=checksum,
                            version=CHECKSUM_VERSION,
                            db_connection=con
                        )

                        if success:
                            print(f"[ingest-processor] Generated checksum {checksum} (v{CHECKSUM_VERSION}) for {format_ext.upper()} format", flush=True)
                        else:
                            print(f"[ingest-processor] WARN: Failed to store checksum for {format_ext.upper()} format", flush=True)
                    else:
                        print(f"[ingest-processor] WARN: Failed to generate checksum for {file_path}", flush=True)

                con.commit()
                print(f"[ingest-processor] Checksum generation complete for book ID {book_id}", flush=True)

        except Exception as e:
            print(f"[ingest-processor] Error generating book checksums: {e}", flush=True)
            # Don't fail the import if checksum generation fails


    def refresh_cwa_session(self) -> None:
        """Refresh Calibre-Web's database session to make newly added books visible

        This solves the issue where external calibredb adds aren't immediately visible
        in Calibre-Web until container restart.
        """
        # Route DB reconnect via the long-lived web process to avoid cross-process config/session issues
        try:
            url = get_internal_api_url("/cwa-internal/reconnect-db")
            print("[ingest-processor] Refreshing Calibre-Web database session...", flush=True)
            resp = requests.post(
                url,
                headers=get_internal_api_headers(),
                timeout=5,
                verify=False,
            )
            if resp.status_code == 200:
                print("[ingest-processor] Database session refresh enqueued", flush=True)
            else:
                print(f"[ingest-processor] WARN: DB refresh endpoint returned {resp.status_code}", flush=True)
        except Exception as e:
            print(f"[ingest-processor] WARN: Failed to call DB refresh endpoint: {e}", flush=True)
            print("[ingest-processor] Continuing despite session refresh failure - books may require manual refresh", flush=True)


    def invalidate_duplicate_cache(self) -> None:
        """Invalidate the duplicate detection cache after adding a new book

        This marks the cache as stale (scan_pending=1) but does NOT trigger an automatic scan.
        Users must manually trigger a scan from the /duplicates page, or wait for scheduled scans.
        """
        try:
            url = get_internal_api_url("/duplicates/invalidate-cache")
            resp = requests.post(
                url,
                headers=get_internal_api_headers(),
                timeout=5,
                verify=False,
            )
            if resp.status_code == 200:
                print("[ingest-processor] Duplicate cache invalidated", flush=True)
            else:
                print(f"[ingest-processor] WARN: Duplicate cache invalidation returned {resp.status_code}", flush=True)
        except Exception as e:
            # Don't fail the import if cache invalidation fails
            print(f"[ingest-processor] WARN: Failed to invalidate duplicate cache: {e}", flush=True)


    def schedule_debounced_duplicate_scan(self) -> None:
        """Schedule a debounced background duplicate scan if enabled.

        Uses a 60-second timer that resets on each new import to avoid repeated scans
        during batch ingest.
        """
        try:
            enabled = bool(self.cwa_settings.get('duplicate_scan_enabled', 0))
            frequency = self.cwa_settings.get('duplicate_scan_frequency', 'manual')

            if not enabled or frequency != 'after_import':
                return
            # Schedule in the long-lived web process so the debounce survives
            # the short-lived ingest process exiting.
            try:
                delay_seconds = int(self.cwa_settings.get('duplicate_scan_debounce_seconds', 5))
                delay_seconds = max(5, min(600, delay_seconds))
                url = get_internal_api_url("/cwa-internal/queue-duplicate-scan")
                payload = {"delay_seconds": delay_seconds}
                resp = requests.post(
                    url,
                    json=payload,
                    headers=get_internal_api_headers(),
                    timeout=5,
                    verify=False,
                )
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                        if body.get('queued'):
                            print("[ingest-processor] Debounced duplicate scan scheduled via web process", flush=True)
                        elif body.get('skipped'):
                            print("[ingest-processor] Duplicate scan scheduling skipped (disabled/manual)", flush=True)
                    except Exception:
                        print("[ingest-processor] Debounced duplicate scan scheduled via web process", flush=True)
                else:
                    print(f"[ingest-processor] WARN: Duplicate scan scheduling returned {resp.status_code}", flush=True)
            except Exception as e:
                print(f"[ingest-processor] WARN: Failed to schedule duplicate scan via web API: {e}", flush=True)
        except Exception as e:
            print(f"[ingest-processor] WARN: Failed to schedule debounced duplicate scan: {e}", flush=True)


    def set_library_permissions(self):
        try:
            nsm = os.getenv("NETWORK_SHARE_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
            if not nsm:
                subprocess.run(["chown", "-R", "abc:abc", self.library_dir], check=True)
            else:
                print(f"[ingest-processor] NETWORK_SHARE_MODE=true detected; skipping chown of {self.library_dir}", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor] An error occurred while attempting to recursively set ownership of {self.library_dir} to abc:abc. See the following error:\n{e}", flush=True)


def main(filepath=None):
    """Checks if filepath is a directory. If it is, main will be ran on every file in the given directory
    Inotifywait won't detect files inside folders if the folder was moved rather than copied"""

    if filepath is None:
        if len(sys.argv) < 2:
            print("[ingest-processor] ERROR: No file path provided", flush=True)
            print("[ingest-processor] Usage: python ingest_processor.py <filepath>", flush=True)
            sys.exit(1)
        filepath = sys.argv[1]

    nbp = None
    skip_delete = False
    try:
        ##############################################################################################
        # Truncates the filename if it is too long
        MAX_LENGTH = 150
        filename = os.path.basename(filepath)
        name, ext = os.path.splitext(filename)
        allowed_len = MAX_LENGTH - len(ext)

        # Ignore sidecar manifests entirely (handled when the real file is processed)
        if filename.endswith(".cwa.json") or filename.endswith(".cwa.failed.json"):
            print(f"[ingest-processor] Skipping sidecar manifest file: {filename}", flush=True)
            return

        if len(name) > allowed_len:
            new_name = name[:allowed_len] + ext
            new_path = os.path.join(os.path.dirname(filepath), new_name)
            os.rename(filepath, new_path)
            filepath = new_path
        ###############################################################################################
        if os.path.isdir(filepath) and Path(filepath).exists():
            # print(os.listdir(filepath))
            for filename in os.listdir(filepath):
                f = os.path.join(filepath, filename)
                if Path(f).exists():
                    main(f)
            return

        nbp = NewBookProcessor(filepath)

        # If this file is not an ignored temporary, wait briefly for stability to avoid importing a still-growing file
        ext_tmp_check = Path(nbp.filename).suffix.replace('.', '')
        if ext_tmp_check not in nbp.ingest_ignored_formats:
            timeout_minutes = nbp.cwa_settings.get('ingest_timeout_minutes', 15)
            print(f"[ingest-processor] Checking if file is ready (timeout: {timeout_minutes} minutes): {nbp.filename}", flush=True)
            ready = nbp.is_file_in_use()
            if not ready:
                print(f"[ingest-processor] WARN: File did not become ready in time or vanished (after {timeout_minutes} minutes): {nbp.filename}", flush=True)
                skip_delete = True
                return

        # Sidecar manifest handling for explicit actions (e.g., add_format)
        manifest_path = filepath + ".cwa.json"
        try:
            if Path(manifest_path).exists():
                with open(manifest_path, 'r', encoding='utf-8') as mf:
                    manifest = json.load(mf)
                action = manifest.get("action")
                if action == "add_format":
                    success = False
                    try:
                        book_id = int(manifest.get("book_id", -1))
                    except Exception:
                        book_id = -1
                    
                    if book_id > -1:
                        # Validate book exists before attempting add_format
                        if nbp._validate_book_exists(book_id):
                            nbp.add_format_to_book(book_id, filepath)
                            success = True
                        else:
                            print(f"[ingest-processor] ERROR: Book ID {book_id} not found in library for {os.path.basename(filepath)}", flush=True)
                            nbp.backup(filepath, backup_type="failed")
                    else:
                        print(f"[ingest-processor] ERROR: Invalid book_id in manifest for {os.path.basename(filepath)}", flush=True)
                        nbp.backup(filepath, backup_type="failed")
                    
                    # Cleanup manifest: delete on success, preserve on failure for debugging
                    try:
                        if success:
                            os.remove(manifest_path)
                        else:
                            failed_manifest_path = manifest_path.replace(".cwa.json", ".cwa.failed.json")
                            os.rename(manifest_path, failed_manifest_path)
                            print(f"[ingest-processor] Preserved failed manifest: {os.path.basename(failed_manifest_path)}", flush=True)
                    except Exception as e:
                        print(f"[ingest-processor] WARN: Failed to handle manifest cleanup: {e}", flush=True)
                    
                    nbp.set_library_permissions()
                    nbp.delete_current_file()
                    return
        except Exception as e:
            print(f"[ingest-processor] Error processing manifest file: {e}", flush=True)
            # Continue with normal processing if manifest handling fails

        # Check if the user has chosen to exclude files of this type from the ingest process
        # Remove . (dot), check is against exclude whitout dot
        ext = Path(nbp.filename).suffix.replace('.', '')
        if ext in nbp.ingest_ignored_formats:
            # Do NOT delete ignored temporary files; they may be renamed shortly (e.g. .uploading -> .epub)
            print(f"[ingest-processor] Skipping ignored/temporary file (no action taken): {nbp.filename}", flush=True)
            skip_delete = True
            return

        if nbp.is_target_format: # File can just be imported
            print(f"\n[ingest-processor]: No conversion needed for {nbp.filename}, importing now...", flush=True)
            nbp.add_book_to_library(filepath)
        elif nbp.is_supported_audiobook():
            print(f"\n[ingest-processor]: No conversion needed for {nbp.filename}, is audiobook, importing now...", flush=True)
            nbp.add_book_to_library(filepath, False, Path(nbp.filename).suffix)
        else:
            if nbp.auto_convert_on and nbp.can_convert: # File can be converted to target format and Auto-Converter is on

                if nbp.input_format in nbp.convert_ignored_formats: # File could be converted & the converter is activated but the user has specified files of this format should not be converted
                    print(f"\n[ingest-processor]: {nbp.filename} not in target format but user has told CWA not to convert this format so importing the file anyway...", flush=True)
                    nbp.add_book_to_library(filepath)
                    convert_successful = False
                elif nbp.target_format == "kepub": # File is not in the convert ignore list and target is kepub, so we start the kepub conversion process
                    convert_successful, converted_filepath = nbp.convert_to_kepub()
                else: # File is not in the convert ignore list and target is not kepub, so we start the regular conversion process
                    convert_successful, converted_filepath = nbp.convert_book()

                if convert_successful: # If previous conversion process was successful, remove tmp files and import into library
                    nbp.add_book_to_library(converted_filepath) # type: ignore

                    # If the original format should be retained, also add it as an additional format
                    if nbp.input_format in nbp.convert_retained_formats and nbp.input_format not in nbp.ingest_ignored_formats:
                        print(f"[ingest-processor]: Retaining original format ({nbp.input_format}) for {nbp.filename}...", flush=True)
                        # Find the book that was just added to get its ID
                        try:
                            # Prefer the exact id we just added if available
                            if nbp.last_added_book_id is not None:
                                target_book_id = nbp.last_added_book_id
                            else:
                                with sqlite3.connect(nbp.metadata_db, timeout=30) as con:
                                    cur = con.cursor()
                                    cur.execute("SELECT id FROM books ORDER BY timestamp DESC LIMIT 1")
                                    res = cur.fetchone()
                                    target_book_id = res[0] if res else None

                            if target_book_id is not None:
                                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                                    nbp.add_format_to_book(int(target_book_id), filepath)
                                else:
                                    print(f"[ingest-processor] Original file no longer exists or is empty, cannot retain format: {filepath}", flush=True)
                            else:
                                print(f"[ingest-processor] Could not find book ID to add retained format for: {nbp.filename}", flush=True)
                        except Exception as e:
                            print(f"[ingest-processor] Error adding retained format: {e}", flush=True)

            elif nbp.can_convert and not nbp.auto_convert_on: # Books not in target format but Auto-Converter is off so files are imported anyway
                print(f"\n[ingest-processor]: {nbp.filename} not in target format but CWA Auto-Convert is deactivated so importing the file anyway...", flush=True)
                nbp.add_book_to_library(filepath)
            else:
                print(f"[ingest-processor]: Cannot convert {nbp.filepath}. {nbp.input_format} is currently unsupported / is not a known ebook format.", flush=True)

    except Exception as e:
        print(f"[ingest-processor] Unexpected error during processing: {e}", flush=True)
        raise
    finally:
        # Ensure cleanup always happens, even if an exception occurred
        if nbp:
            try:
                nbp.set_library_permissions()
            except Exception as e:
                print(f"[ingest-processor] Error setting library permissions during cleanup: {e}", flush=True)

            try:
                if skip_delete:
                    print(f"[ingest-processor] Skipping delete for ignored/temporary file: {nbp.filename}", flush=True)
                else:
                    nbp.delete_current_file()
            except Exception as e:
                print(f"[ingest-processor] Error deleting current file during cleanup: {e}", flush=True)

            try:
                # Cleanup the temp conversion folder, which now contains the staging dir
                shutil.rmtree(nbp.tmp_conversion_dir, ignore_errors=True)
            except Exception as e:
                print(f"[ingest-processor] Error cleaning up temp conversion directory: {e}", flush=True)

            try:
                del nbp # New in Version 2.0.0, should drastically reduce memory usage with large ingests
            except Exception:
                pass  # Ignore errors in cleanup

if __name__ == "__main__":
    main()
