# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import re
import zipfile
from xml.dom import minidom
import argparse
from pathlib import Path
import sys
import sqlite3
import subprocess

import logging
import tempfile
import atexit
import traceback
from datetime import datetime
import json
import shutil
from typing import Optional, Tuple

import pwd
import grp

from cwa_db import CWA_DB

try:
    from charset_normalizer import from_bytes as _charset_from_bytes
except Exception:
    _charset_from_bytes = None

try:
    import chardet
except Exception:
    chardet = None

### Code adapted from https://github.com/innocenat/kindle-epub-fix
### Translated from Javascript to Python & modified by crocodilestick

# Compile regex pattern once at module level for performance
LANGUAGE_TAG_PATTERN = re.compile(r'^[a-z]{2,3}(-[a-z]{2,4})?$', re.IGNORECASE)

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
# Create a FileHandler if possible, otherwise use StreamHandler
try:
    file_handler = logging.FileHandler(epub_fixer_log_file, mode='w', encoding='utf-8')
    # Create a Formatter and set it for the handler
    LOG_FORMAT = '%(message)s'
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler.setFormatter(formatter)
    # Add the handler to the logger
    logger.addHandler(file_handler)
except FileNotFoundError:
    # Fallback for test environments where /config might not exist
    stream_handler = logging.StreamHandler()
    LOG_FORMAT = '%(message)s'
    formatter = logging.Formatter(LOG_FORMAT)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Define user and group
USER_NAME = "abc"
GROUP_NAME = "abc"

# Get UID and GID (skip if user doesn't exist, e.g., in CI environments)
uid = None
gid = None
try:
    uid = pwd.getpwnam(USER_NAME).pw_uid
    gid = grp.getgrnam(GROUP_NAME).gr_gid
except KeyError:
    # User/group doesn't exist (e.g., in CI/test environments)
    # This is okay - just skip ownership operations
    pass

# Set permissions for log file (skip on network shares or if uid/gid not available)
if uid is not None and gid is not None:
    try:
        nsm = os.getenv("NETWORK_SHARE_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
        if not nsm:
            subprocess.run(["chown", f"{uid}:{gid}", epub_fixer_log_file], check=True)
        else:
            print(f"[cwa-kindle-epub-fixer] NETWORK_SHARE_MODE=true detected; skipping chown of {epub_fixer_log_file}", flush=True)
    except subprocess.CalledProcessError as e:
        print(f"[cwa-kindle-epub-fixer] An error occurred while attempting to set ownership of {epub_fixer_log_file} to abc:abc. See the following error:\n{e}", flush=True)


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
        self.file_original_bytes = {}
        self.file_encodings = {}
        self.file_encoding_sources = {}
        self.file_target_encodings = {}
        self.file_decode_confidence = {}
        self.decode_warnings = []

        self.aggressive_mode = bool(self.cwa_settings.get('kindle_epub_fixer_aggressive', 0))
        self.encoding_confidence_threshold = 0.7 if not self.aggressive_mode else 0.4

    def _normalize_encoding_name(self, encoding: Optional[str]) -> Optional[str]:
        if not encoding:
            return None
        return encoding.strip().lower().replace('_', '-').replace(' ', '')

    def _sniff_bom(self, data: bytes) -> Optional[str]:
        if data.startswith(b'\xff\xfe\x00\x00'):
            return 'utf-32-le'
        if data.startswith(b'\x00\x00\xfe\xff'):
            return 'utf-32-be'
        if data.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        if data.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        if data.startswith(b'\xfe\xff'):
            return 'utf-16-be'
        return None

    def _extract_xml_declared_encoding(self, data: bytes) -> Optional[str]:
        try:
            head = data[:1024].decode('ascii', errors='ignore')
        except Exception:
            return None
        match = re.search(r'<\?xml[^>]*encoding=["\']([^"\']+)["\']', head, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_html_meta_charset(self, data: bytes) -> Optional[str]:
        try:
            head = data[:2048].decode('ascii', errors='ignore')
        except Exception:
            return None
        match = re.search(r'<meta[^>]+charset=["\']?([^"\'>\s]+)', head, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'charset=([^"\'>\s;]+)', head, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _detect_encoding(self, data: bytes, filename: str) -> Tuple[Optional[str], float, str]:
        bom = self._sniff_bom(data)
        if bom:
            return bom, 1.0, 'bom'

        xml_decl = self._extract_xml_declared_encoding(data)
        if xml_decl:
            return xml_decl, 1.0, 'xml_decl'

        html_meta = self._extract_html_meta_charset(data)
        if html_meta:
            return html_meta, 0.95, 'html_meta'

        if _charset_from_bytes is not None:
            try:
                best = _charset_from_bytes(data).best()
                if best and best.encoding:
                    return best.encoding, float(best.confidence or 0.0), 'charset_normalizer'
            except Exception:
                pass

        if chardet is not None:
            try:
                result = chardet.detect(data)
                if result and result.get('encoding'):
                    return result.get('encoding'), float(result.get('confidence') or 0.0), 'chardet'
            except Exception:
                pass

        return None, 0.0, 'unknown'

    def _decode_text_entry(self, filename: str, data: bytes) -> Optional[str]:
        self.file_original_bytes[filename] = data

        encoding, confidence, source = self._detect_encoding(data, filename)
        encoding = self._normalize_encoding_name(encoding)
        self.file_encodings[filename] = encoding
        self.file_encoding_sources[filename] = source
        self.file_decode_confidence[filename] = confidence

        if not encoding:
            self.decode_warnings.append(f"No encoding detected for {filename}; leaving bytes unchanged")
            return None

        if confidence < self.encoding_confidence_threshold and source not in ('bom', 'xml_decl', 'html_meta'):
            self.decode_warnings.append(
                f"Low encoding confidence for {filename} ({encoding}, {confidence:.2f}); leaving bytes unchanged"
            )
            return None

        is_utf16 = encoding.startswith('utf-16')
        allow_utf16 = is_utf16 and source in ('bom', 'xml_decl')

        if is_utf16 and not allow_utf16:
            if self.aggressive_mode and confidence >= 0.85:
                self.decode_warnings.append(
                    f"UTF-16 detected without BOM/declaration for {filename}; converting to UTF-8 (aggressive mode)"
                )
            else:
                self.decode_warnings.append(
                    f"UTF-16 detected without BOM/declaration for {filename}; leaving bytes unchanged"
                )
                return None

        try:
            text = data.decode(encoding, errors='strict')
        except Exception:
            if self.aggressive_mode:
                try:
                    text = data.decode(encoding, errors='replace')
                    self.decode_warnings.append(
                        f"Decoded {filename} with replacement characters using {encoding}"
                    )
                except Exception:
                    self.decode_warnings.append(
                        f"Failed to decode {filename} using {encoding}; leaving bytes unchanged"
                    )
                    return None
            else:
                self.decode_warnings.append(
                    f"Failed to decode {filename} using {encoding}; leaving bytes unchanged"
                )
                return None

        if is_utf16 and allow_utf16:
            target_encoding = encoding
        else:
            target_encoding = 'utf-8'

        self.file_target_encodings[filename] = target_encoding

        if encoding != target_encoding:
            self.fixed_problems.append(f"Converted {filename} from {encoding} to {target_encoding}")

        return text

    def _get_text_content(self, filename: str) -> Optional[str]:
        content = self.files.get(filename)
        if isinstance(content, bytes):
            return None
        return content

    def _update_html_charset(self, content: str, target_encoding: str) -> str:
        charset = target_encoding.lower()
        if charset.startswith('utf-16'):
            charset = 'utf-16'

        http_equiv_pattern = re.compile(
            r'(<meta[^>]+http-equiv=["\']content-type["\'][^>]*content=["\'][^"\']*charset=)([^"\'>\s;]+)([^"\']*["\'][^>]*>)',
            re.IGNORECASE
        )
        if http_equiv_pattern.search(content):
            return http_equiv_pattern.sub(rf"\1{charset}\3", content, count=1)

        meta_charset_pattern = re.compile(r'<meta[^>]+charset=["\']?[^"\'>\s]+[^>]*>', re.IGNORECASE)
        if meta_charset_pattern.search(content):
            return meta_charset_pattern.sub(f'<meta charset="{charset}">', content, count=1)

        head_pattern = re.compile(r'<head[^>]*>', re.IGNORECASE)
        match = head_pattern.search(content)
        if match:
            insert_at = match.end()
            return content[:insert_at] + f"\n    <meta charset=\"{charset}\">" + content[insert_at:]

        return f"<meta charset=\"{charset}\">\n" + content

    def _extract_book_info_from_path(self, file_path: str) -> tuple[int | None, str]:
        """Extract book ID and format from file path.

        Expected path format: /calibre-library/Author/Title (123)/book.epub
        Returns: (book_id, format) or (None, 'EPUB')
        """
        try:
            path_parts = str(file_path).split(os.sep)
            # Look for directory with format "Title (123)"
            for part in path_parts:
                match = re.search(r'\((\d+)\)$', part)
                if match:
                    book_id = int(match.group(1))
                    format_ext = Path(file_path).suffix.lstrip('.').upper()
                    return book_id, format_ext
            return None, 'EPUB'
        except Exception:
            return None, 'EPUB'

    def _get_metadata_db_path(self) -> str:
        """Get the path to metadata.db considering split library configuration."""
        try:
            con = sqlite3.connect("/config/app.db", timeout=30)
            cur = con.cursor()
            split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

            if split_library:
                db_path = cur.execute('SELECT config_calibre_dir FROM settings;').fetchone()[0]
                con.close()
                return os.path.join(db_path, "metadata.db")
            else:
                con.close()
                library_location = get_library_location()
                return os.path.join(library_location, "metadata.db")
        except Exception:
            # Fallback to default location
            return "/calibre-library/metadata.db"

    def _recalculate_checksum_after_modification(self, book_id: int, file_format: str, file_path: str) -> None:
        """Calculate and store new checksum after modifying an EPUB file."""
        try:
            # Import the checksum calculation function
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from cps.progress_syncing.checksums import calculate_koreader_partial_md5, store_checksum, CHECKSUM_VERSION

            # Calculate new checksum
            checksum = calculate_koreader_partial_md5(file_path)
            if not checksum:
                print_and_log(f"[cwa-kindle-epub-fixer] Warning: Failed to calculate checksum for {file_path}", log=self.manually_triggered)
                return

            # Store in database using centralized manager function
            metadb_path = self._get_metadata_db_path()
            con = sqlite3.connect(metadb_path, timeout=30)

            try:
                success = store_checksum(
                    book_id=book_id,
                    book_format=file_format,
                    checksum=checksum,
                    version=CHECKSUM_VERSION,
                    db_connection=con
                )

                if success:
                    print_and_log(f"[cwa-kindle-epub-fixer] Stored checksum {checksum[:8]}... for book {book_id} (v{CHECKSUM_VERSION})", log=self.manually_triggered)
                else:
                    print_and_log(f"[cwa-kindle-epub-fixer] Warning: Failed to store checksum for book {book_id}", log=self.manually_triggered)
            finally:
                con.close()
        except Exception as e:
            print_and_log(f"[cwa-kindle-epub-fixer] Warning: Failed to recalculate checksum: {e}", log=self.manually_triggered)
            print_and_log(traceback.format_exc(), log=self.manually_triggered)


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
                if filename == 'mimetype':
                    self.files[filename] = zip_ref.read(filename)
                    continue

                if ext in ['html', 'xhtml', 'htm', 'xml', 'svg', 'css', 'opf', 'ncx']:
                    data = zip_ref.read(filename)
                    decoded = self._decode_text_entry(filename, data)
                    if decoded is None:
                        self.files[filename] = data
                    else:
                        self.files[filename] = decoded
                else:
                    self.binary_files[filename] = zip_ref.read(filename)

    def fix_encoding(self):
        """Add UTF-8 encoding declaration if missing and fix malformed XML declarations"""
        xml_decl_pattern = re.compile(r'^(\s*)<\?xml[^>]*\?>', re.IGNORECASE)
        xml_decl_encoding_pattern = re.compile(
            r'^\s*<\?xml[^>]*encoding=["\']([^"\']+)["\']',
            re.IGNORECASE
        )

        for filename in list(self.files.keys()):
            ext = filename.split('.')[-1]
            content = self._get_text_content(filename)
            if content is None:
                continue

            target_encoding = self.file_target_encodings.get(filename, 'utf-8')
            declared_encoding = target_encoding
            if declared_encoding.startswith('utf-16'):
                declared_encoding = 'utf-16'

            if ext in ['html', 'htm']:
                updated = self._update_html_charset(content, declared_encoding)
                if updated != content:
                    self.fixed_problems.append(f"Updated HTML charset in {filename} to {declared_encoding}")
                self.files[filename] = updated
                continue

            if ext not in ['xhtml', 'xml', 'opf', 'ncx', 'svg']:
                continue

            new_decl = f'<?xml version="1.0" encoding="{declared_encoding}"?>'
            decl_match = xml_decl_encoding_pattern.match(content)
            if decl_match:
                current_encoding = self._normalize_encoding_name(decl_match.group(1))
                if current_encoding != self._normalize_encoding_name(declared_encoding):
                    content = xml_decl_pattern.sub(r'\1' + new_decl, content, count=1)
                    self.fixed_problems.append(f"Updated XML declaration in {filename} to {declared_encoding}")
            elif xml_decl_pattern.match(content):
                # This checks to see if there is an xml declaration without an encoding present.
                # If there is, replace the entire xml declaration with one that includes the encoding.
                content = xml_decl_pattern.sub(new_decl, content, count=1)
                self.fixed_problems.append(f"Added {declared_encoding} to XML declaration missing encoding info in {filename}")
            else:
                content = new_decl + '\n' + content
                self.fixed_problems.append(f"Added XML declaration to {filename}")

            self.files[filename] = content

    def fix_container_xml(self):
        """Fix duplicate XML declarations in META-INF/container.xml"""
        filename = 'META-INF/container.xml'
        if filename not in self.files:
            return

        content = self._get_text_content(filename)
        if content is None:
            return
        content = content.lstrip()

        decl_pattern = r'<\?xml[^>]*\?>'
        decls = list(re.finditer(decl_pattern, content))
        if len(decls) <= 1:
            return

        first = decls[0]
        cleaned = content[:first.end()] + re.sub(decl_pattern, '', content[first.end():])

        # Validate to avoid breaking container.xml
        try:
            minidom.parseString(cleaned)
        except Exception as e:
            print_and_log(f"[cwa-kindle-epub-fixer] Warning: container.xml still invalid after cleanup: {e}", log=self.manually_triggered)
            return

        self.files[filename] = cleaned
        self.fixed_problems.append("Removed duplicate XML declaration(s) in META-INF/container.xml")

    def fix_body_id_link(self):
        """Fix linking to body ID showing up as unresolved hyperlink"""
        body_id_list = []

        # Create list of ID tag of <body>
        for filename in self.files:
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml']:
                html = self._get_text_content(filename)
                if html is None:
                    continue
                if '<body' not in html:
                    continue
                try:
                    dom = minidom.parseString(html)
                except Exception:
                    continue
                body_elements = dom.getElementsByTagName('body')
                if body_elements and body_elements[0].hasAttribute('id'):
                    body_id = body_elements[0].getAttribute('id')
                    if body_id:
                        link_target = os.path.basename(filename) + '#' + body_id
                        body_id_list.append([link_target, os.path.basename(filename)])

        # Replace all
        for filename in self.files:
            for src, target in body_id_list:
                content = self._get_text_content(filename)
                if content is None:
                    continue
                if src in content:
                    self.files[filename] = content.replace(src, target)
                    self.fixed_problems.append(f"Replaced link target {src} with {target} in file {filename}.")

    def fix_book_language(self, default_language='en', epub_path=None):
        """Fix language field - preserves valid tags, only fixes truly invalid ones"""
        # From https://kdp.amazon.com/en_US/help/topic/G200673300
        # NOTE: Amazon's Send-to-Kindle only reads the FIRST 2 CHARACTERS of language tags.
        # This means zh-TW and zh-CN both become 'zh' (we cannot distinguish them).
        # We normalize region codes (de-DE → de) to match Amazon's behavior.
        allowed_languages = [
            # ISO 639-1 (2-character codes - what Amazon actually uses)
            'af', 'gsw', 'ar', 'eu', 'nb', 'br', 'ca', 'zh', 'kw', 'co', 'da', 'nl', 'stq', 'en', 'fi', 'fr', 'fy', 'gl',
            'de', 'gu', 'hi', 'is', 'ga', 'it', 'ja', 'lb', 'mr', 'ml', 'gv', 'frr', 'nn', 'pl', 'pt', 'oc', 'rm',
            'sco', 'gd', 'es', 'sv', 'ta', 'cy',
            # ISO 639-2 (3-character codes - also supported)
            'afr', 'ara', 'eus', 'baq', 'nob', 'bre', 'cat', 'zho', 'chi', 'cor', 'cos', 'dan', 'nld', 'dut', 'eng', 'fin',
            'fra', 'fre', 'fry', 'glg', 'deu', 'ger', 'guj', 'hin', 'isl', 'ice', 'gle', 'ita', 'jpn', 'ltz', 'mar', 'mal',
            'glv', 'nor', 'nno', 'por', 'oci', 'roh', 'gla', 'spa', 'swe', 'tam', 'cym', 'wel',
        ]

        try:
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

            opf_content = self._get_text_content(opf_filename)
            if opf_content is None:
                return
            if not self.aggressive_mode and 'xmlns:dc' not in opf_content:
                print_and_log(f"[cwa-kindle-epub-fixer] Skipping language update for {opf_filename} (missing xmlns:dc)", log=self.manually_triggered)
                return

            opf = minidom.parseString(opf_content)
            language_tags = opf.getElementsByTagName('dc:language')
            language = None
            original_language = None

            # Check if language tag exists and has content
            if not language_tags or not language_tags[0].firstChild:
                # No language tag - try to detect from Calibre metadata, else use default
                language = self._detect_language_from_metadata(epub_path) or default_language
                self.fixed_problems.append(f"No language tag found. Setting to: {language}")
            else:
                # Language tag exists - extract and validate
                original_language = language_tags[0].firstChild.nodeValue.strip()
                
                # First check if the language looks like a valid code format (case-insensitive)
                # Valid: en, de, zh, en-US, en-us, de-DE, zh-TW, eng, deu, zho
                # Invalid: Unknown, undefined, garbage, 12345
                if LANGUAGE_TAG_PATTERN.match(original_language):
                    # Looks like a proper language tag - extract and normalize base language code
                    simplified_lang = original_language.split('-')[0].lower()
                    
                    if simplified_lang in allowed_languages:
                        # Valid language code - use it
                        language = simplified_lang
                        
                        # If original had region code or different case, note the normalization
                        if original_language.lower() != language and '-' in original_language:
                            self.fixed_problems.append(f"Normalized language from {original_language} to {language} (Amazon only reads base code)")
                        elif original_language != language:
                            self.fixed_problems.append(f"Normalized language from {original_language} to {language} (case standardization)")
                    else:
                        # Looks like a language tag but not in Amazon's allowed list
                        detected = self._detect_language_from_metadata(epub_path)
                        if detected:
                            language = detected
                            self.fixed_problems.append(f"Unsupported language '{original_language}'. Detected from metadata: {language}")
                        else:
                            language = default_language
                            self.fixed_problems.append(f"Unsupported language '{original_language}'. Using default: {language}")
                else:
                    # Doesn't look like a language tag at all (e.g., "Unknown", "garbage")
                    detected = self._detect_language_from_metadata(epub_path)
                    if detected:
                        language = detected
                        self.fixed_problems.append(f"Invalid language tag '{original_language}'. Detected from metadata: {language}")
                    else:
                        language = default_language
                        self.fixed_problems.append(f"Invalid language tag '{original_language}'. Using default: {language}")

            # Update or create language tag
            if not language_tags:
                # Create new tag
                language_tag = opf.createElement('dc:language')
                text_node = opf.createTextNode(language)
                language_tag.appendChild(text_node)
                metadata_nodes = opf.getElementsByTagName('metadata')
                if not metadata_nodes:
                    return
                metadata_nodes[0].appendChild(language_tag)
            else:
                # Update existing tag
                if language_tags[0].firstChild:
                    language_tags[0].firstChild.nodeValue = language
                else:
                    text_node = opf.createTextNode(language)
                    language_tags[0].appendChild(text_node)

            # Only write if we actually changed something
            if original_language != language or not original_language:
                # Use regex replacement to preserve XML formatting instead of minidom.toxml()
                # This prevents attribute reordering which can break Amazon's parser
                opf_content = opf_content
                
                if not language_tags:
                    # Need to add language tag - insert before </metadata>
                    if '</metadata>' not in opf_content:
                        return
                    opf_content = opf_content.replace(
                        '</metadata>',
                        f'    <dc:language>{language}</dc:language>\n  </metadata>'
                    )
                else:
                    # Replace existing language tag content
                    opf_content = re.sub(
                        r'<dc:language>.*?</dc:language>',
                        f'<dc:language>{language}</dc:language>',
                        opf_content,
                        count=1,
                        flags=re.DOTALL
                    )
                
                self.files[opf_filename] = opf_content

        except Exception as e:
            print_and_log(f'[cwa-kindle-epub-fixer] Skipping language validation - EPUB has non-standard structure: {e}', log=self.manually_triggered)

    def _detect_language_from_metadata(self, epub_path=None):
        """Attempt to detect language from Calibre's metadata.db"""
        try:
            # Extract book_id from the EPUB file path
            if not epub_path:
                return None
                
            book_id, _ = self._extract_book_info_from_path(epub_path)
            if not book_id:
                return None
            
            # Query metadata.db for language
            metadb_path = self._get_metadata_db_path()
            con = sqlite3.connect(metadb_path, timeout=30)
            cur = con.cursor()
            
            # Get language from books table via languages link table
            result = cur.execute(
                '''SELECT languages.lang_code 
                   FROM books 
                   JOIN books_languages_link ON books.id = books_languages_link.book
                   JOIN languages ON books_languages_link.lang_code = languages.id
                   WHERE books.id = ?
                   LIMIT 1''',
                (book_id,)
            ).fetchone()
            
            con.close()
            
            if result and result[0]:
                lang = result[0].lower().split('-')[0]  # Normalize
                print_and_log(f"[cwa-kindle-epub-fixer] Detected language '{lang}' from Calibre metadata", log=self.manually_triggered)
                return lang
                
        except Exception as e:
            # Silent fail - this is just a helpful fallback
            pass
        
        return None

    def fix_stray_img(self):
        """Fix stray IMG tags"""
        for filename in list(self.files.keys()):
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml']:
                content = self._get_text_content(filename)
                if content is None:
                    continue
                if self.aggressive_mode:
                    try:
                        dom = minidom.parseString(content)
                    except Exception:
                        continue
                    stray_img = []

                    for img in dom.getElementsByTagName('img'):
                        if not img.getAttribute('src'):
                            stray_img.append(img)

                    if stray_img:
                        for img in stray_img:
                            img.parentNode.removeChild(img)
                        self.fixed_problems.append(f"Remove stray image tag(s) in {filename}")
                        self.files[filename] = dom.toxml()
                else:
                    no_src_pattern = re.compile(r'<img\b(?![^>]*\bsrc\s*=)[^>]*>', re.IGNORECASE)
                    empty_src_pattern = re.compile(r'<img\b[^>]*\bsrc\s*=\s*["\']?\s*["\'][^>]*>', re.IGNORECASE)

                    updated = empty_src_pattern.sub('', content)
                    updated = no_src_pattern.sub('', updated)

                    if updated != content:
                        self.fixed_problems.append(f"Remove stray image tag(s) in {filename}")
                        self.files[filename] = updated

    def strip_embedded_fonts(self):
        """Remove embedded font files and @font-face CSS declarations for Kindle compatibility"""
        # Remove font files from binary files
        font_extensions = ('.ttf', '.otf', '.woff', '.woff2', '.eot')
        fonts_removed = []
        
        for filename in list(self.binary_files.keys()):
            if filename.lower().endswith(font_extensions):
                del self.binary_files[filename]
                fonts_removed.append(filename)
        
        if fonts_removed:
            self.fixed_problems.append(f"Removed {len(fonts_removed)} embedded font file(s) for Kindle compatibility")
            
            # Also remove font references from OPF manifest
            opf_path = 'content.opf'
            if opf_path in self.files:
                opf_content = self.files[opf_path]
                for font_file in fonts_removed:
                    # Remove manifest item for this font
                    # Match: <item href="fonts/00001.ttf" id="..." media-type="..."/>
                    pattern = re.compile(
                        r'<item[^>]*href=["\']' + re.escape(font_file) + r'["\'][^>]*/?>',
                        re.IGNORECASE
                    )
                    opf_content = pattern.sub('', opf_content)
                
                self.files[opf_path] = opf_content
        
        # Remove @font-face declarations from CSS files
        font_face_pattern = re.compile(r'@font-face\s*\{[^}]*\}', re.IGNORECASE | re.DOTALL)
        
        for filename in list(self.files.keys()):
            if filename.endswith('.css'):
                original_css = self.files[filename]
                cleaned_css = font_face_pattern.sub('', original_css)
                
                if cleaned_css != original_css:
                    self.files[filename] = cleaned_css
                    self.fixed_problems.append(f"Removed @font-face declarations from {filename}")
    
    def remove_javascript(self):
        """Remove JavaScript code for Kindle compatibility (not supported)"""
        script_pattern = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
        
        for filename in list(self.files.keys()):
            ext = filename.split('.')[-1]
            if ext in ['html', 'xhtml', 'htm']:
                original_content = self.files[filename]
                cleaned_content = script_pattern.sub('', original_content)
                
                if cleaned_content != original_content:
                    self.files[filename] = cleaned_content
                    self.fixed_problems.append(f"Removed JavaScript from {filename}")
    
    def validate_images(self):
        """Validate images for Kindle compatibility and report issues"""
        issues = []
        total_size = 0
        
        # Supported formats by Kindle
        supported_formats = {
            b'\xff\xd8\xff': 'JPEG',
            b'\x89PNG': 'PNG',
            b'GIF87a': 'GIF',
            b'GIF89a': 'GIF'
        }
        
        for filename in list(self.binary_files.keys()):
            ext = filename.split('.')[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'bmp']:
                file_data = self.binary_files[filename]
                file_size = len(file_data)
                total_size += file_size
                
                # Check for unsupported formats
                if ext in ['svg', 'webp']:
                    issues.append(f"{filename}: {ext.upper()} format has limited Kindle support")
                
                # Check individual file size (warn if > 2MB)
                if file_size > 2 * 1024 * 1024:
                    size_mb = file_size / (1024 * 1024)
                    issues.append(f"{filename}: Large image ({size_mb:.1f}MB) may cause issues")
                
                # Verify actual format matches extension
                format_detected = None
                for magic_bytes, format_name in supported_formats.items():
                    if file_data.startswith(magic_bytes):
                        format_detected = format_name
                        break
                
                if format_detected and ext in ['jpg', 'jpeg'] and format_detected != 'JPEG':
                    issues.append(f"{filename}: File type mismatch (ext: {ext}, actual: {format_detected})")
                elif format_detected and ext == 'png' and format_detected != 'PNG':
                    issues.append(f"{filename}: File type mismatch (ext: {ext}, actual: {format_detected})")
        
        if issues:
            for issue in issues:
                self.fixed_problems.append(f"Image validation warning: {issue}")
        
        # Check total EPUB size (warn if approaching 50MB uncompressed)
        total_size_mb = total_size / (1024 * 1024)
        if total_size_mb > 40:
            self.fixed_problems.append(f"Warning: Total image size is {total_size_mb:.1f}MB (Kindle works best with <50MB total)")
    
    def validate_css(self):
        """Validate CSS and only fix actual syntax errors, warn about potential Kindle issues"""
        for filename in list(self.files.keys()):
            if filename.endswith('.css'):
                original_css = self.files[filename]
                issues_found = []
                
                # Check for syntax errors that would break rendering
                # 1. Unclosed braces
                open_braces = original_css.count('{')
                close_braces = original_css.count('}')
                if open_braces != close_braces:
                    issues_found.append(f"CSS syntax error: mismatched braces ({open_braces} open, {close_braces} close)")
                
                # 2. Invalid @import statements (must be at top)
                lines = original_css.split('\n')
                import_after_rules = False
                seen_rule = False
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('/*') and not stripped.startswith('*/'):
                        if '@import' in stripped:
                            if seen_rule:
                                import_after_rules = True
                        elif stripped.startswith('@') or '{' in stripped:
                            seen_rule = True
                
                if import_after_rules:
                    issues_found.append("CSS syntax error: @import must appear before other rules")
                
                # 3. Check for common Kindle-problematic features (warning only, don't remove)
                kindle_warnings = []
                if re.search(r'position\s*:\s*(absolute|fixed)', original_css, re.IGNORECASE):
                    kindle_warnings.append("absolute/fixed positioning")
                if re.search(r'@media', original_css, re.IGNORECASE):
                    kindle_warnings.append("media queries")
                if re.search(r'javascript:', original_css, re.IGNORECASE):
                    kindle_warnings.append("javascript URLs")
                
                # Only report if there are actual syntax errors
                if issues_found:
                    for issue in issues_found:
                        self.fixed_problems.append(f"CSS validation: {issue} in {filename}")
                
                # Add informational note about Kindle compatibility (not counted as a fix needing action)
                if kindle_warnings:
                    warning_str = ', '.join(kindle_warnings)
                    print_and_log(f"[cwa-kindle-epub-fixer] Note: {filename} uses {warning_str} (may render differently on Kindle)", log=self.manually_triggered)

    def strip_amazon_identifiers(self):
        """Remove ASIN/Amazon identifiers and Calibre metadata from OPF file.
        
        Amazon may reject books that already have an ASIN in their system.
        Also removes Calibre-specific metadata that's not needed for Kindle.
        """
        opf_path = 'content.opf'
        if opf_path not in self.files:
            return
        
        opf_content = self.files[opf_path]
        
        try:
            dom = minidom.parseString(opf_content)
            package = dom.getElementsByTagName('package')[0]
            metadata = dom.getElementsByTagName('metadata')[0]
            
            changes_made = False
            
            # Remove Calibre namespace from package tag
            if package.hasAttribute('xmlns:calibre'):
                package.removeAttribute('xmlns:calibre')
                changes_made = True
                print_and_log("[cwa-kindle-epub-fixer] Removing Calibre namespace from package tag", log=self.manually_triggered)
            
            # Remove Calibre namespace from metadata tag
            if metadata.hasAttribute('xmlns:calibre'):
                metadata.removeAttribute('xmlns:calibre')
                changes_made = True
            
            # Remove Amazon/MOBI-ASIN identifiers using regex (preserve structure)
            identifiers_removed = []
            
            # Match AMAZON and MOBI-ASIN identifiers
            asin_pattern = re.compile(
                r'<dc:identifier[^>]*opf:scheme=["\'](?:AMAZON|MOBI-ASIN|mobi-asin|calibre)["\'][^>]*>.*?</dc:identifier>',
                re.IGNORECASE | re.DOTALL
            )
            
            matches = asin_pattern.findall(opf_content)
            if matches:
                for match in matches:
                    # Extract scheme and value for logging
                    scheme_match = re.search(r'opf:scheme=["\']([^"\']+)["\']', match)
                    if scheme_match:
                        identifiers_removed.append(scheme_match.group(1))
                
                opf_content = asin_pattern.sub('', opf_content)
                changes_made = True
            
            if identifiers_removed:
                print_and_log(f"[cwa-kindle-epub-fixer] Removing Amazon/Calibre identifiers: {', '.join(identifiers_removed)}", log=self.manually_triggered)
                self.fixed_problems.append(f"Removed {len(identifiers_removed)} Amazon/Calibre identifier(s)")
            
            # Remove Calibre-specific meta tags using regex (preserve structure)
            calibre_meta_pattern = re.compile(
                r'<meta[^>]*name=["\']calibre:[^"\']+["\'][^>]*/>',
                re.IGNORECASE
            )
            
            calibre_matches = calibre_meta_pattern.findall(opf_content)
            if calibre_matches:
                opf_content = calibre_meta_pattern.sub('', opf_content)
                changes_made = True
                print_and_log(f"[cwa-kindle-epub-fixer] Removing {len(calibre_matches)} Calibre meta tag(s)", log=self.manually_triggered)
                self.fixed_problems.append(f"Removed {len(calibre_matches)} Calibre meta tag(s)")
            
            # Remove xmlns:calibre from metadata tag if present
            if 'xmlns:calibre=' in opf_content:
                opf_content = re.sub(r'\s*xmlns:calibre="[^"]*"', '', opf_content)
                changes_made = True
            
            if changes_made:
                self.files[opf_path] = opf_content
            
        except Exception as e:
            print_and_log(f"[cwa-kindle-epub-fixer] Warning: Could not strip Amazon identifiers: {e}", log=self.manually_triggered)

    def write_epub(self, output_path):
        """Write EPUB file"""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
            # First write mimetype file
            if 'mimetype' in self.files:
                mimetype_content = self.files['mimetype']
                if isinstance(mimetype_content, str):
                    mimetype_content = mimetype_content.encode('utf-8')
                zip_ref.writestr('mimetype', mimetype_content, compress_type=zipfile.ZIP_STORED)

            # Add text files
            for filename, content in self.files.items():
                if filename != 'mimetype':
                    if isinstance(content, bytes):
                        zip_ref.writestr(filename, content)
                    else:
                        encoding = self.file_target_encodings.get(filename, 'utf-8')
                        zip_ref.writestr(filename, content.encode(encoding))

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

        # Extract book_id and format from path for checksum management
        book_id, book_format = self._extract_book_info_from_path(input_path)

        # Back Up Original File
        print_and_log("[cwa-kindle-epub-fixer] Backing up original file...", log=self.manually_triggered)
        self.backup_original_file(input_path)

        # Load EPUB
        print_and_log("[cwa-kindle-epub-fixer] Loading provided EPUB...", log=self.manually_triggered)
        self.read_epub(input_path)

        if self.decode_warnings:
            for warning in self.decode_warnings:
                print_and_log(f"[cwa-kindle-epub-fixer] Warning: {warning}", log=self.manually_triggered)

        # Run fixing procedures
        print_and_log("[cwa-kindle-epub-fixer] Checking linking to body ID to prevent unresolved hyperlinks...", log=self.manually_triggered)
        self.fix_body_id_link()
        print_and_log("[cwa-kindle-epub-fixer] Checking META-INF/container.xml integrity...", log=self.manually_triggered)
        self.fix_container_xml()
        print_and_log("[cwa-kindle-epub-fixer] Checking UTF-8 encoding declaration...", log=self.manually_triggered)
        self.fix_encoding()
        print_and_log("[cwa-kindle-epub-fixer] Checking language field tag is valid...", log=self.manually_triggered)
        self.fix_book_language(default_language, input_path)
        print_and_log("[cwa-kindle-epub-fixer] Checking for stray images...", log=self.manually_triggered)
        self.fix_stray_img()

        # Notify user and/or write to log
        self.export_issue_summary(input_path)

        # Write EPUB
        print_and_log("[cwa-kindle-epub-fixer] Writing EPUB...", log=self.manually_triggered)
        if Path(output_path).is_dir():
            output_path = output_path + os.path.basename(input_path)
        self.write_epub(output_path)
        print_and_log("[cwa-kindle-epub-fixer] EPUB successfully written.", log=self.manually_triggered)

        # Calculate and store new checksum after modification
        if book_id and self.fixed_problems:
            # Only recalculate if fixes were actually applied
            self._recalculate_checksum_after_modification(book_id, book_format, output_path)

        # Add entry to cwa.db
        print_and_log("[cwa-kindle-epub-fixer] Adding run to cwa.db...", log=self.manually_triggered)
        self.add_entry_to_db(input_path, output_path)
        print_and_log("[cwa-kindle-epub-fixer] Run successfully added to cwa.db.", log=self.manually_triggered)
        return self.fixed_problems


def get_library_location() -> str:
    con = sqlite3.connect("/config/app.db", timeout=30)
    cur = con.cursor()
    split_library = cur.execute('SELECT config_calibre_split FROM settings;').fetchone()[0]

    if split_library:
        split_path = cur.execute('SELECT config_calibre_split_dir FROM settings;').fetchone()[0]
        con.close()
        return split_path
    else:
        dirs = {}
        with open('/app/calibre-web-automated/dirs.json', 'r') as f:
            dirs: dict[str, str] = json.load(f)
        library_dir = f"{dirs['calibre_library_dir']}/"
        return library_dir

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
        except Exception as e:
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
