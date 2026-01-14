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
            $('#selection_count').text('');
            $('#delete_selected').addClass('disabled').attr('aria-disabled', true);
            $('#merge_selected').addClass('disabled').attr('aria-disabled', true);
        } else if (count === 1) {
            $('#selection_count').text(count + ' book selected');
            $('#delete_selected').removeClass('disabled').attr('aria-disabled', false);
            // Need at least 2 books to merge
            $('#merge_selected').addClass('disabled').attr('aria-disabled', true);
        } else {
            $('#selection_count').text(count + ' books selected');
            $('#delete_selected').removeClass('disabled').attr('aria-disabled', false);
            $('#merge_selected').removeClass('disabled').attr('aria-disabled', false);
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
    
    // Merge Selected button
    $('#merge_selected').click(function(event) {
        if ($(this).hasClass('disabled')) {
            event.stopPropagation();
        } else {
            // Check if at least 2 books are selected
            if (selectedBooks.length < 2) {
                $('#error_modal_message').text("Please select at least 2 books to merge.");
                $('#error_modal').modal('show');
                return;
            }
            
            // Use absolute URL like working table.js
            var relativeUrl = "/ajax/displayselectedbooks";
            
            $('#merge_selected_modal').modal('show');
            
            // Convert book IDs to integers (same as table.js)
            var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });
            
            // Show list of books to be merged (no CSRF - match table.js exactly)
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
                    $('#display-merge-target-book').empty();
                    $('#display-merge-source-books').empty();
                    
                    // First book is the target (kept)
                    if (response.books && response.books.length > 0) {
                        $("<span>✓ " + response.books[0] + "</span>").appendTo("#display-merge-target-book");
                        
                        // Rest are source books (merged and deleted)
                        for (var i = 1; i < response.books.length; i++) {
                            $("<span>- " + response.books[i] + "</span><p></p>").appendTo("#display-merge-source-books");
                        }
                    }
                },
                error: function(xhr, status, error) {
                    $('#error_modal_message').text("Error loading book list for merge confirmation. Status: " + xhr.status + ". Check browser console for details.");
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
            
            // Use absolute URL like working table.js
            var relativeUrl = "/ajax/displayselectedbooks";
            
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
        var mergeUrl = "/ajax/mergebooks";
        
        // Convert book IDs to integers (same as table.js)
        var bookIds = selectedBooks.map(function(id) { return parseInt(id, 10); });
        
        // First book in array is target, rest are merged into it
        var mergeData = {"Merge_books": bookIds};
        
        $.ajax({
            method: "post",
            contentType: "application/json; charset=utf-8",
            dataType: "json",
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
                    $('#success_modal_message').text("Selected books have been merged successfully!");
                    $('#success_modal').modal('show');
                } else {
                    // Close the merge confirmation modal
                    $('#merge_selected_modal').modal('hide');
                    
                    // Show error modal
                    $('#error_modal_message').text("Error: " + (response.error || "Unknown error occurred during merge"));
                    $('#error_modal').modal('show');
                }
            },
            error: function(xhr, status, error) {
                // Close the merge confirmation modal
                $('#merge_selected_modal').modal('hide');
                
                // Show error modal
                $('#error_modal_message').text("An error occurred while merging books. Check browser console for details.");
                $('#error_modal').modal('show');
            }
        });
    });
    
    // Confirm delete
    $('#delete_selected_confirm').click(function() {
        var deleteUrl = "/ajax/deleteselectedbooks";
        
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
        // Reload the page to refresh the duplicate list
        window.location.reload();
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
    
    // Initialize
    updateSelectionCount();
    updateBookItemVisuals();
}); 