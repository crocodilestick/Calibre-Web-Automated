/**
 * waits until queue is finished, meaning the book is done loading
 * @param callback
 */
function qFinished(callback){
    clearProgress();
    let bookLoadingInterval=setInterval(()=>{
        if (reader && reader.rendition && reader.rendition.q && reader.rendition.q.running === undefined) {
            clearInterval(bookLoadingInterval);
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
    console.log("last location on page: " + data.cfi);
    console.log("epub.locations.length(): " + epub.locations.length());
    if (!data || !data.cfi || !epub || !epub.locations) {
        return 0;
    }
    let percentageFromCfi = epub.locations.percentageFromCfi(data.cfi);
    // console.log("percentageFromCfi: " + percentageFromCfi);
    let progress = Math.round(epub.locations.percentageFromCfi(data.cfi) * 100);
    // console.log("progress: " + progress);
    return progress;
}

function clearProgress() {
    if (progressDiv) {
        progressDiv.textContent="";
    }
}

function updateCurrentPosition() {
    let newPos = calculateProgress();
    if (progressDiv) {
        progressDiv.textContent = newPos ? newPos+"%" : "";
    }
    // Save progress to localStorage per book
    if (window.calibre && window.calibre.bookUrl && newPos && newPos > 0) {
        // Use bookUrl as a unique key, or use bookid if available
        console.log("Storing progress: " + newPos);
        let bookKey = window.calibre.bookUrl;
        localStorage.setItem("calibre.reader.progress." + bookKey, newPos);
    }
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
    // If location changes, abort attempt to restore progress.
    clearInterval(restoreProgressInterval);
    if (!epub.locations.isReady) {
        clearProgress();
        return;
    }
    updateCurrentPosition();
});

var epub=ePub(calibre.bookUrl)

let progressDiv=document.getElementById("progress");

function restoreProgressWithLocations(locations) {
    // Restore progress: from localStorage if available, using kosync progress
    // as a fallback, with bookmark as last resort.
    if (window.calibre && window.calibre.bookUrl && reader && reader.rendition) {
        let bookKey = window.calibre.bookUrl;
        let savedProgress = parseInt(localStorage.getItem("calibre.reader.progress." + bookKey))
        let kosyncProgress = parseFloat(window.calibre.kosyncPercent);
        console.log("savedProgress: " + savedProgress);
        console.log("kosyncProgress: " + kosyncProgress);
        let progress = savedProgress || kosyncProgress
        console.log("About to advance to progress: " + progress);
        let percentage = progress && (parseInt(progress, 10) / 100);
        console.log("Progress percentage is: " + percentage);
        let percentageCfi = locations.cfiFromPercentage(percentage);
        console.log("percentageCfi: " + percentageCfi);
        console.log("bookmark: " + window.calibre.bookmark);
        let cfi = (percentageCfi !== -1 && percentageCfi) || window.calibre.bookmark;
        console.log("Advancing to cfi: " + cfi);
        if (cfi && cfi.length > 0) {
            reader.rendition.display(cfi);
            console.log("Advanced to cfi: " + cfi);
        }
        window.dispatchEvent(new Event('locationchange'))
    }
}

// Track attempt to restore progress
let restoreProgressInterval = null;

qFinished(()=>{
    if (!epub || !epub.locations) {
        return;
    }
    if (epub.locations.length() == 0) {
        epub.locations.generate().then(()=> {
            console.log("Locations generated promise resolved.");
            // The `epub.locations.generate()` promise resolves before the locations
            // have completed being added, so we must poll until they are all
            // there.
            let attempt = 0;
            let pollingFrequency = 100;
            let retryAfter = 10;
            let subsequentRetryAfter = 50;
            epub.locations.isReady = false;
            restoreProgressInterval=setInterval(()=> {
                attempt = attempt + 1;
                if (progressDiv) {
                    progressDiv.textContent="Restoring Position [" + (attempt % 2 == 0 ? "/" : "\\") + "]"
                }
                let count = epub.locations.length();
                let total = epub.locations.total;
                console.log("count and total: " + count + " (" + total + ")");
                // Handle off-by-one issue with total
                let isReady = count > 0 && (count - total == 1);
                if (isReady) {
                    console.log("Locations now available...")
                    epub.locations.isReady = true;
                    clearInterval(restoreProgressInterval);
                    restoreProgressWithLocations(epub.locations);
                } else {
                    // Under some conditions, `epub.locations.generate()` appears
                    // not to start adding locations at all, so try it again if
                    // we have not seen any progress after a few attempts.
                    if (count == 0 && (attempt % retryAfter) == 0) {
                        console.log("Locations not available and still empty, regenerating...")
                        // Don't want to unnecessarily attempt to re-generate too often.
                        retryAfter = subsequentRetryAfter;
                        epub.locations.generate();
                    }
                }
            }, pollingFrequency);
        });
    } else {
        console.log("Locations already generated");
        restoreProgressWithLocations(epub.locations);
    }
})
