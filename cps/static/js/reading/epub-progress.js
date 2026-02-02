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
        progressDiv.textContent=newPos+"%";
    }
    // Save progress to localStorage per book
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
            if (savedProgress) {
                // Try to jump to the saved progress (percentage)
                let percentage = parseInt(savedProgress, 10) / 100;
                let cfi = epub.locations.cfiFromPercentage(percentage);
                if (cfi) {
                    reader.rendition.display(cfi);
                }
            }
        }
        window.dispatchEvent(new Event('locationchange'))
    });
})
