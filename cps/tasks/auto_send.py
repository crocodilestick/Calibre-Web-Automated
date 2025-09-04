# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import time
from datetime import datetime

from flask_babel import lazy_gettext as N_

from cps.services.worker import CalibreTask, STAT_FINISH_SUCCESS
from cps import helper, ub, db, calibre_db, config, logger

log = logger.create()


class TaskAutoSend(CalibreTask):
    def __init__(self, task_message, book_id, user_id, delay_minutes=5):
        super(TaskAutoSend, self).__init__(task_message)
        self.start_time = self.end_time = datetime.now()
        self.book_id = book_id
        self.user_id = user_id
        self.delay_minutes = delay_minutes
        self.book_title = ""
        self.progress = 0

    def run(self, worker_thread):
        """Auto-send newly ingested book to user's eReader addresses"""
        self.worker_thread = worker_thread
        
        try:
            # Wait for specified delay to allow metadata fetching to complete
            if self.delay_minutes > 0:
                self.message = N_("Waiting for metadata processing...")
                time.sleep(self.delay_minutes * 60)
            
            # Get fresh book data
            calibre_db_instance = db.CalibreDB(expire_on_commit=False, init=True)
            book = calibre_db_instance.get_book(self.book_id)
            if not book:
                self._handleError(f"Book with ID {self.book_id} not found")
                return
                
            self.book_title = book.title
            self.progress = 0.3
            
            # Get user data
            user = ub.session.query(ub.User).filter(ub.User.id == self.user_id).first()
            if not user or not user.auto_send_enabled:
                self._handleError(f"User {self.user_id} not found or auto-send disabled")
                return
                
            if not user.kindle_mail:
                self._handleError(f"User {user.name} has no eReader email addresses configured")
                return
                
            self.progress = 0.5
            self.message = N_("Checking available formats...")
            
            # Check available formats for sending
            email_share_list = helper.check_send_to_ereader(book)
            if not email_share_list:
                self._handleError(f"No suitable formats available for sending book '{book.title}'")
                return
                
            # Use the first available format (highest priority)
            book_format = email_share_list[0]['format']
            convert_flag = email_share_list[0]['convert']
            
            self.progress = 0.7
            self.message = N_("Sending to eReader...")
            
            # Send to all configured email addresses
            result = helper.send_mail(
                book_id=self.book_id,
                book_format=book_format,
                convert=convert_flag,
                ereader_mail=user.kindle_mail,
                calibrepath=config.get_book_path(),
                user_id=user.name
            )
            
            if result is None:
                # Update download stats
                ub.update_download(self.book_id, int(user.id))
                self.progress = 1.0
                self.message = N_("Auto-send completed successfully")
                self._handleSuccess()
                log.info(f"Auto-sent book '{book.title}' to {user.kindle_mail}")
            else:
                self._handleError(f"Failed to auto-send book '{book.title}': {result}")
                
        except Exception as e:
            self._handleError(f"Auto-send task failed: {str(e)}")
        finally:
            if 'calibre_db_instance' in locals():
                calibre_db_instance.session.close()

    @property
    def name(self):
        return N_("Auto-Send")

    def __str__(self):
        return f"Auto-Send {self.book_title}"

    @property
    def is_cancellable(self):
        return True
