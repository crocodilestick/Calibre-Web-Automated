/* Sub-project (4) — page-level annotation badge for the CBR/CBZ comic reader.
 *
 * Comic books are image-based; there's no "highlight a passage" concept.
 * We support page-level notes (one or more annotations per page) and
 * display them as a small badge in the reader UI when the user is on a
 * page that has annotations.
 *
 * Depends on `calibre.annotationsApiBase` set by readcbr.html.
 */
/* global jQuery, $ */
(function () {
    "use strict";

    var COLOR_BG = {
        yellow: "#f0c419",
        red:    "#d9534f",
        green:  "#5cb85c",
        blue:   "#5bc0de"
    };

    // Annotations cache, keyed by comic_page (1-indexed).
    var byPage = {};

    function fetchAnnotations() {
        if (!window.calibre || !window.calibre.annotationsApiBase) { return; }
        var url = window.calibre.annotationsApiBase + "/data.json";
        return fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { annotations: [] }; })
            .then(function (payload) {
                var rows = (payload && payload.annotations) || [];
                rows.forEach(function (row) {
                    if (row.position_type !== "comic_page") { return; }
                    if (!row.comic_page) { return; }
                    if (!byPage[row.comic_page]) { byPage[row.comic_page] = []; }
                    byPage[row.comic_page].push(row);
                });
                installBadge();
            })
            .catch(function (err) {
                if (window.console) { console.warn("annotations_comic fetch failed:", err); }
            });
    }

    function installBadge() {
        if (document.getElementById("cwa-comic-annotation-badge")) { return; }
        var badge = document.createElement("div");
        badge.id = "cwa-comic-annotation-badge";
        badge.style.position = "fixed";
        badge.style.bottom = "12px";
        badge.style.right = "12px";
        badge.style.minWidth = "26px";
        badge.style.padding = "8px 12px";
        badge.style.borderRadius = "14px";
        badge.style.fontSize = "13px";
        badge.style.fontWeight = "bold";
        badge.style.color = "#222";
        badge.style.boxShadow = "0 2px 8px rgba(0,0,0,0.35)";
        badge.style.zIndex = "999";
        badge.style.cursor = "pointer";
        badge.style.display = "none";
        badge.title = "This page has annotations — click to view";
        badge.addEventListener("click", function () {
            // Jump to the per-book annotations view page.
            window.open(window.calibre.annotationsApiBase, "_blank");
        });
        document.body.appendChild(badge);
        startWatching();
    }

    function startWatching() {
        // The comic reader updates `$(".page").text()` with "<n>/<total>"
        // whenever the user navigates. Watch that element and reflect
        // annotation status onto the badge.
        var pageEl = document.querySelector(".page");
        if (!pageEl) {
            setTimeout(startWatching, 200);
            return;
        }
        var observer = new MutationObserver(function () { updateBadge(pageEl); });
        observer.observe(pageEl, { childList: true, characterData: true, subtree: true });
        updateBadge(pageEl); // initial paint
    }

    function updateBadge(pageEl) {
        var badge = document.getElementById("cwa-comic-annotation-badge");
        if (!badge) { return; }
        var txt = (pageEl.textContent || "").trim();
        var match = txt.match(/^(\d+)\s*\/\s*\d+$/);
        if (!match) {
            badge.style.display = "none";
            return;
        }
        var pageNum = parseInt(match[1], 10);
        var rows = byPage[pageNum] || [];
        if (rows.length === 0) {
            badge.style.display = "none";
            return;
        }
        // Use the first annotation's color for the badge background.
        var color = COLOR_BG[(rows[0] && rows[0].highlight_color) || "yellow"] || COLOR_BG.yellow;
        badge.style.backgroundColor = color;
        badge.textContent = rows.length === 1
            ? "1 note"
            : (rows.length + " notes");
        badge.style.display = "block";
    }

    function init() { fetchAnnotations(); }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
