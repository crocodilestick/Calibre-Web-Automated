import zipfile
import os
import re
import xml.etree.ElementTree as ET
import sys
import argparse
from pathlib import Path
import logging
import tempfile
import atexit
from datetime import datetime
import json

### Code adapted from https://github.com/innocenat/kindle-epub-fix
### Translated from Javascript to Python by community member tedderstar
### & modified and integrated into CWA by CrocodileStick

# Global Variables
dirs_json = "/app/calibre-web-automated/dirs.json"
change_logs_dir = "/app/calibre-web-automated/metadata_change_logs"
metadata_temp_dir = "/app/calibre-web-automated/metadata_temp"

logger = logging.getLogger(__name__)
LOG_FORMAT = '%(message)s'
logging.basicConfig(filename='/config/epub-fixer.log',
                    level=logging.INFO,
                    filemode='w',
                    format=LOG_FORMAT)

def print_and_log(string) -> None:
    logging.info(string)
    print(string)

# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/kindle_epub_fixer.lock', 'x')
    lock.close()
except FileExistsError:
    print_and_log("[cwa-kindle-epub-fixer] CANCELLING... kindle-epub-fixer was initiated but is already running")
    logging.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}")
    sys.exit(2)

# Defining function to delete the lock on script exit
def removeLock():
    try:
        os.remove(tempfile.gettempdir() + '/kindle_epub_fixer.lock')
    except FileNotFoundError:
        ...

# Will automatically run when the script exits
atexit.register(removeLock)

class EPUBFixer:
    def __init__(self, epub_path:str, as_script=False):
        self.epub_path = epub_path
        self.as_script = as_script
        self.files = {}
        self.fixed_problems = []

    def read_epub(self):
        with zipfile.ZipFile(self.epub_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                ext = os.path.splitext(file)[1]
                if ext in ['.html', '.xhtml', '.xml', '.css', '.opf', '.ncx', '.svg']:
                    self.files[file] = zip_ref.read(file).decode('utf-8')
                else:
                    self.files[file] = zip_ref.read(file)

    def fix_encoding(self):
        encoding_declaration = '<?xml version="1.0" encoding="utf-8"?>'
        xml_declaration_pattern = re.compile(r'^<\?xml.*?\?>', re.IGNORECASE)

        for filename, content in self.files.items():
            if filename.endswith(('.html', '.xhtml')):
                if not xml_declaration_pattern.match(content):
                    self.files[filename] = f"{encoding_declaration}\n{content}"
                    self.fixed_problems.append(f"Fixed encoding for file {filename}")
                    if self.as_script:
                        print_and_log(f"   - Fixed encoding for file {filename}")
                    else:
                        print(f"   - Fixed encoding for file {filename}")

    def fix_language(self):
        allowed_languages = {# ISO 639-1
                            'af', 'gsw', 'ar', 'eu', 'nb', 'br', 'ca', 'zh', 'kw', 'co', 'da', 'nl', 'stq', 'en', 'fi', 'fr', 'fy', 'gl',
                            'de', 'gu', 'hi', 'is', 'ga', 'it', 'ja', 'lb', 'mr', 'ml', 'gv', 'frr', 'nb', 'nn', 'pl', 'pt', 'oc', 'rm',
                            'sco', 'gd', 'es', 'sv', 'ta', 'cy',
                            # ISO 639-2
                            'afr', 'ara', 'eus', 'baq', 'nob', 'bre', 'cat', 'zho', 'chi', 'cor', 'cos', 'dan', 'nld', 'dut', 'eng', 'fin',
                            'fra', 'fre', 'fry', 'glg', 'deu', 'ger', 'guj', 'hin', 'isl', 'ice', 'gle', 'ita', 'jpn', 'ltz', 'mar', 'mal',
                            'glv', 'nor', 'nno', 'por', 'oci', 'roh', 'gla', 'spa', 'swe', 'tam', 'cym', 'wel'}
        opf_file = next((f for f in self.files if f.endswith('.opf')), None)

        if opf_file:
            root = ET.fromstring(self.files[opf_file])
            lang_tag = root.find(".//{http://purl.org/dc/elements/1.1/}language")

            current_lang = lang_tag.text if lang_tag is not None else 'undefined'

            if current_lang not in allowed_languages:
                new_lang = "en"  # Automatically set to 'en' for unsupported languages

                if lang_tag is None:
                    metadata = root.find(".//{http://www.idpf.org/2007/opf}metadata")
                    lang_tag = ET.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}language") # type: ignore
                lang_tag.text = new_lang

                self.files[opf_file] = ET.tostring(root, encoding='unicode')
                self.fixed_problems.append(f"Updated language from {current_lang} to {new_lang}")
                if self.as_script:
                    print_and_log(f"   - Updated language from {current_lang} to {new_lang}")
                else:
                    print(f"   - Updated language from {current_lang} to {new_lang}")

    def fix_stray_images(self):
        img_tag_pattern = re.compile(r'<img([^>]*)>', re.IGNORECASE)
        src_pattern = re.compile(r'src\s*=\s*[\'"].+?[\'"]', re.IGNORECASE)

        for filename, content in self.files.items():
            if filename.endswith(('.html', '.xhtml')):
                original_content = content
                content = re.sub(
                    img_tag_pattern,
                    lambda match: '' if not src_pattern.search(match.group(1)) else match.group(0),
                    content
                )

                if content != original_content:
                    self.files[filename] = content
                    self.fixed_problems.append(f"Removed stray images in {filename}")
                    if self.as_script:
                        print_and_log(f"   - Removed stray images in {filename}")
                    else:
                        print(f"   - Removed stray images in {filename}")

    def write_epub(self):
        with zipfile.ZipFile(self.epub_path, 'w') as zip_out:
            for filename, content in self.files.items():
                if isinstance(content, str):
                    zip_out.writestr(filename, content.encode('utf-8'))
                else:
                    zip_out.writestr(filename, content)

    def process(self):
        self.read_epub()
        self.fix_encoding()
        self.fix_language()
        self.fix_stray_images()
        self.write_epub()
        print("[cwa-kindle-epub-fixer] Processing completed.")
        if self.fixed_problems:
            print(f"[cwa-kindle-epub-fixer] {len(self.fixed_problems)} issues fixed with {self.epub_path}:")
            for count, problem in enumerate(self.fixed_problems):
                print(f"   {count} - {problem}")
        else:
            print(f"[cwa-kindle-epub-fixer] No issues found! - {self.epub_path}")


def get_library_location() -> str:
    """Gets Calibre-Library location from dirs_json path"""
    with open(dirs_json, 'r') as f:
        dirs = json.load(f)
    return dirs['calibre_library_dir'] # Returns without / on the end

def get_all_epubs_in_library() -> list[str]:
    """ Returns a list if the book dir given contains files of one or more of the supported formats"""
    library_location = get_library_location()
    library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(library_location) for f in filenames]
    epubs_in_library = [f for f in library_files if f.endswith(f'.epub')]
    return epubs_in_library


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='kindle-epub-fixer',
        description='Checks the encoding of a given epub file and automatically corrects any errors that would \
        potentially prevent the file from being compatible with Amazon\'s Send-to-Kindle service. If the "-all" \
        flag is passed, all epub files in the user\'s calibre library will be processed'
    )

    parser.add_argument('--file', '-f',  action='store', dest='file', required=False, help='Will enforce the covers and metadata of the books in the given log file.', default=None)
    parser.add_argument('--all', '-a', action='store_true', dest='all', help='Will enforce covers & metadata for ALL books currently in your calibre-library-dir', default=False)
    args = parser.parse_args()

    logging.info(f"CWA Kindle EPUB Fixer Service - Run Started: {datetime.now()}\n")
    if not args.file and not args.all:
        print("[cwa-kindle-epub-fixer] ERROR - Nothing given")
        logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(4)
    elif args.all and args.file:
        print("[cwa-kindle-epub-fixer] ERROR - Can't give all and file at the same time")
        logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(5)
    elif args.file and not args.all:
        if not args.file.lower().endswith('.epub'):
            print("[cwa-kindle-epub-fixer] ERROR - The input file must be an EPUB file with a .epub extension.")
            logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(1)
        else:
            if Path(args.file).exists():
                print(f"[cwa-kindle-epub-fixer] Processing given file - {args.file}...")
                EPUBFixer(args.file, as_script=True).process()
                logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
                sys.exit(0)
            else:
                print(f"[cwa-kindle-epub-fixer] ERROR - Given file {args.file} does not exist")
                logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
                sys.exit(3)
    elif args.all and not args.file:
        print("[cwa-kindle-epub-fixer] Processing all epubs in library...")
        epubs_to_process = get_all_epubs_in_library()
        if len(epubs_to_process) > 0:
            print_and_log(f"[cwa-kindle-epub-fixer] {len(epubs_to_process)} EPUBs found to process.")
            for count, epub in enumerate(epubs_to_process):
                try:
                    print_and_log(f"[cwa-kindle-epub-fixer] {count}/{len(epubs_to_process)} - Processing {epub}...")
                    EPUBFixer(epub, as_script=True).process()
                except Exception as e:
                    print_and_log(f"[cwa-kindle-epub-fixer] {count}/{len(epubs_to_process)} - The following error occurred when processing {epub}\n{e}")
            print_and_log(f"All {len(epubs_to_process)} EPUBs in Library successfully processed! Exiting now...")
            logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(0)
        else:
            print_and_log("[cwa-kindle-epub-fixer] No EPUBs found to process. Exiting now...")
            logging.info(f"CWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(0)