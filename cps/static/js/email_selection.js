/**
 * Email Selection functionality for selective eReader sending
 * Handles both modal and redirect scenarios
 */

$(document).ready(function() {
    var currentBookId = null;

    // Function to show page-level flash message (same as handleResponse in details.js)
    function showPageFlashMessage(message, type) {
        // Remove any existing flash messages (same as handleResponse)
        $(".row-fluid.text-center").remove();
        $("#flash_danger").remove();
        $("#flash_success").remove();
        
        // Use same logic as handleResponse function
        var alertType = type === 'error' ? 'danger' : type;
        $(".navbar").after('<div class="row-fluid text-center">' +
            '<div id="flash_' + alertType + '" class="alert alert-' + alertType + '">' + message + '</div>' +
            '</div>');
    }

    // Store book ID when modal is shown
    $('#emailSelectModal').on('show.bs.modal', function (e) {
        var button = $(e.relatedTarget); // Button that triggered the modal
        currentBookId = button.data('book-id');
    });

    // Handle send button click in email selection modal
    $('#sendSelectedBtn').click(function() {
        var selectedEmails = [];
        $('input[name="selected_emails"]:checked').each(function() {
            selectedEmails.push($(this).val());
        });

        if (selectedEmails.length === 0) {
            showPageFlashMessage('Please select at least one email address', 'error');
            return;
        }

        var formatSelect = $('select[name="format_selection"]');
        var selectedFormat = formatSelect.val();
        var convertFlag = formatSelect.find(':selected').data('convert');
        
        // Disable send button to prevent double-clicking
        $(this).prop('disabled', true);

        // Send AJAX request to endpoint
        $.ajax({
            url: '/send_selected/' + currentBookId,
            method: 'POST',
            data: {
                'csrf_token': $('input[name="csrf_token"]').val(),
                'selected_emails': selectedEmails.join(','),
                'book_format': selectedFormat,
                'convert': convertFlag
            },
            success: function(response) {
                if (response.length > 0) {
                    var messageType = response[0].type === 'success' ? 'success' : 'error';
                    showPageFlashMessage(response[0].message, messageType);
                    
                    // Close modal immediately after successful send
                    if (response[0].type === 'success') {
                        $('#emailSelectModal').modal('hide');
                    }
                } else {
                    showPageFlashMessage('Unknown error occurred', 'error');
                }
            },
            error: function() {
                showPageFlashMessage('Error sending email', 'error');
            },
            complete: function() {
                // Re-enable send button
                $('#sendSelectedBtn').prop('disabled', false);
            }
        });
    });

    // Handle select all/none functionality
    $('#selectAllEmails').change(function() {
        $('input[name="selected_emails"]').prop('checked', this.checked);
    });

    // Update select all checkbox when individual checkboxes change
    $('input[name="selected_emails"]').change(function() {
        var totalCheckboxes = $('input[name="selected_emails"]').length;
        var checkedCheckboxes = $('input[name="selected_emails"]:checked').length;
        $('#selectAllEmails').prop('checked', totalCheckboxes === checkedCheckboxes);
    });
});