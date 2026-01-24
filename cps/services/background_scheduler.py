# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import atexit
import threading

from .. import logger
from .worker import WorkerThread

try:
    from apscheduler.schedulers.background import BackgroundScheduler as BScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    use_APScheduler = True
except (ImportError, RuntimeError) as e:
    use_APScheduler = False
    log = logger.create()
    log.info('APScheduler not found. Unable to schedule tasks.')


class BackgroundScheduler:
    _instance = None

    def __new__(cls):
        if not use_APScheduler:
            return False

        if cls._instance is None:
            cls._instance = super(BackgroundScheduler, cls).__new__(cls)
            cls.log = logger.create()
            logger.logging.getLogger('tzlocal').setLevel(logger.logging.WARNING)
            cls.scheduler = BScheduler()
            cls.scheduler.start()
            cls._schedule_lock = threading.Lock()  # Prevent concurrent task scheduling

        return cls._instance

    def schedule(self, func, trigger, name=None):
        if use_APScheduler:
            return self.scheduler.add_job(func=func, trigger=trigger, name=name)

    def remove_job(self, job_id: str):
        if use_APScheduler and job_id:
            try:
                return self.scheduler.remove_job(job_id)
            except Exception:
                # Ignore if job not found
                return None

    # Expects a lambda expression for the task
    def schedule_task(self, task, user=None, name=None, hidden=False, trigger=None):
        if use_APScheduler:
            def scheduled_task():
                worker_task = task()
                worker_task.scheduled = True
                WorkerThread.add(user, worker_task, hidden=hidden)
            return self.schedule(func=scheduled_task, trigger=trigger, name=name)

    # Expects a list of lambda expressions for the tasks
    def schedule_tasks(self, tasks, user=None, trigger=None):
        if use_APScheduler:
            for task in tasks:
                self.schedule_task(task[0], user=user, trigger=trigger, name=task[1], hidden=task[2])

    # Expects a lambda expression for the task
    def schedule_task_immediately(self, task, user=None, name=None, hidden=False):
        if use_APScheduler:
            def immediate_task():
                WorkerThread.add(user, task(), hidden)
            return self.schedule(func=immediate_task, trigger=DateTrigger(), name=name)

    # Expects a list of lambda expressions for the tasks
    def schedule_tasks_immediately(self, tasks, user=None):
        if use_APScheduler:
            # Use lock to prevent "Set changed size during iteration" when tasks are scheduled simultaneously
            with self._schedule_lock:
                for task in tasks:
                    self.schedule_task_immediately(task[0], user, name="immediately " + task[1], hidden=task[2])

    # Remove all jobs
    def remove_all_jobs(self):
        self.scheduler.remove_all_jobs()
