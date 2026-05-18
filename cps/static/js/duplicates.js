/* This file is part of the Calibre-Web-Automated (CWA) duplicate management system
 *    Copyright (C) 2024 CWA Contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program. If not, see <http://www.gnu.org/licenses/>.
 */

/* Duplicate book management functionality */

$(document).ready(function() {
    var selectedBooks = [];
    
    // Get CSRF token
    var csrfToken = $('input[name="csrf_token"]').val();
    
    function updateSelectionCount() {
        var count = selectedBooks.length;
        if (count === 0) {
            $('#selection_count').text('0 BOOKS SELECTED');
            $('#delete_selected').addClass('disabled').attr('aria-disabled', true);
            $('.merge-selected-btn').addClass('disabled').attr('aria-disabled', true);
        } else if (count === 1) {
            $('#selection_count').text('1 BOOK SELECTED');
            $('#delete_selected').removeClass('disabled').attr('aria-disabled', false);
            $('.merge-selected-btn').addClass('disabled').attr('aria-disabled', true);
        } else {
            $('#selection_count').text(count + ' BOOKS SELECTED');
            $('#delete_selected').removeClass('disabled').attr('aria-disabled', false);
            $('.merge-selected-btn').removeClass('disabled').attr('aria-disabled', false);
        }
    }
    
    function updateBookItemVisuals() {
        $('.book-item').each(function() {
            var checkbox = $(this).find('.book-checkbox');
            if (checkbox.is(':checked')) {
                $(this).addClass('selected');
            } else {
                $(this).removeClass('selected');
            }
        });
    }

    function escapeHtml(value) {
        return $('<div>').text(value || '').html();
    }

    function showResolutionSuccess(data) {
        $('#success_modal_title').text('Resolution Complete');
        $('#success_modal_message').html(
            '<div class="resolution-success-summary">' +
                '<div class="resolution-success-stat">' +
                    '<span class="resolution-success-value">' + data.resolved_count + '</span>' +
                    '<span class="resolution-success-label">Groups Resolved</span>' +
                '</div>' +
                '<div class="resolution-success-stat">' +
                    '<span class="resolution-success-value">' + data.kept_count + '</span>' +
                    '<span class="resolution-success-label">Books Kept</span>' +
                '</div>' +
                '<div class="resolution-success-stat">' +
                    '<span class="resolution-success-value">' + data.deleted_count + '</span>' +
                    '<span class="resolution-success-label">Books Deleted</span>' +
                '</div>' +
            '</div>'
        );
        $('#success_modal').modal('show');
    }

    function showResolutionError(message) {
        $('#error_modal_title').text('Resolution Failed');
        $('#error_modal_message').html(message);
        $('#error_modal').modal('show');
    }

    function showDuplicateScanError(title, message) {
        $('#error_modal_title').text(title);
        $('#error_modal_message').html(escapeHtml(message));
        $('#error_modal').modal('show');
    }
    
    // Handle individual checkbox changes  
    $(document).on('change', '.book-checkbox', function() {
        var bookId = $(this).val();
        
        if ($(this).is(':checked')) {
            if (selectedBooks.indexOf(bookId) === -1) {
                selectedBooks.push(bookId);
            }
        } else {
            var index = selectedBooks.indexOf(bookId);
            if (index > -1) {
                selectedBooks.splice(index, 1);
            }
        }
        updateSelectionCount();
        updateBookItemVisuals();
    });
    
    // Select All button - intelligently select duplicates to delete
    $('#select_all').click(function() {
        selectedBooks = [];
        
        // For each duplicate group, select all books except the first one
        $('.duplicate-group').each(function() {
            var checkboxes = $(this).find('.book-checkbox');
            
            // Skip the first checkbox (index 0) and check the rest
            checkboxes.each(function(index) {
                if (index > 0) {
                    $(this).prop('checked', true);
                    selectedBooks.push($(this).val());
                } else {
                    // Ensure the first book is unchecked
                    $(this).prop('checked', false);
                }
            });
        });
        
        updateSelectionCount();
        updateBookItemVisuals();
    });
    
    // Select None button
    $('#select_none').click(function() {
        $('.book-checkbox').prop('checked', false);
        selectedBooks = [];
        updateSelectionCount();
        updateBookItemVisuals();
    });
    
    // Merge Selected button (delegated for multiple buttons)
    $(document).on('click', '.merge-selected-btn', function(event) {
        if ($(this).hasClass('disabled')) {
            event.stopPropagation();
        } else {
            // Check if at least 2 books are selected
            if (selectedBooks.length < 2) {
                $('#error_modal_message').text('Please select at least 2 books to merge.');
                $('#error_modal').modal('show');
                return;
            }

            // Use relative URL like table.js to respect base paths
            var relativeUrl = window.location.pathname + "/../ajax/displayselectedbooks";

            $('#merge_selected_modal').modal('show');

            // Convert book IDs to integers (same as table.js)
            var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });

            // Show list of books to be merged (no CSRF - match table.js exactly)
            var ajaxData = {"selections": bookIds};

            $.ajax({
                method: 'post',
                contentType: 'application/json; charset=utf-8',
                dataType: 'json',
                url: relativeUrl,
                data: JSON.stringify(ajaxData),
                beforeSend: function(xhr) {
                    // Add CSRF token as header (like table.js)
                    if (csrfToken) {
                        xhr.setRequestHeader('X-CSRFToken', csrfToken);
                    }
                },
                success: function(response) {
                    $('#display-merge-target-book').empty();
                    $('#display-merge-source-books').empty();

                    // First book is the target (kept)
                    if (response.books && response.books.length > 0) {
                        $("<span>✓ " + response.books[0] + "</span>").appendTo('#display-merge-target-book');

                        // Rest are source books (merged and deleted)
                        for (var i = 1; i < response.books.length; i++) {
                            $("<span>- " + response.books[i] + "</span><p></p>").appendTo('#display-merge-source-books');
                        }
                    }
                },
                error: function(xhr, status, error) {
                    $('#error_modal_message').text('Error loading book list for merge confirmation. Status: ' + xhr.status + '. Check browser console for details.');
                    $('#error_modal').modal('show');
                }
            });
        }
    });

    // Delete Selected button
    $('#delete_selected').click(function(event) {
        if ($(this).hasClass('disabled')) {
            event.stopPropagation();
        } else {
            // Check if any books are actually selected
            if (selectedBooks.length === 0) {
                $('#error_modal_message').text("No books selected! Please select books to delete.");
                $('#error_modal').modal('show');
                return;
            }
            
            // Use relative URL like table.js to respect base paths
            var relativeUrl = window.location.pathname + "/../ajax/displayselectedbooks";
            
            $('#delete_selected_modal').modal('show');
            
            // Convert book IDs to integers (same as table.js)
            var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });
            
            // Show list of books to be deleted (no CSRF - match table.js exactly)
            var ajaxData = {"selections": bookIds};
            
            $.ajax({
                method: "post",
                contentType: "application/json; charset=utf-8",
                dataType: "json",
                url: relativeUrl,
                data: JSON.stringify(ajaxData),
                beforeSend: function(xhr) {
                    // Add CSRF token as header (like table.js)
                    if (csrfToken) {
                        xhr.setRequestHeader('X-CSRFToken', csrfToken);
                    }
                },
                success: function(response) {
                    $('#display-delete-selected-books').empty();
                    $.each(response.books, function(i, item) {
                        $("<span>- " + item + "</span><p></p>").appendTo("#display-delete-selected-books");
                    });
                },
                error: function(xhr, status, error) {
                    $('#error_modal_message').text("Error loading book list for confirmation. Status: " + xhr.status + ". Check browser console for details.");
                    $('#error_modal').modal('show');
                }
            });
        }
    });

    // Confirm merge
    $('#merge_selected_confirm').click(function() {
        var mergeUrl = window.location.pathname + "/../ajax/mergebooks";

        // Convert book IDs to integers (same as table.js)
        var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });

        // First book in array is target, rest are merged into it
        var mergeData = {"Merge_books": bookIds};

        $.ajax({
            method: 'post',
            contentType: 'application/json; charset=utf-8',
            dataType: 'json',
            url: mergeUrl,
            data: JSON.stringify(mergeData),
            beforeSend: function(xhr) {
                // Add CSRF token as header (like table.js)
                if (csrfToken) {
                    xhr.setRequestHeader('X-CSRFToken', csrfToken);
                }
            },
            success: function(response) {
                if (response.success) {
                    // Close the merge confirmation modal
                    $('#merge_selected_modal').modal('hide');

                    // Show success modal
                    $('#success_modal_message').text('Selected books have been merged successfully!');
                    $('#success_modal').modal('show');
                } else {
                    // Close the merge confirmation modal
                    $('#merge_selected_modal').modal('hide');

                    // Show error modal
                    $('#error_modal_message').text('Error: ' + (response.error || 'Unknown error occurred during merge'));
                    $('#error_modal').modal('show');
                }
            },
            error: function(xhr, status, error) {
                // Close the merge confirmation modal
                $('#merge_selected_modal').modal('hide');

                // Show error modal
                $('#error_modal_message').text('An error occurred while merging books. Check browser console for details.');
                $('#error_modal').modal('show');
            }
        });
    });
    
    // Confirm delete
    $('#delete_selected_confirm').click(function() {
        var deleteUrl = window.location.pathname + "/../ajax/deleteselectedbooks";
        
        // Convert book IDs to integers (same as table.js)
        var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });
        
        var deleteData = {"selections": bookIds};
        
        $.ajax({
            method: "post",
            contentType: "application/json; charset=utf-8",
            dataType: "json",
            url: deleteUrl,
            data: JSON.stringify(deleteData),
            beforeSend: function(xhr) {
                // Add CSRF token as header (like table.js)
                if (csrfToken) {
                    xhr.setRequestHeader('X-CSRFToken', csrfToken);
                }
            },
            success: function(response) {
                if (response.success) {
                    // Close the delete confirmation modal
                    $('#delete_selected_modal').modal('hide');
                    
                    // Show success modal
                    $('#success_modal_message').text("Selected duplicate books have been deleted successfully!");
                    $('#success_modal').modal('show');
                } else {
                    // Close the delete confirmation modal
                    $('#delete_selected_modal').modal('hide');
                    
                    // Show error modal
                    $('#error_modal_message').text("Error: " + (response.error || "Unknown error occurred"));
                    $('#error_modal').modal('show');
                }
            },
            error: function(xhr, status, error) {
                // Close the delete confirmation modal
                $('#delete_selected_modal').modal('hide');
                
                // Show error modal
                $('#error_modal_message').text("An error occurred while deleting books. Check browser console for details.");
                $('#error_modal').modal('show');
            }
        });
    });
    
    // Success modal OK button handler
    $('#success_modal_ok').click(function() {
        // Add small delay before reload to allow background cleanup to complete
        // This prevents race conditions with duplicate cache invalidation
        setTimeout(function() {
            window.location.reload();
        }, 800);
    });
    
    // Dismiss/Undismiss duplicate group handlers
    $(document).on('click', '.dismiss-duplicate-btn', function(e) {
        e.preventDefault();
        var btn = $(this);
        var groupHash = btn.data('group-hash');
        var isDismissed = btn.data('dismissed');
        var groupContainer = btn.closest('.duplicate-group');
        
        // Determine action
        var action = isDismissed ? 'undismiss' : 'dismiss';
        var endpoint = '/duplicates/' + action + '/' + groupHash;
        
        // Disable button during request
        btn.prop('disabled', true);
        
        // Make AJAX request
        $.ajax({
            url: endpoint,
            type: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            dataType: 'json',
            success: function(response) {
                if (response.success) {
                    // Update button state
                    if (action === 'dismiss') {
                        btn.data('dismissed', true);
                        btn.html('<span class="glyphicon glyphicon-eye-open"></span> Show');
                        btn.attr('title', 'Show this duplicate group');
                        btn.css('background', 'rgba(46, 204, 113, 0.2)');
                        btn.css('border-color', 'rgba(46, 204, 113, 0.4)');
                        
                        // Fade out the group
                        groupContainer.fadeOut(300);
                    } else {
                        btn.data('dismissed', false);
                        btn.html('<span class="glyphicon glyphicon-eye-close"></span> Dismiss');
                        btn.attr('title', 'Dismiss this duplicate group');
                        btn.css('background', 'rgba(255,255,255,0.15)');
                        btn.css('border-color', 'rgba(255,255,255,0.3)');
                    }
                    
                    // Update badge count in real-time
                    if (window.CWADuplicates && window.CWADuplicates.updateBadge) {
                        window.CWADuplicates.updateBadge(response.count);
                    }
                    
                    // Show success message (optional)
                    console.log('[CWA Duplicates] ' + response.message);
                } else {
                    // Show error
                    alert('Error: ' + response.error);
                }
                
                // Re-enable button
                btn.prop('disabled', false);
            },
            error: function(xhr, status, error) {
                console.error('[CWA Duplicates] Error ' + action + 'ing duplicate group:', error);
                alert('Error: Failed to update duplicate group');
                
                // Re-enable button
                btn.prop('disabled', false);
            }
        });
    });
    
    function showScanNotification(message, alertClass) {
        $('#duplicate_scan_notification').parent().remove();

        var notificationHtml =
            '<div class="row-fluid text-center">' +
                '<div id="duplicate_scan_notification" class="alert ' + alertClass + ' refresh-cwa">' +
                    message +
                    '<button type="button" class="close" data-dismiss="alert" aria-label="Close">' +
                        '<span aria-hidden="true">&times;</span>' +
                    '</button>' +
                '</div>' +
            '</div>';

        $('.navbar').after(notificationHtml);
    }

    var duplicateScanPollTimer = null;
    var duplicateScanTaskId = null;
    var duplicateScanWasActive = false;
    window.CWADuplicateScanActive = false;

    function duplicateScanEndpoint(path) {
        if (typeof getPath === 'function') {
            return getPath() + path;
        }
        return path;
    }

    function parseTaskProgress(task) {
        var progress = parseInt(task.progress, 10);
        if (isNaN(progress)) {
            return 0;
        }
        return Math.max(0, Math.min(100, progress));
    }

    function isDuplicateScanTask(task) {
        if (duplicateScanTaskId && String(task.task_id) === String(duplicateScanTaskId)) {
            return true;
        }
        return String(task.taskMessage || '').toLowerCase().indexOf('duplicate scan') !== -1;
    }

    function isRunningDuplicateScanTask(task) {
        return isDuplicateScanTask(task) && task.stat !== 1 && task.stat !== 3 && task.stat !== 4 && task.stat !== 5;
    }

    function setDuplicateScanNotice(task) {
        var progress = parseTaskProgress(task);
        var message = task.taskMessage || 'Duplicate scan is running in the background.';
        window.CWADuplicateScanActive = true;
        if (window.CWADuplicates && window.CWADuplicates.updateBadge) {
            window.CWADuplicates.updateBadge(0);
        }
        $('#duplicate_index_setup_notice').hide();
        $('#duplicate_results_content').hide();
        $('#no_duplicate_books_message').hide();
        $('#duplicate_scan_results_status').show();
        $('#duplicate_scan_task_title').text('Duplicate scan is running.');
        $('#duplicate_scan_task_message').text(message);
        $('#duplicate_scan_task_progress_container').show();
        $('#duplicate_scan_task_link')
            .attr('href', duplicateScanEndpoint('/tasks'))
            .text('View Background Tasks');
        $('#duplicate_scan_task_progress')
            .addClass('active')
            .css('width', progress + '%')
            .attr('aria-valuenow', progress);
        $('#duplicate_scan_task_progress_label').text(progress + '%');
    }

    function showDuplicateScanFinishedNotice() {
        window.CWADuplicateScanActive = false;
        $('#duplicate_index_setup_notice').hide();
        $('#duplicate_results_content').hide();
        $('#no_duplicate_books_message').hide();
        $('#duplicate_scan_results_status').show();
        $('#duplicate_scan_task_title').text('Duplicate scan is running.');
        $('#duplicate_scan_task_message').text('Duplicate scan finished. Updating results...');
        $('#duplicate_scan_task_progress_container').show();
        $('#duplicate_scan_task_link')
            .attr('href', duplicateScanEndpoint('/tasks'))
            .text('View Background Tasks');
        $('#duplicate_scan_task_progress')
            .removeClass('active')
            .css('width', '100%')
            .attr('aria-valuenow', 100);
        $('#duplicate_scan_task_progress_label').text('100%');
        setTimeout(function() {
            window.location.reload();
        }, 500);
    }

    function showDuplicateResultsAvailableNotice(count) {
        if (duplicateScanWasActive) {
            return;
        }
        if (!$('#no_duplicate_books_message').length) {
            return;
        }
        if ($('#duplicate_scan_results_status').is(':visible')) {
            if ($('#duplicate_scan_task_title').text() === 'Duplicate Books Found') {
                $('#duplicate_scan_task_message').text(
                    'Found ' + count + ' duplicate ' + (count === 1 ? 'group' : 'groups') + '. Refresh the page to review them.'
                );
            }
            return;
        }
        $('#duplicate_results_content').hide();
        $('#no_duplicate_books_message').hide();
        $('#duplicate_scan_results_status').show();
        $('#duplicate_scan_task_title').text('Duplicate Books Found');
        $('#duplicate_scan_task_message').text(
            'Found ' + count + ' duplicate ' + (count === 1 ? 'group' : 'groups') + '. Refresh the page to review them.'
        );
        $('#duplicate_scan_task_progress_container').hide();
        $('#duplicate_scan_task_link')
            .attr('href', window.location.href)
            .text('Refresh Page');
    }

    function pollDuplicateScanTask() {
        $.getJSON(duplicateScanEndpoint('/ajax/emailstat'), function(tasks) {
            var runningTask = null;
            $.each(tasks || [], function(index, task) {
                if (isRunningDuplicateScanTask(task)) {
                    runningTask = task;
                    return false;
                }
            });

            if (runningTask) {
                duplicateScanWasActive = true;
                duplicateScanTaskId = runningTask.task_id;
                setDuplicateScanNotice(runningTask);
                if (!duplicateScanPollTimer) {
                    duplicateScanPollTimer = setInterval(pollDuplicateScanTask, 2000);
                }
            } else if (duplicateScanWasActive) {
                showDuplicateScanFinishedNotice();
                clearInterval(duplicateScanPollTimer);
                duplicateScanPollTimer = null;
            }
        });
    }

    pollDuplicateScanTask();

    document.addEventListener('cwa:duplicates-status', function(event) {
        var data = event.detail || {};
        if (data.count > 0 && !data.needs_scan && !data.needs_full_scan) {
            showDuplicateResultsAvailableNotice(Number(data.count || 0));
        }
    });

    // Manual scan trigger
    $('#trigger_scan').on('click', function() {
        var btn = $(this);
        btn.prop('disabled', true);
        btn.html('<span class="glyphicon glyphicon-refresh glyphicon-spin"></span> Scanning...');
        
        $.ajax({
            url: duplicateScanEndpoint('/duplicates/trigger-scan'),
            type: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            dataType: 'json',
            success: function(response) {
                if (response.success) {
                    if (response.queued === true) {
                        duplicateScanTaskId = response.task_id || null;
                        duplicateScanWasActive = true;
                        setDuplicateScanNotice({
                            taskMessage: 'Duplicate scan is queued.',
                            progress: '0 %',
                            task_id: duplicateScanTaskId,
                            stat: 0
                        });
                        if (!duplicateScanPollTimer) {
                            duplicateScanPollTimer = setInterval(pollDuplicateScanTask, 2000);
                        }
                        pollDuplicateScanTask();
                        return;
                    }
                    if (response.queued === false && response.fallback_reason) {
                        console.warn('[CWA Duplicates] Background queue failed, fallback used:', response.fallback_reason);
                    }
                    var count = (response.count !== undefined && response.count !== null)
                        ? response.count
                        : null;
                    var message = count !== null
                        ? 'Scan completed. Found ' + count + ' duplicate groups.'
                        : 'Scan completed.';
                    showScanNotification(message, 'alert-success');
                    setTimeout(function() {
                        location.reload();
                    }, 800);
                } else {
                    showScanNotification('Scan failed: ' + response.error, 'alert-danger');
                }
            },
            error: function(xhr, status, error) {
                console.error('[CWA Duplicates] Error triggering scan:', error);
                var response = xhr.responseJSON || {};
                if (xhr.status === 409 && response.blocked) {
                    showDuplicateScanError(
                        'Duplicate Scan Blocked',
                        response.message || 'Import is in progress. Run a full duplicate scan after ingest finishes.'
                    );
                } else {
                    showScanNotification('Error: Failed to trigger duplicate scan', 'alert-danger');
                }
            },
            complete: function() {
                btn.prop('disabled', false);
                btn.html('<span class="glyphicon glyphicon-refresh"></span> Scan for Duplicates Now');
            }
        });
    });
    
    // Auto-resolution preview
    $('#preview_resolution').on('click', function() {
        var strategy = $('#resolution_strategy').val();
        var btn = $(this);
        btn.prop('disabled', true);
        btn.html('<span class="glyphicon glyphicon-refresh glyphicon-spin"></span> Loading...');
        
        $.ajax({
            url: '/duplicates/preview-resolution',
            method: 'POST',
            contentType: 'application/json',
            headers: {
                'X-CSRFToken': csrfToken
            },
            data: JSON.stringify({ strategy: strategy }),
            success: function(data) {
                if (data.success && data.preview) {
                    showResolutionPreview(data);
                    $('#execute_resolution').removeClass('disabled').prop('aria-disabled', false);
                } else {
                    alert('Error generating preview: ' + (data.errors || []).join(', '));
                }
            },
            error: function() {
                alert('Failed to generate preview');
            },
            complete: function() {
                btn.prop('disabled', false);
                btn.html('<span class="glyphicon glyphicon-eye-open"></span> Preview');
            }
        });
    });
    
    // Execute resolution
    $('#execute_resolution').on('click', function() {
        if ($(this).hasClass('disabled')) return;

        $('#execute_resolution_strategy_name').text($('#resolution_strategy option:selected').text());
        $('#execute_resolution_modal').modal('show');
    });

    $('#execute_resolution_confirm').on('click', function() {
        var strategy = $('#resolution_strategy').val();
        var btn = $('#execute_resolution');
        btn.addClass('disabled').html('<span class="glyphicon glyphicon-refresh glyphicon-spin"></span> Executing...');
        
        $.ajax({
            url: '/duplicates/execute-resolution',
            method: 'POST',
            contentType: 'application/json',
            headers: {
                'X-CSRFToken': csrfToken
            },
            data: JSON.stringify({ strategy: strategy }),
            success: function(data) {
                if (data.success) {
                    showResolutionSuccess(data);
                } else {
                    var errors = data.errors || ['Unknown error occurred during resolution'];
                    showResolutionError('Errors occurred:<br>' + errors.map(escapeHtml).join('<br>'));
                    btn.removeClass('disabled').html('<span class="glyphicon glyphicon-flash"></span> Execute Resolution');
                }
            },
            error: function(xhr, status, error) {
                console.error('[CWA Duplicates] Failed to execute resolution:', error);
                var response = xhr.responseJSON || {};
                showResolutionError(response.message || response.error || 'Failed to execute resolution. Check browser console for details.');
                btn.removeClass('disabled').html('<span class="glyphicon glyphicon-flash"></span> Execute Resolution');
            }
        });
    });
    
    function showResolutionPreview(data) {
        var html = '<div style="margin-bottom: 20px; padding: 15px; background: #6d6d6d66; border-left: 4px solid #4caf50; border-radius: 4px; color: white">' +
            '<h4 style="color: #98f99c; margin-top: 0;">Summary</h4>' +
            '<p><strong>Groups to resolve:</strong> ' + data.resolved_count + '</p>' +
            '<p><strong>Books to keep:</strong> ' + data.kept_count + '</p>' +
            '<p><strong>Books to delete:</strong> ' + data.deleted_count + '</p>' +
            '</div>';
        
        if (data.preview && data.preview.length > 0) {
            html += '<div style="margin-top: 20px;"><h4>Preview:</h4>';
            
            data.preview.forEach(function(group) {
                html += '<div style="padding: 15px; border: none; border-radius: 6px; background: #6d6d6d66;">' +
                    '<h5 style="color: white; margin-top: 0;">' + escapeHtml(group.title) + ' <small>by ' + escapeHtml(group.author) + '</small></h5>' +
                    '<div style="margin-bottom: 15px; padding: 10px; background: #d4edda; border-left: 3px solid #28a745; border-radius: 4px; color: #1c2832">' +
                    '<strong style="color: #155724;">✓ KEEP:</strong> Book ID ' + group.kept_book_id + ' ' +
                    '<small style="color: #666;">(Added: ' + group.kept_book_timestamp + ', Formats: ' + group.kept_book_formats.join(', ') + ')</small>' +
                    '</div>' +
                    '<div style="padding: 10px; background: #f8d7da; border-left: 3px solid #dc3545; border-radius: 4px;">' +
                    '<strong style="color: #721c24;">✗ DELETE:</strong>' +
                    '<ul style="margin: 5px 0 0 20px; padding: 0; color: #1c2832">';
                
                group.deleted_books_info.forEach(function(book) {
                    html += '<li style="margin: 5px 0;">' +
                        'Book ID ' + book.id + ' ' +
                        '<small style="color: #666;">(Added: ' + book.timestamp + ', Formats: ' + book.formats.join(', ') + ')</small>' +
                        '</li>';
                });
                
                html += '</ul></div></div>';
            });
            
            html += '</div>';
        }
        
        $('#resolution_preview_body').html(html);
        $('#resolution_preview_modal').modal('show');
    }
    
    function escapeHtml(text) {
        var map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, function(m) { return map[m]; });
    }
    
    // Initialize
    updateSelectionCount();
    updateBookItemVisuals();
});
