/**
 * Email Selection functionality for selective eReader sending
 * Handles both modal and redirect scenarios
 */

$(document).ready(function() {
    var currentBookId = null;

    // Email validation function
    function isValidEmail(email) {
        // More comprehensive email validation
        var emailRegex = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
        return emailRegex.test(email) && email.length <= 254; // RFC 5322 length limit
    }

    // Function to show validation message in modal
    function showModalValidation(message) {
        // Check if the validation message element exists, if not recreate it
        if ($('#modal-validation-message').length === 0) {
            // Recreate the validation message element
            var validationHtml = '<div id="modal-validation-message" class="alert alert-danger text-center">' +
                                '<button type="button" class="close" data-dismiss="alert" aria-label="Close">' +
                                '<span aria-hidden="true">&times;</span>' +
                                '</button>' +
                                '<span id="validation-message-text"></span>' +
                                '</div>';
            
            // Insert at the beginning of modal body
            $('#emailSelectModal .modal-body').prepend(validationHtml);
        }
        
        $('#validation-message-text').text(message);
        $('#modal-validation-message').show();
    }

    // Function to hide validation message in modal
    function hideModalValidation() {
        $('#modal-validation-message').hide();
    }

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
        hideModalValidation(); // Clear any previous validation messages
    });
    
    // Clear custom emails and validation when modal is hidden
    $('#emailSelectModal').on('hidden.bs.modal', function () {
        $('#custom_emails').val('');
        hideModalValidation();
    });

    // Handle send button click in email selection modal
    $('#sendSelectedBtn').click(function() {
        var $sendBtn = $(this); // Store button reference
        var selectedEmails = [];
        
        // Clear any previous validation messages
        hideModalValidation();
        
        // Get checked email addresses from list
        $('input[name="selected_emails"]:checked').each(function() {
            selectedEmails.push($(this).val());
        });
        
        // Get custom email addresses from textarea
        var customEmails = $('#custom_emails').val().trim();
        var hasInvalidEmail = false;
        
        if (customEmails) {
            // Split by comma and clean up each email
            var customEmailList = customEmails.split(',');
            for (var i = 0; i < customEmailList.length; i++) {
                var cleanEmail = customEmailList[i].trim();
                if (cleanEmail && isValidEmail(cleanEmail)) {
                    selectedEmails.push(cleanEmail);
                } else if (cleanEmail) {
                    showModalValidation('Invalid email address: ' + cleanEmail);
                    hasInvalidEmail = true;
                    break;
                }
            }
        }
        
        if (hasInvalidEmail) {
            return;
        }

        if (selectedEmails.length === 0) {
            showModalValidation('Please select at least one email address or enter valid custom email addresses');
            return;
        }

        var formatSelect = $('select[name="format_selection"]');
        var selectedFormat = formatSelect.val();
        var convertFlag = formatSelect.find(':selected').data('convert');
        
        // Disable send button to prevent double-clicking
        $sendBtn.prop('disabled', true);

        // Send AJAX request to endpoint
        $.ajax({
            url: getPath() + '/send_selected/' + currentBookId,
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
                $sendBtn.prop('disabled', false);
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