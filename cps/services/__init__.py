# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from .. import logger

log = logger.create()

try:
    from . import goodreads_support
except ImportError as err:
    log.debug("Cannot import goodreads, showing authors-metadata will not work: %s", err)
    goodreads_support = None


try:
    from . import simpleldap as ldap
    from .simpleldap import ldapVersion
except ImportError as err:
    log.debug("Cannot import simpleldap, logging in with ldap will not work: %s", err)
    ldap = None
    ldapVersion = None

try:
    from . import SyncToken as SyncToken
    kobo = True
except ImportError as err:
    log.debug("Cannot import SyncToken, syncing books with Kobo Devices will not work: %s", err)
    kobo = None
    SyncToken = None

try:
    from . import gmail
except ImportError as err:
    log.debug("Cannot import gmail, sending books via Gmail Oauth2 Verification will not work: %s", err)
    gmail = None

try:
    from . import hardcover
except ImportError as err:
    log.debug("Cannot import hardcover, syncing Kobo read progress to Hardcover will not work: %s", err)
    hardcover = None