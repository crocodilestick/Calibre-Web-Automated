# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from datetime import datetime
from gevent.pywsgi import WSGIHandler


class MyWSGIHandler(WSGIHandler):
    def get_environ(self):
        env = super().get_environ()
        path, __ = self.path.split('?', 1) if '?' in self.path else (self.path, '')
        env['RAW_URI'] = path
        return env

    def format_request(self):
        now = datetime.now().replace(microsecond=0)
        length = self.response_length or '-'
        if self.time_finish:
            delta = '%.6f' % (self.time_finish - self.time_start)
        else:
            delta = '-'
        forwarded = self.environ.get('HTTP_X_FORWARDED_FOR', None)
        if forwarded:
            client_address = forwarded
        else:
            client_address = self.client_address[0] if isinstance(self.client_address, tuple) else self.client_address
        return '%s - - [%s] "%s" %s %s %s' % (
            client_address or '-',
            now,
            self.requestline or '',
            # Use the native string version of the status, saved so we don't have to
            # decode. But fallback to the encoded 'status' in case of subclasses
            # (Is that really necessary? At least there's no overhead.)
            (self._orig_status or self.status or '000').split()[0],
            length,
            delta)

