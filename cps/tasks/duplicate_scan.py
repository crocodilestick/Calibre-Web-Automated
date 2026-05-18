# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
from datetime import datetime
from sqlalchemy import func
from flask_babel import lazy_gettext as N_

from cps import calibre_db, db, logger
from cps.duplicate_index import (
    MAX_INCREMENTAL_BOOK_IDS,
    get_duplicate_groups_from_index,
    has_valid_duplicate_index_baseline,
    ingest_batch_follow_up_pending,
    mark_duplicate_index_pending,
    merge_affected_groups_into_cache,
    rebuild_duplicate_index,
)
from cps.services.worker import CalibreTask, STAT_CANCELLED, STAT_ENDED
from cps.ub import init_db_thread

# Access CWA DB (scripts path)
if '/app/calibre-web-automated/scripts/' not in sys.path:
    sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()


class TaskDuplicateScan(CalibreTask):
    def __init__(self, full_scan=True, task_message=None, trigger_type='manual', user_id=None, book_ids=None):
        super(TaskDuplicateScan, self).__init__(task_message or N_('Duplicate scan'))
        self.full_scan = full_scan
        self.trigger_type = trigger_type
        self.result_count = 0
        self.user_id = user_id
        self.book_ids = []
        for book_id in book_ids or []:
            try:
                parsed_book_id = int(book_id)
            except (TypeError, ValueError):
                continue
            if parsed_book_id > 0:
                self.book_ids.append(parsed_book_id)

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

            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                return

            if self.full_scan and self.trigger_type != 'manual' and ingest_batch_follow_up_pending():
                self.result_count = 0
                self.found_duplicate_groups = []
                self.progress = 1
                self.message = N_('Duplicate scan skipped: import in progress')
                self._handleSuccess()
                log.info("[cwa-duplicates] Full duplicate scan skipped because ingest is active")
                return

            if self.full_scan:
                settings = cwa_db.cwa_settings
                self.progress = 0.05
                self.message = N_('Building duplicate index')

                def update_rebuild_progress(processed, total):
                    if self.stat in (STAT_CANCELLED, STAT_ENDED):
                        return
                    if total:
                        self.progress = 0.05 + (0.75 * (processed / total))
                        self.message = N_(
                            'Building duplicate index: %(processed)s/%(total)s books',
                            processed=processed,
                            total=total,
                        )
                    else:
                        self.progress = 0.8
                        self.message = N_('Building duplicate index: no books')

                rebuild_metadata = rebuild_duplicate_index(settings, progress_callback=update_rebuild_progress)
                self.progress = 0.85
                self.message = N_('Finding duplicate groups')
                duplicate_groups = get_duplicate_groups_from_index(
                    settings,
                    include_dismissed=False,
                    user_id=self.user_id,
                )
                self.result_count = len(duplicate_groups)

                # Store the duplicate groups for passing to auto-resolution
                self.found_duplicate_groups = duplicate_groups

                if self.stat in (STAT_CANCELLED, STAT_ENDED):
                    return

                # Update cache with full results (including dismissed groups)
                self.progress = 0.95
                self.message = N_('Updating duplicate cache')
                all_groups = get_duplicate_groups_from_index(settings, include_dismissed=True)
                max_book_id = rebuild_metadata.get('max_book_id', 0)
                cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)
                log.info("[cwa-duplicates] Duplicate cache updated (full scan): groups=%s max_book_id=%s",
                         len(all_groups), max_book_id)
            else:
                # Incremental after-import work must stay bounded to changed candidate groups.
                settings = cwa_db.cwa_settings
                last_scanned_book_id = int(cache_data.get('last_scanned_book_id') or 0)
                if self.book_ids:
                    candidate_ids = list(dict.fromkeys(self.book_ids))
                else:
                    candidate_ids = [
                        int(row[0])
                        for row in (
                            calibre_db.session.query(db.Books.id)
                            .filter(db.Books.id > last_scanned_book_id)
                            .order_by(db.Books.id)
                            .limit(MAX_INCREMENTAL_BOOK_IDS + 1)
                            .all()
                        )
                        if row[0] is not None
                    ]
                    if len(candidate_ids) > MAX_INCREMENTAL_BOOK_IDS:
                        mark_duplicate_index_pending("after_import incremental book set too large")
                        self.result_count = 0
                        self.found_duplicate_groups = []
                        self.progress = 1
                        self.message = N_('Duplicate scan pending: manual scan required')
                        self._handleSuccess()
                        log.info("[cwa-duplicates] After-import duplicate scan marked pending: too many new books")
                        return

                if not has_valid_duplicate_index_baseline(settings, candidate_book_ids=candidate_ids):
                    mark_duplicate_index_pending("after_import without valid duplicate index baseline")
                    self.result_count = 0
                    self.found_duplicate_groups = []
                    self.progress = 1
                    self.message = N_('Duplicate scan pending: manual scan required')
                    self._handleSuccess()
                    log.info("[cwa-duplicates] After-import duplicate scan marked pending: no valid baseline")
                    return

                log.debug("[cwa-duplicates] Incremental scan: last_scanned_book_id=%s, candidate_ids=%s",
                         last_scanned_book_id, len(candidate_ids) if candidate_ids else 0)

                max_book_id = 0
                try:
                    max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                    max_book_id = max_id_result if max_id_result is not None else 0
                except Exception as ex:
                    log.warning("[cwa-duplicates] Could not get max book ID in TaskDuplicateScan: %s", str(ex))

                if not candidate_ids:
                    # No impacted groups; just bump last_scanned_book_id
                    try:
                        cwa_db.cur.execute("""
                            UPDATE cwa_duplicate_cache
                            SET last_scanned_book_id = ?, scan_pending = 0, scan_timestamp = ?
                            WHERE id = 1
                        """, (max_book_id, datetime.now().isoformat()))
                        cwa_db.con.commit()
                        log.info(
                            "[cwa-duplicates] Incremental scan: no candidates; cache timestamp updated "
                            "(last_scanned_book_id=%s)",
                            max_book_id,
                        )
                    except Exception:
                        pass
                    self.result_count = 0
                else:
                    try:
                        merge_result = merge_affected_groups_into_cache(candidate_ids, settings)
                    except Exception as ex:
                        mark_duplicate_index_pending("after_import incremental duplicate merge failed")
                        self.result_count = 0
                        self.found_duplicate_groups = []
                        self.progress = 1
                        self.message = N_('Duplicate scan pending: manual scan required')
                        self._handleSuccess()
                        log.warning("[cwa-duplicates] Failed to update incremental duplicate index cache: %s", str(ex))
                        return

                    if merge_result.get("pending"):
                        self.result_count = 0
                        self.found_duplicate_groups = []
                        self.progress = 1
                        self.message = N_('Duplicate scan pending: manual scan required')
                        self._handleSuccess()
                        log.info("[cwa-duplicates] Incremental duplicate merge marked pending: %s",
                                 merge_result.get("reason", "unknown"))
                        return

                    unresolved_in_candidates = get_duplicate_groups_from_index(
                        settings,
                        include_dismissed=False,
                        user_id=self.user_id,
                        candidate_book_ids=candidate_ids,
                    )
                    self.result_count = len(unresolved_in_candidates)
                    self.found_duplicate_groups = unresolved_in_candidates
                    log.debug("[cwa-duplicates] Incremental scan result: %s unresolved groups among candidates",
                             self.result_count)

            self.progress = 1
            if self.full_scan:
                self.message = N_('Duplicate scan completed: %(count)s groups', count=self.result_count)
            else:
                self.message = N_('Duplicate scan completed: %(count)s new groups', count=self.result_count)
            self._handleSuccess()

            # Check if auto-resolution is enabled
            log.debug("[cwa-duplicates] Scan complete. result_count=%s, trigger_type=%s",
                     self.result_count, self.trigger_type)

            if self.result_count > 0:  # Only if duplicates were found
                try:
                    auto_resolve_enabled = cwa_db.cwa_settings.get('duplicate_auto_resolve_enabled', 0)
                    auto_resolve_strategy = cwa_db.cwa_settings.get('duplicate_auto_resolve_strategy', 'newest')
                    cooldown_minutes = int(cwa_db.cwa_settings.get('duplicate_auto_resolve_cooldown_minutes', 0))

                    log.debug("[cwa-duplicates] Auto-resolution settings: enabled=%s, strategy=%s, cooldown=%s min",
                             auto_resolve_enabled, auto_resolve_strategy, cooldown_minutes)

                    if auto_resolve_enabled:
                        # Check cooldown period
                        if cooldown_minutes > 0:
                            try:
                                last_resolution = cwa_db.cur.execute("""
                                    SELECT MAX(timestamp) FROM cwa_duplicate_resolutions
                                    WHERE trigger_type='automatic'
                                """).fetchone()[0]

                                if last_resolution:
                                    last_time = datetime.fromisoformat(last_resolution)
                                    now = datetime.now()
                                    elapsed = (now - last_time).total_seconds() / 60

                                    if elapsed < cooldown_minutes:
                                        remaining = cooldown_minutes - elapsed
                                        log.info("[cwa-duplicates] Auto-resolution skipped due to cooldown: %.1f minutes remaining",
                                                remaining)
                                        return
                            except Exception as e:
                                log.warning("[cwa-duplicates] Cooldown check failed: %s", str(e))

                        log.info("[cwa-duplicates] Auto-resolution enabled, triggering resolution with strategy: %s",
                                auto_resolve_strategy)

                        from cps.duplicates import auto_resolve_duplicates

                        # Pass the pre-scanned duplicate groups to avoid re-scanning
                        groups_to_pass = getattr(self, 'found_duplicate_groups', None)
                        log.debug("[cwa-duplicates] Passing %s groups to auto_resolve (type: %s)",
                                 len(groups_to_pass) if groups_to_pass else 'None', type(groups_to_pass).__name__)

                        result = auto_resolve_duplicates(
                            strategy=auto_resolve_strategy,
                            dry_run=False,
                            user_id=None,
                            trigger_type='automatic',
                            duplicate_groups=groups_to_pass
                        )

                        if result['success']:
                            log.info("[cwa-duplicates] Auto-resolution completed: resolved=%s, kept=%s, deleted=%s",
                                    result['resolved_count'], result['kept_count'], result['deleted_count'])

                            self.message = N_('Duplicate scan completed: %(count)s groups auto-resolved',
                                            count=result['resolved_count'])
                        else:
                            log.warning("[cwa-duplicates] Auto-resolution completed with errors: %s",
                                       result.get('errors', []))
                    else:
                        log.debug("[cwa-duplicates] Auto-resolution disabled in settings")
                except Exception as ex:
                    log.error("[cwa-duplicates] Exception during auto-resolution check: %s", str(ex))
            else:
                log.debug("[cwa-duplicates] No duplicates found, skipping auto-resolution")

        except Exception as ex:
            log.error("[cwa-duplicates] Duplicate scan task failed: %s", str(ex))
            self._handleError(str(ex))
        finally:
            try:
                if calibre_db.session is not None:
                    calibre_db.session.close()
            except Exception:
                pass
