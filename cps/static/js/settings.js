// Consolidated Settings UI Actions (Roadmap-Punkt 2)

// Scoped translator helper to avoid conflict with Underscore.js
function _(text) {
    if (window.settingsTranslations && window.settingsTranslations[text]) {
        return window.settingsTranslations[text];
    }
    return text;
}

$(document).ready(function() {
    // Helper to get root path prefix from current path
    function getPath() {
        var base = window.location.pathname.split('/settings')[0];
        return base || '';
    }

    // Helper to show/hide dynamic success alerts
    function showSuccessAlert($form, message) {
        var alertHtml = '<div class="settings-alert settings-alert-success">' +
            '<span class="glyphicon glyphicon-ok-sign"></span> ' +
            '<span>' + message + '</span>' +
            '</div>';
        $form.prepend(alertHtml);

        setTimeout(function() {
            $form.find('.settings-alert-success').fadeOut(500, function() {
                $(this).remove();
            });
        }, 5000);
    }

    // Helper to show/hide dynamic error alerts
    function showErrorAlert($form, message) {
        var alertHtml = '<div class="settings-alert settings-alert-warning">' +
            '<span class="glyphicon glyphicon-exclamation-sign"></span> ' +
            '<span>' + message + '</span>' +
            '</div>';
        $form.prepend(alertHtml);
    }

    // Reboot Overlay management
    function showRebootOverlay() {
        var overlayHtml = '<div id="reboot-overlay" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(10, 10, 10, 0.85); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); z-index: 9999; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #f8f9fa;">' +
            '<div style="margin-bottom: 20px; display: flex; justify-content: center; align-items: center; width: 60px; height: 60px; border-radius: 50%; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1);">' +
            '<img src="' + getPath() + '/static/css/libs/images/loading-icon.gif" style="width: 24px; height: 24px; filter: invert(1);"/>' +
            '</div>' +
            '<h3 style="margin: 0 0 10px 0; font-weight: 500; font-family: inherit;">' + _('Restarting Server...') + '</h3>' +
            '<p style="margin: 0; color: #909296; font-size: 0.9rem; font-family: inherit;">' + _('Please wait while the application reboots.') + '</p>' +
            '</div>';
        $('body').append(overlayHtml);
    }

    function hideRebootOverlay() {
        $('#reboot-overlay').remove();
    }

    function pollAliveEndpoint(callback) {
        var interval = setInterval(function() {
            $.ajax({
                url: getPath() + "/admin/alive",
                timeout: 2000,
                success: function(data, statusText, xhr) {
                    if (xhr.status < 400) {
                        clearInterval(interval);
                        callback();
                    }
                }
            });
        }, 1500);
    }

    // Intercept form submits for Ajax-based saving
    $('form[id$="-form"]').submit(function(e) {
        e.preventDefault();
        var $form = $(this);
        var actionUrl = $form.attr('action');

        // Show loading state
        var $saveBtn = $form.find('button[type="submit"]');
        var originalBtnText = $saveBtn.html();
        $saveBtn.prop('disabled', true).html('<span class="glyphicon glyphicon-refresh Gly-spin"></span> ' + _('Saving...'));

        // Clear existing alerts in this tab
        $form.find('.settings-alert').remove();

        // Serialize data
        var formData = new FormData($form[0]);

        // Capture and append the clicked button name/value
        if (e.originalEvent && e.originalEvent.submitter) {
            var submitter = e.originalEvent.submitter;
            if (submitter.name) {
                formData.append(submitter.name, submitter.value || 'submit');
            }
        }

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

            var contentType = response.headers.get("content-type");
            if (contentType && contentType.indexOf("application/json") !== -1) {
                return response.json().then(function(json) {
                    return { isJson: true, data: json };
                });
            } else {
                return response.text().then(function(text) {
                    return { isJson: false, data: text };
                });
            }
        })
        .then(function(res) {
            if (!res) return;

            $saveBtn.prop('disabled', false).html(originalBtnText);

            if (res.isJson) {
                var json = res.data;
                // Check if there's any danger/error result in the list
                if (json.result) {
                    var errorMsg = '';
                    json.result.forEach(function(item) {
                        if (item.type === 'danger') {
                            errorMsg += item.message + ' ';
                        }
                    });
                    if (errorMsg) {
                        throw new Error(errorMsg.trim());
                    }
                }

                // Handle reboot flag
                if (json.reboot) {
                    showRebootOverlay();
                    pollAliveEndpoint(function() {
                        hideRebootOverlay();
                        showSuccessAlert($form, _('Settings saved and server restarted successfully.'));
                    });
                    return;
                }
            } else {
                // Parse HTML text for flash errors
                var text = res.data;
                var parser = new DOMParser();
                var doc = parser.parseFromString(text, 'text/html');
                var $dangerAlert = $(doc).find('#flash_danger, .alert-danger');
                if ($dangerAlert.length > 0) {
                    var errMsg = $dangerAlert.first().text().replace(/×/g, '').trim();
                    throw new Error(errMsg || _('An error occurred while saving.'));
                }
            }

            showSuccessAlert($form, _('Settings saved successfully.'));
        })
        .catch(function(error) {
            $saveBtn.prop('disabled', false).html(originalBtnText);
            console.error('Error saving settings:', error);
            showErrorAlert($form, _('Error saving settings: ') + error.message);
        });
    });

    // Universal controller switch toggling (supports checkboxes and select inputs)
    function initializeControlToggles() {
        $('[data-control]').each(function() {
            var $el = $(this);
            var target = $el.data('control');

            function updateVisibility() {
                if ($el.is(':checkbox')) {
                    var isChecked = $el.is(':checked');
                    $('[data-related^="' + target + '"]').each(function() {
                        var rel = $(this).data('related');
                        if (rel === target) {
                            if (isChecked) $(this).slideDown(200);
                            else $(this).slideUp(200);
                        }
                    });
                } else if ($el.is('select')) {
                    var selectedVal = $el.val();
                    $('[data-related^="' + target + '-"]').each(function() {
                        var rel = $(this).data('related');
                        var suffix = rel.replace(target + '-', '');
                        if (suffix === selectedVal) {
                            $(this).slideDown(200);
                        } else {
                            $(this).slideUp(200);
                        }
                    });
                }
            }

            $el.off('change.control').on('change.control', updateVisibility);
            updateVisibility();
        });
    }

    initializeControlToggles();

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
