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

    // Enable swipe support
    // I have no idea why swiperRight/swiperLeft from plugins is not working, events just don't get fired
    var touchStart = 0;
    var touchEnd = 0;

    if (reader && reader.rendition) {
        reader.rendition.on('touchstart', function(event) {
            touchStart = event.changedTouches[0].screenX;
        });
        reader.rendition.on('touchend', function(event) {
          touchEnd = event.changedTouches[0].screenX;
            if (touchStart < touchEnd) {
                if(reader.book.package.metadata.direction === "rtl") {
					reader.rendition.next();
				} else {
					reader.rendition.prev();
				}
                // Swiped Right
            }
            if (touchStart > touchEnd) {
                if(reader.book.package.metadata.direction === "rtl") {
					reader.rendition.prev();
				} else {
                    reader.rendition.next();
				}
                // Swiped Left
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
