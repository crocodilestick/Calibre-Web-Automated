# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from babel import negotiate_locale
from flask_babel import Babel, Locale
from babel.core import UnknownLocaleError
from flask import request, has_request_context
from .cw_login import current_user

from . import logger

log = logger.create()

babel = Babel()


def get_locale():
    # If no request context (e.g. background thread), fall back to English
    if not has_request_context():
        return 'en'
    # if a user is logged in, use the locale from the user settings
    if current_user is not None and hasattr(current_user, "locale"):
        # if the account is the guest account bypass the config lang settings
        if current_user.name != 'Guest':
            return current_user.locale

    preferred = list()
    if has_request_context() and request.accept_languages:
        for x in request.accept_languages.values():
            # Skip wildcard '*' from Accept-Language headers (common in internal API requests)
            if x == '*':
                continue
            try:
                preferred.append(str(Locale.parse(x.replace('-', '_'))))
            except (UnknownLocaleError, ValueError) as e:
                log.debug('Could not parse locale "%s": %s', x, e)

    return negotiate_locale(preferred or ['en'], get_available_translations())


def get_user_locale_language(user_language):
    return Locale.parse(user_language).get_language_name(get_locale())


def get_available_locale():
    return [Locale('en')] + babel.list_translations()


def get_available_translations():
    return set(str(item) for item in get_available_locale())
