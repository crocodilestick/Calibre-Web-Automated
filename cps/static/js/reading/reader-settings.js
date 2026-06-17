/* global $, calibre */
// Per-user web-reader display settings.
//
// Settings (theme, font, fontSize, spread, reflow, margin) used to live only
// in this browser's localStorage, so they didn't follow the reader to a phone
// or another browser. This module makes the server the source of truth for
// signed-in users: the page is rendered with the saved settings in
// window.calibre.readerSettings, and every change is persisted to BOTH
// localStorage (instant, offline, anonymous fallback) AND the server
// (debounced POST to /ajax/readersettings, signed-in only). See web.py
// save_reader_settings() + view_settings['reader'].
//
// Exposes window.ReaderSettings.{get,set,isAuthenticated}. Loaded before
// epub.js so the reader restore + the settings-modal handlers can use it.
(function () {
    "use strict";

    var LS_PREFIX = "calibre.reader.";
    var INT_KEYS = { fontSize: true, margin: true };
    var BOOL_KEYS = { reflow: true };

    var server = (typeof calibre === "object" && calibre && calibre.readerSettings) ? calibre.readerSettings : {};
    // useBookmarks mirrors current_user.is_authenticated (tojson'd to "true"/"false").
    var authenticated = !!(typeof calibre === "object" && calibre && String(calibre.useBookmarks) === "true");

    var pending = {};
    var saveTimer = null;

    function lsGet(key) {
        try { return localStorage.getItem(LS_PREFIX + key); } catch (e) { return null; }
    }
    function lsSet(key, value) {
        try { localStorage.setItem(LS_PREFIX + key, value); } catch (e) { /* private mode / quota */ }
    }

    // Normalise a raw value (server-typed, or a localStorage string) to the
    // canonical type for its key so consumers don't each re-parse.
    function coerce(key, raw, dflt) {
        if (raw === undefined || raw === null || raw === "") { return dflt; }
        if (INT_KEYS[key]) {
            var n = parseInt(raw, 10);
            return isNaN(n) ? dflt : n;
        }
        if (BOOL_KEYS[key]) {
            return raw === true || raw === "true";
        }
        return raw;
    }

    function flush() {
        saveTimer = null;
        if (!authenticated) { return; }
        var csrf = $("input[name='csrf_token']").val();
        var body = pending;
        pending = {};
        $.ajax("/ajax/readersettings", {
            method: "post",
            contentType: "application/json",
            data: JSON.stringify(body),
            headers: { "X-CSRFToken": csrf }
        }).fail(function () {
            // Server save failed — localStorage already holds the change, so the
            // setting still survives a reload on this device; just re-queue it.
            Object.keys(body).forEach(function (k) {
                if (!(k in pending)) { pending[k] = body[k]; }
            });
        });
    }

    window.ReaderSettings = {
        // Signed-in: the server snapshot wins (cross-device). Otherwise
        // localStorage. Falls back to dflt when neither has the key.
        get: function (key, dflt) {
            if (authenticated && server && Object.prototype.hasOwnProperty.call(server, key)) {
                return coerce(key, server[key], dflt);
            }
            return coerce(key, lsGet(key), dflt);
        },
        set: function (key, value) {
            lsSet(key, value);
            var prev = server[key];
            server[key] = value;          // keep the in-memory snapshot current
            // Skip the server round-trip when nothing actually changed — the
            // restore-on-load path re-applies saved values (theme/font/spread)
            // and shouldn't fire a POST each time the reader opens.
            if (prev === value) { return; }
            pending[key] = value;
            if (saveTimer) { clearTimeout(saveTimer); }
            saveTimer = setTimeout(flush, 400);   // debounce slider drags into one POST
        },
        isAuthenticated: function () { return authenticated; }
    };
})();
