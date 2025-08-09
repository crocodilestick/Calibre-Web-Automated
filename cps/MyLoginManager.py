# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from .cw_login import LoginManager
from flask import session


class MyLoginManager(LoginManager):
    def _session_protection_failed(self):
        sess = session._get_current_object()
        ident = self._session_identifier_generator()
        if(sess and not (len(sess) == 1
                         and sess.get('csrf_token', None))) and ident != sess.get('_id', None):
            return super(). _session_protection_failed()
        return False



