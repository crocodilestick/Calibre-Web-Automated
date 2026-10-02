"""Regression tests for background worker task cleanup."""

import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase

from cps.services.worker import QueuedTask, TASK_CLEANUP_TRIGGER, WorkerThread


class WorkerCleanupTest(TestCase):
    def test_cancelled_task_without_end_time_does_not_crash_cleanup(self):
        worker = object.__new__(WorkerThread)
        worker.doLock = threading.Lock()
        now = datetime.now()
        worker.dequeued = [
            QueuedTask(index, "test", now, SimpleNamespace(
                dead=True, end_time=now + timedelta(seconds=index)
            ), False)
            for index in range(TASK_CLEANUP_TRIGGER + 1)
        ]
        cancelled = SimpleNamespace(dead=True, end_time=None)
        worker.dequeued.append(QueuedTask(999, "test", now, cancelled, False))

        worker.cleanup_tasks()

        self.assertEqual(TASK_CLEANUP_TRIGGER, len(worker.dequeued))
        self.assertTrue(all(item.task is not cancelled for item in worker.dequeued))
