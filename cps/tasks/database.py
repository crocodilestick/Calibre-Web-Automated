# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask_babel import lazy_gettext as N_

from cps import config, logger, db, ub
from cps.services.worker import CalibreTask


class TaskReconnectDatabase(CalibreTask):
    def __init__(self, task_message=N_('Reconnecting Calibre database')):
        super(TaskReconnectDatabase, self).__init__(task_message)
        self.log = logger.create()
        self.calibre_db = db.CalibreDB(expire_on_commit=False, init=True)

    def run(self, worker_thread):
        self.calibre_db.reconnect_db(config, ub.app_DB_path)
        self.calibre_db.session.close()
        self._handleSuccess()

    @property
    def name(self):
        return "Reconnect Database"

    @property
    def is_cancellable(self):
        return False
