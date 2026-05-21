/**
 * waits until queue is finished, meaning the book is done loading
 * @param callback
 */
function qFinished(callback){
    let timeout=setInterval(()=>{
        if (reader && reader.rendition && reader.rendition.q && reader.rendition.q.running === undefined) {
            clearInterval(timeout);
            callback();
        }
        },300
    )
}

function calculateProgress(){
    if (!reader || !reader.rendition || !reader.rendition.location || !reader.rendition.location.end) {
        return 0;
    }
    let data=reader.rendition.location.end;
    if (!data || !data.cfi || !epub || !epub.locations) {
        return 0;
    }
    return Math.round(epub.locations.percentageFromCfi(data.cfi)*100);
}

/**
 * Compute the user's progress within the CURRENT spine section (chapter),
 * complementing the book-wide calculateProgress() above. Backport of
 * janeczku/calibre-web#3370 (@ryan-c-scott) adapted to our split
 * epub-progress.js architecture.
 *
 * Returns a number 0..100, or null if not enough state to compute.
 * Uses the `epub` global's `locations._locations` (the array of CFIs
 * that our `epub.locations.generate()` call in qFinished() produced).
 * Note: upstream uses `reader.book.locations` because their PR runs
 * inside epub.js where `reader.book === epub`. Our progress logic
 * lives in a separate file and uses its own `epub` instance; the
 * reader has a different ePub instance whose locations are never
 * generated. We rely on the `epub` global throughout for consistency.
 *
 * The section's start CFI is the first locations-array entry whose
 * string contains the spine item's `cfiBase`; the section's end CFI
 * is the last such entry. We map
 * (current - sectionStart) / (sectionEnd - sectionStart) to 0..100.
 */
function calculateSectionProgress(){
    if (!reader || !reader.rendition || !reader.rendition.location) {
        return null;
    }
    const loc = reader.rendition.location;
    if (!loc.start || typeof loc.start.index !== "number" || !loc.start.cfi) {
        return null;
    }
    // Use the `epub` global throughout — that's the instance whose
    // locations we actually generate. `reader.book` is a separate ePub
    // instance whose `locations._locations` stays empty in our setup.
    if (!epub || !epub.spine || !epub.locations) {
        return null;
    }
    const spineItem = epub.spine.get(loc.start.index);
    if (!spineItem || !spineItem.cfiBase) {
        return null;
    }
    const allLocations = epub.locations._locations;
    if (!Array.isArray(allLocations) || allLocations.length === 0) {
        return null;
    }
    const baseCfi = spineItem.cfiBase;
    const sectionStartCfi = allLocations.find(cfi => cfi.includes(baseCfi));
    // findLast is ES2023 (Safari 15.4+, Chrome 97+, Firefox 104+); the
    // reader is a modern-browser surface anyway. Manual fallback via
    // reverse iteration kept tight in case the runtime is older.
    let sectionEndCfi;
    if (typeof allLocations.findLast === "function") {
        sectionEndCfi = allLocations.findLast(cfi => cfi.includes(baseCfi));
    } else {
        for (let i = allLocations.length - 1; i >= 0; i--) {
            if (allLocations[i].includes(baseCfi)) {
                sectionEndCfi = allLocations[i];
                break;
            }
        }
    }
    if (!sectionStartCfi || !sectionEndCfi) {
        return null;
    }
    if (sectionStartCfi === sectionEndCfi) {
        // Single-location section: by definition we've covered all of it.
        return 100;
    }
    const startNorm = epub.locations.percentageFromCfi(sectionStartCfi);
    const endNorm = epub.locations.percentageFromCfi(sectionEndCfi);
    const sectionSpan = endNorm - startNorm;
    if (!sectionSpan || sectionSpan <= 0) {
        return null;
    }
    const bookNorm = epub.locations.percentageFromCfi(loc.start.cfi);
    const sectionNorm = (bookNorm - startNorm) / sectionSpan;
    return Math.max(0, Math.min(100, Math.round(sectionNorm * 100)));
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

window.addEventListener('locationchange',()=>{
    let newPos=calculateProgress();
    if (progressDiv) {
        // CW #3370 (@ryan-c-scott) backport: also show section progress
        // alongside the book percentage. Falls back to book-only if
        // section computation isn't ready yet (e.g. before
        // locations.generate() finishes).
        const sectionPct = calculateSectionProgress();
        if (sectionPct !== null) {
            progressDiv.textContent = sectionPct + "% (" + newPos + "% in book)";
        } else {
            progressDiv.textContent = newPos + "%";
        }
    }
    // Save progress to localStorage per book (book percentage — keep the
    // single-number contract so saved values stay readable across upgrades).
    if (window.calibre && window.calibre.bookUrl) {
        // Use bookUrl as a unique key, or use bookid if available
        let bookKey = window.calibre.bookUrl;
        localStorage.setItem("calibre.reader.progress." + bookKey, newPos);
    }
});

var epub=ePub(calibre.bookUrl)

let progressDiv=document.getElementById("progress");

qFinished(()=>{
    if (!epub || !epub.locations) {
        return;
    }
    epub.locations.generate().then(()=> {
        // Restore progress from localStorage if available
        if (window.calibre && window.calibre.bookUrl && reader && reader.rendition) {
            let bookKey = window.calibre.bookUrl;
            let savedProgress = localStorage.getItem("calibre.reader.progress." + bookKey);
            let hasBookmark = window.calibre.bookmark && window.calibre.bookmark.length > 0;
            if (savedProgress) {
                // Try to jump to the saved progress (percentage)
                let percentage = parseInt(savedProgress, 10) / 100;
                let cfi = epub.locations.cfiFromPercentage(percentage);
                if (cfi) {
                    reader.rendition.display(cfi);
                }
            } else if (!hasBookmark && window.calibre.kosyncPercent !== null && window.calibre.kosyncPercent !== undefined) {
                let kosyncPercent = parseFloat(window.calibre.kosyncPercent);
                if (!isNaN(kosyncPercent) && kosyncPercent > 0) {
                    let percentage = kosyncPercent / 100;
                    let cfi = epub.locations.cfiFromPercentage(percentage);
                    if (cfi) {
                        reader.rendition.display(cfi);
                    }
                }
            }
        }
        window.dispatchEvent(new Event('locationchange'))
    });
})
