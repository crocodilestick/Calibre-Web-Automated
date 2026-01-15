# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
from sqlalchemy import func
from flask_babel import lazy_gettext as N_

from cps import calibre_db, db, logger
from cps.services.worker import CalibreTask, STAT_CANCELLED, STAT_ENDED
from cps.ub import init_db_thread

# Access CWA DB (scripts path)
if '/app/calibre-web-automated/scripts/' not in sys.path:
    sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()


class TaskDuplicateScan(CalibreTask):
    def __init__(self, full_scan=True, task_message=None, trigger_type='manual', user_id=None):
        super(TaskDuplicateScan, self).__init__(task_message or N_('Duplicate scan'))
        self.full_scan = full_scan
        self.trigger_type = trigger_type
        self.result_count = 0
        self.user_id = user_id

    @property
    def name(self):
        return str(N_('Duplicate scan'))

    @property
    def is_cancellable(self):
        return True

    def run(self, worker_thread):
        try:
            init_db_thread()
        except Exception:
            # Non-fatal; continue
            pass

        try:
            # Ensure calibre DB session is ready in this thread
            calibre_db.ensure_session()

            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                return

            cwa_db = CWA_DB()
            cache_data = cwa_db.get_duplicate_cache() or {}

            if not self.full_scan and not cache_data.get('scan_pending', True):
                self._handleSuccess()
                return

            self.progress = 0.1
            self.message = N_('Scanning for duplicates')

            # Import here to avoid circular dependency during module import
            from cps.duplicates import find_duplicate_books

            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                return

            duplicate_groups = find_duplicate_books(include_dismissed=False, user_id=self.user_id)
            self.result_count = len(duplicate_groups)

            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                return

            # Update cache with full results (including dismissed groups)
            all_groups = find_duplicate_books(include_dismissed=True, user_id=self.user_id)

            max_book_id = 0
            try:
                max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                max_book_id = max_id_result if max_id_result is not None else 0
            except Exception as ex:
                log.warning("[cwa-duplicates] Could not get max book ID in TaskDuplicateScan: %s", str(ex))

            cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)

            self.progress = 1
            self.message = N_('Duplicate scan completed: %(count)s groups', count=len(duplicate_groups))
            self._handleSuccess()
        except Exception as ex:
            log.error("[cwa-duplicates] Duplicate scan task failed: %s", str(ex))
            self._handleError(str(ex))
        finally:
            try:
                if calibre_db.session is not None:
                    calibre_db.session.close()
            except Exception:
                pass
