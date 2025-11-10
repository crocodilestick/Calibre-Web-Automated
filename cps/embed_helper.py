# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from uuid import uuid4
import os

from .file_helper import get_temp_dir
from .subproc_wrapper import process_open
from . import logger, config
from .constants import SUPPORTED_CALIBRE_BINARIES

log = logger.create()


def do_calibre_export(book_id, book_format):
    try:
        quotes = [4, 6]
        tmp_dir = get_temp_dir()
        calibredb_binarypath = get_calibre_binarypath("calibredb")
        temp_file_name = str(uuid4())
        my_env = os.environ.copy()
        if config.config_calibre_split:
            my_env['CALIBRE_OVERRIDE_DATABASE_PATH'] = os.path.join(config.config_calibre_dir, "metadata.db")
        library_path = config.get_book_path()
        opf_command = [calibredb_binarypath, 'export', '--dont-write-opf', '--with-library', library_path,
                       '--to-dir', tmp_dir, '--formats', book_format, "--template", "{}".format(temp_file_name),
                       str(book_id)]
        p = process_open(opf_command, quotes, my_env)
        _, err = p.communicate()
        if err:
            log.error('Metadata embedder encountered an error: %s', err)

        # Debug: List what was actually created
        log.debug(f'calibredb export completed. Checking tmp_dir: {tmp_dir}')
        tmp_contents = os.listdir(tmp_dir) if os.path.isdir(tmp_dir) else []
        log.debug(f'Contents of {tmp_dir}: {tmp_contents}')

        # List all epub files for debugging
        epub_files = [f for f in tmp_contents if f.lower().endswith('.epub')]
        log.debug(f'All EPUB files in tmp_dir: {epub_files}')

        # calibredb export with --template may create either:
        # 1. A subdirectory with the template name containing the file
        # 2. A file directly with a modified name

        # First check if a subdirectory was created
        export_dir = os.path.join(tmp_dir, temp_file_name)
        if os.path.isdir(export_dir):
            log.debug(f'Found subdirectory: {export_dir}')
            log.debug(f'Contents: {os.listdir(export_dir)}')
            # Look for the book file with the specified format
            for filename in os.listdir(export_dir):
                if filename.lower().endswith('.' + book_format.lower()):
                    # Found the exported file - return the directory and the filename without extension
                    actual_filename = os.path.splitext(filename)[0]
                    log.info(f'Found exported file in subdirectory: {export_dir}/{filename}')
                    return export_dir, actual_filename

            log.warning(f'No {book_format} file found in export directory: {export_dir}')
        else:
            # No subdirectory - look for files directly in tmp_dir
            log.debug(f'No subdirectory at {export_dir}, checking tmp_dir directly')
            for filename in os.listdir(tmp_dir):
                if filename.lower().endswith('.' + book_format.lower()):
                    actual_filename = os.path.splitext(filename)[0]
                    log.info(f'Found exported file directly in tmp_dir: {tmp_dir}/{filename}')
                    return tmp_dir, actual_filename

            log.warning(f'No {book_format} file found in {tmp_dir}')

        # Fallback to original behavior
        return tmp_dir, temp_file_name
    except OSError as ex:
        # ToDo real error handling
        log.error_or_exception(ex)
        return None, None


def get_calibre_binarypath(binary):
    binariesdir = config.config_binariesdir
    if binariesdir:
        try:
            return os.path.join(binariesdir, SUPPORTED_CALIBRE_BINARIES[binary])
        except KeyError as ex:
            log.error("Binary not supported by Calibre-Web Automated: %s", SUPPORTED_CALIBRE_BINARIES[binary])
            pass
    return ""
