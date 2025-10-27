# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import argparse
import json
import logging
import os
import re
import sys
import shutil
from pathlib import Path
import subprocess
import tempfile
import atexit
from datetime import datetime
import sqlite3

import pwd
import grp

from cwa_db import CWA_DB
from kindle_epub_fixer import EPUBFixer

### Global Variables
convert_library_log_file = "/config/convert-library.log"

# Define the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set the logging level
# Create a FileHandler
file_handler = logging.FileHandler(convert_library_log_file, mode='w', encoding='utf-8')
# Create a Formatter and set it for the handler
LOG_FORMAT = '%(message)s'
formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(formatter)
# Add the handler to the logger
logger.addHandler(file_handler)

# Define user and group
USER_NAME = "abc"
GROUP_NAME = "abc"

# Get UID and GID
uid = pwd.getpwnam(USER_NAME).pw_uid
gid = grp.getgrnam(GROUP_NAME).gr_gid

# Set permissions for log file (skip on network shares)
try:
    nsm = os.getenv("NETWORK_SHARE_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
    if not nsm:
        subprocess.run(["chown", f"{uid}:{gid}", convert_library_log_file], check=True)
    else:
        print(f"[convert-library] NETWORK_SHARE_MODE=true detected; skipping chown of {convert_library_log_file}", flush=True)
except subprocess.CalledProcessError as e:
    print(f"[convert-library] An error occurred while attempting to set ownership of {convert_library_log_file} to abc:abc. See the following error:\n{e}", flush=True)

def print_and_log(string) -> None:
    """ Ensures the provided string is passed to STDOUT and stored in the runs log file """
    logger.info(string)
    print(string)


# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/convert_library.lock', 'x')
    lock.close()
except FileExistsError:
    print_and_log("[convert-library]: CANCELLING... convert-library was initiated but is already running")
    logger.info(f"\nCWA Convert Library Service - Run Cancelled: {datetime.now()}")
    sys.exit(2)

# Defining function to delete the lock on script exit
def removeLock():
    try:
        os.remove(tempfile.gettempdir() + '/convert_library.lock')
    except FileNotFoundError:
        ...

# Will automatically run when the script exits
atexit.register(removeLock)

backup_destinations = {
        entry.name: entry.path
        for entry in os.scandir("/config/processed_books")
        if entry.is_dir()
    }


class LibraryConverter:
    def __init__(self, args) -> None:
        self.args = args
        self.verbose = getattr(args, 'verbose', False)  # Safe attribute access

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings
        self.target_format = self.cwa_settings['auto_convert_target_format']
        
        # Validate target format
        if not self.target_format or not isinstance(self.target_format, str):
            raise ValueError(f"Invalid target format configuration: {self.target_format}. Must be a non-empty string.")
        
        # Enhanced convert_ignored_formats handling
        ignored_formats_setting = self.cwa_settings.get('auto_convert_ignored_formats', [])
        if isinstance(ignored_formats_setting, str):
            # Handle single string
            self.convert_ignored_formats = [ignored_formats_setting] if ignored_formats_setting else []
        elif isinstance(ignored_formats_setting, list):
            # Handle list, filter out empty/None values
            self.convert_ignored_formats = [f for f in ignored_formats_setting if f and isinstance(f, str)]
        else:
            # Fallback for unexpected types
            print_and_log(f"[convert-library]: WARNING - Unexpected type for auto_convert_ignored_formats: {type(ignored_formats_setting)}. Using empty list.")
            self.convert_ignored_formats = []

        if self.verbose and self.convert_ignored_formats:
            print_and_log(f"[convert-library]: Ignoring formats: {', '.join(self.convert_ignored_formats)}")
            
        self.kindle_epub_fixer = self.cwa_settings['kindle_epub_fixer']

        self.supported_book_formats = {'acsm', 'azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz', 'kfx', 'kfx-zip'}
        self.hierarchy_of_success = {'epub', 'lit', 'mobi', 'azw', 'azw3', 'fb2', 'fbz', 'azw4', 'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt', 'kfx', 'kfx-zip'}

        self.current_book = 1
        self.ingest_folder, self.library_dir, self.tmp_conversion_dir = self.get_dirs('/app/calibre-web-automated/dirs.json')

        self.calibre_env = os.environ.copy()
        # Enables Calibre plugins to be used from /config/plugins
        self.calibre_env["HOME"] = "/config"
        # Gets split library info from app.db and sets library dir to the split dir if split library is enabled
        self.split_library = self.get_split_library()
        if self.split_library:
            self.library_dir = self.split_library["split_path"]
            self.calibre_env['CALIBRE_OVERRIDE_DATABASE_PATH'] = os.path.join(self.split_library["db_path"], "metadata.db")
        self.to_convert = self.get_books_to_convert()


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
                "split_path":split_path,
                "db_path":db_path
                }
        else:
            con.close()
            return None


    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/"
        library_dir = f"{dirs['calibre_library_dir']}/"
        tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

        return ingest_folder, library_dir, tmp_conversion_dir

    def get_library_book_formats(self) -> dict[int, list[str]]:
        """Returns a dictionary of formats for all books in the library.
        The key is the book ID and the value is a list of format paths."""
        if self.verbose:
            print_and_log(f"[convert-library]: Retrieving book format information from library: {self.library_dir}")
            
        try:
            args = ["calibredb", "list", "--fields=id,formats", f"--library-path={self.library_dir}", "--for-machine"]
            
            if self.verbose:
                print_and_log(f"[convert-library]: Running command: {' '.join(args)}")
                
            cmd = subprocess.run(
                args,
                env=self.calibre_env,
                capture_output=True,
                check=True,
                text=True,
                encoding='utf-8',
                timeout=300  # 5 minute timeout for large libraries
            )

            # Validate output before parsing
            raw_output = cmd.stdout.strip()
            if not raw_output:
                print_and_log("[convert-library]: No books found in library database.")
                return {}
            
            try:
                books_data = json.loads(raw_output)
            except json.JSONDecodeError as e:
                print_and_log(f"[convert-library]: Failed to parse calibredb command output as JSON: {e}")
                print_and_log(f"[convert-library]: Raw output: {raw_output}")
                return {}
            
            if not isinstance(books_data, list):
                print_and_log(f"[convert-library]: Unexpected JSON format from calibredb. Expected list, got {type(books_data)}")
                return {}

            book_formats = {}
            for book in books_data:
                if not isinstance(book, dict) or 'id' not in book:
                    print_and_log(f"[convert-library]: Skipping malformed book entry: {book}")
                    continue
                    
                try:
                    book_id = int(book['id'])
                    formats = book.get('formats', [])
                    
                    # Validate and clean format paths
                    if formats and isinstance(formats, list):
                        # Filter out None or invalid format entries
                        valid_formats = [f for f in formats if f and isinstance(f, str)]
                        book_formats[book_id] = valid_formats
                    elif formats is None:
                        book_formats[book_id] = []
                    else:
                        if self.verbose:
                            print_and_log(f"[convert-library]: Unexpected formats data for book {book_id}: {formats}")
                        book_formats[book_id] = []
                        
                except (ValueError, KeyError, TypeError) as e:
                    print_and_log(f"[convert-library]: Error processing book entry {book}: {e}")
                    continue
            
            if self.verbose:
                print_and_log(f"[convert-library]: Found {len(book_formats)} books with format information")

        except subprocess.TimeoutExpired:
            print_and_log(f"[convert-library]: Timeout occurred while retrieving book formats from database. This may indicate a very large library or system performance issues.")
            return {}

        except subprocess.CalledProcessError as e:
            print_and_log(f"[convert-library]: An error occurred while running calibredb command {' '.join(args)}: {e}")
            print_and_log(f"[convert-library]: Return code: {e.returncode}")
            if hasattr(e, 'stderr') and e.stderr:
                print_and_log(f"[convert-library]: Error output: {e.stderr}")
            return {}
        except Exception as e:
            print_and_log(f"[convert-library]: Unexpected error retrieving book formats: {e}")
            return {}

        return book_formats

    def get_books_to_convert(self):
        """Returns a list of book format paths to convert."""
        library_formats = self.get_library_book_formats()

        if not library_formats:
            print_and_log("[convert-library]: No books found in library or unable to retrieve format information.")
            return []

        # Filter out books already in the target format (case-insensitive)
        books_with_target_format = set()
        for book_id, formats in library_formats.items():
            for format_path in formats:
                if not format_path or not isinstance(format_path, str):
                    continue
                try:
                    if format_path.lower().endswith(f'.{self.target_format.lower()}'):
                        books_with_target_format.add(book_id)
                        break  # No need to check other formats for this book
                except (AttributeError, UnicodeError):
                    # Skip problematic format paths
                    if self.verbose:
                        print_and_log(f"[convert-library]: Skipping problematic format path: {format_path}")
                    continue
        
        if self.verbose:
            print_and_log(f"[convert-library]: Found {len(books_with_target_format)} books already in {self.target_format} format")

        books_to_convert = [book_id for book_id in library_formats.keys() 
                           if book_id not in books_with_target_format]
        
        if self.verbose:
            print_and_log(f"[convert-library]: {len(books_to_convert)} books need conversion to {self.target_format}")

        # Filter out source formats the user chose to ignore.
        hierarchy_of_success_formats = [format for format in self.hierarchy_of_success if format not in self.convert_ignored_formats]

        if not hierarchy_of_success_formats:
            print_and_log("[convert-library]: WARNING - No valid source formats available after applying ignored formats filter. No conversions will be performed.")
            return []

        if self.convert_ignored_formats:
            print_and_log(f"{', '.join(self.convert_ignored_formats)} in list of user-defined ignored formats for conversion. To change this, navigate to the CWA Settings panel from the Settings page in the Web UI.")

        # Will only contain a single filepath for each book without an existing file in
        # the target format in the format with the highest available conversion success
        # rate, where that filepath is allow to be converted
        to_convert = []

        for book_id in books_to_convert:
            book_formats = library_formats.get(book_id, [])
            if not book_formats:
                if self.verbose:
                    print_and_log(f"[convert-library]: Skipping book {book_id} - no formats found")
                continue
                
            # If multiple formats for a book exist, only the one with the highest
            # success rate will be converted and the rest will be left alone
            for format_ext in hierarchy_of_success_formats:
                if not format_ext or not isinstance(format_ext, str):
                    continue  # Skip invalid format extensions
                    
                # Case-insensitive format matching and file existence validation
                source_formats = []
                for filepath in book_formats:
                    if not filepath or not isinstance(filepath, str):
                        continue
                    try:
                        if (filepath.lower().endswith(f'.{format_ext.lower()}') 
                            and os.path.exists(filepath)):
                            source_formats.append(filepath)
                    except (OSError, AttributeError, UnicodeError):
                        # Skip files with problematic paths
                        if self.verbose:
                            print_and_log(f"[convert-library]: Skipping problematic file path: {filepath}")
                        continue
                if source_formats:
                    to_convert.append(source_formats[0])
                    if self.verbose:
                        print_and_log(f"[convert-library]: Selected {source_formats[0]} for conversion (format: {format_ext})")
                    break
            else:
                # No valid source format found for this book
                if self.verbose:
                    available_formats = []
                    for f in book_formats:
                        if f and os.path.exists(f):
                            try:
                                ext = os.path.splitext(f)[1][1:].lower()
                                if ext:  # Only add non-empty extensions
                                    available_formats.append(ext)
                            except (IndexError, AttributeError):
                                continue  # Skip malformed paths
                    print_and_log(f"[convert-library]: No suitable source format found for book {book_id}. Available: {available_formats}, Hierarchy: {hierarchy_of_success_formats}")

        return to_convert


    def backup(self, input_file, backup_type):
        try:
            output_path = backup_destinations[backup_type]
            shutil.copy2(input_file, output_path)
        except Exception as e:
            print_and_log(f"[convert-library]: ERROR - The following error occurred when trying to copy {input_file} to {output_path}:\n{e}")


    def convert_library(self):
        for file in self.to_convert:
            filename = os.path.basename(file)
            file_extension = Path(file).suffix

            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Converting {filename} from {file_extension} format to {self.target_format} format...")

            try: # Get Calibre Library Book ID from the immediate book folder (e.g., "Title (6120)")
                book_folder = os.path.basename(os.path.dirname(file))
                m = re.search(r"\((\d+)\)$", book_folder)
                book_id = m.group(1)  # type: ignore[attr-defined]
            except Exception as e:
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) A Calibre Library Book ID could not be determined for {file}. Make sure the structure of your calibre library matches the following example:\n")
                print_and_log("Terry Goodkind/")
                print_and_log("└── Wizard's First Rule (6120)")
                print_and_log("    ├── cover.jpg")
                print_and_log("    ├── metadata.opf")
                print_and_log("    └── Wizard's First Rule - Terry Goodkind.epub")

                self.backup(file, backup_type="failed")
                self.current_book += 1
                continue

            if self.target_format == "kepub":
                convert_successful, target_filepath = self.convert_to_kepub(file, file_extension)
                if not convert_successful:
                    print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Conversion of {os.path.basename(file)} was unsuccessful. Moving to next book...")
                    self.current_book += 1
                    continue
            else:
                try: # Convert Book to target format (target is not kepub)
                    target_filepath = f"{self.tmp_conversion_dir}{Path(file).stem}.{self.target_format}"
                    with subprocess.Popen(
                        ["ebook-convert", file, target_filepath],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        env=self.calibre_env,
                        text=True,
                        encoding='utf-8'
                    ) as process:
                        for line in process.stdout: # Read from the combined stdout (which includes stderr)
                            if self.verbose:
                                print_and_log(line)
                            else:
                                print(line)

                    if self.cwa_settings['auto_backup_conversions']:
                        self.backup(file, backup_type="converted")

                    self.db.conversion_add_entry(os.path.basename(target_filepath),
                                                Path(file).suffix,
                                                self.target_format,
                                                str(self.cwa_settings["auto_backup_conversions"]))

                    print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Conversion of {os.path.basename(file)} to {self.target_format} format successful!") # Removed as of V3.0.0 - Removing old version from library...
                except subprocess.CalledProcessError as e:
                    print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Conversion of {os.path.basename(file)} was unsuccessful. See the following error:\n{e}")
                    self.current_book += 1
                    continue

            if self.target_format == "epub" and self.kindle_epub_fixer:
                try:
                    EPUBFixer().process(input_path=target_filepath)
                    print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Resulting EPUB file successfully processed by CWA-EPUB-Fixer!")
                except Exception as e:
                    print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) An error occurred while processing {os.path.basename(target_filepath)} with the kindle-epub-fixer. See the following error:\n{e}")

            try: # Import converted book to library. As of V3.0.0, "add_format" is used instead of "add"
                with subprocess.Popen(
                    ["calibredb", "add_format", book_id, target_filepath, f"--library-path={self.library_dir}"],
                    env=self.calibre_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                ) as process:
                    for line in process.stdout: # Read from the combined stdout (which includes stderr)
                        if self.verbose:
                            print_and_log(line)
                        else:
                            print(line)

                if self.cwa_settings['auto_backup_imports']:
                    self.backup(target_filepath, backup_type="imported")

                self.db.import_add_entry(os.path.basename(target_filepath),
                                        str(self.cwa_settings["auto_backup_imports"]))

                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Import of {os.path.basename(target_filepath)} successfully completed!")
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Import of {os.path.basename(target_filepath)} was not successfully completed. Converted file moved to /config/processed_books/failed/{os.path.basename(target_filepath)}. See the following error:\n{e}")
                try:
                    output_path = f"/config/processed_books/failed/{os.path.basename(target_filepath)}"
                    shutil.move(target_filepath, output_path)
                except Exception as e:
                    print_and_log(f"[convert-library]: ERROR - The following error occurred when trying to copy {file} to {output_path}:\n{e}")
                self.current_book += 1
                continue

            self.set_library_permissions()
            self.empty_tmp_con_dir()
            self.current_book += 1
            continue


    def convert_to_kepub(self, filepath:str ,import_format:str) -> tuple[bool, str]:
        """Kepubify is limited in that it can only convert from epub to kepub, therefore any files not already in epub need to first be converted to epub, and then to kepub"""
        if import_format == "epub":
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) File already in epub format, converting directly to kepub...")

            if self.cwa_settings['auto_backup_conversions']:
                self.backup(filepath, backup_type="converted")

            epub_filepath = filepath
            epub_ready = True
        else:
            print_and_log(f"\n[convert-library]: ({self.current_book}/{len(self.to_convert)}) *** NOTICE TO USER: Kepubify is limited in that it can only convert from epubs. To get around this, CWA will automatically convert other supported formats to epub using the Calibre's conversion tools & then use Kepubify to produce your desired kepubs. Obviously multi-step conversions aren't ideal so if you notice issues with your converted files, bare in mind starting with epubs will ensure the best possible results***\n")
            try: # Convert book to epub format so it can then be converted to kepub
                epub_filepath = f"{self.tmp_conversion_dir}{Path(filepath).stem}.epub"
                with subprocess.Popen(
                    ["ebook-convert", filepath, epub_filepath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=self.calibre_env,
                    text=True
                ) as process:
                    for line in process.stdout: # Read from the combined stdout (which includes stderr)
                        if self.verbose:
                            print_and_log(line)
                        else:
                            print(line)

                if self.cwa_settings['auto_backup_conversions']:
                    self.backup(filepath, backup_type="converted")

                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Intermediate conversion of {os.path.basename(filepath)} to epub from {import_format} successful, now converting to kepub...")
                epub_ready = True
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Intermediate conversion of {os.path.basename(filepath)} to epub was unsuccessful. Cancelling kepub conversion and moving on to next file. See the following error:\n{e}")
                return False, ""

        if epub_ready:
            epub_filepath = Path(epub_filepath)
            target_filepath = f"{self.tmp_conversion_dir}{epub_filepath.stem}.kepub"
            try:
                with subprocess.Popen(
                    ['kepubify', '--inplace', '--calibre', '--output', self.tmp_conversion_dir, epub_filepath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8'
                ) as process:
                    for line in process.stdout: # Read from the combined stdout (which includes stderr)
                        if self.verbose:
                            print_and_log(line)
                        else:
                            print(line)

                if self.cwa_settings['auto_backup_conversions']:
                    self.backup(filepath, backup_type="converted")

                self.db.conversion_add_entry(epub_filepath.stem,
                                            import_format,
                                            self.target_format,
                                            str(self.cwa_settings["auto_backup_conversions"]))

                return True, target_filepath
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) CON_ERROR: {os.path.basename(filepath)} could not be converted to kepub due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
                self.backup(epub_filepath, backup_type="failed")
                return False, ""
        else:
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) An error occurred when converting the original {import_format} to epub. Cancelling kepub conversion and moving on to next file...")
            return False, ""


    def empty_tmp_con_dir(self):
        try:
            files = os.listdir(self.tmp_conversion_dir)
            for file in files:
                file_path = os.path.join(self.tmp_conversion_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError:
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) An error occurred while emptying {self.tmp_conversion_dir}.")


    def set_library_permissions(self):
        try:
            nsm = os.getenv("NETWORK_SHARE_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
            if not nsm:
                subprocess.run(["chown", "-R", "abc:abc", self.library_dir], check=True)
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Successfully set ownership of new files in {self.library_dir} to abc:abc.")
            else:
                print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) NETWORK_SHARE_MODE=true detected; skipping chown of {self.library_dir}")
        except subprocess.CalledProcessError as e:
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) An error occurred while attempting to recursively set ownership of {self.library_dir} to abc:abc. See the following error:\n{e}")


def main():
    parser = argparse.ArgumentParser(
        prog='convert-library',
        description='Made for the purpose of converting ebooks in a calibre library to the users specified target format (default epub)'
    )

    parser.add_argument('--verbose', '-v', action='store_true', required=False, dest='verbose', help='When passed, the output from the ebook-convert command will be included in what is shown to the user in the Web UI', default=False)
    args = parser.parse_args()

    logger.info(f"CWA Convert Library Service - Run Started: {datetime.now()}\n")
    converter = LibraryConverter(args)
    if len(converter.to_convert) > 0:
        converter.convert_library()
    else:
        print_and_log(f'[convert-library]: No books found in library without a copy in the target format ({converter.target_format}). Exiting now...')
        logger.info(f"\nCWA Convert Library Service - Run Ended: {datetime.now()}")
        sys.exit(0)

    print_and_log(f"\n[convert-library]: Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
    logger.info(f"\nCWA Convert Library Service - Run Ended: {datetime.now()}")
    sys.exit(0)


if __name__ == "__main__":
    main()