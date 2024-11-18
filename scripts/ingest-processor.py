import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
from pathlib import Path

from cwa_db import CWA_DB


# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/ingest-processor.lock', 'x')
    lock.close()
except FileExistsError:
    print("CANCELLING... ingest-processor initiated but is already running")
    sys.exit(2)

# Defining function to delete the lock on script exit
def removeLock():
    os.remove(tempfile.gettempdir() + '/ingest-processor.lock')

# Will automatically run when the script exits
atexit.register(removeLock)

# Make sure required directories are present
required_directories = [
    "/config/.cwa_conversion_tmp",
    "/config/processed_books",
    "/config/processed_books/imported",
    "/config/processed_books/failed",
    "/config/processed_books/converted"
]
for directory in required_directories:
    Path(directory).mkdir(exist_ok=True)
    os.system(f"chown -R abc:abc {directory}")


class NewBookProcessor:
    def __init__(self, filepath: str):
        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

        self.auto_convert_on = self.db.cwa_settings['auto_convert']
        self.target_format = self.db.cwa_settings['auto_convert_target_format']
        self.ingest_ignored_formats = self.db.cwa_settings['auto_ingest_ignored_formats']
        self.convert_ignored_formats = self.db.cwa_settings['auto_convert_ignored_formats']

        self.supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txtz', 'txt']
        self.hierarchy_of_success = ['lit', 'mobi', 'azw', 'epub', 'azw3', 'fb2', 'fbz', 'azw4',  'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt']
        self.ingest_folder, self.library_dir, self.tmp_conversion_dir = self.get_dirs("/app/calibre-web-automated/dirs.json")

        self.filepath = filepath # path of the book we're targeting
        self.filename = os.path.basename(filepath)
        self.is_target_format = bool(self.filepath.endswith(self.target_format))


    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/"
        library_dir = f"{dirs['calibre_library_dir']}/"
        tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

        return ingest_folder, library_dir, tmp_conversion_dir


    def convert_book(self, import_format: str) -> tuple[bool, str]:
        """Uses the following terminal command to convert the books provided using the calibre converter tool:\n\n--- ebook-convert myfile.input_format myfile.output_format\n\nAnd then saves the resulting files to the calibre-web import folder."""
        print(f"[ingest-processor]: START_CON: Converting {self.filename}...\n")
        original_filepath = Path(self.filepath)
        target_filepath = f"{self.tmp_conversion_dir}{original_filepath.stem}.{self.target_format}"
        try:
            t_convert_book_start = time.time()
            subprocess.run(['ebook-convert', self.filepath, target_filepath], check=True)
            t_convert_book_end = time.time()
            time_book_conversion = t_convert_book_end - t_convert_book_start
            print(f"\n[ingest-processor]: END_CON: Conversion of {self.filename} complete in {time_book_conversion:.2f} seconds.\n")

            if self.cwa_settings['auto_backup_conversions']:
                shutil.copyfile(self.filepath, f"/config/processed_books/converted/{os.path.basename(original_filepath)}")

            self.db.conversion_add_entry(original_filepath.stem,
                                        import_format,
                                        str(self.cwa_settings["auto_backup_conversions"]))

            return True, target_filepath

        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor]: CON_ERROR: {self.filename} could not be converted to epub due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
            shutil.copyfile(self.filepath, f"/config/processed_books/failed/{os.path.basename(original_filepath)}")
            return False, ""


    def can_convert_check(self, bool_only=False) -> tuple[bool, str]:
        """When the current filepath isn't of the target format, this function will check if the file is able to be converted to the target format,
        returning a can_convert bool with the answer"""
        can_convert = False
        import_format = Path(self.filepath).suffix
        if import_format in self.supported_book_formats:
            can_convert = True

        if bool_only:
            return can_convert, import_format
        else:
            return can_convert


    def delete_current_file(self) -> None:
        """Deletes file just processed from ingest folder"""
        os.remove(self.filepath) # Removes processed file
        subprocess.run(["find", f"{self.ingest_folder}", "-type", "d", "-empty", "-delete"]) # Removes any now empty folders


    def add_book_to_library(self, book_path) -> None:
        print("[ingest-processor]: Importing new book to CWA...")
        import_path = Path(book_path)
        import_filename = os.path.basename(book_path)
        try:
            subprocess.run(["calibredb", "add", book_path, f"--library-path={self.library_dir}"], check=True)
            print(f"[ingest-processor] Added {import_path.stem} to Calibre database")

            if self.cwa_settings['auto_backup_imports']:
                shutil.copyfile(book_path, f"/config/processed_books/imported/{import_filename}")

            self.db.import_add_entry(import_path.stem,
                                    str(self.cwa_settings["auto_backup_imports"]))

        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor] {import_path.stem} was not able to be added to the Calibre Library due to the following error:\nCALIBREDB EXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
            shutil.copyfile(book_path, f"/config/processed_books/failed/{import_filename}")


    def empty_tmp_con_dir(self):
        try:
            files = os.listdir(self.tmp_conversion_dir)
            for file in files:
                file_path = os.path.join(self.tmp_conversion_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError:
            print(f"[ingest-processor] An error occurred while emptying {self.tmp_conversion_dir}.")

    def set_library_permissions(self):
        try:
            subprocess.run(["chown", "-R", "abc:abc", self.library_dir], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor] An error occurred while attempting to recursively set ownership of {self.library_dir} to abc:abc. See the following error:\n{e}")


def main(filepath=sys.argv[1]):
    # Check if filepath is a directory
    # If it is, main will be ran on every file in the given directory
    # Inotifywait won't detect files inside folders if the folder was moved rather than copied
    if os.path.isdir(filepath):
        print(os.listdir(filepath))
        for filename in os.listdir(filepath):
            f = os.path.join(filepath, filename)
            main(f)
        return

    nbp = NewBookProcessor(filepath)

    # Check if the user has chosen to exclude files of this type from the ingest process
    if Path(nbp.filename).suffix in nbp.ingest_ignored_formats:
        continue
    else:
        if nbp.is_target_format: # File can just be imported
            print(f"\n[ingest-processor]: No conversion needed for {nbp.filename}, importing now...")
            nbp.add_book_to_library(filepath)
        else:
            if nbp.auto_convert_on and nbp.can_convert_check(bool_only=True): # File can be converted to target format and Auto-Converter is on
                print(f"\n[ingest-processor]: Starting conversion process for {nbp.filename}...")
                can_convert, import_format = nbp.can_convert_check()
                print(f"[ingest-processor]: Converting file from {import_format} to epub format...\n")

                if can_convert:
                    result, converted_filepath = nbp.convert_book(import_format)
                    if result:
                        nbp.add_book_to_library(converted_filepath)
                        nbp.empty_tmp_con_dir()
            elif not nbp.auto_convert_on and nbp.can_convert_check(bool_only=True): # Books not in target format but Auto-Converter is off so files are imported anyway
                print(f"\n[ingest-processor]: {nbp.filename} not in target format but CWA Auto-Convert is deactivated so importing file anyway...")
                nbp.add_book_to_library(filepath)
            else:
                print(f"[ingest-processor]: Cannot convert {nbp.filepath}. {import_format} is currently unsupported / is not a known ebook format.")

            nbp.set_library_permissions()
            nbp.delete_current_file()
            del nbp # New in Version 2.0.0, should drastically reduce memory usage with large ingests

if __name__ == "__main__":
    main()
