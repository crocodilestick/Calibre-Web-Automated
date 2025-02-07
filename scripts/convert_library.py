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
file_handler = logging.FileHandler(convert_library_log_file, mode='w')
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

# Set permissions for log file
os.chown(convert_library_log_file, uid, gid)

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
        self.verbose = args.verbose

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings
        self.target_format = self.cwa_settings['auto_convert_target_format']
        self.convert_ignored_formats = self.cwa_settings['auto_convert_ignored_formats']
        self.kindle_epub_fixer = self.cwa_settings['kindle_epub_fixer']

        self.supported_book_formats = {'azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz'}
        self.hierarchy_of_success = {'epub', 'lit', 'mobi', 'azw', 'azw3', 'fb2', 'fbz', 'azw4', 'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt'}

        self.current_book = 1
        self.ingest_folder, self.library_dir, self.tmp_conversion_dir = self.get_dirs('/app/calibre-web-automated/dirs.json') 
        self.to_convert = self.get_books_to_convert()


    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/"
        library_dir = f"{dirs['calibre_library_dir']}/"
        tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

        return ingest_folder, library_dir, tmp_conversion_dir


    def get_books_to_convert(self):
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.library_dir) for f in filenames]

        exclusion_list = [] # If multiple formats for a book exist, only the one with the highest success rate will be converted and the rest will be left alone
        files_already_in_target_format = [f for f in library_files if f.endswith(f'.{self.target_format}')]
        for file in files_already_in_target_format:
            filename, file_extension = os.path.splitext(file)
            exclusion_list.append(filename) # Adding books with a file already in the target format to the exclusion list
        
        to_convert = [] # Will only contain a single filepath for each book without an existing file in the target format in the format with the highest available conversion success rate, where that filepath is allow to be converted
        for format in self.hierarchy_of_success:
            if format in self.convert_ignored_formats:
                print_and_log(f"{format} in list of user-defined ignored formats for conversion. To change this, navigate to the CWA Settings panel from the Settings page in the Web UI.")
                continue
            files_in_format = [f for f in library_files if f.endswith(f'.{format}')]
            if len(files_in_format) > 0:
                for file in files_in_format:
                    filename, file_extension = os.path.splitext(file)
                    if filename not in exclusion_list:
                        to_convert.append(file)
                        exclusion_list.append(filename)

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

            try: # Get Calibre Library Book ID
                book_id = (re.search(r'\(\d*\)', file).group(0))[1:-1] # type: ignore
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
                convert_successful, target_filepath = self.convert_to_kepub(filename, file_extension)
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
                        text=True
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
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True
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
                    text=True
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
            subprocess.run(["chown", "-R", "abc:abc", self.library_dir], check=True)
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Successfully set ownership of new files in {self.library_dir} to abc:abc.")
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
        print_and_log("[convert-library]: No books found in library without a copy in the target format. Exiting now...")
        logger.info(f"\nCWA Convert Library Service - Run Ended: {datetime.now()}")
        sys.exit(0)

    print_and_log(f"\n[convert-library]: Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
    logger.info(f"\nCWA Convert Library Service - Run Ended: {datetime.now()}")
    sys.exit(0)


if __name__ == "__main__":
    main()