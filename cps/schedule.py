# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import datetime

from . import config, constants, helper
from .services.background_scheduler import BackgroundScheduler, CronTrigger, IntervalTrigger, use_APScheduler, DateTrigger
from .tasks.database import TaskReconnectDatabase, TaskCleanArchivedBooks
from .tasks.clean import TaskClean
from .tasks.thumbnail import TaskGenerateCoverThumbnails, TaskGenerateSeriesThumbnails, TaskClearCoverThumbnailCache
from .tasks.thumbnail_migration import check_and_migrate_thumbnails
from .services.worker import WorkerThread
from .tasks.metadata_backup import TaskBackupMetadata
from .tasks.auto_hardcover_id import TaskAutoHardcoverID

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
        _schedule_duplicate_scan(scheduler, timezone_info)
        end_time = calclulate_end_time(start, duration)
        scheduler.schedule(func=end_scheduled_tasks, trigger=CronTrigger(hour=end_time.hour, minute=end_time.minute,
                                                                         timezone=timezone_info),
                           name="end scheduled task")

        _schedule_hardcover_auto_fetch(scheduler, timezone_info)
        _schedule_archived_book_cleanup(scheduler, timezone_info)

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


def _schedule_duplicate_scan(scheduler, timezone_info):
    """Schedule background duplicate scan based on CWA settings."""
    try:
        import sys as _sys
        if '/app/calibre-web-automated/scripts/' not in _sys.path:
            _sys.path.insert(1, '/app/calibre-web-automated/scripts/')
        from cwa_db import CWA_DB
        from .tasks.duplicate_scan import TaskDuplicateScan
        from apscheduler.triggers.cron import CronTrigger

        db = CWA_DB()
        enabled = bool(db.cwa_settings.get('duplicate_scan_enabled', 0))
        cron_expr = (db.cwa_settings.get('duplicate_scan_cron') or '').strip()

        if not enabled:
            return

        if cron_expr:
            trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone_info)
        else:
            # manual/after_import handled elsewhere
            return

        scheduler.schedule_task(lambda: TaskDuplicateScan(full_scan=True, trigger_type='scheduled'),
                                user='System', trigger=trigger, name='duplicate scan', hidden=False)
    except Exception:
        # Scheduling is best-effort; never block startup
        pass


def _schedule_hardcover_auto_fetch(scheduler, timezone_info):
    """Schedule background Hardcover auto-fetch based on CWA settings."""
    try:
        import sys as _sys
        if '/app/calibre-web-automated/scripts/' not in _sys.path:
            _sys.path.insert(1, '/app/calibre-web-automated/scripts/')
        from cwa_db import CWA_DB
        from .tasks.auto_hardcover_id import TaskAutoHardcoverID

        db = CWA_DB()
        cwa_settings = db.get_cwa_settings()
        
        # Check if enabled and token available
        enabled = bool(cwa_settings.get('hardcover_auto_fetch_enabled', False))
        token_available = bool(
            getattr(config, "config_hardcover_token", None) or
            helper.get_secret("HARDCOVER_TOKEN")
        )
        
        if not enabled or not token_available:
            return

        schedule_type = cwa_settings.get('hardcover_auto_fetch_schedule', 'weekly')
        schedule_day = cwa_settings.get('hardcover_auto_fetch_schedule_day', 'sunday')
        schedule_hour = int(cwa_settings.get('hardcover_auto_fetch_schedule_hour', 2))
        min_confidence = float(cwa_settings.get('hardcover_auto_fetch_min_confidence', 0.85))
        batch_size = int(cwa_settings.get('hardcover_auto_fetch_batch_size', 50))
        rate_limit = float(cwa_settings.get('hardcover_auto_fetch_rate_limit', 5.0))
        
        # Create lambda that returns task instance with configured settings
        task_lambda = lambda: TaskAutoHardcoverID(
            min_confidence=min_confidence,
            batch_size=batch_size,
            rate_limit_delay=rate_limit
        )
        
        # Map day names to APScheduler format
        day_map = {
            'monday': 'mon', 'tuesday': 'tue', 'wednesday': 'wed',
            'thursday': 'thu', 'friday': 'fri', 'saturday': 'sat', 'sunday': 'sun'
        }
        
        # Determine trigger based on schedule type
        trigger = None
        name = "hardcover auto-fetch"
        
        if schedule_type == '15min':
            trigger = IntervalTrigger(minutes=15, timezone=timezone_info)
        elif schedule_type == '30min':
            trigger = IntervalTrigger(minutes=30, timezone=timezone_info)
        elif schedule_type == '1hour':
            trigger = IntervalTrigger(hours=1, timezone=timezone_info)
        elif schedule_type == '2hours':
            trigger = IntervalTrigger(hours=2, timezone=timezone_info)
        elif schedule_type == '4hours':
            trigger = IntervalTrigger(hours=4, timezone=timezone_info)
        elif schedule_type == '6hours':
            trigger = IntervalTrigger(hours=6, timezone=timezone_info)
        elif schedule_type == '12hours':
            trigger = IntervalTrigger(hours=12, timezone=timezone_info)
        elif schedule_type == 'daily':
            trigger = CronTrigger(hour=schedule_hour, minute=0, timezone=timezone_info)
        elif schedule_type == 'weekly':
            day_abbr = day_map.get(schedule_day.lower(), 'sun')
            trigger = CronTrigger(day_of_week=day_abbr, hour=schedule_hour, minute=0, timezone=timezone_info)
        elif schedule_type == 'monthly':
            # For monthly, schedule_day contains day of month (1-28)
            try:
                day_of_month = int(schedule_day) if str(schedule_day).isdigit() else 1
                day_of_month = max(1, min(28, day_of_month))  # Clamp to 1-28
            except (ValueError, TypeError):
                day_of_month = 1
            trigger = CronTrigger(day=day_of_month, hour=schedule_hour, minute=0, timezone=timezone_info)
        
        if trigger:
            scheduler.schedule_task(task_lambda, user='System', trigger=trigger, name=name, hidden=False)
    except Exception:
        # Scheduling is best-effort; never block startup
        pass


def _schedule_archived_book_cleanup(scheduler, timezone_info):
    """Schedule cleanup for stale archived_book entries (default 03:00 local)."""
    try:
        import sys as _sys
        if '/app/calibre-web-automated/scripts/' not in _sys.path:
            _sys.path.insert(1, '/app/calibre-web-automated/scripts/')
        from cwa_db import CWA_DB

        db = CWA_DB()
        cwa_settings = db.get_cwa_settings()

        enabled = bool(cwa_settings.get('archived_cleanup_enabled', True))
        if not enabled:
            return

        schedule_type = (cwa_settings.get('archived_cleanup_schedule') or 'daily').strip().lower()
        schedule_day = (cwa_settings.get('archived_cleanup_schedule_day') or 'sunday')
        schedule_hour = int(cwa_settings.get('archived_cleanup_schedule_hour', 3))

        day_map = {
            'monday': 'mon', 'tuesday': 'tue', 'wednesday': 'wed',
            'thursday': 'thu', 'friday': 'fri', 'saturday': 'sat', 'sunday': 'sun'
        }

        trigger = None
        name = 'clean archived book references'

        if schedule_type == '15min':
            trigger = IntervalTrigger(minutes=15, timezone=timezone_info)
        elif schedule_type == '30min':
            trigger = IntervalTrigger(minutes=30, timezone=timezone_info)
        elif schedule_type == '1hour':
            trigger = IntervalTrigger(hours=1, timezone=timezone_info)
        elif schedule_type == '2hours':
            trigger = IntervalTrigger(hours=2, timezone=timezone_info)
        elif schedule_type == '4hours':
            trigger = IntervalTrigger(hours=4, timezone=timezone_info)
        elif schedule_type == '6hours':
            trigger = IntervalTrigger(hours=6, timezone=timezone_info)
        elif schedule_type == '12hours':
            trigger = IntervalTrigger(hours=12, timezone=timezone_info)
        elif schedule_type == 'daily':
            trigger = CronTrigger(hour=schedule_hour, minute=0, timezone=timezone_info)
        elif schedule_type == 'weekly':
            day_abbr = day_map.get(str(schedule_day).lower(), 'sun')
            trigger = CronTrigger(day_of_week=day_abbr, hour=schedule_hour, minute=0, timezone=timezone_info)
        elif schedule_type == 'monthly':
            try:
                day_of_month = int(schedule_day) if str(schedule_day).isdigit() else 1
                day_of_month = max(1, min(28, day_of_month))
            except (ValueError, TypeError):
                day_of_month = 1
            trigger = CronTrigger(day=day_of_month, hour=schedule_hour, minute=0, timezone=timezone_info)

        if trigger:
            scheduler.schedule_task(lambda: TaskCleanArchivedBooks(), user='System',
                                    trigger=trigger, name=name, hidden=True)
    except Exception:
        # Scheduling is best-effort; never block startup
        pass
