# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for the comma separated Send-to-eReader address list.

Every entry may optionally carry a human readable label using the
RFC 5322 display-name syntax, e.g.::

    My Paperwhite <reader_abc123@kindle.com>, reader2@kindle.com

Plain addresses keep working unchanged. Labels must not contain commas,
angle brackets, quotes or line breaks so the stored value can always be
split on commas.
"""

import re
from email.utils import parseaddr

# Regex according to https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input/email#validation
EMAIL_REGEX = re.compile(
    r"^[\w.!#$%&'*+\\/=?^_`{|}~-]+@[\w](?:[\w-]{0,61}[\w])?(?:\.[\w](?:[\w-]{0,61}[\w])?)*$")
_ENTRY_REGEX = re.compile(r"^(?:(?P<label>[^<>]*?)\s*<(?P<addr>[^<>]*)>|(?P<plain>[^<>\s]+))$")
_FORBIDDEN_LABEL_CHARS = set('<>,"\r\n\\')


def parse_ereader_email(entry):
    """Parse one entry into (label, address). Raises ValueError if invalid."""
    entry = (entry or "").strip()
    match = _ENTRY_REGEX.match(entry)
    if not match:
        raise ValueError(entry)
    if match.group("plain") is not None:
        label, address = "", match.group("plain")
    else:
        label, address = match.group("label").strip(), match.group("addr").strip()
    if any(c in _FORBIDDEN_LABEL_CHARS for c in label):
        raise ValueError(entry)
    # Cross-check with the stdlib parser so we only ever accept what it agrees with
    if parseaddr(address)[1] != address or not EMAIL_REGEX.match(address):
        raise ValueError(entry)
    return label, address


def parse_ereader_emails(emails):
    """Parse a comma separated list into [(label, address), ...], skipping empty entries."""
    result = []
    for entry in (emails or "").split(','):
        if entry.strip():
            result.append(parse_ereader_email(entry))
    return result


def format_ereader_email(label, address):
    return "{} <{}>".format(label, address) if label else address


def ereader_addresses(emails):
    """Return just the bare addresses; invalid legacy entries are passed through stripped."""
    addresses = []
    for entry in (emails or "").split(','):
        entry = entry.strip()
        if not entry:
            continue
        try:
            addresses.append(parse_ereader_email(entry)[1])
        except ValueError:
            addresses.append(parseaddr(entry)[1] or entry)
    return addresses


def bare_address(entry):
    """Envelope address for a single entry (label stripped)."""
    addresses = ereader_addresses(entry)
    return addresses[0] if addresses else ""
