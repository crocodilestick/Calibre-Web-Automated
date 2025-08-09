# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import re

from flask_babel import lazy_gettext as N_

from . import config, logger
from .subproc_wrapper import process_wait


log = logger.create()

# strings getting translated when used
_NOT_INSTALLED = N_('not installed')
_EXECUTION_ERROR = N_('Execution permissions missing')


def _get_command_version(path, pattern, argument=None):
    if os.path.exists(path):
        command = [path]
        if argument:
            command.append(argument)
        try:
            match = process_wait(command, pattern=pattern)
            if isinstance(match, re.Match):
                return match.string
        except Exception as ex:
            log.warning("%s: %s", path, ex)
            return _EXECUTION_ERROR
    return _NOT_INSTALLED


def get_calibre_version():
    return _get_command_version(config.config_converterpath, r'ebook-convert.*\(calibre', '--version')


def get_unrar_version():
    unrar_version = _get_command_version(config.config_rarfile_location, r'UNRAR.*\d')
    if unrar_version == "not installed":
        unrar_version = _get_command_version(config.config_rarfile_location, r'unrar.*\d', '-V')
    return unrar_version


def get_kepubify_version():
    return _get_command_version(config.config_kepubifypath, r'kepubify\s', '--version')
