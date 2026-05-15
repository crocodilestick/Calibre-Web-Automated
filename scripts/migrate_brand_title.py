# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Rebrand legacy instance titles to ``Calibre-Web NextGen``.

The fresh-install default in ``cps/config_sql.py`` is already
``Calibre-Web NextGen``. But existing installs carry whatever string
was the default when their ``settings`` row was first inserted — that's
``Calibre-Web`` for users migrating in from stock calibre-web, and
``Calibre-Web Automated`` for users coming from CWA. Both of those
read as the old brand in the browser tab and navbar after the v4.0.60
rebrand and confuse users into thinking the upgrade didn't apply.

We migrate those two legacy defaults — and only those — to the new
brand. Any custom title (e.g. ``Maggie's Library``) is left untouched.
The match is hyphen-and-case-agnostic so variants like
``CALIBRE-WEB AUTOMATED`` or ``calibre web`` also get rebranded.

The migration is idempotent: running it against a DB that's already
on the new brand (or has a custom title) is a no-op.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys


TARGET_TITLE = "Calibre-Web NextGen"

# Normalized forms of the two legacy default titles we want to migrate.
# Anything else (custom title, already on new brand) is left alone.
_LEGACY_NORMALIZED = frozenset({"calibreweb", "calibrewebautomated"})


def _normalize(value: str) -> str:
    """Strip everything but ASCII letters/digits, then lowercase."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def should_migrate(current_title: str | None) -> bool:
    """True iff ``current_title`` is a legacy default we should rebrand.

    ``None`` and empty/whitespace strings are treated as legacy — those
    mean "row was created before the column had any default", which is
    effectively the same as the old default.
    """
    if current_title is None or not current_title.strip():
        return True
    return _normalize(current_title) in _LEGACY_NORMALIZED


def migrate(db_path: str) -> tuple[bool, str | None]:
    """Run the migration against ``db_path``.

    Returns ``(updated, previous_value)``. ``updated`` is True only when
    we actually changed the row; otherwise the DB was already on a
    non-legacy title and we left it alone.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT config_calibre_web_title FROM settings LIMIT 1")
        row = cur.fetchone()
        if row is None:
            # No settings row yet — fresh-install path. The column
            # default handles it, nothing to migrate.
            return False, None
        previous = row[0]
        if not should_migrate(previous):
            return False, previous
        cur.execute(
            "UPDATE settings SET config_calibre_web_title = ?",
            (TARGET_TITLE,),
        )
        conn.commit()
        return True, previous
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebrand legacy instance titles to Calibre-Web NextGen",
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default="/config/app.db",
        help="Path to app.db (default: /config/app.db)",
    )
    args = parser.parse_args(argv)

    try:
        updated, previous = migrate(args.db_path)
    except sqlite3.Error as exc:
        print(f"[brand-title-migration] sqlite error: {exc}", flush=True)
        return 1

    if updated:
        print(
            f"[brand-title-migration] Updated config_calibre_web_title: "
            f"{previous!r} -> {TARGET_TITLE!r}",
            flush=True,
        )
    else:
        print(
            f"[brand-title-migration] No change: {previous!r} is not a legacy default",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
