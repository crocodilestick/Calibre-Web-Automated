# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import argparse
import atexit
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
import unicodedata

from cwa_db import CWA_DB
try:
    from cps.utils.filename_sanitizer import get_valid_filename_shared
except ModuleNotFoundError:
    # Add project root (parent of scripts/) to sys.path and retry
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(this_dir, '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        from cps.utils.filename_sanitizer import get_valid_filename_shared  # type: ignore
    except Exception:
        # Inline fallback: minimal mirror of CW behavior used only if import fails
        import re as _re
        try:
            import unidecode as _unidecode  # type: ignore
        except Exception:
            _unidecode = None

        _ZW_TRIM_RE = _re.compile(r"(^[\s\u200B-\u200D\ufeff]+)|([\s\u200B-\u200D\ufeff]+$)")

        def _strip_ws(text: str) -> str:
            return _ZW_TRIM_RE.sub("", text)

        def get_valid_filename_shared(value: str,
                                       replace_whitespace: bool = True,
                                       chars: int = 128,
                                       unicode_filename: bool = False) -> str:
            if not isinstance(value, str):
                value = str(value) if value is not None else ""
            if value[-1:] == '.':
                value = value[:-1] + '_'
            value = value.replace("/", "_").replace(":", "_").strip('\0')
            if unicode_filename and _unidecode is not None:
                value = _unidecode.unidecode(value)
            if replace_whitespace:
                value = _re.sub(r'[*+:\\\"/<>?]+', '_', value, flags=_re.U)
                value = _re.sub(r'[|]+', ',', value, flags=_re.U)
            value = _strip_ws(value.encode('utf-8')[:chars].decode('utf-8', errors='ignore'))
            if not value:
                raise ValueError("Filename cannot be empty")
            return value
try:
    from unidecode import unidecode  # transliteration used when unicode-filename mode is on
except Exception:
    unidecode = None

# Global Variables
dirs_json = "/app/calibre-web-automated/dirs.json"
change_logs_dir = "/app/calibre-web-automated/metadata_change_logs"
metadata_temp_dir = "/app/calibre-web-automated/metadata_temp"


# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/cover_enforcer.lock', 'x')
    lock.close()
except FileExistsError:
    print("[cover-metadata-enforcer]: CANCELLING... cover-metadata-enforcer was initiated but is already running")
    sys.exit(2)

# Defining function to delete the lock on script exit
def removeLock():
    os.remove(tempfile.gettempdir() + '/cover_enforcer.lock')

# Will automatically run when the script exits
atexit.register(removeLock)


class Book:
    def __init__(self, book_dir: str, file_path: str):
        self.book_dir: str = book_dir
        self.file_path: str = file_path

        self.calibre_library = self.get_calibre_library()

        self.file_format: str = Path(file_path).suffix.replace('.', '')
        self.timestamp: str = self.get_time()
        self.book_id: str = (list(re.findall(r"\(\d*\)", book_dir))[-1])[1:-1]
        self.book_title, self.author_name, self.title_author = self.get_title_and_author()

        self.calibre_env = os.environ.copy()
        # Enables Calibre plugins to be used from /config/plugins
        self.calibre_env["HOME"] = "/config"
        # Gets split library info from app.db and sets library dir to the split dir if split library is enabled
        self.split_library = self.get_split_library()
        if self.split_library:
            self.calibre_library = self.split_library["split_path"]
            self.calibre_env['CALIBRE_OVERRIDE_DATABASE_PATH'] = os.path.join(self.split_library["db_path"], "metadata.db")

        self.cover_path = book_dir + '/cover.jpg'
        self.old_metadata_path = book_dir + '/metadata.opf'
        self.new_metadata_path = self.get_new_metadata_path()

        self.log_info = None


    def get_split_library(self) -> dict[str, str] | None:
        """Checks whether or not the user has split library enabled. Returns None if they don't and the path of the Split Library location if True."""
        con = sqlite3.connect("/config/app.db", timeout=30)
        cur = con.cursor()
        split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

        if split_library:
            split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
            db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
            con.close()
            return {
                "split_path": split_path,
                "db_path": db_path
            }
        else:
            con.close()
            return None

    def get_calibre_library(self) -> str:
        """Gets Calibre-Library location from dirs.json"""
        with open(dirs_json, 'r') as f:
            dirs = json.load(f)
        return dirs['calibre_library_dir'] # Returns without / on the end


    def get_time(self) -> str:
        now = datetime.now()
        return now.strftime('%Y-%m-%d %H:%M:%S')


    def get_title_and_author(self) -> tuple[str, str, str]:
        title_author = self.file_path.split('/')[-1].split(f'.{self.file_format}')[0]
        book_title = title_author.split(f" - {title_author.split(' - ')[-1]}")[0]
        author_name = title_author.split(' - ')[-1]

        return book_title, author_name, title_author


    def get_new_metadata_path(self) -> str:
        """Uses the export function of the calibredb utility to export any new metadata for the given book to metadata_temp, and returns the path to the new metadata.opf"""
        subprocess.run(["calibredb", "export", "--with-library", self.calibre_library, "--to-dir", metadata_temp_dir, self.book_id], env=self.calibre_env, check=True)
        temp_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(metadata_temp_dir) for f in filenames]
        return [f for f in temp_files if f.endswith('.opf')][0]


    def export_as_dict(self) -> dict[str,str | None]:
        return {
            "book_dir":self.book_dir,
            "file_path":self.file_path,
            "calibre_library":self.calibre_library,
            "file_format":self.file_format,
            "timestamp":self.timestamp,
            "book_id":self.book_id,
            "book_title":self.book_title,
            "author_name":self.author_name,
            "title_author":self.title_author,
            "cover_path":self.cover_path,
            "old_metadata_path":self.old_metadata_path,
            "new_metadata_path":self.new_metadata_path,
            "log_info":self.log_info
        }


class Enforcer:
    def __init__(self, args):
        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings
        self.enforcer_on = self.cwa_settings["auto_metadata_enforcement"]
        self.supported_formats = ["epub", "azw3"]

        self.args = args
        self.calibre_library = self.get_calibre_library()

        self.illegal_characters = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]

        self.calibre_env = os.environ.copy()
        # Enables Calibre plugins to be used from /config/plugins
        self.calibre_env["HOME"] = "/config"
        # Gets split library info from app.db and sets library dir to the split dir if split library is enabled
        self.split_library = self.get_split_library()
        if self.split_library:
            self.calibre_library = self.split_library["split_path"]
            self.calibre_env['CALIBRE_OVERRIDE_DATABASE_PATH'] = os.path.join(self.split_library["db_path"], "metadata.db")

        # Read Calibre-Web setting: config_unicode_filename (True -> transliterate non-English in filenames)
        try:
            with sqlite3.connect("/config/app.db", timeout=30) as con:
                cur = con.cursor()
                self.unicode_filename = bool(cur.execute('SELECT config_unicode_filename FROM settings;').fetchone()[0])
        except Exception:
            self.unicode_filename = False

    def _ascii_transliterate(self, s: str) -> str:
        """Transliterate non-English characters to ASCII when configured.
        Prefer unidecode if available; otherwise use NFKD normalization and drop diacritics."""
        if not s:
            return s
        if unidecode is not None:
            return unidecode(s)
        # Fallback transliteration
        return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')


    def get_split_library(self) -> dict[str, str] | None:
        """Checks whether or not the user has split library enabled. Returns None if they don't and the path of the Split Library location if True."""
        con = sqlite3.connect("/config/app.db", timeout=30)
        cur = con.cursor()
        split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

        if split_library:
            split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
            db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
            con.close()
            return {
                "split_path": split_path,
                "db_path": db_path
            }
        else:
            con.close()
            return None


    def get_calibre_library(self) -> str:
        with open(dirs_json, 'r') as f:
            dirs = json.load(f)
        return dirs['calibre_library_dir'] # Returns without / on the end


    def _recalculate_checksum_after_modification(self, book_id: str, file_format: str, file_path: str) -> None:
        """Calculate and store new checksum after modifying a book file."""
        try:
            # Import the checksum calculation function
            import sys
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from cps.progress_syncing.checksums import calculate_koreader_partial_md5, store_checksum, CHECKSUM_VERSION

            # Calculate new checksum
            checksum = calculate_koreader_partial_md5(file_path)
            if not checksum:
                print(f"[cover-metadata-enforcer] Warning: Failed to calculate checksum for {file_path}", flush=True)
                return

            # Store in database using centralized manager function
            metadb_path = os.path.join(
                (self.split_library or {}).get("db_path", self.calibre_library),
                "metadata.db"
            )

            con = sqlite3.connect(metadb_path, timeout=30)

            try:
                success = store_checksum(
                    book_id=int(book_id),
                    book_format=file_format.upper(),
                    checksum=checksum,
                    version=CHECKSUM_VERSION,
                    db_connection=con
                )

                if success:
                    print(f"[cover-metadata-enforcer] Stored checksum {checksum[:8]}... for book {book_id} format {file_format} ({CHECKSUM_VERSION})", flush=True)
                else:
                    print(f"[cover-metadata-enforcer] Warning: Failed to store checksum for book {book_id}", flush=True)
            finally:
                con.close()
        except Exception as e:
            print(f"[cover-metadata-enforcer] Warning: Failed to recalculate checksum: {e}", flush=True)
            import traceback
            print(traceback.format_exc(), flush=True)


    def read_log(self, auto=True, log_path: str = "None") -> dict:
        """Reads pertinent information from the given log file, adds the book_id from the log name and returns the info as a dict"""
        if auto:
            book_id = (self.args.log.split('-')[1]).split('.')[0]
            timestamp_raw = self.args.log.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(f'{change_logs_dir}/{self.args.log}', 'r', encoding='utf-8') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            log_name = os.path.basename(log_path)
            book_id = (log_name.split('-')[1]).split('.')[0]
            timestamp_raw = log_name.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(log_path, 'r', encoding='utf-8') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        return log_info


    def get_book_dir_from_log(self, log_info: dict) -> str:
        """Resolve the on-disk book directory prioritizing ones that contain supported files.
        Order of preference: DB path -> any (id)-suffix dirs -> reconstructed ASCII/raw (based on config).
        Within each, prefer the one that actually contains EPUB/AZW3. When config_unicode_filename is True,
        prefer the ASCII path over a diacritic sibling if both exist."""
        book_id = str(log_info['book_id']).strip()

        candidate_dirs: list[str] = []

        # 1) DB-based resolution (split-library aware)
        try:
            metadb_path = os.path.join(
                (self.split_library or {}).get("db_path", self.calibre_library),
                "metadata.db",
            )
            with sqlite3.connect(metadb_path, timeout=30) as con:
                cur = con.cursor()
                row = cur.execute('SELECT path FROM books WHERE id = ?', (book_id,)).fetchone()
            if row and row[0]:
                resolved = os.path.join(self.calibre_library, row[0])
                resolved = resolved if resolved.endswith(os.sep) else resolved + os.sep
                if os.path.isdir(resolved):
                    candidate_dirs.append(resolved)
                    if self.args and getattr(self.args, 'verbose', False):
                        print(f"[cover-metadata-enforcer] Candidate from DB: {resolved}", flush=True)
        except Exception as e:
            if self.args and getattr(self.args, 'verbose', False):
                print(f"[cover-metadata-enforcer] WARN: DB lookup failed for id={book_id}: {e}", flush=True)

        # 2) All directories that end with (book_id)
        target_suffix = f"({book_id})"
        try:
            for dirpath, dirnames, _ in os.walk(self.calibre_library):
                for d in dirnames:
                    if d.endswith(target_suffix):
                        p = os.path.join(dirpath, d)
                        p = p if p.endswith(os.sep) else p + os.sep
                        if os.path.isdir(p):
                            candidate_dirs.append(p)
            if self.args and getattr(self.args, 'verbose', False):
                if candidate_dirs:
                    print(f"[cover-metadata-enforcer] Found {len(candidate_dirs)} candidate(s) including DB/ID-search", flush=True)
        except Exception:
            pass

        # 3) Reconstruct from log names using EXACT CW sanitization
        raw_title = str(log_info.get('title', '')).strip()
        # CW uses only the first author to build the folder
        raw_author_full = str(log_info.get('authors', '')).strip().replace(' & ', ', ')
        raw_author = raw_author_full.split(', ')[0] if ', ' in raw_author_full else raw_author_full

        # Build both transliterated and non-transliterated variants using shared sanitizer
        # Guard against empty/invalid values to avoid crashing on fresh/partial metadata
        try:
            title_ascii = get_valid_filename_shared(raw_title, chars=96, unicode_filename=True)
        except Exception:
            # Fallback: minimal safe title using book id
            title_ascii = f"book_{book_id}"
        try:
            author_ascii = get_valid_filename_shared(raw_author, chars=96, unicode_filename=True)
        except Exception:
            author_ascii = "Unknown Author"
        try:
            title_raw = get_valid_filename_shared(raw_title, chars=96, unicode_filename=False)
        except Exception:
            title_raw = f"book_{book_id}"
        try:
            author_raw = get_valid_filename_shared(raw_author, chars=96, unicode_filename=False)
        except Exception:
            author_raw = "Unknown Author"

        reconstructed_ascii = os.path.join(self.calibre_library, author_ascii, f"{title_ascii} ({book_id})")
        reconstructed_raw = os.path.join(self.calibre_library, author_raw, f"{title_raw} ({book_id})")
        # Prefer ASCII first when config demands transliteration
        recon_order = [reconstructed_ascii, reconstructed_raw] if self.unicode_filename else [reconstructed_raw, reconstructed_ascii]
        candidate_dirs.extend([(p if p.endswith(os.sep) else p + os.sep) for p in recon_order])

        # Deduplicate while preserving order
        seen = set()
        deduped_candidates = []
        for c in candidate_dirs:
            if c not in seen:
                seen.add(c)
                deduped_candidates.append(c)

        # Split into preferred vs alternate based on config_unicode_filename
        def is_preferred(path: str) -> bool:
            base = author_ascii if self.unicode_filename else author_raw
            return path.startswith(os.path.join(self.calibre_library, base) + os.sep)

        preferred_candidates = [c for c in deduped_candidates if is_preferred(c)]
        alternate_candidates = [c for c in deduped_candidates if not is_preferred(c)]

        # Choose the first candidate that exists and contains supported files (preferred first)
        for group_name, group in (("preferred", preferred_candidates), ("alternate", alternate_candidates)):
            for c in group:
                if os.path.isdir(c):
                    sf = self.get_supported_files_from_dir(c)
                    if sf:
                        if self.args and getattr(self.args, 'verbose', False):
                            print(f"[cover-metadata-enforcer] Selected {group_name} candidate with supported files: {c}", flush=True)
                        log_info['file_path'] = c
                        return c

        # If none have supported files, but some dirs exist, choose best available (prefer ASCII if exists)
        existing_pref = [c for c in preferred_candidates if os.path.isdir(c)]
        existing_alt = [c for c in alternate_candidates if os.path.isdir(c)]
        existing = existing_pref or existing_alt
        if existing:
            # Try to pick ASCII-looking path if config is True
            preferred = None
            for c in existing_pref:
                preferred = c
                break
            if not preferred:
                preferred = existing[0]
            if self.args and getattr(self.args, 'verbose', False):
                print(f"[cover-metadata-enforcer] No supported files in candidates; falling back to existing dir: {preferred}", flush=True)
            log_info['file_path'] = preferred
            return preferred

        # Nothing exists; fall back to reconstructed path that matches config
        fallback = (reconstructed_ascii if self.unicode_filename else reconstructed_raw)
        fallback = fallback if fallback.endswith(os.sep) else fallback + os.sep
        if self.args and getattr(self.args, 'verbose', False):
            print(f"[cover-metadata-enforcer] Resolved via reconstructed path (not found on disk): {fallback}", flush=True)
        log_info['file_path'] = fallback
        return fallback


    def get_supported_files_from_dir(self, dir: str) -> list[str]:
        """ Returns a list if the book dir given contains files of one or more of the supported formats"""
        library_files = [os.path.join(dirpath, f) for (dirpath, dirnames, filenames) in os.walk(dir) for f in filenames]

        supported_files = []
        for format in self.supported_formats:
            supported_files += [f for f in library_files if f.lower().endswith(f'.{format}')]

        return supported_files

    def enforce_cover(self, book_dir: str) -> list:
        """Will force the Cover & Metadata to update for the supported book files in the given directory"""
        supported_files = self.get_supported_files_from_dir(book_dir)
        if supported_files:
            if len(supported_files) > 1:
                print("[cover-metadata-enforcer] Multiple file formats for current book detected...", flush=True)
            book_objects = []
            for file in supported_files:
                book = Book(book_dir, file)
                self.replace_old_metadata(book.old_metadata_path, book.new_metadata_path)
                if Path(book.cover_path).exists():
                    os.system(f'ebook-polish -c "{book.cover_path}" -o "{book.new_metadata_path}" -U "{file}" "{file}"')
                else:
                    os.system(f'ebook-polish -o "{book.new_metadata_path}" -U "{file}" "{file}"')
                self.empty_metadata_temp()
                print(f"[cover-metadata-enforcer]: DONE: '{book.title_author}.{book.file_format}': Cover & Metadata updated", flush=True)

                # Calculate and store new checksum after modification
                self._recalculate_checksum_after_modification(book.book_id, book.file_format, file)

                book_objects.append(book)

            return book_objects
        else:
            print(f"[cover-metadata-enforcer]: No supported file formats found in {book_dir}.", flush=True)
            print("[cover-metadata-enforcer]: *** NOTICE **** Only EPUB & AZW3 formats are currently supported.", flush=True)
            return []


    def enforce_all_covers(self) -> tuple[int, float, int] | tuple[bool, bool, bool]:
        """Will force the covers and metadata to be re-generated for all books in the library"""
        t_start = time.time()

        supported_files = self.get_supported_files_from_dir(self.calibre_library)
        if supported_files:
            book_dirs = []
            for file in supported_files:
                book_dirs.append(os.path.dirname(file))

            print(f"[cover-metadata-enforcer]: {len(book_dirs)} books detected in Library")
            print(f"[cover-metadata-enforcer]: Enforcing covers for {len(supported_files)} supported file(s) in {self.calibre_library} ...")

            successful_enforcements = len(supported_files)

            for book_dir in book_dirs:
                try:
                    book_objects = self.enforce_cover(book_dir)
                    if book_objects:
                        book_dicts = []
                        for book in book_objects:
                            book_dicts.append(book.export_as_dict())
                        self.db.enforce_add_entry_from_all(book_dicts)
                except Exception as e:
                    print(f"[cover-metadata-enforcer]: ERROR: {book_dir}")
                    print(f"[cover-metadata-enforcer]: Skipping book due to following error: {e}")
                    successful_enforcements = successful_enforcements - 1
                    continue

            t_end = time.time()

            return successful_enforcements, (t_end - t_start), len(supported_files)
        else: # No supported files found
            return False, False, False


    def replace_old_metadata(self, old_metadata: str, new_metadata: str) -> None:
        """Switches the metadata in metadata_temp with the metadata in the Calibre-Library"""
        os.system(f'cp "{new_metadata}" "{old_metadata}"')


    def print_library_list(self) -> None:
        """Uses the calibredb command line utility to list the books in the library"""
        subprocess.run(["calibredb", "list", "--with-library", self.calibre_library], env=self.calibre_env, check=True)


    def delete_log(self, auto=True, log_path="None"):
        """Deletes the log file"""
        if auto:
            log = os.path.join(change_logs_dir, self.args.log)
            os.remove(log)
        else:
            os.remove(log_path)


    def empty_metadata_temp(self):
        """Empties the metadata_temp folder"""
        os.system(f"rm -r {metadata_temp_dir}/*")


    def check_for_other_logs(self):
        log_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(change_logs_dir) for f in filenames]
        if len(log_files) > 0:
            print(f"[cover-metadata-enforcer] {len(log_files)} Additional metadata changes detected, processing now..", flush=True)
            for log in log_files:
                if log.endswith('.json'):
                    log_info = self.read_log(auto=False, log_path=log)
                    book_dir = self.get_book_dir_from_log(log_info)
                    book_objects = self.enforce_cover(book_dir)
                    if book_objects:
                        for book in book_objects:
                            book.log_info = log_info
                            book.log_info['file_path'] = book.file_path
                            self.db.enforce_add_entry_from_log(book.log_info)
                    self.delete_log(auto=False, log_path=log)


def main():
    parser = argparse.ArgumentParser(
        prog='cover-enforcer',
        description='Upon receiving a log, valid directory or an "-all" flag, this \
        script will enforce the covers and metadata of the corresponding books, making \
        sure that each are correctly stored in both the ebook files themselves as well as in the \
        user\'s Calibre Library. Additionally, if an epub file happens to be in EPUB 2 \
        format, it will also be automatically upgraded to EPUB 3.'
    )

    parser.add_argument('--log', action='store', dest='log', required=False, help='Will enforce the covers and metadata of the books in the given log file.', default=None)
    parser.add_argument('--dir', action='store', dest='dir', required=False, help='Will enforce the covers and metadata of the books in the given directory.', default=None)
    parser.add_argument('-all', action='store_true', dest='all', help='Will enforce covers & metadata for ALL books currently in your calibre-library-dir', default=False)
    parser.add_argument('-list', '-l', action='store_true', dest='list', help='List all books in your calibre-library-dir', default=False)
    parser.add_argument('-history', action='store_true', dest='history', help='Display a history of all enforcements ever carried out on your machine (not yet implemented)', default=False)
    parser.add_argument('-paths', '-p', action='store_true', dest='paths', help="Use with '-history' flag to display stored paths of all files in enforcement database", default=False)
    parser.add_argument('-v', '--verbose', action='store_true', dest='verbose', help="Use with history to display entire enforcement history instead of only the most recent 10 entries", default=False)
    args = parser.parse_args()

    enforcer = Enforcer(args)

    if len(sys.argv) == 1:
        parser.print_help()
    #########################     QUERY ARGS     ###########################
    elif args.log is not None and args.dir is not None:
        ### log and dir provided together
        parser.print_usage()
    elif args.list and args.log is None and args.dir is None and args.all is False and args.history is False:
        ### only list flag passed
        enforcer.print_library_list()
    elif args.history and args.log is None and args.dir is None and args.all is False and args.list is False:
        ### only history flag passed
        enforcer.db.enforce_show(args.paths, args.verbose)
    #########################  ENFORCEMENT ARGS  ###########################
    elif args.all and args.log is None and args.dir is None and args.list is False and args.history is False:
        ### only all flag passed
        print('[cover-metadata-enforcer]: Enforcing metadata and covers for all books in library...')
        n_enforced, completion_time, n_supported_files = enforcer.enforce_all_covers()
        if n_enforced == False:
            print(f"\n[cover-metadata-enforcer]: No supported ebook files found in library (only EPUB & AZW3 formats are currently supported)")
        elif n_enforced == n_supported_files:
            print(f"\n[cover-metadata-enforcer]: SUCCESS: All covers & metadata successfully updated for all {n_enforced} supported ebooks in the library in {completion_time:.2f} seconds!")
        elif n_enforced == 0:
            print("\n[cover-metadata-enforcer]: FAILURE: Supported files found but none we're successfully enforced. See the log above for details.")
        elif n_enforced < n_supported_files:
            print(f"\n[cover-metadata-enforcer]: PARTIAL SUCCESS: Out of {n_supported_files} supported files detected, {n_enforced} were successfully enforced. See log above for details")
    elif args.log is None and args.dir is not None and args.all is False and args.list is False and args.history is False:
        ### dir passed, no log, not all, no flags
        if args.dir[-1] == '/':
            args.dir = args.dir[:-1]
        if os.path.isdir(args.dir):
            book_objects = enforcer.enforce_cover(args.dir)
            if book_objects:
                book_dicts = []
                for book in book_objects:
                    book_dicts.append(book.export_as_dict())
                enforcer.db.enforce_add_entry_from_dir(book_dicts)
        else:
            print(f"[cover-metadata-enforcer]: ERROR: '{args.dir}' is not a valid directory")
    elif args.log is not None and args.dir is None and args.all is False and args.list is False and args.history is False:
        ### log passed: (args.log), no dir
        log_info = enforcer.read_log()
        book_dir = enforcer.get_book_dir_from_log(log_info)
        if enforcer.enforcer_on:
            book_objects = enforcer.enforce_cover(book_dir)
            if not book_objects:
                print(f"[cover-metadata-enforcer] Metadata for '{log_info['title']}' not successfully enforced")
                sys.exit(1)
            for book in book_objects:
                book.log_info = log_info
                book.log_info['file_path'] = book.file_path
                enforcer.db.enforce_add_entry_from_log(book.log_info)
            enforcer.delete_log()
            enforcer.check_for_other_logs()
        else: # Enforcer has been disabled in the CWA Settings
            print(f"[cover-metadata-enforcer] The CWA Automatic Metadata enforcement service is currently disabled in the settings. Therefore the metadata changes for {log_info['title'].replace(':', '_')} won't be enforced.\n\nThis means that the changes made will appear in the Web UI, but not be stored in the ebook files themselves.")
            enforcer.delete_log()
    else:
        parser.print_usage()

    sys.exit(0)

if __name__ == "__main__":
    main()
