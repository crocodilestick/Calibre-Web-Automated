# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from datetime import datetime

from flask_babel import lazy_gettext as N_

from cps.services.worker import CalibreTask, STAT_FINISH_SUCCESS


class TaskUpload(CalibreTask):
    def __init__(self, task_message, book_title):
        super(TaskUpload, self).__init__(task_message)
        self.start_time = self.end_time = datetime.now()
        self.stat = STAT_FINISH_SUCCESS
        self.progress = 1
        self.book_title = book_title

    def run(self, worker_thread):
        """Upload task doesn't have anything to do, it's simply a way to add information to the task list"""

    @property
    def name(self):
        return N_("Upload")

    def __str__(self):
        return "Upload {}".format(self.book_title)

    @property
    def is_cancellable(self):
        return False
