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
