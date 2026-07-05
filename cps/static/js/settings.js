// Consolidated Settings UI Actions (Roadmap-Punkt 2)

$(document).ready(function() {
    // Intercept form submits for Ajax-based saving
    $('form[id$="-form"]').submit(function(e) {
        e.preventDefault();
        var $form = $(this);
        var formId = $form.attr('id');
        var actionUrl = $form.attr('action');

        // Show loading state
        var $saveBtn = $form.find('button[type="submit"]');
        var originalBtnText = $saveBtn.html();
        $saveBtn.prop('disabled', true).html('<span class="glyphicon glyphicon-refresh Gly-spin"></span> ' + _('Saving...'));

        // Clear existing alerts in this tab
        $form.find('.settings-alert').remove();

        // Serialize data
        var formData = new FormData($form[0]);

        // Submit via Fetch
        fetch(actionUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(function(response) {
            // Check redirect (e.g. if authentication expired)
            if (response.redirected) {
                window.location.href = response.url;
                return;
            }

            if (!response.ok) {
                throw new Error(_('HTTP error! status: ') + response.status);
            }
            return response.text();
        })
        .then(function(responseText) {
            // Parse response as HTML to check for flash errors
            if (responseText) {
                var parser = new DOMParser();
                var doc = parser.parseFromString(responseText, 'text/html');
                var $dangerAlert = $(doc).find('#flash_danger, .alert-danger');
                if ($dangerAlert.length > 0) {
                    var errMsg = $dangerAlert.first().text().replace(/×/g, '').trim();
                    throw new Error(errMsg || _('An error occurred while saving.'));
                }
            }

            // Restore button state
            $saveBtn.prop('disabled', false).html(originalBtnText);

            // Create a success banner
            var alertHtml = '<div class="settings-alert settings-alert-success">' +
                '<span class="glyphicon glyphicon-ok-sign"></span> ' +
                '<span>' + _('Settings saved successfully.') + '</span>' +
                '</div>';
            $form.prepend(alertHtml);

            // Auto-dismiss alert after 5 seconds
            setTimeout(function() {
                $form.find('.settings-alert-success').fadeOut(500, function() {
                    $(this).remove();
                });
            }, 5000);
        })
        .catch(function(error) {
            $saveBtn.prop('disabled', false).html(originalBtnText);
            console.error('Error saving settings:', error);

            var alertHtml = '<div class="settings-alert settings-alert-warning">' +
                '<span class="glyphicon glyphicon-exclamation-sign"></span> ' +
                '<span>' + _('Error saving settings: ') + error.message + '</span>' +
                '</div>';
            $form.prepend(alertHtml);
        });
    });

    // Toggle description helper blocks
    $('.settings-switch input').change(function() {
        var isChecked = $(this).is(':checked');
        var controlId = $(this).attr('data-control');
        if (controlId) {
            if (isChecked) {
                $('[data-related="' + controlId + '"]').slideDown(200);
            } else {
                $('[data-related="' + controlId + '"]').slideUp(200);
            }
        }
    });

    // Collapsible sections
    $('.collapsible-trigger').click(function() {
        var targetId = $(this).attr('data-target');
        var $content = $('#' + targetId);
        var isExpanded = $content.hasClass('expanded');

        if (isExpanded) {
            $content.removeClass('expanded').css('max-height', '0px');
            $(this).find('.glyphicon').removeClass('glyphicon-chevron-down').addClass('glyphicon-chevron-right');
        } else {
            $content.addClass('expanded').css('max-height', $content[0].scrollHeight + 'px');
            $(this).find('.glyphicon').removeClass('glyphicon-chevron-right').addClass('glyphicon-chevron-down');
        }
    });
});
