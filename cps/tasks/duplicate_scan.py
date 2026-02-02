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
from cps.duplicates import find_duplicate_books_python, find_duplicate_candidate_ids_sql
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

            if not self.full_scan:
                last_scanned_book_id = int(cache_data.get('last_scanned_book_id') or 0)
                if last_scanned_book_id == 0:
                    # No baseline yet; fall back to full scan
                    self.full_scan = True

            self.progress = 0.1
            self.message = N_('Scanning for duplicates')

            # Import here to avoid circular dependency during module import
            from cps.duplicates import find_duplicate_books

            if self.stat in (STAT_CANCELLED, STAT_ENDED):
                return

            if self.full_scan:
                duplicate_groups = find_duplicate_books(include_dismissed=False, user_id=self.user_id)
                self.result_count = len(duplicate_groups)
                
                # Store the duplicate groups for passing to auto-resolution
                self.found_duplicate_groups = duplicate_groups

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
                log.info("[cwa-duplicates] Duplicate cache updated (full scan): groups=%s max_book_id=%s",
                         len(all_groups), max_book_id)
            else:
                # Incremental scan: only groups impacted by newly added books
                settings = cwa_db.cwa_settings
                use_title = settings.get('duplicate_detection_title', 1)
                use_author = settings.get('duplicate_detection_author', 1)
                use_language = settings.get('duplicate_detection_language', 1)
                use_series = settings.get('duplicate_detection_series', 0)
                use_publisher = settings.get('duplicate_detection_publisher', 0)
                use_format = settings.get('duplicate_detection_format', 0)

                last_scanned_book_id = int(cache_data.get('last_scanned_book_id') or 0)
                candidate_ids = find_duplicate_candidate_ids_sql(use_title, use_author, user_id=self.user_id,
                                                                min_book_id=last_scanned_book_id)

                if candidate_ids is None:
                    log.warning("[cwa-duplicates] Incremental scan prefilter unavailable; falling back to full scan")
                    print("[cwa-duplicates] Incremental scan prefilter unavailable; falling back to full scan", flush=True)

                    duplicate_groups = find_duplicate_books(include_dismissed=False, user_id=self.user_id)
                    self.result_count = len(duplicate_groups)
                    self.found_duplicate_groups = duplicate_groups

                    all_groups = find_duplicate_books(include_dismissed=True, user_id=self.user_id)

                    max_book_id = 0
                    try:
                        max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                        max_book_id = max_id_result if max_id_result is not None else 0
                    except Exception as ex:
                        log.warning("[cwa-duplicates] Could not get max book ID in TaskDuplicateScan fallback: %s", str(ex))

                    cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)
                    log.info("[cwa-duplicates] Duplicate cache updated (fallback full scan): groups=%s max_book_id=%s",
                             len(all_groups), max_book_id)

                    self.progress = 1
                    self.message = N_('Duplicate scan completed: %(count)s groups', count=self.result_count)
                    self._handleSuccess()

                    log.debug("[cwa-duplicates] Scan complete (fallback). result_count=%s, trigger_type=%s",
                              self.result_count, self.trigger_type)
                    print(f"[cwa-duplicates] Scan complete (fallback): {self.result_count} groups found, trigger_type={self.trigger_type}",
                          flush=True)

                    if self.result_count > 0:
                        try:
                            auto_resolve_enabled = cwa_db.cwa_settings.get('duplicate_auto_resolve_enabled', 0)
                            auto_resolve_strategy = cwa_db.cwa_settings.get('duplicate_auto_resolve_strategy', 'newest')
                            cooldown_minutes = int(cwa_db.cwa_settings.get('duplicate_auto_resolve_cooldown_minutes', 0))

                            log.debug("[cwa-duplicates] Auto-resolution settings: enabled=%s, strategy=%s, cooldown=%s min",
                                      auto_resolve_enabled, auto_resolve_strategy, cooldown_minutes)
                            print(f"[cwa-duplicates] Auto-resolution settings: enabled={auto_resolve_enabled}, "
                                  f"strategy={auto_resolve_strategy}, cooldown={cooldown_minutes} min", flush=True)

                            if auto_resolve_enabled:
                                if cooldown_minutes > 0:
                                    try:
                                        last_resolution = cwa_db.cur.execute("""
                                            SELECT MAX(timestamp) FROM cwa_duplicate_resolutions 
                                            WHERE trigger_type='automatic'
                                        """).fetchone()[0]

                                        if last_resolution:
                                            from datetime import datetime, timedelta
                                            last_time = datetime.fromisoformat(last_resolution)
                                            now = datetime.now()
                                            elapsed = (now - last_time).total_seconds() / 60

                                            if elapsed < cooldown_minutes:
                                                remaining = cooldown_minutes - elapsed
                                                log.info("[cwa-duplicates] Auto-resolution skipped due to cooldown: %.1f minutes remaining",
                                                         remaining)
                                                print(f"[cwa-duplicates] Auto-resolution on cooldown ({remaining:.1f} min remaining)",
                                                      flush=True)
                                                return
                                    except Exception as e:
                                        log.warning("[cwa-duplicates] Cooldown check failed: %s", str(e))

                                log.info("[cwa-duplicates] Auto-resolution enabled, triggering resolution with strategy: %s",
                                         auto_resolve_strategy)
                                print(f"[cwa-duplicates] Auto-resolution enabled, triggering with strategy: {auto_resolve_strategy}",
                                      flush=True)

                                from cps.duplicates import auto_resolve_duplicates

                                groups_to_pass = getattr(self, 'found_duplicate_groups', None)
                                log.debug("[cwa-duplicates] Passing %s groups to auto_resolve (type: %s)",
                                          len(groups_to_pass) if groups_to_pass else 'None', type(groups_to_pass).__name__)
                                print(f"[cwa-duplicates] Passing {len(groups_to_pass) if groups_to_pass else 'None'} pre-scanned groups to auto_resolve",
                                      flush=True)

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
                                    print(f"[cwa-duplicates] Auto-resolution completed: {result['resolved_count']} groups resolved, "
                                          f"{result['deleted_count']} books deleted, {result['kept_count']} books kept", flush=True)

                                    self.message = N_('Duplicate scan completed: %(count)s groups auto-resolved',
                                                      count=result['resolved_count'])
                                else:
                                    log.warning("[cwa-duplicates] Auto-resolution completed with errors: %s",
                                                result.get('errors', []))
                                    print(f"[cwa-duplicates] Auto-resolution errors: {result.get('errors', [])}", flush=True)
                            else:
                                log.debug("[cwa-duplicates] Auto-resolution disabled in settings")
                                print("[cwa-duplicates] Auto-resolution disabled in settings", flush=True)
                        except Exception as ex:
                            log.error("[cwa-duplicates] Exception during auto-resolution check: %s", str(ex))
                            print(f"[cwa-duplicates] Exception during auto-resolution check: {str(ex)}", flush=True)
                    else:
                        log.debug("[cwa-duplicates] No duplicates found, skipping auto-resolution")
                        print("[cwa-duplicates] No duplicates found, skipping auto-resolution", flush=True)
                    return
                
                log.debug("[cwa-duplicates] Incremental scan: last_scanned_book_id=%s, candidate_ids=%s",
                         last_scanned_book_id, len(candidate_ids) if candidate_ids else 0)
                print(f"[cwa-duplicates] Incremental scan: last_scanned_book_id={last_scanned_book_id}, "
                      f"candidates={len(candidate_ids) if candidate_ids else 0}", flush=True)

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
                        log.info("[cwa-duplicates] Incremental scan: no candidates; cache timestamp updated (last_scanned_book_id=%s)",
                                 max_book_id)
                    except Exception:
                        pass
                    self.result_count = 0
                else:
                    # Identify affected groups in cache
                    cached_groups = cache_data.get('duplicate_groups', [])
                    candidate_set = set(candidate_ids)
                    affected_hashes = {
                        group.get('group_hash')
                        for group in cached_groups
                        if group.get('book_ids') and candidate_set.intersection(set(group.get('book_ids')))
                    }

                    # Recompute groups for candidate IDs (include dismissed for cache)
                    recomputed_groups = find_duplicate_books_python(
                        use_title, use_author, use_language, use_series, use_publisher, use_format,
                        include_dismissed=True, user_id=self.user_id, candidate_ids=candidate_ids
                    )

                    # Serialize recomputed groups
                    serialized_groups = []
                    for group in recomputed_groups:
                        serialized_groups.append({
                            'title': group.get('title', ''),
                            'author': group.get('author', ''),
                            'count': group.get('count', 0),
                            'group_hash': group.get('group_hash', ''),
                            'book_ids': [book.id for book in group.get('books', [])]
                        })

                    # Merge cache: remove affected, then append recomputed
                    kept_groups = [g for g in cached_groups if g.get('group_hash') not in affected_hashes]
                    merged_groups = kept_groups + serialized_groups

                    try:
                        import json
                        cwa_db.cur.execute("""
                            UPDATE cwa_duplicate_cache
                            SET scan_timestamp = ?,
                                duplicate_groups_json = ?,
                                total_count = ?,
                                scan_pending = 0,
                                last_scanned_book_id = ?
                            WHERE id = 1
                        """, (datetime.now().isoformat(), json.dumps(merged_groups), len(merged_groups), max_book_id))
                        cwa_db.con.commit()
                        log.info("[cwa-duplicates] Duplicate cache updated (incremental): merged_groups=%s max_book_id=%s",
                                 len(merged_groups), max_book_id)
                    except Exception as ex:
                        log.warning("[cwa-duplicates] Failed to update incremental cache: %s", str(ex))

                    # Result count is unresolved duplicates for this run (exclude dismissed)
                    unresolved_in_candidates = find_duplicate_books_python(
                        use_title, use_author, use_language, use_series, use_publisher, use_format,
                        include_dismissed=False, user_id=self.user_id, candidate_ids=candidate_ids
                    )
                    self.result_count = len(unresolved_in_candidates)
                    
                    # Store the duplicate groups for passing to auto-resolution
                    self.found_duplicate_groups = unresolved_in_candidates
                    
                    log.debug("[cwa-duplicates] Incremental scan result: %s unresolved groups among candidates",
                             self.result_count)
                    print(f"[cwa-duplicates] Incremental scan result: {self.result_count} unresolved duplicate groups", 
                          flush=True)

            self.progress = 1
            if self.full_scan:
                self.message = N_('Duplicate scan completed: %(count)s groups', count=self.result_count)
            else:
                self.message = N_('Duplicate scan completed: %(count)s new groups', count=self.result_count)
            self._handleSuccess()

            # Ensure cache is refreshed for after_import scans so notifications update reliably
            try:
                if self.trigger_type == 'after_import':
                    all_groups = find_duplicate_books(include_dismissed=True, user_id=self.user_id)
                    max_book_id = 0
                    try:
                        max_id_result = calibre_db.session.query(func.max(db.Books.id)).scalar()
                        max_book_id = max_id_result if max_id_result is not None else 0
                    except Exception as ex:
                        log.warning("[cwa-duplicates] Could not get max book ID for after_import cache refresh: %s", str(ex))
                    cwa_db.update_duplicate_cache(all_groups, len(all_groups), max_book_id)
                    log.info("[cwa-duplicates] Cache refreshed after after_import scan: groups=%s max_book_id=%s",
                             len(all_groups), max_book_id)
            except Exception as ex:
                log.warning("[cwa-duplicates] Failed to refresh cache after after_import scan: %s", str(ex))
            
            # Check if auto-resolution is enabled
            log.debug("[cwa-duplicates] Scan complete. result_count=%s, trigger_type=%s", 
                     self.result_count, self.trigger_type)
            print(f"[cwa-duplicates] Scan complete: {self.result_count} groups found, trigger_type={self.trigger_type}", 
                  flush=True)
            
            if self.result_count > 0:  # Only if duplicates were found
                try:
                    auto_resolve_enabled = cwa_db.cwa_settings.get('duplicate_auto_resolve_enabled', 0)
                    auto_resolve_strategy = cwa_db.cwa_settings.get('duplicate_auto_resolve_strategy', 'newest')
                    cooldown_minutes = int(cwa_db.cwa_settings.get('duplicate_auto_resolve_cooldown_minutes', 0))
                    
                    log.debug("[cwa-duplicates] Auto-resolution settings: enabled=%s, strategy=%s, cooldown=%s min",
                             auto_resolve_enabled, auto_resolve_strategy, cooldown_minutes)
                    print(f"[cwa-duplicates] Auto-resolution settings: enabled={auto_resolve_enabled}, "
                          f"strategy={auto_resolve_strategy}, cooldown={cooldown_minutes} min", flush=True)
                    
                    if auto_resolve_enabled:
                        # Check cooldown period
                        if cooldown_minutes > 0:
                            try:
                                last_resolution = cwa_db.cur.execute("""
                                    SELECT MAX(timestamp) FROM cwa_duplicate_resolutions 
                                    WHERE trigger_type='automatic'
                                """).fetchone()[0]
                                
                                if last_resolution:
                                    from datetime import datetime, timedelta
                                    last_time = datetime.fromisoformat(last_resolution)
                                    now = datetime.now()
                                    elapsed = (now - last_time).total_seconds() / 60
                                    
                                    if elapsed < cooldown_minutes:
                                        remaining = cooldown_minutes - elapsed
                                        log.info("[cwa-duplicates] Auto-resolution skipped due to cooldown: %.1f minutes remaining", 
                                                remaining)
                                        print(f"[cwa-duplicates] Auto-resolution on cooldown ({remaining:.1f} min remaining)", 
                                              flush=True)
                                        return
                            except Exception as e:
                                log.warning("[cwa-duplicates] Cooldown check failed: %s", str(e))
                        
                        log.info("[cwa-duplicates] Auto-resolution enabled, triggering resolution with strategy: %s", 
                                auto_resolve_strategy)
                        print(f"[cwa-duplicates] Auto-resolution enabled, triggering with strategy: {auto_resolve_strategy}", 
                              flush=True)
                        
                        from cps.duplicates import auto_resolve_duplicates
                        
                        # Pass the pre-scanned duplicate groups to avoid re-scanning
                        groups_to_pass = getattr(self, 'found_duplicate_groups', None)
                        log.debug("[cwa-duplicates] Passing %s groups to auto_resolve (type: %s)", 
                                 len(groups_to_pass) if groups_to_pass else 'None', type(groups_to_pass).__name__)
                        print(f"[cwa-duplicates] Passing {len(groups_to_pass) if groups_to_pass else 'None'} pre-scanned groups to auto_resolve", 
                              flush=True)
                        
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
                            print(f"[cwa-duplicates] Auto-resolution completed: {result['resolved_count']} groups resolved, "
                                  f"{result['deleted_count']} books deleted, {result['kept_count']} books kept", flush=True)
                            
                            self.message = N_('Duplicate scan completed: %(count)s groups auto-resolved', 
                                            count=result['resolved_count'])
                        else:
                            log.warning("[cwa-duplicates] Auto-resolution completed with errors: %s", 
                                       result.get('errors', []))
                            print(f"[cwa-duplicates] Auto-resolution errors: {result.get('errors', [])}", flush=True)
                    else:
                        log.debug("[cwa-duplicates] Auto-resolution disabled in settings")
                        print("[cwa-duplicates] Auto-resolution disabled in settings", flush=True)
                except Exception as ex:
                    log.error("[cwa-duplicates] Exception during auto-resolution check: %s", str(ex))
                    print(f"[cwa-duplicates] Exception during auto-resolution check: {str(ex)}", flush=True)
            else:
                log.debug("[cwa-duplicates] No duplicates found, skipping auto-resolution")
                print("[cwa-duplicates] No duplicates found, skipping auto-resolution", flush=True)
                    
        except Exception as ex:
            log.error("[cwa-duplicates] Duplicate scan task failed: %s", str(ex))
            self._handleError(str(ex))
        finally:
            try:
                if calibre_db.session is not None:
                    calibre_db.session.close()
            except Exception:
                pass
