/* H1 Phase 5 — render imported Kobo highlights as colored overlays in
 * the in-browser EPUB reader.
 *
 * Reads `/annotations/<book_id>/data.json` once on rendition ready,
 * iterates the result, and calls `rendition.annotations.highlight(cfi,
 * data, callback, className, styles)` for each annotation that has a
 * resolvable CFI. Annotations without a CFI (P2's converter couldn't
 * place them) still appear in the sidebar list — they just don't
 * overlay on the page.
 *
 * The annotations panel in the reader sidebar gets populated from
 * the same payload.
 *
 * Depends on the `calibre.annotationsApiBase` global set by read.html
 * (the per-book root, e.g. `/annotations/2`). The data endpoint is
 * `${base}/data.json`.
 */
/* global $, calibre, reader */
(function () {
    "use strict";

    var COLOR_RGBA = {
        yellow: "rgba(240, 196, 25, 0.40)",
        red:    "rgba(217, 83, 79, 0.40)",
        green:  "rgba(92, 184, 92, 0.40)",
        blue:   "rgba(91, 192, 222, 0.40)"
    };

    function colorStyle(color) {
        var c = (color in COLOR_RGBA) ? color : "yellow";
        return { fill: COLOR_RGBA[c], "fill-opacity": "0.40", "mix-blend-mode": "multiply" };
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

        var dataUrl = calibre.annotationsApiBase + "/data.json";
        fetch(dataUrl, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { annotations: [] }; })
            .then(function (payload) {
                var rows = (payload && payload.annotations) || [];
                renderOverlays(rows);
                renderSidebarList(rows);
            })
            .catch(function (err) {
                if (window.console) { console.warn("annotations fetch failed:", err); }
            });
    }

    function renderOverlays(rows) {
        if (!reader || !reader.rendition || !reader.rendition.annotations) {
            return;
        }
        rows.forEach(function (row) {
            if (!row.cfi_range) {
                return; // No CFI — sidebar only, no page overlay.
            }
            try {
                reader.rendition.annotations.highlight(
                    row.cfi_range,
                    { id: row.annotation_id },
                    null,
                    "cwa-annotation-overlay cwa-annotation-overlay-" + (row.highlight_color || "yellow"),
                    colorStyle(row.highlight_color)
                );
            } catch (e) {
                if (window.console) { console.warn("annotation overlay failed for " + row.annotation_id + ":", e); }
            }
        });
    }

    function renderSidebarList(rows) {
        var ol = document.getElementById("annotations-list");
        if (!ol) { return; }
        ol.innerHTML = "";
        if (!rows.length) {
            var empty = document.createElement("li");
            empty.className = "text-muted small";
            empty.textContent = "No annotations on this book.";
            ol.appendChild(empty);
            return;
        }
        rows.forEach(function (row) {
            var li = document.createElement("li");
            li.className = "cwa-annotation cwa-annotation-" + (row.highlight_color || "yellow");
            li.dataset.cfi = row.cfi_range || "";
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
            // Click the entry to jump to its CFI in the reader.
            if (row.cfi_range) {
                li.style.cursor = "pointer";
                li.addEventListener("click", function () {
                    try {
                        reader.rendition.display(row.cfi_range);
                    } catch (e) {
                        // CFI may not resolve if the book has been reuploaded — silent fall-through.
                    }
                });
            }
            ol.appendChild(li);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
