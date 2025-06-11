import argparse
import json
import os
import re
import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path
import subprocess

import tempfile
import atexit

from cwa_db import CWA_DB

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
        self.book_id: str = re.findall(r'\((\d*)\)', book_dir)[-1]
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
        con = sqlite3.connect("/config/app.db")
        cur = con.cursor()
        split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

        if split_library:
            split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
            db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
            con.close()
            return {
                "split_path":split_path,
                "db_path":db_path
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
        return {"book_dir":self.book_dir,
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
                "self.new_metadata_path":self.new_metadata_path,
                "log_info":self.log_info}


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
            
    
    def get_split_library(self) -> dict[str, str] | None:
        """Checks whether or not the user has split library enabled. Returns None if they don't and the path of the Split Library location if True."""
        con = sqlite3.connect("/config/app.db")
        cur = con.cursor()
        split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

        if split_library:
            split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
            db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
            con.close()
            return {
                "split_path":split_path,
                "db_path":db_path
                }
        else:
            con.close()
            return None


    def get_calibre_library(self) -> str:
        with open(dirs_json, 'r') as f:
            dirs = json.load(f)
        return dirs['calibre_library_dir'] # Returns without / on the end


    def read_log(self, auto=True, log_path: str = "None") -> dict:
        """Reads pertinent information from the given log file, adds the book_id from the log name and returns the info as a dict"""
        if auto:
            book_id = (self.args.log.split('-')[1]).split('.')[0]
            timestamp_raw = self.args.log.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(f'{change_logs_dir}/{self.args.log}', 'r') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            log_name = os.path.basename(log_path)
            book_id = (log_name.split('-')[1]).split('.')[0]
            timestamp_raw = log_name.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(log_path, 'r') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        return log_info


    def get_book_dir_from_log(self, log_info: dict) -> str:
        book_title = log_info['title'].replace(':', '_')
        author_name = (log_info['authors'].split(', ')[0]).split(' & ')[0]
        book_id = log_info['book_id']

        for char in book_title:
            if char in self.illegal_characters:
                book_title = book_title.replace(char, '_')
        for char in author_name:
            if char in self.illegal_characters:
                author_name = author_name.replace(char, '_')

        book_dir = f"{self.calibre_library}/{author_name}/{book_title} ({book_id})/"
        log_info['file_path'] = book_dir

        return book_dir


    def get_supported_files_from_dir(self, dir: str) -> list[str]:
        """ Returns a list if the book dir given contains files of one or more of the supported formats"""
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(dir) for f in filenames]
        
        supported_files = []
        for format in self.supported_formats:
            supported_files = supported_files + [f for f in library_files if f.endswith(f'.{format}')]

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
                os.system(f'ebook-polish -c "{book.cover_path}" -o "{book.new_metadata_path}" -U "{file}" "{file}"')
                self.empty_metadata_temp()
                print(f"[cover-metadata-enforcer]: DONE: '{book.title_author}.{book.file_format}': Cover & Metadata updated", flush=True)
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