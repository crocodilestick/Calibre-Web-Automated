(function() {
    "use strict";

    var config = window.CWA_PDF_READER;
    if (!config) {
        return;
    }

    var state = sanitizeState(config.initialState);
    var notes = sanitizeNotes(readJson(config.notesStorageKey, []));
    var app = null;
    var currentPage = Number(state.page_number) || 1;
    var editingNoteId = null;
    var restoring = true;
    var saveTimer = null;
    var serverThemeReloaded = false;

    var elements = {
        panel: document.getElementById("cwaNotesPanel"),
        toggle: document.getElementById("cwaNotesToggle"),
        close: document.getElementById("cwaNotesClose"),
        currentPage: document.getElementById("cwaCurrentPage"),
        syncStatus: document.getElementById("cwaSyncStatus"),
        form: document.getElementById("cwaNoteForm"),
        body: document.getElementById("cwaNoteBody"),
        save: document.getElementById("cwaNoteSave"),
        cancel: document.getElementById("cwaNoteCancel"),
        list: document.getElementById("cwaNotesList"),
        empty: document.getElementById("cwaNotesEmpty"),
        count: document.getElementById("cwaNotesCount"),
        theme: document.getElementById("cwaThemeSelect")
    };

    function readJson(key, fallback) {
        try {
            var value = JSON.parse(localStorage.getItem(key) || "null");
            return value === null ? fallback : value;
        } catch (error) {
            return fallback;
        }
    }

    function writeJson(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (error) {
            setStatus("Could not save locally", "error");
        }
    }

    function isPlainObject(value) {
        return Boolean(value) && Object.prototype.toString.call(value) === "[object Object]";
    }

    function validScaleValue(value) {
        if (typeof value !== "string") {
            return false;
        }
        if (/^(auto|page-actual|page-fit|page-width)$/.test(value)) {
            return true;
        }
        if (!/^\d+(?:\.\d+)?$/.test(value)) {
            return false;
        }
        var numericScale = Number(value);
        return numericScale >= 0.1 && numericScale <= 10;
    }

    function sanitizeState(value) {
        var candidate = isPlainObject(value) ? value : {};
        var clean = {
            page_number: 1,
            scale_value: "auto",
            rotation: 0,
            sidebar_view: 1,
            sidebar_open: false,
            notes_open: false,
            theme: config.initialTheme || "system"
        };
        if (Number.isInteger(candidate.page_number) && candidate.page_number >= 1 && candidate.page_number <= 1000000) {
            clean.page_number = candidate.page_number;
        }
        if (validScaleValue(candidate.scale_value)) {
            clean.scale_value = candidate.scale_value;
        }
        if ([0, 90, 180, 270].indexOf(candidate.rotation) >= 0) {
            clean.rotation = candidate.rotation;
        }
        if (Number.isInteger(candidate.sidebar_view) && candidate.sidebar_view >= 0 && candidate.sidebar_view <= 4) {
            clean.sidebar_view = candidate.sidebar_view;
        }
        if (typeof candidate.sidebar_open === "boolean") {
            clean.sidebar_open = candidate.sidebar_open;
        }
        if (typeof candidate.notes_open === "boolean") {
            clean.notes_open = candidate.notes_open;
        }
        if (["system", "light", "sepia", "dark"].indexOf(candidate.theme) >= 0) {
            clean.theme = candidate.theme;
        }
        return clean;
    }

    function sanitizeNotes(value) {
        if (!Array.isArray(value)) {
            return [];
        }
        return value.filter(function(note) {
            return isPlainObject(note) &&
                (typeof note.id === "number" || typeof note.id === "string") &&
                Number.isInteger(note.page_number) &&
                note.page_number >= 1 && note.page_number <= 1000000 &&
                typeof note.body === "string" && note.body.trim().length > 0;
        }).map(function(note) {
            return Object.assign({}, note, {
                color: ["yellow", "green", "blue", "pink", "purple"].indexOf(note.color) >= 0
                    ? note.color
                    : "yellow"
            });
        });
    }

    function setStatus(message, status) {
        elements.syncStatus.textContent = message;
        elements.syncStatus.dataset.state = status || "idle";
    }

    function request(url, options) {
        var requestOptions = Object.assign({
            credentials: "same-origin",
            headers: {"Accept": "application/json"}
        }, options || {});
        if (requestOptions.body) {
            requestOptions.headers["Content-Type"] = "application/json";
        }
        if (requestOptions.method && !/^(GET|HEAD|OPTIONS)$/i.test(requestOptions.method)) {
            requestOptions.headers["X-CSRFToken"] = config.csrfToken;
        }
        return fetch(url, requestOptions).then(function(response) {
            if (!response.ok) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    throw new Error(data.error || "Request failed");
                });
            }
            if (response.status === 204) {
                return null;
            }
            return response.json();
        });
    }

    function noteUrl(noteId) {
        return config.notesUrl + "/" + encodeURIComponent(noteId);
    }

    function resolvedTheme(theme) {
        if (theme === "system") {
            return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        }
        return theme;
    }

    function annotationChangesExist() {
        try {
            return Boolean(app && app.pdfDocument && app.pdfDocument.annotationStorage.size);
        } catch (error) {
            return false;
        }
    }

    function collectState() {
        if (!app || !app.pdfViewer) {
            return state;
        }
        var scale = String(app.pdfViewer.currentScaleValue || state.scale_value || "auto");
        if (!validScaleValue(scale)) {
            scale = "auto";
        }
        state = {
            page_number: app.pdfViewer.currentPageNumber || currentPage || 1,
            scale_value: scale,
            rotation: app.pdfViewer.pagesRotation || 0,
            sidebar_view: app.pdfSidebar ? (app.pdfSidebar.active || 1) : 1,
            sidebar_open: Boolean(app.pdfSidebar && app.pdfSidebar.isOpen),
            notes_open: document.body.classList.contains("cwaNotesOpen"),
            theme: state.theme || "system"
        };
        return state;
    }

    function persistState(options) {
        options = options || {};
        var nextState = collectState();
        writeJson(config.storageKey, nextState);
        if (!config.authenticated) {
            if (!options.quiet) {
                setStatus("On this device", "idle");
            }
            return Promise.resolve(nextState);
        }
        if (!options.quiet) {
            setStatus("Saving…", "saving");
        }
        return request(config.stateUrl, {
            method: "PUT",
            body: JSON.stringify({state: nextState}),
            keepalive: Boolean(options.keepalive)
        }).then(function(data) {
            if (!options.quiet) {
                setStatus("Synced", "idle");
            }
            return data.state;
        }).catch(function(error) {
            if (!options.quiet) {
                setStatus("Saved on this device", "error");
            }
            throw error;
        });
    }

    function scheduleStateSave() {
        if (restoring) {
            return;
        }
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(function() {
            persistState().catch(function() {});
        }, 650);
    }

    function setNotesOpen(open, save) {
        document.body.classList.toggle("cwaNotesOpen", open);
        elements.panel.setAttribute("aria-hidden", String(!open));
        elements.toggle.setAttribute("aria-expanded", String(open));
        state.notes_open = open;
        if (open) {
            window.setTimeout(function() { elements.body.focus(); }, 180);
        }
        if (save !== false) {
            scheduleStateSave();
        }
    }

    function setCurrentPage(pageNumber) {
        currentPage = Number(pageNumber) || 1;
        elements.currentPage.textContent = "Page " + currentPage;
        renderNotes();
    }

    function goToPage(pageNumber) {
        if (app && app.pdfViewer) {
            app.pdfViewer.currentPageNumber = Number(pageNumber) || 1;
            document.getElementById("viewerContainer").focus();
        }
    }

    function selectedColor() {
        var checked = elements.form.querySelector("input[name='noteColor']:checked");
        return checked ? checked.value : "yellow";
    }

    function setSelectedColor(color) {
        var input = elements.form.querySelector("input[name='noteColor'][value='" + color + "']");
        if (input) {
            input.checked = true;
        }
    }

    function resetComposer() {
        editingNoteId = null;
        elements.form.reset();
        setSelectedColor("yellow");
        elements.save.textContent = "Add note";
        elements.cancel.hidden = true;
    }

    function startEditing(note) {
        editingNoteId = note.id;
        elements.body.value = note.body;
        setSelectedColor(note.color);
        elements.save.textContent = "Update note";
        elements.cancel.hidden = false;
        setNotesOpen(true, false);
        elements.body.focus();
    }

    function cacheNotes() {
        notes.sort(function(a, b) {
            return a.page_number - b.page_number || String(a.id).localeCompare(String(b.id));
        });
        writeJson(config.notesStorageKey, notes);
        renderNotes();
    }

    function renderNotes() {
        elements.list.replaceChildren();
        elements.count.textContent = String(notes.length);
        elements.empty.hidden = notes.length > 0;

        notes.forEach(function(note) {
            var card = document.createElement("article");
            card.className = "cwaNoteCard cwaColor-" + note.color;
            card.dataset.current = String(Number(note.page_number) === currentPage);

            var header = document.createElement("div");
            header.className = "cwaNoteCardHeader";

            var page = document.createElement("button");
            page.type = "button";
            page.className = "cwaNotePageButton";
            page.textContent = "Page " + note.page_number;
            page.addEventListener("click", function() { goToPage(note.page_number); });

            var actions = document.createElement("div");
            actions.className = "cwaNoteCardActions";
            var edit = document.createElement("button");
            edit.type = "button";
            edit.className = "cwaNoteAction";
            edit.textContent = "Edit";
            edit.addEventListener("click", function() { startEditing(note); });
            var remove = document.createElement("button");
            remove.type = "button";
            remove.className = "cwaNoteAction";
            remove.textContent = "Delete";
            remove.addEventListener("click", function() { deleteNote(note); });
            actions.append(edit, remove);
            header.append(page, actions);

            var body = document.createElement("p");
            body.className = "cwaNoteCardBody";
            body.textContent = note.body;
            card.append(header, body);
            elements.list.appendChild(card);
        });
    }

    function createLocalNote(values) {
        var now = new Date().toISOString();
        return Object.assign({
            id: "local-" + Date.now() + "-" + Math.random().toString(16).slice(2),
            created_at: now,
            updated_at: now
        }, values);
    }

    function saveNote(values) {
        var existing = editingNoteId !== null
            ? notes.find(function(note) { return String(note.id) === String(editingNoteId); })
            : null;

        if (!config.authenticated) {
            if (existing) {
                Object.assign(existing, values, {updated_at: new Date().toISOString()});
            } else {
                notes.push(createLocalNote(values));
            }
            cacheNotes();
            resetComposer();
            setStatus("On this device", "idle");
            return Promise.resolve();
        }

        setStatus("Saving…", "saving");
        return request(existing ? noteUrl(existing.id) : config.notesUrl, {
            method: existing ? "PATCH" : "POST",
            body: JSON.stringify(values)
        }).then(function(data) {
            if (existing) {
                Object.assign(existing, data.note);
            } else {
                notes.push(data.note);
            }
            cacheNotes();
            resetComposer();
            setStatus("Synced", "idle");
        }).catch(function(error) {
            setStatus(error.message || "Could not save note", "error");
            throw error;
        });
    }

    function deleteNote(note) {
        if (!window.confirm("Delete this page note?")) {
            return;
        }
        function removeCachedNote() {
            notes = notes.filter(function(candidate) { return String(candidate.id) !== String(note.id); });
            if (String(editingNoteId) === String(note.id)) {
                resetComposer();
            }
            cacheNotes();
        }
        if (!config.authenticated) {
            removeCachedNote();
            return;
        }
        setStatus("Saving…", "saving");
        request(noteUrl(note.id), {method: "DELETE"}).then(function() {
            removeCachedNote();
            setStatus("Synced", "idle");
        }).catch(function(error) {
            setStatus(error.message || "Could not delete note", "error");
        });
    }

    function applyState(nextState) {
        state = sanitizeState(Object.assign({}, state, isPlainObject(nextState) ? nextState : {}));
        writeJson(config.storageKey, state);
        elements.theme.value = state.theme || "system";
        setNotesOpen(Boolean(state.notes_open), false);

        if (!app || !app.pdfViewer) {
            return;
        }
        if ([0, 90, 180, 270].indexOf(Number(state.rotation)) >= 0) {
            app.pdfViewer.pagesRotation = Number(state.rotation);
        }
        if (state.scale_value) {
            app.pdfViewer.currentScaleValue = state.scale_value;
        }
        if (Number(state.page_number) > 0) {
            app.pdfViewer.currentPageNumber = Number(state.page_number);
        }
        if (app.pdfSidebar) {
            if (state.sidebar_open) {
                app.pdfSidebar.switchView(Number(state.sidebar_view) || 1, true);
            } else {
                app.pdfSidebar.close();
            }
        }
        setCurrentPage(app.pdfViewer.currentPageNumber);
    }

    function loadRemoteData() {
        if (!config.authenticated) {
            applyState(state);
            renderNotes();
            setStatus("On this device", "idle");
            return Promise.resolve();
        }
        setStatus("Syncing…", "saving");
        return Promise.all([
            request(config.stateUrl),
            request(config.notesUrl)
        ]).then(function(results) {
            var remoteState = sanitizeState(results[0].state);
            var remoteTheme = remoteState.theme || state.theme || "system";
            notes = sanitizeNotes(results[1].notes);
            cacheNotes();

            if (!serverThemeReloaded && resolvedTheme(remoteTheme) !== config.resolvedTheme) {
                serverThemeReloaded = true;
                state = Object.assign(state, remoteState, {theme: remoteTheme});
                writeJson(config.storageKey, state);
                window.location.reload();
                return;
            }
            applyState(remoteState);
            setStatus("Synced", "idle");
        }).catch(function() {
            applyState(state);
            renderNotes();
            setStatus("Using device copy", "error");
        });
    }

    function bindViewer() {
        app = window.PDFViewerApplication;
        if (!app) {
            return;
        }
        app.initializedPromise.then(function() {
            var eventBus = app.eventBus;
            eventBus.on("pagechanging", function(event) {
                setCurrentPage(event.pageNumber);
                scheduleStateSave();
            });
            eventBus.on("scalechanging", scheduleStateSave);
            eventBus.on("rotationchanging", scheduleStateSave);
            eventBus.on("sidebarviewchanged", scheduleStateSave);
            eventBus.on("documentloaded", function() {
                loadRemoteData().finally(function() {
                    restoring = false;
                });
            });
        });
    }

    elements.toggle.addEventListener("click", function() {
        setNotesOpen(!document.body.classList.contains("cwaNotesOpen"));
    });
    elements.close.addEventListener("click", function() { setNotesOpen(false); });
    elements.cancel.addEventListener("click", resetComposer);
    elements.form.addEventListener("submit", function(event) {
        event.preventDefault();
        var body = elements.body.value.trim();
        if (!body) {
            elements.body.focus();
            return;
        }
        var existing = editingNoteId !== null
            ? notes.find(function(note) { return String(note.id) === String(editingNoteId); })
            : null;
        saveNote({
            page_number: existing ? existing.page_number : currentPage,
            body: body,
            color: selectedColor()
        }).catch(function() {});
    });
    elements.theme.value = state.theme || "system";
    elements.theme.addEventListener("change", function() {
        var nextTheme = elements.theme.value;
        if (nextTheme === state.theme) {
            return;
        }
        if (annotationChangesExist() && !window.confirm(
            "Changing theme reloads the reader. Save your annotated PDF first, or continue and discard unsaved PDF annotations."
        )) {
            elements.theme.value = state.theme;
            return;
        }
        state.theme = nextTheme;
        document.documentElement.dataset.cwaTheme = resolvedTheme(nextTheme);
        writeJson(config.storageKey, collectState());
        persistState().catch(function() {}).finally(function() {
            window.location.reload();
        });
    });
    function flushState() {
        window.clearTimeout(saveTimer);
        persistState({keepalive: true, quiet: true}).catch(function() {});
    }

    document.addEventListener("visibilitychange", function() {
        if (document.visibilityState === "hidden") {
            flushState();
        }
    });
    window.addEventListener("pagehide", flushState);
    window.addEventListener("webviewerloaded", bindViewer, {once: true});

    renderNotes();
    setNotesOpen(Boolean(state.notes_open), false);
    setCurrentPage(currentPage);
})();
