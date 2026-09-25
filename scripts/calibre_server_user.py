#!/usr/bin/env python3
# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create the content server's single user, reading the password from stdin.

Run under calibre's interpreter:

    calibre-debug -e calibre_server_user.py -- <userdb> <username>

``calibre-server --manage-users -- add <user> <pass>`` is the documented
non-interactive equivalent, but it takes the password as an argument, and
/proc/<pid>/cmdline is world readable. Driving UserManager directly lets the
password arrive on stdin instead.
"""

import os
import sys

from calibre.srv.users import UserManager


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: calibre_server_user.py <userdb> <username>\n")
        return 2
    userdb, username = argv
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        sys.stderr.write("no password supplied on stdin\n")
        return 2
    manager = UserManager(userdb)
    if manager.has_user(username):
        manager.change_password(username, password)
    else:
        manager.add_user(username, password)
    try:
        os.chmod(userdb, 0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
