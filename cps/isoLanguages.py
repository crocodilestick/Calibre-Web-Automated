# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys

from .iso_language_names import LANGUAGE_NAMES as _LANGUAGE_NAMES
from . import logger
from .string_helper import strip_whitespaces

log = logger.create()


try:
    from pycountry import languages as pyc_languages

    def _copy_fields(l):
        l.part1 = getattr(l, 'alpha_2', None)
        l.part3 = getattr(l, 'alpha_3', None)
        return l

    def get(name=None, part1=None, part3=None):
        if part3 is not None:
            return _copy_fields(pyc_languages.get(alpha_3=part3))
        if part1 is not None:
            return _copy_fields(pyc_languages.get(alpha_2=part1))
        if name is not None:
            return _copy_fields(pyc_languages.get(name=name))
except ImportError as ex:
    if sys.version_info >= (3, 12):
        print("Python 3.12 isn't compatible with iso-639. Please install pycountry.")
    from iso639 import languages
    get = languages.get


def get_language_names(locale):
    names = _LANGUAGE_NAMES.get(str(locale))
    if names is None:
        names = _LANGUAGE_NAMES.get(locale.language)
    return names


def get_language_name(locale, lang_code):
    UNKNOWN_TRANSLATION = "Unknown"
    names = get_language_names(locale)
    if names is None:
        log.error(f"Missing language names for locale: {str(locale)}/{locale.language}")
        return UNKNOWN_TRANSLATION

    name = names.get(lang_code, UNKNOWN_TRANSLATION)
    if name == UNKNOWN_TRANSLATION:
        log.error("Missing translation for language name: {}".format(lang_code))

    return name


def get_language_code_from_name(locale, language_names, remainder=None):
    language_names = set(strip_whitespaces(x).lower() for x in language_names if x)
    lang = list()
    for key, val in get_language_names(locale).items():
        val = val.lower()
        if val in language_names:
            lang.append(key)
            language_names.remove(val)
    if remainder is not None and language_names:
        remainder.extend(language_names)
    return lang


def get_valid_language_codes_from_code(locale, language_names, remainder=None):
    lang = list()
    if "" in language_names:
        language_names.remove("")
    for k, __ in get_language_names(locale).items():
        if k in language_names:
            lang.append(k)
            language_names.remove(k)
    if remainder is not None and len(language_names):
        remainder.extend(language_names)
    return lang


def get_lang3(lang):
    try:
        if len(lang) == 2:
            ret_value = get(part1=lang).part3
        elif len(lang) == 3:
            ret_value = lang
        else:
            ret_value = ""
    except (KeyError, AttributeError):
        ret_value = lang
    return ret_value
