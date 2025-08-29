/**
 * waits until queue is finished, meaning the book is done loading
 * @param callback
 */
function qFinished(callback){
    let timeout=setInterval(()=>{
        if(reader.rendition.q.running===undefined)
            clearInterval(timeout);
            callback();
        },300
    )
}

function calculateProgress(){
    let data=reader.rendition.location.end;
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


async function saveProgressToAPI(bookId, cfi, page, percent) {
    try {
        await fetch('/api/progress/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                book_id: bookId,
                progress_cfi: cfi,
                progress_page: page,
                progress_percent: percent,
                device: navigator.userAgent
            })
        });
    } catch (e) {
        // Optionally log or ignore
    }
}

window.addEventListener('locationchange',()=>{
    let newPos=calculateProgress();
    progressDiv.textContent=newPos+"%";
    if (window.calibre && window.calibre.bookUrl) {
        let bookKey = window.calibre.bookUrl;
        // Save to localStorage
        localStorage.setItem("calibre.reader.progress." + bookKey, newPos);
        // Save to API
        let cfi = reader.rendition.location.end.cfi;
        let page = reader.rendition.location.end.displayed ? reader.rendition.location.end.displayed.page : null;
        saveProgressToAPI(bookKey, cfi, page, newPos);
    }
});

var epub=ePub(calibre.bookUrl)

let progressDiv=document.getElementById("progress");

qFinished(()=>{
    epub.locations.generate().then(async ()=> {
        if (window.calibre && window.calibre.bookUrl) {
            let bookKey = window.calibre.bookUrl;
            // Try to restore from API first
            let restored = false;
            try {
                let resp = await fetch(`/api/progress/get?book_id=${encodeURIComponent(bookKey)}`);
                if (resp.ok) {
                    let data = await resp.json();
                    if (data.progress_cfi) {
                        reader.rendition.display(data.progress_cfi);
                        restored = true;
                    } else if (data.progress_page) {
                        // If you have page logic, implement here
                        // Example: reader.rendition.displayPage(data.progress_page);
                        restored = true;
                    } else if (data.progress_percent) {
                        let percentage = parseInt(data.progress_percent, 10) / 100;
                        let cfi = epub.locations.cfiFromPercentage(percentage);
                        if (cfi) {
                            reader.rendition.display(cfi);
                            restored = true;
                        }
                    }
                }
            } catch (e) {}
            // Fallback to localStorage if nothing restored
            if (!restored) {
                let savedProgress = localStorage.getItem("calibre.reader.progress." + bookKey);
                if (savedProgress) {
                    let percentage = parseInt(savedProgress, 10) / 100;
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
