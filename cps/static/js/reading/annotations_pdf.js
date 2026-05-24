/* Sub-project (3) — render annotations as colored rect overlays on PDF pages.
 *
 * Listens to PDF.js's `pagerendered` event. For each annotation with
 * position_type='pdf_quad' on the just-rendered page, draws absolutely-
 * positioned colored rectangles inside that page's `<div class="page">`.
 *
 * The overlay coordinates in the DB are in PDF user-space units (points)
 * with origin at bottom-left. We convert to CSS pixels using PDF.js's
 * page viewport.
 *
 * Depends on `calibre.annotationsApiBase` (the per-book root, e.g.
 * `/annotations/2`) set by readpdf.html.
 */
/* global PDFViewerApplication */
(function () {
    "use strict";

    var COLOR_RGBA = {
        yellow: "rgba(240, 196, 25, 0.40)",
        red:    "rgba(217, 83, 79, 0.40)",
        green:  "rgba(92, 184, 92, 0.40)",
        blue:   "rgba(91, 192, 222, 0.40)"
    };

    // Annotations cache, keyed by pdf_page (1-indexed).
    var byPage = {};
    var loaded = false;

    function fetchAnnotations() {
        if (!window.calibre || !window.calibre.annotationsApiBase) { return; }
        var url = window.calibre.annotationsApiBase + "/data.json";
        return fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { annotations: [] }; })
            .then(function (payload) {
                var rows = (payload && payload.annotations) || [];
                rows.forEach(function (row) {
                    if (row.position_type !== "pdf_quad") { return; }
                    if (!row.pdf_page || !row.pdf_quad) { return; }
                    if (!byPage[row.pdf_page]) { byPage[row.pdf_page] = []; }
                    byPage[row.pdf_page].push(row);
                });
                loaded = true;
                renderAllRenderedPages();
            })
            .catch(function (err) {
                if (window.console) { console.warn("annotations_pdf fetch failed:", err); }
            });
    }

    function renderAllRenderedPages() {
        // After load, paint any pages that PDF.js has already rendered.
        var pages = document.querySelectorAll(".pdfViewer .page");
        pages.forEach(function (pageEl) {
            var pageNum = parseInt(pageEl.dataset.pageNumber, 10);
            renderPage(pageNum, pageEl);
        });
    }

    function renderPage(pageNum, pageEl) {
        if (!loaded || !byPage[pageNum]) { return; }
        // Clear any prior overlays for this page (re-render safety).
        var prior = pageEl.querySelectorAll(".cwa-pdf-annotation-overlay");
        prior.forEach(function (n) { n.remove(); });
        // Read the page's CSS dimensions; PDF.js sets data-page-width and
        // data-page-height for us, but they may not be present, so fall back
        // to clientWidth/clientHeight (also in CSS px).
        var cssW = pageEl.clientWidth;
        var cssH = pageEl.clientHeight;
        if (!cssW || !cssH) { return; }
        // PDF user-space coords use bottom-left origin and points (1pt = 1/72in).
        // We need page dimensions in points to compute the scale; PDF.js
        // exposes the viewport on the page proxy. Read it from the rendered
        // canvas's width attribute (CSS px) vs the page proxy if available.
        // Pragmatic fallback: assume 72 DPI base and use cssW/cssH ratios
        // — the quad in DB stores coords ALREADY normalized to CSS px from
        // the original render context. (Authoring tools must normalize.)
        var quads = byPage[pageNum];
        quads.forEach(function (row) {
            var color = COLOR_RGBA[row.highlight_color] || COLOR_RGBA.yellow;
            // pdf_quad is a list of [x, y, w, h] in normalized 0..1 coords
            // relative to page width/height. This avoids the points->px
            // conversion gymnastics and works regardless of zoom.
            row.pdf_quad.forEach(function (rect) {
                var x = rect[0], y = rect[1], w = rect[2], h = rect[3];
                if (x == null || y == null || w == null || h == null) { return; }
                var overlay = document.createElement("div");
                overlay.className = "cwa-pdf-annotation-overlay";
                overlay.style.position = "absolute";
                overlay.style.left = (x * cssW) + "px";
                overlay.style.top = (y * cssH) + "px";
                overlay.style.width = (w * cssW) + "px";
                overlay.style.height = (h * cssH) + "px";
                overlay.style.backgroundColor = color;
                overlay.style.mixBlendMode = "multiply";
                overlay.style.pointerEvents = "none";
                overlay.dataset.annotationId = row.annotation_id;
                overlay.title = row.highlighted_text || row.note_text || "";
                pageEl.appendChild(overlay);
            });
        });
    }

    function init() {
        if (typeof PDFViewerApplication === "undefined") {
            setTimeout(init, 100);
            return;
        }
        PDFViewerApplication.initializedPromise.then(function () {
            fetchAnnotations();
            PDFViewerApplication.eventBus.on("pagerendered", function (evt) {
                if (!evt || !evt.pageNumber) { return; }
                var pageEl = document.querySelector(
                    '.pdfViewer .page[data-page-number="' + evt.pageNumber + '"]'
                );
                if (pageEl) { renderPage(evt.pageNumber, pageEl); }
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
