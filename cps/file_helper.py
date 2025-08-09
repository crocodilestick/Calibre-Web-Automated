# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from tempfile import gettempdir
import os
import shutil
import zipfile
import mimetypes
from io import BytesIO

from . import logger

log = logger.create()

try:
    import magic
    error = None
except ImportError as e:
    error = "Cannot import python-magic, checking uploaded file metadata will not work: {}".format(e)


def get_mimetype(ext):
    # overwrite some mimetypes for proper file detection
    mimes = {".cbz": "application/zip",
             ".cbr": "application/x-rar",
             ".cbt": "application/x-tar"
             }
    return mimes.get(ext, mimetypes.types_map[ext])


def get_temp_dir():
    tmp_dir = os.path.join(gettempdir(), 'calibre_web')
    if not os.path.isdir(tmp_dir):
        os.mkdir(tmp_dir)
    return tmp_dir


def del_temp_dir():
    tmp_dir = os.path.join(gettempdir(), 'calibre_web')
    shutil.rmtree(tmp_dir)


def validate_mime_type(file_buffer, allowed_extensions):
    if error:
        log.error(error)
        return False
    mime = magic.Magic(mime=True)
    allowed_mimetypes = list()
    for x in allowed_extensions:
        try:
            allowed_mimetypes.append(get_mimetype("." + x))
        except KeyError:
            log.error("Unkown mimetype for Extension: {}".format(x))
    tmp_mime_type = mime.from_buffer(file_buffer.read())
    file_buffer.seek(0)
    if any(mime_type in tmp_mime_type for mime_type in allowed_mimetypes):
        return True
    # Some epubs show up as zip mimetypes
    elif "zip" in tmp_mime_type:
        try:
            with zipfile.ZipFile(BytesIO(file_buffer.read()), 'r') as epub:
                file_buffer.seek(0)
                if "mimetype" in epub.namelist():
                    return True
        except:
            file_buffer.seek(0)
    log.error("Mimetype '{}' not found in allowed types".format(tmp_mime_type))
    return False
