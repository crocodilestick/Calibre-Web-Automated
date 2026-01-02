# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import datetime

from . import config, constants
from .services.background_scheduler import BackgroundScheduler, CronTrigger, use_APScheduler, DateTrigger
from .tasks.database import TaskReconnectDatabase
from .tasks.clean import TaskClean
from .tasks.thumbnail import TaskGenerateCoverThumbnails, TaskGenerateSeriesThumbnails, TaskClearCoverThumbnailCache
from .tasks.thumbnail_migration import check_and_migrate_thumbnails
from .services.worker import WorkerThread
from .tasks.metadata_backup import TaskBackupMetadata

def get_scheduled_tasks(reconnect=True):
    tasks = list()
    # Reconnect Calibre database (metadata.db) based on config.schedule_reconnect
    if reconnect:
        tasks.append([lambda: TaskReconnectDatabase(), 'reconnect', False])

    # Delete temp folder
    tasks.append([lambda: TaskClean(), 'delete temp', True])

    # Generate metadata.opf file for each changed book
    if config.schedule_metadata_backup:
        tasks.append([lambda: TaskBackupMetadata("en"), 'backup metadata', False])

    # Generate all missing book cover thumbnails
    if config.schedule_generate_book_covers:
        tasks.append([lambda: TaskClearCoverThumbnailCache(0), 'delete superfluous book covers', True])
        tasks.append([lambda: TaskGenerateCoverThumbnails(), 'generate book covers', False])

    # Generate all missing series thumbnails
    if config.schedule_generate_series_covers:
        tasks.append([lambda: TaskGenerateSeriesThumbnails(), 'generate book covers', False])

    return tasks


def end_scheduled_tasks():
    worker = WorkerThread.get_instance()
    for __, __, __, task, __ in worker.tasks:
        if task.scheduled and task.is_cancellable:
            worker.end_task(task.id)


def register_scheduled_tasks(reconnect=True):
    scheduler = BackgroundScheduler()

    if scheduler:
        # Remove all existing jobs
        scheduler.remove_all_jobs()

        start = config.schedule_start_time
        duration = config.schedule_duration

        # Register scheduled tasks
        timezone_info = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
        scheduler.schedule_tasks(tasks=get_scheduled_tasks(reconnect), trigger=CronTrigger(hour=start,
                                                                                           timezone=timezone_info))
        end_time = calclulate_end_time(start, duration)
        scheduler.schedule(func=end_scheduled_tasks, trigger=CronTrigger(hour=end_time.hour, minute=end_time.minute,
                                                                         timezone=timezone_info),
                           name="end scheduled task")

        # Kick-off tasks, if they should currently be running
        if should_task_be_running(start, duration):
            scheduler.schedule_tasks_immediately(tasks=get_scheduled_tasks(reconnect))


def register_startup_tasks():
    scheduler = BackgroundScheduler()

    if scheduler:
        start = config.schedule_start_time
        duration = config.schedule_duration

        # Run thumbnail migration on startup (one-time operation)
        try:
            check_and_migrate_thumbnails()
        except Exception as ex:
            # Don't let migration failures stop the application
            pass

        # Rehydrate scheduled auto-send jobs from cwa.db (if any)
        try:
            import sys as _sys
            if '/app/calibre-web-automated/scripts/' not in _sys.path:
                _sys.path.insert(1, '/app/calibre-web-automated/scripts/')
            from cwa_db import CWA_DB
            from .tasks.auto_send import TaskAutoSend
            from .services.worker import WorkerThread
            from datetime import datetime, timezone

            db = CWA_DB()
            delay_minutes = int(db.cwa_settings.get('auto_send_delay_minutes', 0) or 0)
            pending = db.scheduled_get_pending_autosend()
            for row in pending:
                try:
                    # Parse UTC run time, convert to local naive for DateTrigger
                    run_at_utc = datetime.fromisoformat(row['run_at_utc'].replace('Z', '+00:00'))
                    run_at_local = run_at_utc.astimezone().replace(tzinfo=None)
                    username = row.get('username') or 'System'
                    title = row.get('title') or 'Book'
                    book_id = int(row['book_id']) if row.get('book_id') is not None else None
                    user_id = int(row['user_id']) if row.get('user_id') is not None else None
                    schedule_id = int(row['id'])

                    def _rehydrate_enqueue(uid=user_id, bid=book_id, u=username, t=title, sid=schedule_id):
                        # Mark dispatched and enqueue the task only if state moved from scheduled
                        should_enqueue = False
                        try:
                            should_enqueue = bool(CWA_DB().scheduled_mark_dispatched(int(sid)))
                        except Exception:
                            pass
                        if should_enqueue and bid is not None and uid is not None:
                            WorkerThread.add(u, TaskAutoSend(f"Auto-sending '{t}' to user's eReader(s)", bid, uid, delay_minutes), hidden=False)

                    job = scheduler.schedule(func=_rehydrate_enqueue, trigger=DateTrigger(run_date=run_at_local), name=f"rehydrated auto-send {schedule_id}")
                    try:
                        if job is not None:
                            db.scheduled_update_job_id(schedule_id, str(job.id))
                    except Exception:
                        pass
                except Exception:
                    # Never break startup on rehydration issues
                    pass
        except Exception:
            # If scripts not available or table missing, skip
            pass

        # Rehydrate other scheduled ops (convert_library, epub_fixer)
        try:
            import sys as _sys
            if '/app/calibre-web-automated/scripts/' not in _sys.path:
                _sys.path.insert(1, '/app/calibre-web-automated/scripts/')
            from cwa_db import CWA_DB
            from datetime import datetime
            # wrappers will trigger internal routes themselves
            from .tasks.ops import TaskConvertLibraryRun, TaskEpubFixerRun

            db = CWA_DB()
            for job_type in ('convert_library', 'epub_fixer'):
                try:
                    rows = db.scheduled_get_pending_by_type(job_type)
                except Exception:
                    rows = []
                for row in rows:
                    try:
                        run_at_utc = datetime.fromisoformat(row['run_at_utc'].replace('Z', '+00:00'))
                        run_at_local = run_at_utc.astimezone().replace(tzinfo=None)
                        schedule_id = int(row['id'])
                        username = row.get('username') or 'System'

                        def _rehydrate_trigger(sid=schedule_id, jt=job_type, u=username):
                            should_run = False
                            try:
                                should_run = bool(CWA_DB().scheduled_mark_dispatched(int(sid)))
                            except Exception:
                                pass
                            if not should_run:
                                return
                            if jt == 'convert_library':
                                WorkerThread.add(u, TaskConvertLibraryRun(), hidden=False)
                            elif jt == 'epub_fixer':
                                WorkerThread.add(u, TaskEpubFixerRun(), hidden=False)

                        job = scheduler.schedule(func=_rehydrate_trigger, trigger=DateTrigger(run_date=run_at_local), name=f"rehydrated {job_type} {schedule_id}")
                        try:
                            if job is not None:
                                db.scheduled_update_job_id(schedule_id, str(job.id))
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass

        # Run scheduled tasks immediately for development and testing
        # Ignore tasks that should currently be running, as these will be added when registering scheduled tasks
        if constants.APP_MODE in ['development', 'test'] and not should_task_be_running(start, duration):
            scheduler.schedule_tasks_immediately(tasks=get_scheduled_tasks(False))
        else:
            scheduler.schedule_tasks_immediately(tasks=[[lambda: TaskClean(), 'delete temp', True]])


def should_task_be_running(start, duration):
    now = datetime.datetime.now()
    start_time = datetime.datetime.now().replace(hour=start, minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=duration // 60, minutes=duration % 60)
    return start_time < now < end_time


def calclulate_end_time(start, duration):
    start_time = datetime.datetime.now().replace(hour=start, minute=0)
    return start_time + datetime.timedelta(hours=duration // 60, minutes=duration % 60)
