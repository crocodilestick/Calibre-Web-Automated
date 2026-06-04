/* H1 Phase 5 — render imported Kobo highlights as colored overlays in
 * the in-browser EPUB reader.
 *
 * Reads `/annotations/<book_id>/data.json` once on rendition ready,
 * iterates the result, and overlays each highlight on the page.
 *
 * Why the CFI is generated client-side
 * ------------------------------------
 * Kobo records a highlight as a KoboSpan id (`kobo.<p>.<s>`) plus a
 * character offset. The server CANNOT author a CFI that epub.js will
 * resolve, because epub.js resolves highlight CFIs via a
 * position-constrained XPath against its *rendered* DOM — and at render
 * time epub.js injects its own wrapper divs (`book-columns` /
 * `book-inner`) that the server has no way to know about. A
 * source-document CFI therefore never matches the rendered tree
 * ("No startContainer found").
 *
 * The KoboSpan id, by contrast, survives rendering untouched. So the
 * reader resolves the KoboSpan element in the live document via
 * getElementById, builds a DOM Range with the stored offsets, and asks
 * epub.js itself to generate the canonical (wrapper-aware) CFI through
 * `contents.cfiFromRange(range)`. That CFI is by construction resolvable
 * by the same epub.js that produced it, and re-resolves correctly every
 * time the section re-renders.
 *
 * Section scoping: KoboSpan ids (`kobo.0.3`) are only unique within a
 * chapter — the same id can appear in another chapter — so a highlight
 * is only applied to the rendered contents whose section matches the
 * annotation's `content_id` chapter file.
 *
 * Annotations without a KoboSpan anchor (and without a resolvable CFI)
 * still appear in the sidebar list — they just don't overlay on the
 * page.
 *
 * Depends on the `calibre.annotationsApiBase` global set by read.html.
 */
/* global $, calibre, reader */
(function () {
    "use strict";

    // Named highlight colors the web-reader create path emits. Real Kobo
    // devices store a hex color instead (e.g. "#F6F3B3"); colorToRgba
    // handles both. RGB triples here, alpha applied uniformly below.
    var NAMED_RGB = {
        yellow: [240, 196, 25],
        red:    [217, 83, 79],
        green:  [92, 184, 92],
        blue:   [91, 192, 222],
        pink:   [233, 30, 99],
        purple: [156, 39, 176],
        orange: [255, 152, 0]
    };
    var HIGHLIGHT_ALPHA = 0.4;

    // Map a color (named or "#rrggbb"/"#rgb") to an rgba() fill string.
    // Falls back to yellow for anything unrecognized so a highlight is
    // never silently dropped just because the color is odd.
    function colorToRgba(color) {
        var c = (color == null ? "" : String(color)).trim().toLowerCase();
        var rgb = null;
        if (c.charAt(0) === "#") {
            var hex = c.slice(1);
            if (hex.length === 3) {
                hex = hex.charAt(0) + hex.charAt(0) + hex.charAt(1) + hex.charAt(1) + hex.charAt(2) + hex.charAt(2);
            }
            if (/^[0-9a-f]{6}$/.test(hex)) {
                rgb = [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
            }
        } else if (NAMED_RGB.hasOwnProperty(c)) {
            rgb = NAMED_RGB[c];
        }
        if (!rgb) { rgb = NAMED_RGB.yellow; }
        return "rgba(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + "," + HIGHLIGHT_ALPHA + ")";
    }

    function colorStyle(color) {
        return { fill: colorToRgba(color), "fill-opacity": String(HIGHLIGHT_ALPHA), "mix-blend-mode": "multiply" };
    }

    // CSS-safe class token from a color (strips "#", spaces, etc.) so the
    // sidebar entry can be color-targeted without an invalid selector.
    function safeColorToken(color) {
        var c = (color == null ? "" : String(color)).trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
        return c || "yellow";
    }

    // Resolve a character offset within a KoboSpan to a (text node, offset)
    // pair. Handles the common single-text-node span and nested inline
    // markup (<i>, <b>) by walking descendant text nodes. Clamps to the
    // span end if the stored offset overshoots (defensive — never throws).
    function locateOffset(doc, span, charOffset) {
        var walker = doc.createTreeWalker(span, NodeFilter.SHOW_TEXT, null, false);
        var node = walker.nextNode();
        if (!node) { return { node: span, offset: 0 }; }
        var remaining = charOffset;
        while (node) {
            var len = node.nodeValue.length;
            if (remaining <= len) { return { node: node, offset: remaining }; }
            remaining -= len;
            var next = walker.nextNode();
            if (!next) { return { node: node, offset: len }; }
            node = next;
        }
        return { node: node, offset: node.nodeValue.length };
    }

    // Does this annotation's chapter (from content_id "<uuid>!!<file>")
    // match the rendered section's href? Tolerant of OEBPS/ prefixes the
    // way the server-side spine resolver is.
    function chapterMatches(contentId, sectionHref) {
        if (!contentId || !sectionHref) { return true; } // no info → don't exclude
        var bang = contentId.indexOf("!!");
        if (bang < 0) { return true; }
        var chap = contentId.slice(bang + 2);
        if (!chap) { return true; }
        if (chap === sectionHref) { return true; }
        if (sectionHref.indexOf("/") >= 0 && sectionHref.split("/").pop() === chap.split("/").pop()) { return true; }
        return sectionHref.indexOf(chap) >= 0 || chap.indexOf(sectionHref) >= 0;
    }

    function sectionHrefForContents(contents) {
        try {
            if (contents && reader.book && reader.book.spine && typeof reader.book.spine.get === "function") {
                var sec = reader.book.spine.get(contents.sectionIndex);
                if (sec && sec.href) { return sec.href; }
            }
        } catch (e) { /* fall through */ }
        return null;
    }

    var appliedIds = {};   // annotation_id -> true once overlaid
    var allRows = [];      // the data.json payload, kept for late renders

    // Apply every not-yet-applied annotation whose KoboSpans live in this
    // rendered `contents`. Called for the initial section and on every
    // subsequent "rendered" event as the user navigates.
    function applyToContents(contents) {
        if (!contents || !contents.document || typeof contents.cfiFromRange !== "function") { return; }
        if (!reader.rendition || !reader.rendition.annotations) { return; }
        var doc = contents.document;
        var sectionHref = sectionHrefForContents(contents);

        allRows.forEach(function (row) {
            if (appliedIds[row.annotation_id]) { return; }
            if (!row.start_kobospan) { return; } // sidebar-only (no anchor)
            if (!chapterMatches(row.content_id, sectionHref)) { return; }

            var startSpan = doc.getElementById(row.start_kobospan);
            var endSpan = doc.getElementById(row.end_kobospan || row.start_kobospan);
            if (!startSpan || !endSpan) { return; } // not in this section

            try {
                var a = locateOffset(doc, startSpan, row.start_offset || 0);
                var b = locateOffset(doc, endSpan, row.end_offset || 0);
                var range = doc.createRange();
                range.setStart(a.node, a.offset);
                range.setEnd(b.node, b.offset);
                if (range.collapsed) { return; }

                var cfi = contents.cfiFromRange(range);
                if (!cfi) { return; }

                reader.rendition.annotations.highlight(
                    cfi,
                    { id: row.annotation_id, color: row.highlight_color },
                    function (e) { showEditPopup(row, contents, e); },
                    "cwa-annotation-overlay",
                    colorStyle(row.highlight_color)
                );
                appliedIds[row.annotation_id] = true;
                appliedCfi[row.annotation_id] = cfi;
            } catch (e) {
                if (window.console) { console.warn("annotation overlay failed for " + row.annotation_id + ":", e); }
            }
        });
    }

    // Sweep whatever sections are currently rendered (covers the initial
    // section that may already be on screen before our hook attaches).
    function applyToRenderedContents() {
        try {
            var contentsList = reader.rendition.getContents();
            (contentsList || []).forEach(applyToContents);
        } catch (e) { /* nothing rendered yet */ }
    }

    function renderSidebarList(rows) {
        var ol = document.getElementById("annotations-list");
        if (!ol) { return; }
        ol.replaceChildren();
        if (!rows.length) {
            var empty = document.createElement("li");
            empty.className = "text-muted small";
            empty.textContent = t("noAnnotations", "No annotations on this book yet.");
            ol.appendChild(empty);
            return;
        }
        rows.forEach(function (row) {
            var li = document.createElement("li");
            li.className = "cwa-annotation cwa-annotation-" + safeColorToken(row.highlight_color);
            li.dataset.annotationId = row.annotation_id;

            var quote = document.createElement("blockquote");
            quote.textContent = row.highlighted_text || "";
            li.appendChild(quote);

            if (row.note_text) {
                var noteP = document.createElement("p");
                noteP.className = "cwa-annotation-note";
                noteP.textContent = row.note_text;
                li.appendChild(noteP);
            }
            // Click the entry to jump to the highlight. Prefer the live
            // KoboSpan (works regardless of wrapper layout); fall back to a
            // stored cfi_range only if there's no anchor.
            li.style.cursor = "pointer";
            li.addEventListener("click", function () {
                if (jumpToAnnotation(row)) { return; }
                if (row.cfi_range) {
                    try { reader.rendition.display(row.cfi_range); } catch (e) { /* unresolvable — ignore */ }
                }
            });
            ol.appendChild(li);
        });
    }

    // Navigate the reader to an annotation by resolving its start KoboSpan
    // in whichever section currently holds it. If that section isn't
    // rendered yet, display its chapter first, then re-resolve.
    function jumpToAnnotation(row) {
        if (!row.start_kobospan) { return false; }
        var contentsList;
        try { contentsList = reader.rendition.getContents() || []; } catch (e) { contentsList = []; }
        for (var i = 0; i < contentsList.length; i++) {
            var c = contentsList[i];
            var el = c.document && c.document.getElementById(row.start_kobospan);
            if (el && chapterMatches(row.content_id, sectionHrefForContents(c))) {
                try {
                    var loc = locateOffset(c.document, el, row.start_offset || 0);
                    var range = c.document.createRange();
                    range.setStart(loc.node, loc.offset);
                    range.setEnd(loc.node, loc.offset);
                    var cfi = c.cfiFromRange(range);
                    if (cfi) { reader.rendition.display(cfi); return true; }
                } catch (e) { /* fall through */ }
            }
        }
        // Section not rendered — jump to the chapter; the rendered hook
        // overlays the highlight once it loads.
        if (row.content_id && row.content_id.indexOf("!!") >= 0) {
            try { reader.rendition.display(row.content_id.split("!!")[1]); return true; } catch (e) { /* ignore */ }
        }
        return false;
    }

    // --- Phase 1: create / edit / delete -----------------------------------

    var appliedCfi = {};          // annotation_id -> the cfi actually drawn (for removal on edit/delete)
    var CREATE_COLORS = ["yellow", "red", "green", "blue"];  // the set a Kobo round-trips

    function csrfToken() {
        var el = document.querySelector("input[name='csrf_token']");
        return el ? el.value : "";
    }

    // The reader is a standalone page (no layout.html fetch shim), so we set
    // the CSRF header ourselves from read.html's hidden input.
    function apiFetch(method, url, body) {
        return fetch(url, {
            method: method,
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
            body: body ? JSON.stringify(body) : undefined
        });
    }

    function apiBase() {
        return (calibre && calibre.annotationsApiBase) ? calibre.annotationsApiBase : null;
    }

    // Nearest enclosing KoboSpan element for a selection endpoint node.
    function nearestKoboSpan(node) {
        var el = (node && node.nodeType === 3) ? node.parentNode : node;
        while (el && el.nodeType === 1) {
            if (el.id && el.id.indexOf("kobo.") === 0) { return el; }
            el = el.parentNode;
        }
        return null;
    }

    // Character offset of (node, nodeOffset) within `span` — the inverse of
    // locateOffset: sum the lengths of the span's descendant text nodes.
    function offsetWithinSpan(doc, span, node, nodeOffset) {
        if (node === span) { return 0; }
        var walker = doc.createTreeWalker(span, NodeFilter.SHOW_TEXT, null, false);
        var total = 0, n;
        while ((n = walker.nextNode())) {
            if (n === node) { return total + nodeOffset; }
            total += n.nodeValue.length;
        }
        return nodeOffset;
    }

    // Map a live selection Range to the create payload's KoboSpan anchors, or
    // null when the selection isn't inside KoboSpans (e.g. a non-kepub render).
    function selectionToAnchor(range, contents) {
        var doc = contents.document;
        var sSpan = nearestKoboSpan(range.startContainer);
        var eSpan = nearestKoboSpan(range.endContainer);
        if (!sSpan || !eSpan) { return null; }
        return {
            start_kobospan: sSpan.id,
            start_offset: offsetWithinSpan(doc, sSpan, range.startContainer, range.startOffset),
            end_kobospan: eSpan.id,
            end_offset: offsetWithinSpan(doc, eSpan, range.endContainer, range.endOffset),
            chapter_filename: sectionHrefForContents(contents),
            highlighted_text: range.toString()
        };
    }

    // Translate an in-iframe client rect to parent-viewport coordinates so a
    // popup appended to the parent body lands next to the selection.
    function iframeRectToParent(contents, rect) {
        try {
            var fr = contents.document.defaultView.frameElement.getBoundingClientRect();
            return { left: fr.left + rect.left, top: fr.top + rect.top, bottom: fr.top + rect.bottom };
        } catch (e) {
            return { left: rect.left, top: rect.top, bottom: rect.bottom };
        }
    }

    function removePopup() {
        var p = document.getElementById("cwa-ann-popup");
        if (p && p.parentNode) { p.parentNode.removeChild(p); }
    }

    // User-facing popup strings come translated from read.html (window.calibre
    // .annotationsI18n) so they follow the reader's i18n convention; English
    // fallbacks keep the popup working if the bridge is ever absent.
    function annI18n() { return (window.calibre && window.calibre.annotationsI18n) || {}; }
    function t(key, fallback) { var v = annI18n()[key]; return (typeof v === "string" && v) ? v : fallback; }
    function colorLabel(c) { var m = annI18n().colors || {}; return (typeof m[c] === "string" && m[c]) ? m[c] : c; }

    function makeSwatchRow(selected, onPick) {
        var wrap = document.createElement("div");
        wrap.className = "cwa-ann-swatches";
        CREATE_COLORS.forEach(function (c) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "cwa-ann-swatch cwa-ann-swatch-" + c + (c === selected ? " is-selected" : "");
            b.setAttribute("aria-label", colorLabel(c));
            b.style.background = "rgb(" + NAMED_RGB[c].join(",") + ")";
            b.addEventListener("click", function () {
                wrap.querySelectorAll(".cwa-ann-swatch").forEach(function (s) { s.classList.remove("is-selected"); });
                b.classList.add("is-selected");
                onPick(c);
            });
            wrap.appendChild(b);
        });
        return wrap;
    }

    function positionPopup(popup, pos) {
        popup.style.left = Math.max(8, Math.min(pos.left, window.innerWidth - 260)) + "px";
        popup.style.top = Math.max(8, Math.min(pos.bottom + 8, window.innerHeight - 160)) + "px";
    }

    function showCreatePopup(anchor, range, contents) {
        removePopup();
        var popup = document.createElement("div");
        popup.id = "cwa-ann-popup";
        popup.className = "cwa-ann-popup";
        var chosen = { color: "yellow" };

        if (!anchor) {
            var msg = document.createElement("div");
            msg.className = "cwa-ann-msg";
            msg.textContent = t("selectWithin", "Select within a paragraph to highlight.");
            popup.appendChild(msg);
        } else {
            popup.appendChild(makeSwatchRow("yellow", function (c) { chosen.color = c; }));
            var note = document.createElement("textarea");
            note.className = "cwa-ann-note";
            note.placeholder = t("addNote", "Add a note (optional)");
            popup.appendChild(note);
            var actions = document.createElement("div");
            actions.className = "cwa-ann-actions";
            var save = document.createElement("button");
            save.type = "button"; save.className = "cwa-ann-save"; save.textContent = t("save", "Save");
            save.addEventListener("click", function () {
                save.disabled = true;
                apiFetch("POST", apiBase(), {
                    start_kobospan: anchor.start_kobospan, start_offset: anchor.start_offset,
                    end_kobospan: anchor.end_kobospan, end_offset: anchor.end_offset,
                    chapter_filename: anchor.chapter_filename,
                    highlighted_text: anchor.highlighted_text,
                    highlight_color: chosen.color, note_text: note.value || null
                })
                .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
                .then(function (row) {
                    allRows.push(row);
                    renderSidebarList(allRows);
                    applyToRenderedContents();
                    try { contents.window.getSelection().removeAllRanges(); } catch (e) { /* ignore */ }
                    removePopup();
                })
                .catch(function (err) {
                    save.disabled = false;
                    if (window.console) { console.warn("annotation create failed:", err); }
                });
            });
            actions.appendChild(save);
            var cancel = document.createElement("button");
            cancel.type = "button"; cancel.className = "cwa-ann-cancel"; cancel.textContent = t("cancel", "Cancel");
            cancel.addEventListener("click", removePopup);
            actions.appendChild(cancel);
            popup.appendChild(actions);
        }
        document.body.appendChild(popup);
        try {
            positionPopup(popup, iframeRectToParent(contents, range.getBoundingClientRect()));
        } catch (e) { positionPopup(popup, { left: 40, bottom: 80 }); }
    }

    function showEditPopup(row, contents, evt) {
        removePopup();
        var popup = document.createElement("div");
        popup.id = "cwa-ann-popup";
        popup.className = "cwa-ann-popup";
        var chosen = { color: safeColorToken(row.highlight_color) };
        popup.appendChild(makeSwatchRow(chosen.color, function (c) { chosen.color = c; }));
        var note = document.createElement("textarea");
        note.className = "cwa-ann-note";
        note.placeholder = t("note", "Note");
        note.value = row.note_text || "";
        popup.appendChild(note);
        var actions = document.createElement("div");
        actions.className = "cwa-ann-actions";
        var save = document.createElement("button");
        save.type = "button"; save.className = "cwa-ann-save"; save.textContent = t("save", "Save");
        save.addEventListener("click", function () {
            save.disabled = true;
            apiFetch("PATCH", apiBase() + "/" + encodeURIComponent(row.annotation_id),
                     { highlight_color: chosen.color, note_text: note.value || null })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (updated) { repaintAnnotation(row.annotation_id, updated); removePopup(); })
            .catch(function (err) { save.disabled = false; if (window.console) { console.warn("annotation edit failed:", err); } });
        });
        actions.appendChild(save);
        var del = document.createElement("button");
        del.type = "button"; del.className = "cwa-ann-delete"; del.textContent = t("del", "Delete");
        del.addEventListener("click", function () {
            del.disabled = true;
            apiFetch("DELETE", apiBase() + "/" + encodeURIComponent(row.annotation_id), null)
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function () { removeAnnotation(row.annotation_id); removePopup(); })
            .catch(function (err) { del.disabled = false; if (window.console) { console.warn("annotation delete failed:", err); } });
        });
        actions.appendChild(del);
        var cancel = document.createElement("button");
        cancel.type = "button"; cancel.className = "cwa-ann-cancel"; cancel.textContent = t("cancel", "Cancel");
        cancel.addEventListener("click", removePopup);
        actions.appendChild(cancel);
        popup.appendChild(actions);
        document.body.appendChild(popup);
        var pos = { left: 40, bottom: 80 };
        try {
            if (evt && contents) {
                pos = iframeRectToParent(contents, { left: evt.clientX, top: evt.clientY, bottom: evt.clientY });
            }
        } catch (e) { /* fall back to default pos */ }
        positionPopup(popup, pos);
    }

    // Remove an annotation's overlay + sidebar entry + state.
    function removeAnnotation(id) {
        if (appliedCfi[id]) {
            try { reader.rendition.annotations.remove(appliedCfi[id], "highlight"); } catch (e) { /* ignore */ }
            delete appliedCfi[id];
        }
        delete appliedIds[id];
        allRows = allRows.filter(function (r) { return r.annotation_id !== id; });
        renderSidebarList(allRows);
    }

    // Replace an annotation's data + repaint (after a color/note edit).
    function repaintAnnotation(id, updated) {
        if (appliedCfi[id]) {
            try { reader.rendition.annotations.remove(appliedCfi[id], "highlight"); } catch (e) { /* ignore */ }
            delete appliedCfi[id];
        }
        delete appliedIds[id];
        for (var i = 0; i < allRows.length; i++) {
            if (allRows[i].annotation_id === id) { allRows[i] = updated; break; }
        }
        renderSidebarList(allRows);
        applyToRenderedContents();
    }

    function injectStyles() {
        if (document.getElementById("cwa-ann-style")) { return; }
        var s = document.createElement("style");
        s.id = "cwa-ann-style";
        s.textContent =
            ".cwa-ann-popup{position:fixed;z-index:10000;background:#fff;border:1px solid #ccc;" +
            "border-radius:6px;box-shadow:0 2px 12px rgba(0,0,0,.25);padding:8px;width:240px;" +
            "font-size:14px;color:#222;}" +
            ".cwa-ann-swatches{display:flex;gap:6px;margin-bottom:6px;}" +
            ".cwa-ann-swatch{width:26px;height:26px;border-radius:50%;border:2px solid transparent;" +
            "cursor:pointer;padding:0;}" +
            ".cwa-ann-swatch.is-selected{border-color:#333;}" +
            ".cwa-ann-note{width:100%;min-height:48px;box-sizing:border-box;margin-bottom:6px;}" +
            ".cwa-ann-actions{display:flex;gap:6px;justify-content:flex-end;}" +
            ".cwa-ann-actions button{padding:4px 10px;cursor:pointer;}" +
            ".cwa-ann-delete{color:#d9534f;}" +
            ".cwa-ann-msg{color:#777;}";
        document.head.appendChild(s);
    }

    var hookAttached = false;
    function attachRenderHook() {
        if (hookAttached || !reader.rendition || typeof reader.rendition.on !== "function") { return; }
        hookAttached = true;
        // Fires for the initial section and each section the user navigates
        // to. view.contents is the rendered Contents for that section.
        reader.rendition.on("rendered", function (section, view) {
            var contents = view && view.contents ? view.contents : (view && typeof view.contents === "function" ? view.contents() : null);
            if (contents) {
                applyToContents(contents);
            } else {
                applyToRenderedContents();
            }
        });
        // Selecting text in the rendered section offers a create popup.
        reader.rendition.on("selected", function (cfiRange, contents) {
            try {
                var sel = contents.window.getSelection();
                if (!sel || !sel.rangeCount) { return; }
                var range = sel.getRangeAt(0);
                if (range.collapsed || !range.toString().trim()) { return; }
                showCreatePopup(selectionToAnchor(range, contents), range, contents);
            } catch (e) {
                if (window.console) { console.warn("annotation selection handler failed:", e); }
            }
        });
        // Paging away dismisses any open popup (its anchor is gone).
        reader.rendition.on("relocated", removePopup);
    }

    function init() {
        if (!calibre || !calibre.annotationsApiBase) {
            return;
        }
        if (!window.reader || !reader.rendition) {
            // epub.js init runs async; retry on next tick.
            setTimeout(init, 100);
            return;
        }

        injectStyles();
        // Clicking the parent chrome (outside the popup) dismisses it. Clicks
        // inside the iframe are handled by the select/relocate hooks.
        document.addEventListener("mousedown", function (e) {
            var p = document.getElementById("cwa-ann-popup");
            if (p && !p.contains(e.target)) { removePopup(); }
        });

        var dataUrl = calibre.annotationsApiBase + "/data.json";
        fetch(dataUrl, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { annotations: [] }; })
            .then(function (payload) {
                allRows = (payload && payload.annotations) || [];
                renderSidebarList(allRows);
                attachRenderHook();
                applyToRenderedContents();
            })
            .catch(function (err) {
                if (window.console) { console.warn("annotations fetch failed:", err); }
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
