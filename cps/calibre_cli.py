# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os


def get_calibre_cli_context(config):
    """Return the book root and environment for Calibre CLI commands.

    Calibre expects ``--with-library`` to point at the book-files root. In a
    split library, ``metadata.db`` lives elsewhere and must be supplied via
    ``CALIBRE_OVERRIDE_DATABASE_PATH``.
    """
    library_path = config.get_book_path()
    calibre_env = os.environ.copy()
    if config.config_calibre_split:
        calibre_env["CALIBRE_OVERRIDE_DATABASE_PATH"] = os.path.join(
            config.config_calibre_dir,
            "metadata.db",
        )
    return library_path, calibre_env
