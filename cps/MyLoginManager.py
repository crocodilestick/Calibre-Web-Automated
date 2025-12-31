# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from .cw_login import LoginManager
from flask import session, request
from . import logger

log = logger.create()


class MyLoginManager(LoginManager):
    def _session_protection_failed(self):
        sess = session._get_current_object()
        # If user is not logged in, skip session protection
        if not sess.get('_user_id'):
            return False

        ident = self._session_identifier_generator()
        if(sess and not (len(sess) == 1
                         and sess.get('csrf_token', None))) and ident != sess.get('_id', None):
            # Log session identifier mismatch for debugging (issue #141)
            stored_id = sess.get('_id', 'None')
            user_id = sess.get('_user_id', 'unknown')
            log.debug(
                "Session protection triggered for user %s: identifier mismatch "
                "(stored: %s..., current: %s..., IP: %s)",
                user_id,
                stored_id[:16] if stored_id != 'None' else 'None',
                ident[:16] if ident else 'None',
                request.remote_addr
            )
            return super(). _session_protection_failed()
        return False



