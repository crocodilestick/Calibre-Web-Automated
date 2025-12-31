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
            // Try to trigger a layout update (simulate a resize or call a known method)
            if (reader.rendition && typeof reader.rendition.resize === 'function') {
                setTimeout(function() { reader.rendition.resize(); }, 0);
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
        if (savedFontSize && fontSizeFader) {
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
            if (savedFont !== 'default' && fontValue) {
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
