/* Calibre-Web Automated – Modern Duplicates Notification System
 * Copyright (C) 2024-2025 Calibre-Web Automated contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

(function() {
    'use strict';
    
    const STORAGE_KEY = 'cwa_duplicates_notification_shown';
    // Removed automatic polling - badge updates only on cache invalidation events
    
    let currentDuplicateCount = 0;
    
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
        return fetch('/duplicates/status', {
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
    
    /**
     * Show the notification modal
     */
    function showNotificationModal(data) {
        const { count, preview } = data;
        
        // Don't show if already shown this session
        if (wasNotificationShown()) {
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
            previewList.innerHTML = preview.map(item => `
                <li class="duplicate-preview-item">
                    <strong>${escapeHtml(item.title)}</strong>
                    <small>${escapeHtml(item.author)} - ${item.count} copies</small>
                </li>
            `).join('');
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
                
                // Mark as shown
                markNotificationShown();
            }, 500);
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
        
        // Fetch initial status once on page load
        // No periodic updates - badge refreshes after ingest operations only
        fetchDuplicateStatus().then(data => {
            if (data.success) {
                // Update badge
                updateBadge(data.count);
                
                // Show notification modal if there are duplicates and notifications are enabled
                if (data.count > 0 && data.enabled) {
                    showNotificationModal(data);
                }
            }
        });
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
