// Globals
var epub = ePub(calibre.bookUrl)
let progressDiv = document.getElementById("progress");


/**
 * Extracts the CSRF token from the input element in read.html.
 */
function getCSRFToken() {
    const input = document.querySelector('input[name="csrf_token"]');

    return input ? input.value : '';
}

function calculateProgress() {
    let data = reader.rendition.location.end;

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

    // console.log("Saved at cfi", cfi);
}

window.addEventListener('locationchange', () => {
    let newPos = calculateProgress();
    progressDiv.textContent = newPos + "%";

    if (window.calibre && window.calibre.bookId) {
        let bookId = window.calibre.bookId;

        // Save to localStorage
        localStorage.setItem("calibre.reader.progress." + bookId, newPos);

        // Save to API
        let cfi = reader.rendition.location.end.cfi;
        let page = reader.rendition.location.end.displayed ? reader.rendition.location.end.displayed.page : null;

        saveProgressToAPI(bookId, cfi, page, newPos);
    }
});

document.addEventListener("DOMContentLoaded", async () => {
    if (window.calibre && window.calibre.bookId) {
        let bookId = window.calibre.bookId;

        // Try to restore from API first
        let restored = false;
        try {
            let resp = await fetch(`/api/progress/get?book_id=${encodeURIComponent(bookId)}`);
            if (resp.ok) {
                let data = await resp.json();

                if (data.progress_cfi != undefined) {
                    reader.rendition.display(data.progress_cfi);
                    restored = true;
                } else if (data.progress_page != undefined) {
                    // If you have page logic, implement here
                    // Example: reader.rendition.displayPage(data.progress_page);
                    restored = true;
                } else if (data.progress_percent != undefined) {
                    let percentage = parseInt(data.progress_percent, 10) / 100;
                    let cfi = epub.locations.cfiFromPercentage(percentage);

                    if (cfi) {
                        reader.rendition.display(cfi);
                        restored = true;
                    }
                }
            }
        } catch (e) {
            console.error("Error fetching from server: ", e);
        }

        // Fallback to localStorage if nothing restored
        if (!restored) {
            let savedProgress = localStorage.getItem("calibre.reader.progress." + bookId);

            if (savedProgress != undefined) {
                let percentage = parseInt(savedProgress, 10) / 100;
                let cfi = epub.locations.cfiFromPercentage(percentage);
                if (cfi) {
                    reader.rendition.display(cfi);
                }
            }
        }
    }
});
