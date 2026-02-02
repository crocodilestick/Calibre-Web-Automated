// Globals
var epub = ePub(calibre.bookUrl);
let progressDiv = document.getElementById("progress");
let blockKeysHandler = null;

/* ---------- helpers ---------- */

/**
 * Waits until queue is finished, meaning the book is done loading
 * @param callback
 */
function qFinished(callback) {
    let timeout = setInterval(() => {
        if (reader && reader.rendition && reader.rendition.q && reader.rendition.q.running === undefined) {
            clearInterval(timeout);
            callback();
        }
    }, 300);
}

/**
 * Extracts the CSRF token from the input element in read.html.
 */
function getCSRFToken() {
    const input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
}

function sleep(ms) {
    return new Promise(res => setTimeout(res, ms));
}

function showLoading(message = "Loading book…") {
    let existing = document.getElementById("loading-overlay");

    if (!existing) {
        // full-screen overlay
        let overlay = document.createElement("div");
        overlay.id = "loading-overlay";

        Object.assign(overlay.style, {
            position: "fixed",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            background: "rgba(0,0,0,0.4)",
            zIndex: 9998,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "all" // absorb all pointer input
        });

        // loading box
        let div = document.createElement("div");
        div.id = "loading-alert";
        div.innerHTML = `<span class="spinner" style="margin-right:.5rem" aria-hidden="true">⏳</span> ${message}`;

        Object.assign(div.style, {
            background: "rgba(0,0,0,0.9)",
            color: "white",
            padding: "12px 20px",
            borderRadius: "10px",
            fontSize: "15px",
            zIndex: 9999,
            boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
            transition: "opacity 0.3s ease"
        });

        overlay.appendChild(div);
        document.body.appendChild(overlay);

        // block arrow keys while overlay is active
        blockKeysHandler = function (e) {
            if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
                e.preventDefault();
                e.stopPropagation();
                return false;
            }
        };

        document.addEventListener("keydown", blockKeysHandler, true);
    }
}

function hideLoading() {
    let overlay = document.getElementById("loading-overlay");

    if (overlay) {
        overlay.style.opacity = "0";

        setTimeout(() => {
            overlay.remove();

            // remove key block when overlay disappears
            if (blockKeysHandler) {
                document.removeEventListener("keydown", blockKeysHandler, true);
                blockKeysHandler = null;
            }
        }, 300);
    }
}

/* ---------- progress calc + locationchange ---------- */

function calculateProgress() {
    // Guard against missing reader/rendition/location data
    if (!reader || !reader.rendition || !reader.rendition.location || !reader.rendition.location.end) {
        return 0;
    }
    let data = reader.rendition.location.end;

    if (!data || !data.cfi || !epub || !epub.locations) {
        return 0;
    }

    return Math.round(epub.locations.percentageFromCfi(data.cfi) * 100);
}

// register new event emitter locationchange that fires on urlchange
// source: https://stackoverflow.com/a/52809105/21941129
(() => {
    let oldPushState = history.pushState;
    history.pushState = function pushState() {
        let ret = oldPushState.apply(this, arguments);
        window.dispatchEvent(new Event('locationchange'));
        return ret;
    };

    let oldReplaceState = history.replaceState;
    history.replaceState = function replaceState() {
        let ret = oldReplaceState.apply(this, arguments);
        window.dispatchEvent(new Event('locationchange'));
        return ret;
    };

    window.addEventListener('popstate', () => {
        window.dispatchEvent(new Event('locationchange'));
    });
})();

/* ---------- server progress API ---------- */

async function saveProgressToAPI(bookId, cfi, page, percent) {
    try {
        await fetch('/api/progress/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({
                book_id: bookId,
                progress_cfi: cfi,
                progress_page: page,
                progress_percent: percent,
                device: navigator.userAgent
            })
        });
    } catch (e) {
        console.error("Error saving to server: ", e);
    }
}

window.addEventListener('locationchange', () => {
    // Only update if locations exist and we have a reader location
    if (!epub || !epub.locations || !epub.locations.length) return;
    if (!reader || !reader.rendition || !reader.rendition.location) return;

    let percent = calculateProgress();

    if (progressDiv) {
        progressDiv.textContent = percent + "%";
    }

    // Prefer bookId for stable keys. Fall back to bookUrl.
    let key = null;
    if (window.calibre && window.calibre.bookId) key = String(window.calibre.bookId);
    else if (window.calibre && window.calibre.bookUrl) key = String(window.calibre.bookUrl);

    if (key) {
        // Save to localStorage
        localStorage.setItem("calibre.reader.progress." + key, String(percent));
    }

    // Save to API if we have a bookId
    if (window.calibre && window.calibre.bookId && percent > 0) {
        let cfi = reader.rendition.location.end && reader.rendition.location.end.cfi ? reader.rendition.location.end.cfi : null;
        let page = (reader.rendition.location.end && reader.rendition.location.end.displayed)
            ? reader.rendition.location.end.displayed.page
            : null;

        saveProgressToAPI(window.calibre.bookId, cfi, page, percent);
    }
});

/* ---------- initial restore on load ---------- */

qFinished(() => {
    showLoading("Preparing your book…");

    if (!epub || !epub.locations) {
        hideLoading();
        return;
    }

    epub.locations.generate().then(async () => {
        // Prefer bookId for restore, else fall back to bookUrl
        let bookId = (window.calibre && window.calibre.bookId) ? String(window.calibre.bookId) : null;
        let bookUrl = (window.calibre && window.calibre.bookUrl) ? String(window.calibre.bookUrl) : null;

        let key = bookId || bookUrl;
        let hasBookmark = !!(window.calibre && window.calibre.bookmark && window.calibre.bookmark.length > 0);

        let restored = false;

        // 1) Try restoring from API if we have a bookId
        if (bookId) {
            try {
                let resp = await fetch(`/api/progress/get?book_id=${encodeURIComponent(bookId)}`);
                if (resp.ok) {
                    let data = await resp.json();

                    if (data && data.progress_cfi !== undefined && data.progress_cfi !== null) {
                        reader.rendition.display(data.progress_cfi);
                        restored = true;
                    } else if (data && data.progress_percent !== undefined && data.progress_percent !== null) {
                        let percentage = parseInt(data.progress_percent, 10) / 100;
                        if (!isNaN(percentage)) {
                            let cfi = epub.locations.cfiFromPercentage(percentage);
                            if (cfi) {
                                reader.rendition.display(cfi);
                                restored = true;
                            }
                        }
                    }
                }
            } catch (e) {
                console.error("Error fetching from server: ", e);
            }
        }

        // 2) Fallback: localStorage (bookId first, else bookUrl)
        if (!restored && key && reader && reader.rendition) {
            let savedProgress = localStorage.getItem("calibre.reader.progress." + key);

            if (savedProgress) {
                let percentage = parseInt(savedProgress, 10) / 100;
                if (!isNaN(percentage)) {
                    let cfi = epub.locations.cfiFromPercentage(percentage);
                    if (cfi) {
                        reader.rendition.display(cfi);
                        restored = true;
                    }
                }
            }
        }

        // 3) Fallback: kosyncPercent only if no bookmark and nothing else restored
        if (!restored && !hasBookmark && window.calibre && window.calibre.kosyncPercent !== null && window.calibre.kosyncPercent !== undefined) {
            let kosyncPercent = parseFloat(window.calibre.kosyncPercent);
            if (!isNaN(kosyncPercent) && kosyncPercent > 0) {
                let percentage = kosyncPercent / 100;
                let cfi = epub.locations.cfiFromPercentage(percentage);
                if (cfi) {
                    reader.rendition.display(cfi);
                    restored = true;
                }
            }
        }

        // Force a refresh of the displayed progress
        window.dispatchEvent(new Event('locationchange'));

        hideLoading();
    }).catch((e) => {
        console.error("Error generating locations: ", e);
        hideLoading();
    });
});
