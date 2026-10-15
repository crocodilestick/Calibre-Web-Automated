/* Calibre-Web Automated – Modern Duplicates Notification System
 * Copyright (C) 2024-2025 Calibre-Web Automated contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

(function() {
    'use strict';
    
    const STORAGE_KEY = 'cwa_duplicates_notification_shown';
    const LAST_COUNT_KEY = 'cwa_duplicates_last_count';
    // Status is only polled while a duplicate refresh is pending (its results are
    // about to change). Otherwise: once per page load, on returning to the tab,
    // and a slow refresh for tabs left open. Each request opens cwa.db, so the
    // old unconditional 2.5s poll from every open tab added real load (#1288).
    const POLL_INTERVAL_MS = 5000;
    const POLL_MAX_ATTEMPTS = 60; // ~5 minutes
    const FOCUS_MIN_INTERVAL_MS = 30000;
    const BACKGROUND_REFRESH_MS = 5 * 60 * 1000;
    
    let currentDuplicateCount = 0;
    let pollAttempts = 0;
    let pollTimer = null;
    let lastFetchAt = 0;
    let lastPreviewSignature = '';
    
    /**
     * Check if notification was already shown in this session
     */
    function wasNotificationShown() {
        return sessionStorage.getItem(STORAGE_KEY) === 'true';
    }
    
    /**
     * Mark notification as shown for this session
     */
    function markNotificationShown() {
        sessionStorage.setItem(STORAGE_KEY, 'true');
    }

    function getLastNotifiedCount() {
        const val = sessionStorage.getItem(LAST_COUNT_KEY);
        const parsed = parseInt(val, 10);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function setLastNotifiedCount(count) {
        sessionStorage.setItem(LAST_COUNT_KEY, String(count || 0));
    }
    
    /**
     * Update the duplicate count badge in sidebar
     */
    function updateBadge(count) {
        currentDuplicateCount = count;
        const badge = document.getElementById('duplicate-count-badge');
        
        if (badge) {
            if (count > 0) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
    }
    
    /**
     * Fetch duplicate status from API
     */
    function fetchDuplicateStatus() {
        lastFetchAt = Date.now();
        const basePath = (typeof getPath === 'function') ? getPath() : '';
        const statusUrl = basePath + '/duplicates/status';
        return fetch(statusUrl, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin'
        })
        .then(response => response.json())
        .catch(error => {
            console.error('[CWA Duplicates] Error fetching status:', error);
            return { success: false, count: 0, preview: [], enabled: false };
        });
    }

    function startStatusPolling() {
        if (pollTimer) {
            return;
        }
        if (isModalActive()) {
            return;
        }
        pollAttempts = 0;
        pollTimer = setInterval(() => {
            pollAttempts += 1;
            fetchDuplicateStatus().then(handleStatusResponse);
            if (pollAttempts >= POLL_MAX_ATTEMPTS) {
                stopStatusPolling();
            }
        }, POLL_INTERVAL_MS);
    }

    function stopStatusPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function isModalActive() {
        const modal = document.getElementById('duplicate-notification-modal');
        return modal && modal.classList.contains('active');
    }

    function isDuplicatesPage() {
        return window.location.pathname.replace(/\/+$/, '').endsWith('/duplicates');
    }
    
    /**
     * Show the notification modal
     */
    function showNotificationModal(data) {
        const { count, preview } = data;

        if (isModalActive()) {
            return;
        }
        
        const lastCount = getLastNotifiedCount();
        if (wasNotificationShown() && count <= lastCount) {
            return;
        }
        
        // Update count in modal
        const countBadge = document.getElementById('duplicate-notification-count');
        if (countBadge) {
            countBadge.textContent = count;
        }
        
        // Update preview list
        const previewList = document.getElementById('duplicate-notification-preview');
        if (previewList && preview && preview.length > 0) {
            const signature = preview.map(item => `${item.title}|${item.author}|${item.count}`).join('||');
            if (signature !== lastPreviewSignature) {
                lastPreviewSignature = signature;
                previewList.innerHTML = preview.map(item => `
                    <li class="duplicate-preview-item">
                        <strong>${escapeHtml(item.title)}</strong>
                        <small>${escapeHtml(item.author)} - ${item.count} copies</small>
                    </li>
                `).join('');
            }
        }
        
        // Show modal and backdrop
        const modal = document.getElementById('duplicate-notification-modal');
        const backdrop = document.getElementById('duplicate-notification-backdrop');
        
        if (modal && backdrop) {
            // Small delay for smooth animation
            setTimeout(() => {
                backdrop.classList.add('active');
                modal.classList.add('active');

                // Focus trap
                modal.focus();

                // Mark as shown and store count
                markNotificationShown();
                setLastNotifiedCount(count);
            }, 500);
        }
    }

    function handleStatusResponse(data) {
        if (!data || !data.success) {
            return;
        }

        if (!window.CWADuplicateScanActive) {
            updateBadge(data.count);
        }
        document.dispatchEvent(new CustomEvent('cwa:duplicates-status', { detail: data }));

        if (isModalActive()) {
            return;
        }

        if (data.count > 0 && data.enabled && !isDuplicatesPage()) {
            showNotificationModal(data);
            if (isModalActive()) {
                return;
            }
        }

        // A pending refresh (e.g. after an import) will change the results soon.
        // A full scan only starts when someone triggers it, so there is nothing to wait for.
        const refreshPending = data.stale && !data.needs_full_scan;
        if ((refreshPending || window.CWADuplicateScanActive) && !isModalActive()) {
            startStatusPolling();
        } else {
            stopStatusPolling();
        }
    }
    
    /**
     * Hide the notification modal
     */
    function hideNotificationModal() {
        const modal = document.getElementById('duplicate-notification-modal');
        const backdrop = document.getElementById('duplicate-notification-backdrop');
        
        if (modal && backdrop) {
            modal.classList.remove('active');
            backdrop.classList.remove('active');
        }
    }
    
    /**
     * Escape HTML to prevent XSS
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Initialize event listeners
     */
    function initializeEventListeners() {
        // Close button
        const closeBtn = document.getElementById('duplicate-notification-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', hideNotificationModal);
        }
        
        // Remind me later button
        const remindBtn = document.getElementById('duplicate-notification-remind');
        if (remindBtn) {
            remindBtn.addEventListener('click', hideNotificationModal);
        }
        
        // Click outside to close
        const backdrop = document.getElementById('duplicate-notification-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', hideNotificationModal);
        }
        
        // Escape key to close
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                hideNotificationModal();
            }
        });
    }
    
    /**
     * Main initialization function
     */
    function init() {
        // Check if user has permission (admin or edit)
        const userHasPermission = document.getElementById('duplicate-notification-modal');
        if (!userHasPermission) {
            return; // Modal not rendered, user doesn't have permission
        }
        
        // Initialize event listeners
        initializeEventListeners();
        
        // The page ships the current status; only fetch if it didn't
        const bootstrapData = window.cwaDuplicateBootstrap;
        if (bootstrapData && typeof bootstrapData === 'object' && Object.keys(bootstrapData).length) {
            handleStatusResponse({
                success: true,
                enabled: !!bootstrapData.enabled,
                count: Number(bootstrapData.count || 0),
                preview: bootstrapData.preview || [],
                cached: !!bootstrapData.cached,
                stale: !!bootstrapData.stale,
                needs_scan: !!bootstrapData.stale
            });
        } else {
            fetchDuplicateStatus().then(handleStatusResponse);
        }

        document.addEventListener('visibilitychange', function() {
            if (!document.hidden && Date.now() - lastFetchAt >= FOCUS_MIN_INTERVAL_MS) {
                fetchDuplicateStatus().then(handleStatusResponse);
            }
        });

        setInterval(function() {
            if (!document.hidden && !pollTimer && Date.now() - lastFetchAt >= BACKGROUND_REFRESH_MS) {
                fetchDuplicateStatus().then(handleStatusResponse);
            }
        }, BACKGROUND_REFRESH_MS);
    }
    
    // Expose functions globally for use by other scripts
    window.CWADuplicates = {
        updateBadge: updateBadge,
        fetchStatus: fetchDuplicateStatus,
        hideModal: hideNotificationModal
    };
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
})();
