# import argparse
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

from cwa_db import CWA_DB
from kindle_epub_fixer import EPUBFixer


logger = logging.getLogger(__name__)
logging.basicConfig(filename='/config/convert-library.log', level=logging.INFO, filemode='w')

def print_and_log(string) -> None:
    logging.info(string)
    print(string)


# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/convert_library.lock', 'x')
    lock.close()
except FileExistsError:
    print_and_log("[convert-library]: CANCELLING... convert-library was initiated but is already running")
    print_and_log("FIN")
    sys.exit(2)

# Defining function to delete the lock on script exit
def removeLock():
    os.remove(tempfile.gettempdir() + '/convert_library.lock')

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


class LibraryConverter:
    def __init__(self) -> None: #args
        # self.args = args
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


    def convert_library(self):
        for file in self.to_convert:
            filename = os.path.basename(file)
            file_extension = Path(file).suffix

            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)}) Converting {filename} from {file_extension} format to {self.target_format} format...")

            try: # Get Calibre Library Book ID
                book_id = (re.search(r'\(\d*\)', file).group(0))[1:-1]
            except Exception as e:
                print_and_log(f"[convert-library]: A Calibre Library Book ID could not be determined for {file}. Make sure the structure of your calibre library matches the following example:\n")
                print_and_log("Terry Goodkind/")
                print_and_log("└── Wizard's First Rule (6120)")
                print_and_log("    ├── cover.jpg")
                print_and_log("    ├── metadata.opf")
                print_and_log("    └── Wizard's First Rule - Terry Goodkind.epub")

                shutil.copyfile(file, f"/config/processed_books/failed/{os.path.basename(file)}")
                self.current_book += 1
                continue

            if self.target_format == "kepub":
                convert_successful, target_filepath = self.convert_to_kepub(filename, file_extension)
                if not convert_successful:
                    print_and_log(f"[convert-library]: Conversion of {os.path.basename(file)} was unsuccessful. See the following error:\n{e}")
                    self.current_book += 1
                    continue
            else:
                try: # Convert Book to target format (target is not kepub)
                    target_filepath = f"{self.tmp_conversion_dir}{Path(file).stem}.{self.target_format}"
                    subprocess.run(["ebook-convert", file, target_filepath], check=True)

                    if self.cwa_settings['auto_backup_conversions']:
                        shutil.copyfile(file, f"/config/processed_books/converted/{os.path.basename(file)}")

                    self.db.conversion_add_entry(os.path.basename(target_filepath),
                                                Path(file).suffix,
                                                self.target_format,
                                                str(self.cwa_settings["auto_backup_conversions"]))

                    print_and_log(f"[convert-library]: Conversion of {os.path.basename(file)} to {self.target_format} format successful!") # Removed as of V3.0.0 - Removing old version from library...
                except subprocess.CalledProcessError as e:
                    print_and_log(f"[convert-library]: Conversion of {os.path.basename(file)} was unsuccessful. See the following error:\n{e}")
                    self.current_book += 1
                    continue

            if self.target_format == "epub" and self.kindle_epub_fixer:
                try:
                    EPUBFixer(target_filepath).process()
                except Exception as e:
                    print_and_log(f"[convert-library] An error occurred while processing {os.path.basename(target_filepath)} with the kindle-epub-fixer. See the following error:\n{e}")

            try: # Import converted book to library. As of V3.0.0, "add_format" is used instead of "add"
                subprocess.run(["calibredb", "add_format", book_id, target_filepath, f"--library-path={self.library_dir}"], check=True)

                if self.cwa_settings['auto_backup_imports']:
                    shutil.copyfile(target_filepath, f"/config/processed_books/imported/{os.path.basename(target_filepath)}")

                self.db.import_add_entry(os.path.basename(target_filepath),
                                        str(self.cwa_settings["auto_backup_imports"]))

                print_and_log(f"[convert-library]: Import of {os.path.basename(target_filepath)} successfully completed!")
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: Import of {os.path.basename(target_filepath)} was not successfully completed. Converted file moved to /config/processed_books/failed/{os.path.basename(target_filepath)}. See the following error:\n{e}")
                shutil.move(target_filepath, f"/config/processed_books/failed/{os.path.basename(target_filepath)}")
                self.current_book += 1
                continue

            ### As of Version 3.0.0, CWA will no longer remove the originals of converted files as CWA now supports multiple formats for each book ###

            # try: # Remove Book from Existing Library
            #     subprocess.run(["calibredb", "remove", book_id, "--permanent", "--with-library", self.library_dir], check=True)

            #     print_and_log(f"[convert-library]: Non-epub version of {Path(file).stem} (Book ID: {book_id}) was successfully removed from library.\nAdding converted version to library...")
            # except subprocess.CalledProcessError as e:
            #     print_and_log(f"[convert-library]: Non-epub version of {Path(file).stem} couldn't be successfully removed from library. See the following error:\n{e}")
            #     self.current_book += 1
            #     continue

            self.set_library_permissions()
            self.empty_tmp_con_dir()
            self.current_book += 1
            continue


    def convert_to_kepub(self, filepath:str ,import_format:str) -> tuple[bool, str]:
        """Kepubify is limited in that it can only convert from epub to kepub, therefore any files not already in epub need to first be converted to epub, and then to kepub"""
        if import_format == "epub":
            print_and_log(f"[convert-library]: File in epub format, converting directly to kepub...")

            if self.cwa_settings['auto_backup_conversions']:
                shutil.copyfile(file, f"/config/processed_books/converted/{os.path.basename(filepath)}")

            epub_filepath = filepath
            epub_ready = True
        else:
            print_and_log("\n[convert-library]: *** NOTICE TO USER: Kepubify is limited in that it can only convert from epubs. To get around this, CWA will automatically convert other supported formats to epub using the Calibre's conversion tools & then use Kepubify to produce your desired kepubs. Obviously multi-step conversions aren't ideal so if you notice issues with your converted files, bare in mind starting with epubs will ensure the best possible results***\n")
            try: # Convert book to epub format so it can then be converted to kepub
                epub_filepath = f"{self.tmp_conversion_dir}{Path(filepath).stem}.epub"
                subprocess.run(["ebook-convert", filepath, epub_filepath], check=True)

                if self.cwa_settings['auto_backup_conversions']:
                    shutil.copyfile(file, f"/config/processed_books/converted/{os.path.basename(filepath)}")

                print_and_log(f"[convert-library]: Intermediate conversion of {os.path.basename(filepath)} to epub from {import_format} successful, now converting to kepub...")
                epub_ready = True
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: Intermediate conversion of {os.path.basename(filepath)} to epub was unsuccessful. Cancelling kepub conversion and moving on to next file. See the following error:\n{e}")
                return False, ""
            
        if epub_ready:
            epub_filepath = Path(epub_filepath)
            target_filepath = f"{self.tmp_conversion_dir}{epub_filepath.stem}.kepub"
            try:
                subprocess.run(['kepubify', '--inplace', '--calibre', '--output', self.tmp_conversion_dir, epub_filepath], check=True)
                if self.cwa_settings['auto_backup_conversions']:
                    shutil.copy2(filepath, f"/config/processed_books/converted")

                self.db.conversion_add_entry(epub_filepath.stem,
                                            import_format,
                                            self.target_format,
                                            str(self.cwa_settings["auto_backup_conversions"]))

                return True, target_filepath
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: CON_ERROR: {os.path.basename(filepath)} could not be converted to kepub due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
                shutil.copy2(epub_filepath, f"/config/processed_books/failed")
                return False, ""
        else:
            print_and_log(f"[convert-library]: An error occurred when converting the original {import_format} to epub. Cancelling kepub conversion and moving on to next file...")
            return False, ""


    def empty_tmp_con_dir(self):
        try:
            files = os.listdir(self.tmp_conversion_dir)
            for file in files:
                file_path = os.path.join(self.tmp_conversion_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError:
            print_and_log(f"[convert-library] An error occurred while emptying {self.tmp_conversion_dir}.")


    def set_library_permissions(self):
        try:
            subprocess.run(["chown", "-R", "abc:abc", self.library_dir], check=True)
        except subprocess.CalledProcessError as e:
            print_and_log(f"[convert-library] An error occurred while attempting to recursively set ownership of {self.library_dir} to abc:abc. See the following error:\n{e}")


def main():
    # parser = argparse.ArgumentParser(
    #     prog='convert-library',
    #     description='Made for the purpose of converting ebooks in a calibre library not in epub format, to epub format'
    # )

    # parser.add_argument('--replace', '-r', action='store_true', required=False, dest='replace', help='Replaces the old library with the new one', default=False)
    # parser.add_argument('--keep', '-k', action='store_true', required=False, dest='keep', help='Creates a new epub library with the old one but stores the old files in /config/processed_books', default=False)
    # args = parser.parse_args()

    # if not args.replace and not args.keep:
    #     print("[convert-library]: You must specify either the --replace/-r or --keep/-k flag")
    #     sys.exit(0)
    # else:
    converter = LibraryConverter() # args
    if len(converter.to_convert) > 0:
        converter.convert_library()
    else:
        print_and_log("[convert-library] No books found in library without a copy in the target format. Exiting now...")
        logging.info("FIN")
        sys.exit(0)

    print_and_log(f"\n[convert-library] Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
    logging.info("FIN")
    sys.exit(0)


if __name__ == "__main__":
    main()