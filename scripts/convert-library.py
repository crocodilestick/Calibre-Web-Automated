# import argparse
import json
import logging
import os
import re
import sys
import shutil
from pathlib import Path
import subprocess

from cwa_db import CWA_DB

logger = logging.getLogger(__name__)
logging.basicConfig(filename='/config/calibre-web.log', level=logging.INFO)

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

        self.supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz']
        self.hierarchy_of_success = ['lit', 'mobi', 'azw', 'azw3', 'fb2', 'fbz', 'azw4', 'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt']

        self.ingest_folder, self.library_dir, tmp_conversion_dir = self.get_dirs('/app/calibre-web-automated/dirs.json') 
        self.epubs, self.to_convert = self.get_library_books()
        self.current_book = 1

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

    def get_library_books(self):
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.library_dir) for f in filenames]
        epub_files = [f for f in library_files if f.endswith('.epub')]
        dupe_list = []
        to_convert = []
        for format in self.hierarchy_of_success:
            format_files = [f for f in library_files if f.endswith(f'.{format}')]
            if len(format_files) > 0:
                for file in format_files:
                    filename, file_extension = os.path.splitext(file)
                    if filename not in dupe_list:
                        to_convert.append(file)
                        dupe_list.append(filename)

        return epub_files, to_convert

    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/"
        library_dir = f"{dirs['calibre_library_dir']}/"
        tmp_conversion_dir = f"{dirs['tmp_conversion_dir']}/"

        return ingest_folder, library_dir, tmp_conversion_dir

    def convert_library(self):
        for file in self.to_convert:
            print_and_log(f"[convert-library]: ({self.current_book}/{len(self.to_convert)})  Converting {os.path.basename(file)}...")

            filename = os.path.basename(file)
            file_extension = Path(file).suffix

            try: # Get Calibre Library Book ID
                book_id = (re.search(r'\(\d*\)', file).group(0))[1:-1]
            except Exception as e:
                print_and_log(f"[convert-library] A Calibre Library Book ID could not be determined for {file}. Make sure the structure of your calibre library matches the following example:\n")
                print_and_log("Terry Goodkind/")
                print_and_log("└── Wizard's First Rule (6120)")
                print_and_log("    ├── cover.jpg")
                print_and_log("    ├── metadata.opf")
                print_and_log("    └── Wizard's First Rule - Terry Goodkind.epub")

                shutil.copyfile(file, f"/config/processed_books/failed/{os.path.basename(file)}")
                self.current_book += 1
                continue

            try: # Convert Book
                target_filepath = f"{self.tmp_conversion_dir}{Path(file).stem}.epub"
                subprocess.run(["ebook-convert", file, target_filepath], check=True)

                if self.cwa_settings['auto_backup_conversions']:
                    shutil.copyfile(file, f"/config/processed_books/converted/{os.path.basename(file)}")

                self.db.conversion_add_entry(os.path.basename(target_filepath),
                                             Path(file).suffix,
                                             str(self.cwa_settings["auto_backup_conversions"]))

                print_and_log(f"[convert-library]: Conversion of {os.path.basename(file)} successful! Removing old version from library...")
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: Conversion of {os.path.basename(file)} was unsuccessful. See the following error:\n{e}")
                shutil.copyfile(file, f"/config/processed_books/failed/{os.path.basename(file)}")
                self.current_book += 1
                continue

            try: # Remove Book from Existing Library
                subprocess.run(["calibredb", "remove", book_id, "--permanent", "--with-library", self.library_dir], check=True)

                print_and_log(f"[convert-library]: Non-epub version of {Path(file).stem} (Book ID: {book_id}) was successfully removed from library.\nAdding converted version to library...")
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: Non-epub version of {Path(file).stem} couldn't be successfully removed from library. See the following error:\n{e}")
                self.current_book += 1
                continue

            try: # Import converted book to library
                subprocess.run(["calibredb", "add", target_filepath, f"--library-path={self.library_dir}"], check=True)

                if self.cwa_settings['auto_backup_imports']:
                    shutil.copyfile(target_filepath, f"/config/processed_books/imported/{os.path.basename(target_filepath)}")

                self.db.import_add_entry(os.path.basename(target_filepath),
                                         str(self.cwa_settings["auto_backup_imports"]))

                print_and_log(f"[convert-library]: Import of {os.path.basename(target_filepath)} successfully completed!")
            except subprocess.CalledProcessError as e:
                print_and_log(f"[convert-library]: Import of {os.path.basename(target_filepath)} was not successfully completed. See the following error:\n{e}")
                self.current_book += 1
                continue

            
            self.current_book += 1
            continue

    def empty_tmp_con_dir(self):
        try:
            files = os.listdir(self.tmp_conversion_dir)
            for file in files:
                file_path = os.path.join(self.tmp_conversion_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError:
            print(f"Error occurred while emptying {self.tmp_conversion_dir}.")

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
        print_and_log("[convert-library] No non-epubs found in library. Exiting now...")
        sys.exit(0)

    print_and_log(f"\n[convert-library] Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
    sys.exit(0)

def print_and_log(string) -> None:
    logging.info(string)
    print(string)


if __name__ == "__main__":
    main()