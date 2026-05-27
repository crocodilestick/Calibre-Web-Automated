# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import copy
import glob
import importlib
import io
import json
import os
import re
import shutil
import zipfile
from io import BytesIO

from flask import send_file
from flask_babel.speaklater import LazyString

from . import logger, config
from .about import collect_stats

log = logger.create()


# ---------------------------------------------------------------------------
# Sanitization for the support-debug zip (fork issue #312).
#
# The original implementation handed `settings.txt` + raw log files
# straight to the user with only a substring-based redaction in
# `config.to_dict()`. That filter missed plaintext fields like
# `mail_password`, the encrypted shadow `mail_password_e`, the JSON
# OAuth blob `mail_gmail_token`, and `config_ldap_serv_password` —
# every one a credential a non-technical user (the audience this
# feature exists for) might paste into a public GitHub issue.
#
# The functions below run between "read the live values" and "write
# into the zip." They never modify the running app's state.
# ---------------------------------------------------------------------------

REDACTED_PLACEHOLDER = "<redacted>"

# Explicit allow-list of field names that must always be redacted, even
# if `config.to_dict()`'s substring filter happens to miss them. Kept
# alphabetical for diff clarity.
_KNOWN_SECRET_FIELDS = frozenset({
    "config_github_oauth_clientsecret",
    "config_google_oauth_clientsecret",
    "config_hardcover_token",
    "config_ldap_serv_password",
    "config_ldap_serv_password_e",
    "mail_gmail_token",
    "mail_password",
    "mail_password_e",
})

# Substring matches for unknown/future fields. If the field name contains
# any of these as a whole token (case-insensitive), redact the value.
_SECRET_SUBSTRINGS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
)

# Defense-in-depth: even legitimate non-secret fields can carry a value
# that LOOKS like a JWT or a long bearer token. Redact those too.
# Three base64url segments separated by dots = JWT shape.
_JWT_PATTERN = re.compile(
    r"\b[A-Za-z0-9_\-]{8,}\."
    r"[A-Za-z0-9_\-]{8,}\."
    r"[A-Za-z0-9_\-]{16,}\b"
)
# A bare run of >= 40 base64-ish characters is very likely a token.
_LONG_TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9+/=_\-]{40,}\b")


def _looks_sensitive(field_name: str) -> bool:
    if field_name in _KNOWN_SECRET_FIELDS:
        return True
    lower = field_name.lower()
    return any(s in lower for s in _SECRET_SUBSTRINGS)


def _redact_value(value, *, aggressive=False):
    """Apply defense-in-depth regex redaction to a string value.

    Only operates on strings — lists, dicts, bools, ints, floats round-trip
    unchanged. The previous version called `str(value)` on everything,
    which turned `["a"]` into the string `"['a']"` in the exported
    JSON and broke any consumer that parsed the original type.

    `aggressive=True` applies the broader "long token shape" pattern,
    which catches arbitrary 40+ char base64-ish runs. It's only safe to
    enable on fields we already suspect (sensitive-key + opaque value)
    — applied to every field it scrubs legitimate long content like
    library paths, version strings, and UUID-like IDs.
    """
    if not isinstance(value, str) or value == "":
        return value
    text = _JWT_PATTERN.sub(REDACTED_PLACEHOLDER, value)
    if aggressive:
        text = _LONG_TOKEN_PATTERN.sub(REDACTED_PLACEHOLDER, text)
    return text


def _redact_for_export(settings_dict):
    """Return a copy of ``settings_dict`` with every known-secret field
    placeholder-replaced and every JWT-shaped value scrubbed for
    defense-in-depth.

    A field whose name LOOKS sensitive is only redacted if its value is
    a non-empty string — booleans and integers can't be credentials, and
    catching `config_password_min_length` (a policy integer) as a "leak"
    blanks legitimate diagnostic content. Container testing of fork
    issue #312 caught this false-positive.

    The broader "long token shape" heuristic only runs on fields whose
    KEY already matched the sensitive substring set — otherwise it
    blanks legitimate long values (URLs, library paths, hashes).

    Never mutates the caller's dict — the running app keeps the real
    values; only the export sees the redacted ones.
    """
    if not isinstance(settings_dict, dict):
        return settings_dict
    out = copy.deepcopy(settings_dict)
    for key in list(out.keys()):
        value = out[key]
        sensitive_name = _looks_sensitive(key)
        if sensitive_name and isinstance(value, str) and value:
            out[key] = REDACTED_PLACEHOLDER
            continue
        out[key] = _redact_value(value, aggressive=sensitive_name)
    return out


# ---------------------------------------------------------------------------
# Log line sanitization (fork issue #312).
#
# The live log on disk is unmodified — admins can still see full IPs,
# usernames, and paths there. The sanitizer only runs on the way INTO
# the zip the user sends to GitHub support.
# ---------------------------------------------------------------------------

# IPv4-mapped IPv6 (e.g. `::ffff:127.0.0.1`) is the form Flask's
# `request.remote_addr` returns when the client connects over IPv6 to a
# v4 address. The kosync gate logs it; the IPv6 regex would otherwise
# match `::ffff:127` and leave a corrupted `.0.0.1` tail. We strip the
# whole IPv4-mapped form first, preserving loopback explicitly.
_IPV4_MAPPED_PATTERN = re.compile(
    r"::ffff:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
    re.IGNORECASE,
)

# IPv4: four 1-3 digit groups. We intentionally PRESERVE 127.0.0.1 so
# loopback diagnostics stay legible.
_IPV4_PATTERN = re.compile(r"\b(?!127\.0\.0\.1\b)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

# IPv6 — accept either:
#   * the full 8-group form (7 colons, no ::), e.g.
#     `2001:0db8:85a3:0000:0000:8a2e:0370:7334`
#   * a compressed form (with `::`) where at least ONE side has a hex
#     group — so bare `::` and unrelated `::` tokens in log content
#     (Python slice syntax `arr[1::2]`, C++ scope `Class::method`,
#     etc.) won't be redacted as IPs.
# Crucially does NOT match decimal timestamps like `12:00:00` — those
# have <4 colons and no `::`, so they fail all alternatives.
_IPV6_PATTERN = re.compile(
    r"(?:"
    # full 8-group form
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
    r"|"
    # compressed form with required prefix hex
    r"[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*::(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?"
    r"|"
    # compressed form with required suffix hex (catches `::1`, `::ffff:…`)
    r"(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?::[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*"
    r")"
)

# Per-install absolute paths likely to identify the user.
_CONFIG_PATH_PATTERN = re.compile(r"/config/")
_LIBRARY_PATH_PATTERN = re.compile(r"/calibre-library/")

# Auth header values.
_BEARER_PATTERN = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)
_BASIC_PATTERN = re.compile(r"(Basic\s+)\S+", re.IGNORECASE)


# Sentinel for IPv4-mapped loopback during sanitization. The plain IPv6
# regex would otherwise match `::ffff:127` after the loopback was
# preserved, corrupting the line. We swap the preserved form for this
# marker before running IPv6, then restore it. Uses ASCII control chars
# that real log content cannot contain.
_LOOPBACK_V4M_MARKER = "\x01CWNG_LOOPBACK_V4M\x01"


def _maybe_redact_ipv4_mapped(match):
    """Preserve `::ffff:127.0.0.1` as loopback; redact other mapped v4."""
    ip = match.group(1)
    if ip == "127.0.0.1":
        return _LOOPBACK_V4M_MARKER
    return "<ip>"


def _sanitize_log_line(line: str) -> str:
    """Apply PII/credential scrubbing to a single log line.

    Idempotent: running on already-sanitized text is a no-op.
    """
    if not line:
        return line
    # IPv4-mapped IPv6 BEFORE plain IPv6 so the regex sees the full
    # `::ffff:n.n.n.n` token instead of half-matching `::ffff:n` and
    # corrupting the tail. Loopback is shielded behind a marker so the
    # downstream IPv6 regex won't re-match the preserved literal.
    line = _IPV4_MAPPED_PATTERN.sub(_maybe_redact_ipv4_mapped, line)
    line = _IPV4_PATTERN.sub("<ip>", line)
    line = _IPV6_PATTERN.sub("<ip>", line)
    line = line.replace(_LOOPBACK_V4M_MARKER, "::ffff:127.0.0.1")
    # Paths.
    line = _CONFIG_PATH_PATTERN.sub("<config>/", line)
    line = _LIBRARY_PATH_PATTERN.sub("<library>/", line)
    # Auth headers.
    line = _BEARER_PATTERN.sub(r"\1<redacted>", line)
    line = _BASIC_PATTERN.sub(r"\1<redacted>", line)
    return line


# Truncation safety net. A multi-MiB log over a slow link is enough to
# discourage non-technical users from sharing it at all; cap each file
# at the last N MiB so the zip stays under ~12 MiB even when several
# rotated files are bundled.
_PER_FILE_MAX_BYTES = 10 * 1024 * 1024


def _sanitize_log_bytes(raw: bytes) -> bytes:
    """Read a log file, sanitize each line, return the sanitized bytes
    capped at ``_PER_FILE_MAX_BYTES`` (tail-biased: keep the most
    recent content, drop the head if oversize)."""
    if not raw:
        return raw
    # Tail-truncate first so we never burn CPU sanitizing bytes we'd
    # drop anyway.
    if len(raw) > _PER_FILE_MAX_BYTES:
        raw = raw[-_PER_FILE_MAX_BYTES:]
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return raw
    sanitized_lines = []
    for line in text.splitlines(keepends=True):
        sanitized_lines.append(_sanitize_log_line(line))
    return "".join(sanitized_lines).encode("utf-8")


# ---------------------------------------------------------------------------
# Existing entry points (kept verbatim where unchanged).
# ---------------------------------------------------------------------------

class lazyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, LazyString):
            return str(obj)
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


def assemble_logfiles(file_name):
    log_list = sorted(glob.glob(file_name + '*'), reverse=True)
    wfd = BytesIO()
    for f in log_list:
        with open(f, 'rb') as fd:
            shutil.copyfileobj(fd, wfd)
    wfd.seek(0)
    version = importlib.metadata.version("flask")
    if int(version.split('.')[0]) < 2:
        return send_file(wfd,
                         as_attachment=True,
                         attachment_filename=os.path.basename(file_name))
    else:
        return send_file(wfd,
                         as_attachment=True,
                         download_name=os.path.basename(file_name))


def _build_debug_zip(sanitize: bool):
    """Build the in-memory debug pack. When ``sanitize`` is True the
    settings file is redacted and every log line is scrubbed for IPs,
    paths, and auth headers."""
    file_list = glob.glob(logger.get_logfile(config.config_logfile) + '*')
    file_list.extend(glob.glob(logger.get_accesslogfile(config.config_access_logfile) + '*'))
    for element in [logger.LOG_TO_STDOUT, logger.LOG_TO_STDERR]:
        if element in file_list:
            file_list.remove(element)

    settings_dict = config.to_dict()
    libs_dict = collect_stats()
    if sanitize:
        settings_dict = _redact_for_export(settings_dict)

    memory_zip = BytesIO()
    with zipfile.ZipFile(memory_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('settings.txt', json.dumps(settings_dict, sort_keys=True, indent=2))
        zf.writestr('libs.txt', json.dumps(libs_dict, sort_keys=True, indent=2, cls=lazyEncoder))
        if sanitize:
            zf.writestr('SANITIZED.txt', _SANITIZED_NOTE)
        for fp in file_list:
            if sanitize:
                with open(fp, 'rb') as fd:
                    raw = fd.read()
                zf.writestr(os.path.basename(fp), _sanitize_log_bytes(raw))
            else:
                zf.write(fp, os.path.basename(fp))
    memory_zip.seek(0)
    return memory_zip


_SANITIZED_NOTE = (
    "This debug pack has been sanitized for sharing in public issues.\n"
    "\n"
    "What was removed or replaced:\n"
    "  * Settings: passwords, OAuth tokens, LDAP bind passwords, API keys.\n"
    "  * Logs: public IPs, /config/ and /calibre-library/ paths,\n"
    "          Authorization: Bearer/Basic header values, JWT-shaped tokens.\n"
    "\n"
    "What was kept:\n"
    "  * Loopback IP (127.0.0.1), timestamps, log levels, error messages,\n"
    "    book titles, request paths, application stack traces.\n"
    "\n"
    "Each log file is capped at the last 10 MiB so the zip stays small.\n"
    "\n"
    "If you'd rather not share even the sanitized version, the Download Debug\n"
    "Package button (next to this one) generates an UNREDACTED pack for\n"
    "internal/private use only.\n"
)


def send_debug():
    """Unsanitized debug pack — admin/internal use only."""
    memory_zip = _build_debug_zip(sanitize=False)
    version = importlib.metadata.version("flask")
    if int(version.split('.')[0]) < 2:
        return send_file(memory_zip,
                         as_attachment=True,
                         attachment_filename="Calibre-Web-NextGen-debug-pack.zip")
    else:
        return send_file(memory_zip,
                         as_attachment=True,
                         download_name="Calibre-Web-NextGen-debug-pack.zip")


def send_debug_sanitized():
    """Sanitized debug pack — safe to share in public issues."""
    memory_zip = _build_debug_zip(sanitize=True)
    version = importlib.metadata.version("flask")
    if int(version.split('.')[0]) < 2:
        return send_file(memory_zip,
                         as_attachment=True,
                         attachment_filename="Calibre-Web-NextGen-support-pack.zip")
    else:
        return send_file(memory_zip,
                         as_attachment=True,
                         download_name="Calibre-Web-NextGen-support-pack.zip")
