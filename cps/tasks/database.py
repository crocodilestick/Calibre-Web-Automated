# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from flask_babel import lazy_gettext as N_

from cps import config, logger, db, ub, calibre_db
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


class TaskCleanArchivedBooks(CalibreTask):
    def __init__(self, task_message=N_('Clean archived book references')):
        super(TaskCleanArchivedBooks, self).__init__(task_message)
        self.log = logger.create()
        self.app_db_session = ub.get_new_session_instance()

    @property
    def name(self):
        return "Clean Archived Book References"

    @property
    def is_cancellable(self):
        return False

    def run(self, worker_thread):
        try:
            ub.init_db_thread()
        except Exception:
            # Non-fatal; continue
            pass

        try:
            calibre_db.ensure_session()
        except Exception as ex:
            self.log.warning("Archived cleanup skipped: calibre db unavailable: %s", str(ex))
            self._handleSuccess()
            self.app_db_session.remove()
            return

        def _chunked(values, size=900):
            for i in range(0, len(values), size):
                yield values[i:i + size]

        try:
            archived_ids = [row[0] for row in self.app_db_session.query(ub.ArchivedBook.book_id).distinct().all()]
            archived_ids = [int(x) for x in archived_ids if x is not None]

            if not archived_ids:
                self._handleSuccess()
                self.app_db_session.remove()
                return

            archived_ids = list(set(archived_ids))

            existing_ids = set()
            for chunk in _chunked(archived_ids):
                rows = calibre_db.session.query(db.Books.id).filter(db.Books.id.in_(chunk)).all()
                existing_ids.update(row[0] for row in rows)

            stale_ids = [book_id for book_id in archived_ids if book_id not in existing_ids]

            if not stale_ids:
                self._handleSuccess()
                self.app_db_session.remove()
                return

            deleted_count = 0
            for chunk in _chunked(stale_ids):
                deleted_count += self.app_db_session.query(ub.ArchivedBook).filter(
                    ub.ArchivedBook.book_id.in_(chunk)).delete(synchronize_session=False)

            self.app_db_session.commit()
            self.log.info("Removed %s stale archived_book rows", deleted_count)
            self._handleSuccess()
        except Exception as ex:
            self.log.error("Failed to clean archived_book rows: %s", str(ex))
            self.app_db_session.rollback()
            self._handleError('Failed to clean archived_book rows: ' + str(ex))
        finally:
            self.app_db_session.remove()
