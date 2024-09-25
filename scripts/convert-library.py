import argparse
import glob
import json
import logging
import os
import re
import sys

from cwa_db import CWA_DB

logger = logging.getLogger(__name__)

class LibraryConverter:
    def __init__(self, args) -> None:
        self.args = args

        self.supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz']
        self.hierarchy_of_success = ['lit', 'mobi', 'azw', 'azw3', 'fb2', 'fbz', 'azw4', 'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt']

        self.dirs = self.get_dirs() # Dirs are assigned by user during setup
        self.ingest_folder = f"{self.dirs['ingest_folder']}/" # Dir where new files are looked for to process and subsequently deleted
        self.library = f"{self.dirs['calibre_library_dir']}/"
        self.epubs, self.to_convert = self.get_library_books()
        self.current_book = 1

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

    def get_library_books(self):
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.library) for f in filenames]
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

    def get_dirs(self) -> dict[str, str]:
        dirs = {}
        with open('/app/calibre-web-automated/dirs.json', 'r') as f:
            dirs: dict[str, str] = json.load(f)

        return dirs

    def convert_library(self):
        for file in self.to_convert:
            logging.basicConfig(filename='/config/calibre-web.log', level=logging.INFO)
            print(f"[convert-library]: ({self.current_book}/{len(self.to_convert)})  Converting {os.path.basename(file)}...")
            logging.info(f"[convert-library]: ({self.current_book}/{len(self.to_convert)})  Converting {os.path.basename(file)}...")
            filename, file_extension = os.path.splitext(file)
            filename = filename.split('/')[-1]
            book_id = (re.search(r'\(\d*\)', file).group(0))[1:-1]
            os.system(f"cp '{file}' '/config/processed_books/{filename}{file_extension}'")
            os.system(f"calibredb remove {book_id} --permanent --with-library '{self.library}'")
            os.system(f"ebook-convert '/config/processed_books/{filename}{file_extension}' '{self.import_folder}{filename}.epub'") # >>/config/calibre-web.log 2>&1
            os.system(f"chown -R abc:abc '{self.library}'")
            logging.info(f"[convert-library]: Conversion of {os.path.basename(file)} complete!")
            self.current_book += 1
            if not self.args.keep:
                os.remove(f"/config/processed_books/{filename}{file_extension}")

    def empty_import_folder(self):
        os.system(f"chown -R abc:abc '{self.import_folder}'")
        files = glob.glob(f"{self.import_folder}*")
        for f in files:
            os.remove(f)

def main():
    parser = argparse.ArgumentParser(
        prog='convert-library',
        description='Made for the purpose of converting ebooks in a calibre library not in epub format, to epub format'
    )

    parser.add_argument('--replace', '-r', action='store_true', required=False, dest='replace', help='Replaces the old library with the new one', default=False)
    parser.add_argument('--keep', '-k', action='store_true', required=False, dest='keep', help='Creates a new epub library with the old one but stores the old files in /config/processed_books', default=False)
    args = parser.parse_args()

    if not args.replace and not args.keep:
        print("[convert-library]: You must specify either the --replace/-r or --keep/-k flag")
        sys.exit(0)
    else:
        converter = LibraryConverter(args)
        if len(converter.to_convert) > 0:
            converter.convert_library()
        else:
            print("[convert-library] No non-epubs found in library. Exiting now...")
            logging.info("[convert-library] No non-epubs found in library. Exiting now...")
            sys.exit(0)

        print(f"\n[convert-library] Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
        logging.info(f"[convert-library] Library conversion complete! {len(converter.to_convert)} books converted! Exiting now...")
        sys.exit(0)

if __name__ == "__main__":
    main()
