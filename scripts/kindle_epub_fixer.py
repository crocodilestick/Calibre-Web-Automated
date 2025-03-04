import os
import re
import zipfile
from xml.dom import minidom
import argparse
from pathlib import Path
import sys

import logging
import tempfile
import atexit
from datetime import datetime
import json
import shutil

import pwd
import grp

from cwa_db import CWA_DB

### Code adapted from https://github.com/innocenat/kindle-epub-fix
### Translated from Javascript to Python & modified by crocodilestick

### Global Variables
dirs_json = "/app/calibre-web-automated/dirs.json"
change_logs_dir = "/app/calibre-web-automated/metadata_change_logs"
metadata_temp_dir = "/app/calibre-web-automated/metadata_temp"
# Log file path
epub_fixer_log_file = "/config/epub-fixer.log"

### LOGGING
# Define the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set the logging level
# Create a FileHandler
file_handler = logging.FileHandler(epub_fixer_log_file, mode='w')
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
os.chown(epub_fixer_log_file, uid, gid)

def print_and_log(string, log=True) -> None:
    """ Ensures the provided string is passed to STDOUT AND stored in the run's log file """
    if log:
        logger.info(string.replace("[cwa-kindle-epub-fixer] ", ""))
    print(string)

### LOCK FILES
# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/kindle_epub_fixer.lock', 'x')
    lock.close()
except FileExistsError:
    print_and_log("[cwa-kindle-epub-fixer] CANCELLING... kindle-epub-fixer was initiated but is already running")
    logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}")
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
    def __init__(self, manually_triggered:bool=False, current_position:str=None):
        self.manually_triggered = manually_triggered
        self.current_position = current_position # string in the form of "n/n"

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

        self.fixed_problems = []
        self.files = {}
        self.binary_files = {}
        self.entries = []


    def backup_original_file(self, epub_path):
        """Backup original file"""
        if self.cwa_settings['auto_backup_epub_fixes']:
            try:
                output_path = f"/config/processed_books/fixed_originals/"
                shutil.copy2(epub_path, output_path)
            except Exception as e:
                print_and_log(f"[cwa-kindle-epub-fixer] ERROR - Error occurred when backing up {epub_path} to {output_path}:\n{e}", log=self.manually_triggered)

    def read_epub(self, epub_path):
        """Read EPUB file contents"""
        with zipfile.ZipFile(epub_path, 'r') as zip_ref:
            self.entries = zip_ref.namelist()
            for filename in self.entries:
                ext = filename.split('.')[-1]
                if filename == 'mimetype' or ext in ['html', 'xhtml', 'htm', 'xml', 'svg', 'css', 'opf', 'ncx']:
                    self.files[filename] = zip_ref.read(filename).decode('utf-8')
                else:
                    self.binary_files[filename] = zip_ref.read(filename)

    def fix_encoding(self):
        """Add UTF-8 encoding declaration if missing"""
        encoding = '<?xml version="1.0" encoding="utf-8"?>'
        regex = r'^<\?xml\s+version=["\'][\d.]+["\']\s+encoding=["\'][a-zA-Z\d\-\.]+["\'].*?\?>'

        for filename in list(self.files.keys()):
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml']:
                html = self.files[filename]
                html = html.lstrip()
                if not re.match(regex, html, re.IGNORECASE):
                    html = encoding + '\n' + html
                    self.fixed_problems.append(f"Fixed encoding for file {filename}")
                self.files[filename] = html

    def fix_body_id_link(self):
        """Fix linking to body ID showing up as unresolved hyperlink"""
        body_id_list = []

        # Create list of ID tag of <body>
        for filename in self.files:
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml']:
                html = self.files[filename]
                dom = minidom.parseString(html)
                body_elements = dom.getElementsByTagName('body')
                if body_elements and body_elements[0].hasAttribute('id'):
                    body_id = body_elements[0].getAttribute('id')
                    if body_id:
                        link_target = os.path.basename(filename) + '#' + body_id
                        body_id_list.append([link_target, os.path.basename(filename)])

        # Replace all
        for filename in self.files:
            for src, target in body_id_list:
                if src in self.files[filename]:
                    self.files[filename] = self.files[filename].replace(src, target)
                    self.fixed_problems.append(f"Replaced link target {src} with {target} in file {filename}.")

    def fix_book_language(self, default_language='en'):
        """Fix language field not defined or not available"""
        # From https://kdp.amazon.com/en_US/help/topic/G200673300
        allowed_languages = [
            # ISO 639-1
            'af', 'gsw', 'ar', 'eu', 'nb', 'br', 'ca', 'zh', 'kw', 'co', 'da', 'nl', 'stq', 'en', 'fi', 'fr', 'fy', 'gl',
            'de', 'gu', 'hi', 'is', 'ga', 'it', 'ja', 'lb', 'mr', 'ml', 'gv', 'frr', 'nb', 'nn', 'pl', 'pt', 'oc', 'rm',
            'sco', 'gd', 'es', 'sv', 'ta', 'cy',
            # ISO 639-2
            'afr', 'ara', 'eus', 'baq', 'nob', 'bre', 'cat', 'zho', 'chi', 'cor', 'cos', 'dan', 'nld', 'dut', 'eng', 'fin',
            'fra', 'fre', 'fry', 'glg', 'deu', 'ger', 'guj', 'hin', 'isl', 'ice', 'gle', 'ita', 'jpn', 'ltz', 'mar', 'mal',
            'glv', 'nor', 'nno', 'por', 'oci', 'roh', 'gla', 'spa', 'swe', 'tam', 'cym', 'wel',
        ]

        # Find OPF file
        if 'META-INF/container.xml' not in self.files:
            print('Cannot find META-INF/container.xml')
            return

        container_xml = minidom.parseString(self.files['META-INF/container.xml'])
        opf_filename = None
        for rootfile in container_xml.getElementsByTagName('rootfile'):
            if rootfile.getAttribute('media-type') == 'application/oebps-package+xml':
                opf_filename = rootfile.getAttribute('full-path')
                break

        # Read OPF file
        if not opf_filename or opf_filename not in self.files:
            print('Cannot find OPF file!')
            return

        try:
            opf = minidom.parseString(self.files[opf_filename])
            language_tags = opf.getElementsByTagName('dc:language')
            language = default_language
            original_language = 'undefined'

            if not language_tags:
                # Use default language if no language tag exists
                self.fixed_problems.append(f"No language tag found. Setting to default: {default_language}")
            else:
                language = language_tags[0].firstChild.nodeValue
                original_language = language

            simplified_lang = language.split('-')[0].lower()
            if simplified_lang not in allowed_languages:
                # If language is not supported, use default
                language = default_language
                self.fixed_problems.append(f"Unsupported language {original_language}. Changed to {default_language}")

            if not language_tags:
                language_tag = opf.createElement('dc:language')
                text_node = opf.createTextNode(language)
                language_tag.appendChild(text_node)
                metadata = opf.getElementsByTagName('metadata')[0]
                metadata.appendChild(language_tag)
            else:
                language_tags[0].firstChild.nodeValue = language

            if language != original_language:
                self.files[opf_filename] = opf.toxml()
                self.fixed_problems.append(f"Changed document language from {original_language} to {language}")

        except Exception as e:
            print(f'Error trying to parse OPF file as XML: {e}')

    def fix_stray_img(self):
        """Fix stray IMG tags"""
        for filename in list(self.files.keys()):
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml']:
                dom = minidom.parseString(self.files[filename])
                stray_img = []
                
                for img in dom.getElementsByTagName('img'):
                    if not img.getAttribute('src'):
                        stray_img.append(img)

                if stray_img:
                    for img in stray_img:
                        img.parentNode.removeChild(img)
                    self.fixed_problems.append(f"Remove stray image tag(s) in {filename}")
                    self.files[filename] = dom.toxml()

    def write_epub(self, output_path):
        """Write EPUB file"""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
            # First write mimetype file
            if 'mimetype' in self.files:
                zip_ref.writestr('mimetype', self.files['mimetype'], compress_type=zipfile.ZIP_STORED)

            # Add text files
            for filename, content in self.files.items():
                if filename != 'mimetype':
                    zip_ref.writestr(filename, content)

            # Add binary files
            for filename, content in self.binary_files.items():
                zip_ref.writestr(filename, content)

    def export_issue_summary(self, epub_path):
        if self.current_position:
            line_suffix = f"[cwa-kindle-epub-fixer] {self.current_position} - "
        else:
            line_suffix = "[cwa-kindle-epub-fixer] "
        
        if self.fixed_problems:
            print_and_log(line_suffix + f"{len(self.fixed_problems)} issues fixed with {epub_path}:", log=self.manually_triggered)
            for count, problem in enumerate(self.fixed_problems):
                print_and_log(f"   {str(count + 1).zfill(2)} - {problem}", log=self.manually_triggered)            
        else:
            print_and_log(line_suffix + f"No issues found! - {epub_path}", log=self.manually_triggered)

    def add_entry_to_db(self, input_path, output_path):
        if self.fixed_problems:
            fixed_problems = []
            for count, problem in enumerate(self.fixed_problems):
                fixed_problems.append(f"{str(count + 1).zfill(2)} - {problem}")
            fixed_problems = "\n".join(fixed_problems)
        else:
            fixed_problems = "No fixes required"

        self.db.epub_fixer_add_entry(Path(input_path).stem,
                                    bool(self.manually_triggered),
                                    len(self.fixed_problems),
                                    str(self.cwa_settings['auto_backup_epub_fixes']),
                                    output_path,
                                    fixed_problems)


    def process(self, input_path, output_path=None, default_language='en'):
        """Process a single EPUB file"""
        if not output_path:
            output_path = input_path

        # Back Up Original File
        print_and_log("[cwa-kindle-epub-fixer] Backing up original file...", log=self.manually_triggered)
        self.backup_original_file(input_path)

        # Load EPUB
        print_and_log("[cwa-kindle-epub-fixer] Loading provided EPUB...", log=self.manually_triggered)
        self.read_epub(input_path)

        # Run fixing procedures
        print_and_log("[cwa-kindle-epub-fixer] Checking linking to body ID to prevent unresolved hyperlinks...", log=self.manually_triggered)
        self.fix_body_id_link()
        print_and_log("[cwa-kindle-epub-fixer] Checking language field tag is valid...", log=self.manually_triggered)
        self.fix_book_language(default_language)
        print_and_log("[cwa-kindle-epub-fixer] Checking for stray images...", log=self.manually_triggered)
        self.fix_stray_img()
        print_and_log("[cwa-kindle-epub-fixer] Checking UTF-8 encoding declaration...", log=self.manually_triggered)
        self.fix_encoding()

        # Notify user and/or write to log
        self.export_issue_summary(input_path)

        # Write EPUB
        print_and_log("[cwa-kindle-epub-fixer] Writing EPUB...", log=self.manually_triggered)
        if Path(output_path).is_dir():
            output_path = output_path + os.path.basename(input_path)
        self.write_epub(output_path)
        print_and_log("[cwa-kindle-epub-fixer] EPUB successfully written.", log=self.manually_triggered)
        
        # Add entry to cwa.db
        print_and_log("[cwa-kindle-epub-fixer] Adding run to cwa.db...", log=self.manually_triggered)
        self.add_entry_to_db(input_path, output_path)
        print_and_log("[cwa-kindle-epub-fixer] Run successfully added to cwa.db.", log=self.manually_triggered)
        return self.fixed_problems


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


def main():
    parser = argparse.ArgumentParser(
        prog='kindle-epub-fixer',
        description='Checks the encoding of a given EPUB file and automatically corrects any errors that could \
        prevent the file from being compatible with Amazon\'s Send-to-Kindle service. If the "-all" flag is \
        passed, all epub files in the user\'s calibre library will be processed'
    )
    parser.add_argument('--input_file', '-i', required=False, help='Input EPUB file path')
    parser.add_argument('--output', '-o', required=False, help='Output EPUB file path')
    parser.add_argument('--language', '-l', required=False, default='en', help='Default language to use if not specified or invalid')
    parser.add_argument('--suffix', '-s',required=False,  default=False, action='store_true', help='Adds suffix "fixed" to output filename if given')
    parser.add_argument('--all', '-a', required=False, default=False, action='store_true', help='Will attempt to fix any issues in every EPUB in th user\'s library')
    
    args = parser.parse_args()
    # logger.info(f"CWA Kindle EPUB Fixer Service - Run Started: {datetime.now()}\n")

    ### CATCH INCOMPATIBLE COMBINATIONS OF ARGUMENTS
    if not args.input_file and not args.all:
        print("[cwa-kindle-epub-fixer] ERROR - No file provided")
        # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(4)
    elif args.all and args.input_file:
        print("[cwa-kindle-epub-fixer] ERROR - Can't give all and a filepath at the same time")
        # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(5)

    ### INPUT_FILE PROVIDED
    elif args.input_file and not args.all:
        # Validate input file
        if not Path(args.input_file).exists():
            print(f"[cwa-kindle-epub-fixer] ERROR - Given file {args.input_file} does not exist")
            # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(3)
        if not args.input_file.lower().endswith('.epub'):
            print("[cwa-kindle-epub-fixer] ERROR - The input file must be an EPUB file with a .epub extension.")
            # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(1)
        # Determine output path
        if args.output:
            output_path = args.output
        else:
            if args.suffix:
                output_path = Path(args.input_file.split('.epub')[0] + " - fixed.epub")
            else:
                output_path = Path(args.input_file)
        # Run EPUBFixer
        print(f"[cwa-kindle-epub-fixer] Processing given file - {args.input_file}...")
        try:
            EPUBFixer(manually_triggered=True).process(args.input_file, output_path, args.language)
        except:
            print(f"[cwa-kindle-epub-fixer] ERROR - Error processing {args.input_file}: {e}")
            # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
            sys.exit(6)
        # logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(0)

    ### ALL PASSED AS ARGUMENT
    elif args.all and not args.input_file:
        logger.info(f"CWA Kindle EPUB Fixer Service - Run Started: {datetime.now()}\n")
        print_and_log("[cwa-kindle-epub-fixer] Processing all epubs in library...")
        epubs_to_process = get_all_epubs_in_library()
        if len(epubs_to_process) > 0:
            print_and_log(f"[cwa-kindle-epub-fixer] {len(epubs_to_process)} EPUBs found to process.")
            errored_files = {}
            for count, epub in enumerate(epubs_to_process):
                current_position = f"{count + 1}/{len(epubs_to_process)}"
                try:
                    print_and_log(f"\n[cwa-kindle-epub-fixer] {current_position} - Processing {epub}...")
                    EPUBFixer(manually_triggered=True, current_position=current_position).process(epub, epub, args.language)
                except Exception as e:
                    print_and_log(f"[cwa-kindle-epub-fixer] {current_position} - The following error occurred when processing {epub}:\n{e}")
                    errored_files |= {epub:e}
            if errored_files:
                print_and_log(f"\n[cwa-kindle-epub-fixer] {len(epubs_to_process) - len(errored_files)}/{len(epubs_to_process)} EPUBs in library successfully processed")
                print_and_log(f"\n[cwa-kindle-epub-fixer] The following {len(errored_files)} encountered errors:\n")
                for file in errored_files:
                    print_and_log(f"   - {file}")
                    print_and_log(f"      - Error Encountered: {errored_files[file]}")
            else:
                print_and_log(f"\n[cwa-kindle-epub-fixer] All {len(epubs_to_process)} EPUBs in Library successfully processed! Exiting now...")
        else:
            print_and_log("[cwa-kindle-epub-fixer] No EPUBs found to process. Exiting now...")
        logger.info(f"\nCWA Kindle EPUB Fixer Service - Run Ended: {datetime.now()}\n")
        sys.exit(0)
    

if __name__ == "__main__":
    main()