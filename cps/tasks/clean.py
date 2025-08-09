# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import datetime

from flask_babel import lazy_gettext as N_
from sqlalchemy.sql.expression import or_

from cps import logger, file_helper, ub
from cps.services.worker import CalibreTask


class TaskClean(CalibreTask):
    def __init__(self, task_message=N_('Delete temp folder contents')):
        super(TaskClean, self).__init__(task_message)
        self.log = logger.create()
        self.app_db_session = ub.get_new_session_instance()

    def run(self, worker_thread):
        # delete temp folder
        try:
            file_helper.del_temp_dir()
        except FileNotFoundError:
            pass
        except (PermissionError, OSError) as e:
            self.log.error("Error deleting temp folder: {}".format(e))
        # delete expired session keys
        self.log.debug("Deleted expired session_keys" )
        expiry = int(datetime.datetime.now().timestamp())
        try:
            self.app_db_session.query(ub.User_Sessions).filter(or_(ub.User_Sessions.expiry < expiry,
                                                               ub.User_Sessions.expiry == None)).delete()
            self.app_db_session.commit()
        except Exception as ex:
            self.log.debug('Error deleting expired session keys: ' + str(ex))
            self._handleError('Error deleting expired session keys: ' + str(ex))
            self.app_db_session.rollback()
            return

        self._handleSuccess()
        self.app_db_session.remove()

    @property
    def name(self):
        return "Clean up"

    @property
    def is_cancellable(self):
        return False
