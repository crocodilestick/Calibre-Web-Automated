# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import time
import re

from flask_babel import lazy_gettext as N_

from cps.services.worker import CalibreTask, STAT_CANCELLED, STAT_ENDED
from cps import logger

log = logger.create()


def _get_port():
    port = os.getenv('CWA_PORT_OVERRIDE', '8083')
    try:
        port = str(int(str(port).strip()))
    except Exception:
        port = '8083'
    return port


class TaskConvertLibraryRun(CalibreTask):
    """Lightweight wrapper to surface Convert Library run in Tasks UI.

    It triggers the existing web endpoint and then tails the log for completion,
    updating progress heuristically if counts are present in the log.
    """

    def __init__(self):
        super(TaskConvertLibraryRun, self).__init__(N_(u"Convert Library – full run"))
        self.log_path = "/config/convert-library.log"
        self._finished_marker = "CWA Convert Library Service - Run Ended: "

    def run(self, worker_thread):
        # trigger run via internal route
        try:
            import requests
            url = f"http://127.0.0.1:{_get_port()}/cwa-convert-library-start"
            requests.get(url, timeout=10)
        except Exception as e:
            self._handleError(f"Failed to start Convert Library: {e}")
            return

        # poll log until finished or cancelled
        last_progress = 0.0
        while True:
            # cancellation check
            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                try:
                    import requests
                    url = f"http://127.0.0.1:{_get_port()}/convert-library-cancel"
                    requests.get(url, timeout=5)
                except Exception:
                    pass
                # treat as clean end; UI already shows cancelled/ended state
                return

            # update progress heuristically
            try:
                with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                # finished?
                if self._finished_marker in content:
                    self._handleSuccess()
                    return
                # progress like "12/57" anywhere in log
                matches = re.findall(r"(\d+)/(\d+)", content)
                if matches:
                    cur, total = matches[-1]
                    total_i = max(1, int(total))
                    cur_i = max(0, min(int(cur), total_i))
                    last_progress = max(last_progress, cur_i / float(total_i))
                    # cap below 0.99 until finished marker to avoid flicker
                    self.progress = min(0.99, last_progress)
            except FileNotFoundError:
                # log may not exist yet; keep waiting
                pass
            except Exception:
                # ignore parse errors; keep running
                pass

            time.sleep(0.5)

    @property
    def name(self):
        return N_(u"Convert Library")

    @property
    def is_cancellable(self):
        return True


class TaskEpubFixerRun(CalibreTask):
    """Lightweight wrapper to surface EPUB Fixer run in Tasks UI."""

    def __init__(self):
        super(TaskEpubFixerRun, self).__init__(N_(u"EPUB Fixer – full run"))
        self.log_path = "/config/epub-fixer.log"
        self._finished_marker = "CWA Kindle EPUB Fixer Service - Run Ended: "

    def run(self, worker_thread):
        # trigger run via internal route
        try:
            import requests
            url = f"http://127.0.0.1:{_get_port()}/cwa-epub-fixer-start"
            requests.get(url, timeout=10)
        except Exception as e:
            self._handleError(f"Failed to start EPUB Fixer: {e}")
            return

        last_progress = 0.0
        while True:
            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                try:
                    import requests
                    url = f"http://127.0.0.1:{_get_port()}/epub-fixer-cancel"
                    requests.get(url, timeout=5)
                except Exception:
                    pass
                return

            try:
                with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if self._finished_marker in content:
                    self._handleSuccess()
                    return
                matches = re.findall(r"(\d+)/(\d+)", content)
                if matches:
                    cur, total = matches[-1]
                    total_i = max(1, int(total))
                    cur_i = max(0, min(int(cur), total_i))
                    last_progress = max(last_progress, cur_i / float(total_i))
                    self.progress = min(0.99, last_progress)
            except FileNotFoundError:
                pass
            except Exception:
                pass

            time.sleep(0.5)

    @property
    def name(self):
        return N_(u"EPUB Fixer")

    @property
    def is_cancellable(self):
        return True
