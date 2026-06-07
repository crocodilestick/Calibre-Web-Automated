/* This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
 *    Copyright (C) 2018 jkrehm, OzzieIsaacs
 *    Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program. If not, see <http://www.gnu.org/licenses/>.
 */

/* Shelf reorder as a responsive cover grid (fork #320, @SpookyUSAF +
 * @droM4X's save-on-drop suggestion).
 *
 * Input modalities:
 *  - Mouse: drag a cover between two others (Sortable.js, grid-aware).
 *  - Touch: long-press (150ms) then drag — plain swipes keep scrolling,
 *    so reordering never fights the scroll gesture.
 *  - Keyboard: Tab focuses a cover; arrow keys move it one position;
 *    changes are announced via the aria-live status line.
 *
 * Every change saves automatically (debounced 400ms) via JSON POST to the
 * data-save-url; failures surface in the status line, which becomes a
 * click-to-retry control. No Save button.
 */

/* global Sortable */

(function () {
    "use strict";

    var grid = document.getElementById("reorder-grid");
    if (!grid || typeof Sortable === "undefined") {
        return;
    }
    var statusEl = document.getElementById("reorder-status");
    var saveUrl = grid.getAttribute("data-save-url");
    var saveTimer = null;
    var ITEM_SELECTOR = ".reorder-item";

    function text(name) {
        return statusEl ? (statusEl.getAttribute("data-" + name + "-text") || "") : "";
    }

    function getCsrfToken() {
        var el = document.querySelector("input[name='csrf_token']");
        return el ? el.value : "";
    }

    function currentOrder() {
        var ids = [];
        var items = grid.querySelectorAll(ITEM_SELECTOR);
        for (var i = 0; i < items.length; i++) {
            ids.push(parseInt(items[i].getAttribute("data-book-id"), 10));
        }
        return ids;
    }

    function setStatus(message, isError) {
        if (!statusEl) {
            return;
        }
        statusEl.textContent = message || " ";
        statusEl.classList.toggle("reorder-error", !!isError);
    }

    function persist() {
        setStatus(text("saving"), false);
        fetch(saveUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken()
            },
            body: JSON.stringify({order: currentOrder()})
        }).then(function (response) {
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
            return response.json();
        }).then(function () {
            setStatus(text("saved"), false);
        }).catch(function () {
            // The status line doubles as the retry control while in error.
            setStatus(text("error"), true);
        });
    }

    function schedulePersist() {
        if (saveTimer) {
            window.clearTimeout(saveTimer);
        }
        saveTimer = window.setTimeout(persist, 400);
    }

    if (statusEl) {
        statusEl.addEventListener("click", function () {
            if (statusEl.classList.contains("reorder-error")) {
                persist();
            }
        });
    }

    Sortable.create(grid, {
        animation: 150,
        draggable: ITEM_SELECTOR,
        // Long-press to lift on touch devices so a plain swipe scrolls the
        // page instead of grabbing a cover; immediate on mouse.
        delay: 150,
        delayOnTouchOnly: true,
        touchStartThreshold: 4,
        ghostClass: "reorder-ghost",
        chosenClass: "reorder-chosen",
        onEnd: schedulePersist
    });

    function announceMove(card) {
        var items = Array.prototype.slice.call(grid.querySelectorAll(ITEM_SELECTOR));
        var pos = items.indexOf(card) + 1;
        var template = text("moved");
        setStatus(template.replace("__POS__", String(pos)).replace("__TOTAL__", String(items.length)), false);
    }

    grid.addEventListener("keydown", function (event) {
        var card = event.target.closest ? event.target.closest(ITEM_SELECTOR) : null;
        if (!card) {
            return;
        }
        var key = event.key;
        if (key === "ArrowLeft" || key === "ArrowUp") {
            var prev = card.previousElementSibling;
            if (prev) {
                grid.insertBefore(card, prev);
            }
        } else if (key === "ArrowRight" || key === "ArrowDown") {
            var next = card.nextElementSibling;
            if (next) {
                grid.insertBefore(next, card);
            }
        } else {
            return;
        }
        event.preventDefault();
        card.focus();
        announceMove(card);
        schedulePersist();
    });
})();
