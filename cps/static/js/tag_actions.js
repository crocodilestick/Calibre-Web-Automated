/* Calibre-Web Automated – fork of Calibre-Web
Copyright (C) 2018-2026 Calibre-Web contributors
Copyright (C) 2024-2026 Calibre-Web Automated contributors
SPDX-License-Identifier: GPL-3.0-or-later
See CONTRIBUTORS for full list of authors.
 */

// Rename, merge and delete tags from the Tags list (editors only).
// The CSRF header is added to every POST by the $.ajaxSetup in main.js.

(function() {
    var $strings = $("#tag-actions-strings");
    if (!$strings.length) {
        return;
    }

    function fill(template, name, count) {
        return String(template).split("{name}").join(name).split("{count}").join(count);
    }

    function errorMessage(xhr) {
        var json = xhr && xhr.responseJSON;
        if (json && json.error && json.error.message) {
            return json.error.message;
        }
        return $strings.attr("data-error");
    }

    function postTag(url, payload) {
        return $.ajax({
            method: "post",
            url: url,
            contentType: "application/json; charset=utf-8",
            dataType: "json",
            data: JSON.stringify(payload || {})
        });
    }

    function sendRename(url, name, merge) {
        postTag(url, {name: name, merge: merge === true})
            .done(function() {
                location.reload();
            })
            .fail(function(xhr) {
                var conflict = xhr.status === 409 && xhr.responseJSON && xhr.responseJSON.error &&
                    xhr.responseJSON.error.conflict;
                if (conflict && merge !== true) {
                    if (window.confirm(fill($strings.attr("data-merge-confirm"), conflict.name, conflict.count))) {
                        sendRename(url, name, true);
                    }
                    return;
                }
                window.alert(errorMessage(xhr));
            });
    }

    $(document).on("click", ".tag-rename", function(e) {
        e.preventDefault();
        e.stopPropagation();
        var $btn = $(this);
        var current = String($btn.attr("data-name"));
        var name = window.prompt(fill($strings.attr("data-rename-prompt"), current, $btn.attr("data-count")), current);
        if (name === null) {
            return;
        }
        name = name.trim();
        if (!name || name === current) {
            return;
        }
        sendRename($btn.attr("data-url"), name, false);
    });

    $(document).on("click", ".tag-delete", function(e) {
        e.preventDefault();
        e.stopPropagation();
        var $btn = $(this);
        if (!window.confirm(fill($strings.attr("data-delete-confirm"), String($btn.attr("data-name")), $btn.attr("data-count")))) {
            return;
        }
        postTag($btn.attr("data-url"))
            .done(function() {
                location.reload();
            })
            .fail(function(xhr) {
                window.alert(errorMessage(xhr));
            });
    });
})();
