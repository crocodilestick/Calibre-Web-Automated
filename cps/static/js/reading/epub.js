/* global $, calibre, EPUBJS, ePubReader */

var reader;

(function() {
    "use strict";

    EPUBJS.filePath = calibre.filePath;
    EPUBJS.cssPath = calibre.cssPath;

    window.reader = reader = ePubReader(calibre.bookUrl, {
        restore: true,
        bookmarks: calibre.bookmark ? [calibre.bookmark] : []
    });

    function showReaderError(message, error) {
        try {
            console.error(message, error || "");
        } catch (e) {}
        var loader = document.getElementById("loader");
        if (loader) {
            loader.style.display = "none";
        }
        var viewer = document.getElementById("viewer");
        if (viewer) {
            viewer.innerHTML = "<div class=\"reader-error\">" + message + "</div>";
        }
    }

    if (reader && reader.book && typeof reader.book.on === 'function') {
        reader.book.on("openFailed", function(error) {
            showReaderError("Failed to open this EPUB. It may be corrupted or DRM-protected.", error);
        });
        reader.book.on("error", function(error) {
            showReaderError("An error occurred while loading this EPUB.", error);
        });
    }

    if (reader && reader.rendition && typeof reader.rendition.on === 'function') {
        reader.rendition.on("displayerror", function(error) {
            showReaderError("Unable to display this EPUB content.", error);
        });
        reader.rendition.on("loaderror", function(error) {
            showReaderError("Unable to load this EPUB resource.", error);
        });
    }

    Object.keys(themes).forEach(function (theme) {
        reader.rendition.themes.register(theme, themes[theme].css_path);
    });

    if (calibre.useBookmarks) {
        reader.on("reader:bookmarked", updateBookmark.bind(reader, "add"));
        reader.on("reader:unbookmarked", updateBookmark.bind(reader, "remove"));
    } else {
        $("#bookmark, #show-Bookmarks").remove();
    }

    // Page navigation by touch: tap the left or right half of the screen to
    // turn pages (split down the centre), or swipe left/right. A movement
    // threshold separates a tap from a swipe, so a stray jitter no longer turns
    // the page, and an active text selection (the highlight gesture) never
    // turns the page. Desktop arrow buttons + keyboard nav are handled by the
    // reader library; this layer adds the touch affordances.
    var TAP_SLOP_PX = 10;     // movement at or under this counts as a tap
    var SWIPE_MIN_PX = 40;    // horizontal travel over this counts as a swipe
    var TAP_MAX_MS = 300;     // a longer press is a long-press/selection, not a tap
    var touchStartX = 0, touchStartY = 0, touchStartT = 0;

    // True when the rendered content holds a non-empty selection — used to
    // suppress page turns while the reader is selecting text to highlight.
    function readerHasSelection() {
        try {
            var contents = reader.rendition.getContents() || [];
            for (var i = 0; i < contents.length; i++) {
                var win = contents[i] && contents[i].window;
                var sel = win && win.getSelection && win.getSelection();
                if (sel && String(sel).length > 0) {
                    return true;
                }
            }
        } catch (e) { /* contents unavailable mid-transition — treat as no selection */ }
        return false;
    }

    function readerIsRtl() {
        try {
            return reader.book.package.metadata.direction === "rtl";
        } catch (e) {
            return false;
        }
    }

    if (reader && reader.rendition) {
        reader.rendition.on('touchstart', function(event) {
            var t = event.changedTouches[0];
            touchStartX = t.screenX;
            touchStartY = t.screenY;
            touchStartT = Date.now();
        });
        reader.rendition.on('touchend', function(event) {
            var t = event.changedTouches[0];
            var dx = t.screenX - touchStartX;
            var dy = t.screenY - touchStartY;
            var adx = Math.abs(dx), ady = Math.abs(dy);
            var dt = Date.now() - touchStartT;
            var rtl = readerIsRtl();

            // Never turn the page while text is selected (highlight gesture).
            if (readerHasSelection()) {
                return;
            }

            // Swipe: dominant horizontal movement past the threshold.
            if (adx > SWIPE_MIN_PX && adx > ady) {
                if (dx > 0) {                       // swiped right
                    rtl ? reader.rendition.next() : reader.rendition.prev();
                } else {                            // swiped left
                    rtl ? reader.rendition.prev() : reader.rendition.next();
                }
                return;
            }

            // Tap: little movement, short press → turn by which half was tapped,
            // split down the centre of the viewport.
            if (adx <= TAP_SLOP_PX && ady <= TAP_SLOP_PX && dt <= TAP_MAX_MS) {
                var viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1;
                var tappedLeftHalf = t.screenX < (viewportWidth / 2);
                if (tappedLeftHalf) {
                    rtl ? reader.rendition.next() : reader.rendition.prev();
                } else {
                    rtl ? reader.rendition.prev() : reader.rendition.next();
                }
            }
        });
    }

    /**
     * @param {string} action - Add or remove bookmark
     * @param {string|int} location - Location or zero
     */
    function updateBookmark(action, location) {
        // Remove other bookmarks (there can only be one)
        if (action === "add") {
            this.settings.bookmarks.filter(function (bookmark) {
                return bookmark && bookmark !== location;
            }).map(function (bookmark) {
                this.removeBookmark(bookmark);
            }.bind(this));
        }

        var csrftoken = $("input[name='csrf_token']").val();

        // Save to database
        $.ajax(calibre.bookmarkUrl, {
            method: "post",
            data: { bookmark: location || "" },
            headers: { "X-CSRFToken": csrftoken }
        }).fail(function (xhr, status, error) {
            alert(error);
        });
    }

    // Restore all settings after DOM and reader are ready
    document.addEventListener("DOMContentLoaded", function() {
        // Declare reflowBox once and reuse
        var reflowBox = document.getElementById('sidebarReflow');
        if (reflowBox && reader && reader.settings) {
            reader.settings.sidebarReflow = reflowBox.checked;
            // Trigger resize after first render to avoid calling resize too early
            if (reader.rendition && typeof reader.rendition.on === 'function') {
                let resizedOnce = false;
                reader.rendition.on('rendered', function() {
                    if (resizedOnce) {
                        return;
                    }
                    resizedOnce = true;
                    if (reader && reader.rendition && typeof reader.rendition.resize === 'function') {
                        try {
                            reader.rendition.resize();
                        } catch (e) {
                            // Avoid breaking the reader when resize isn't available
                        }
                    }
                });
            }
        }
        // Ensure reflow logic is always applied if the class is present
        setTimeout(function() {
            if (reflowBox && document.body.classList.contains('reflow-enabled')) {
                // Trigger change event to re-apply reflow logic
                reflowBox.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }, 0);
        // Theme
        const theme = localStorage.getItem("calibre.reader.theme") ?? "lightTheme";
        if (typeof selectTheme === 'function') selectTheme(theme);

        // Font size
        let savedFontSize = localStorage.getItem("calibre.reader.fontSize");
        let fontSizeFader = document.getElementById('fontSizeFader');
        if (savedFontSize && fontSizeFader && reader && reader.rendition && reader.rendition.themes) {
            fontSizeFader.value = savedFontSize;
            reader.rendition.themes.fontSize(`${savedFontSize}%`);
        }

        // Font
        let fontMap = {
            'default': '',
            'Yahei': '"Microsoft YaHei", sans-serif',
            'SimSun': 'SimSun, serif',
            'KaiTi': 'KaiTi, serif',
            'Arial': 'Arial, Helvetica, sans-serif'
        };
        let savedFont = localStorage.getItem("calibre.reader.font");
        if (savedFont && typeof selectFont === 'function') {
            selectFont(savedFont);
            let fontValue = fontMap[savedFont] || '';
            if (savedFont !== 'default' && fontValue && reader && reader.rendition && reader.rendition.themes) {
                reader.rendition.themes.font(fontValue);
            }
        }

        // Spread
        let savedSpread = localStorage.getItem("calibre.reader.spread");
        if (savedSpread && typeof spread === 'function') {
            spread(savedSpread);
        }

        // Reflow
        // Use the reflowBox declared earlier in this handler
        var savedReflow = localStorage.getItem("calibre.reader.reflow");
        function applyReflow(enabled) {
            if (reader && reader.rendition && typeof reader.rendition.reflow === 'function') {
                reader.rendition.reflow(enabled);
            } else {
                document.body.classList.toggle('reflow-enabled', enabled);
            }
        }
        if (reflowBox) {
            if (savedReflow !== null) {
                reflowBox.checked = savedReflow === 'true';
                applyReflow(reflowBox.checked);
            }
            reflowBox.addEventListener("change", function() {
                localStorage.setItem("calibre.reader.reflow", this.checked);
                applyReflow(this.checked);
            });
        }
    });
})();
