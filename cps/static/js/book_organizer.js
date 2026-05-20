/* Book organizer — multi-select mode + bulk operations.
 *
 * Public API: window.BookOrganizer
 *   .enterSelectMode() / .exitSelectMode() / .toggleSelectMode() / .isSelectMode()
 *   .getSelectedIds() / .getSelectedBooks() / .clearSelection() / .selectAll()
 *   .on(event, fn)            'change' | 'enter' | 'exit'
 *
 * Bulk endpoints (server already implements these):
 *   POST /shelf/add_selected_to_shelf  { shelf_id, book_ids: [int] }
 *   POST /ajax/readselectedbooks       { selections: [int], markAsRead: bool }
 *   POST /ajax/deleteselectedbooks     { selections: [int] }
 *
 * The `data-organizer-action="cover-settings"` menu item is intentionally
 * a no-op here; another agent will wire it up to the real cover-settings UI.
 */
(function () {
  "use strict";

  var SELECT_MODE_CLASS = "book-organizer-select-mode";
  var SELECTED_CLASS = "is-selected";
  var BOOK_SELECTOR = ".book";
  var COVER_LINK_SELECTOR = ".book-cover-link";
  var META_LINK_SELECTOR = ".meta a";

  var listeners = { change: [], enter: [], exit: [] };
  var i18n = window.bookOrganizerI18n || {};

  function emit(event, payload) {
    (listeners[event] || []).forEach(function (fn) {
      try { fn(payload); } catch (e) { /* swallow */ }
    });
  }

  function on(event, fn) {
    if (!listeners[event]) listeners[event] = [];
    listeners[event].push(fn);
  }

  function getCsrfToken() {
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : "";
  }

  function fmt(template, params) {
    if (!template) return "";
    return template.replace(/\{(\w+)\}/g, function (_, k) {
      return params && params[k] !== undefined ? params[k] : "{" + k + "}";
    });
  }

  function getBooks() {
    return Array.prototype.slice.call(document.querySelectorAll(BOOK_SELECTOR));
  }

  function getSelectedBooks() {
    return getBooks().filter(function (b) {
      return b.classList.contains(SELECTED_CLASS);
    });
  }

  function getSelectedIds() {
    return getSelectedBooks()
      .map(function (b) {
        var link = b.querySelector(COVER_LINK_SELECTOR);
        return link ? link.getAttribute("data-book-id") : null;
      })
      .filter(Boolean);
  }

  function updateCount() {
    var n = getSelectedIds().length;
    document.querySelectorAll("[data-organizer-count]").forEach(function (el) {
      var template = el.getAttribute("data-template-selected") || "{n} selected";
      el.textContent = fmt(template, { n: n });
    });
    document.querySelectorAll(".book-organizer-actions-row").forEach(function (row) {
      row.classList.toggle("is-empty", n === 0);
    });
    emit("change", { count: n, ids: getSelectedIds() });
  }

  function ensureCheckboxOverlay(book) {
    var cover = book.querySelector(".cover");
    if (!cover) return;
    if (cover.querySelector(".book-organizer-checkbox")) return;
    var box = document.createElement("span");
    box.className = "book-organizer-checkbox";
    box.setAttribute("aria-hidden", "true");
    box.textContent = "✓";
    cover.appendChild(box);
  }

  function toggleBook(book) {
    book.classList.toggle(SELECTED_CLASS);
    updateCount();
  }

  function selectAll() {
    getBooks().forEach(function (b) {
      ensureCheckboxOverlay(b);
      b.classList.add(SELECTED_CLASS);
    });
    updateCount();
  }

  function clearSelection() {
    getBooks().forEach(function (b) {
      b.classList.remove(SELECTED_CLASS);
    });
    updateCount();
  }

  function isSelectMode() {
    return document.body.classList.contains(SELECT_MODE_CLASS);
  }

  function enterSelectMode() {
    if (isSelectMode()) return;
    getBooks().forEach(ensureCheckboxOverlay);
    document.body.classList.add(SELECT_MODE_CLASS);
    document
      .querySelectorAll(".book-organizer-multiselect-toggle")
      .forEach(function (btn) {
        btn.classList.add("active");
        btn.setAttribute("aria-pressed", "true");
      });
    document.querySelectorAll(".book-organizer-actions-row").forEach(function (row) {
      row.removeAttribute("hidden");
    });
    updateCount();
    emit("enter", null);
  }

  function exitSelectMode() {
    if (!isSelectMode()) return;
    clearSelection();
    document.body.classList.remove(SELECT_MODE_CLASS);
    document
      .querySelectorAll(".book-organizer-multiselect-toggle")
      .forEach(function (btn) {
        btn.classList.remove("active");
        btn.setAttribute("aria-pressed", "false");
      });
    document.querySelectorAll(".book-organizer-actions-row").forEach(function (row) {
      row.setAttribute("hidden", "");
    });
    emit("exit", null);
  }

  function toggleSelectMode() {
    if (isSelectMode()) exitSelectMode();
    else enterSelectMode();
  }

  // ---------- Confirmation dialog ----------

  function showConfirm(title, body, onOk) {
    var backdrop = document.getElementById("book-organizer-confirm-backdrop");
    if (!backdrop) {
      // No dialog available — fall back to native confirm.
      if (window.confirm(body)) onOk();
      return;
    }
    var titleEl = backdrop.querySelector("#book-organizer-confirm-title");
    var bodyEl = backdrop.querySelector("[data-organizer-confirm-body]");
    if (titleEl) titleEl.textContent = title;
    if (bodyEl) bodyEl.textContent = body;
    backdrop.removeAttribute("hidden");
    backdrop.classList.add("is-open");

    function close() {
      backdrop.classList.remove("is-open");
      backdrop.setAttribute("hidden", "");
      backdrop.removeEventListener("click", onBackdropClick);
    }
    function onBackdropClick(e) {
      var btn = e.target.closest("[data-organizer-confirm-action]");
      if (e.target === backdrop) {
        close();
        return;
      }
      if (!btn) return;
      var action = btn.getAttribute("data-organizer-confirm-action");
      close();
      if (action === "ok") onOk();
    }
    backdrop.addEventListener("click", onBackdropClick);
  }

  // ---------- Bulk operations ----------

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      return resp.text().then(function (text) {
        var data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { _raw: text }; }
        return { status: resp.status, ok: resp.ok, data: data };
      });
    });
  }

  function ensureFlash() {
    var holder = document.querySelector(".book-organizer-flash");
    if (holder) return holder;
    holder = document.createElement("div");
    holder.className = "book-organizer-flash";
    holder.setAttribute("role", "status");
    holder.setAttribute("aria-live", "polite");
    document.body.appendChild(holder);
    return holder;
  }

  function flash(msg, kind) {
    var holder = ensureFlash();
    holder.textContent = msg;
    holder.dataset.kind = kind || "success";
    holder.classList.add("is-visible");
    clearTimeout(holder._t);
    holder._t = setTimeout(function () {
      holder.classList.remove("is-visible");
    }, kind === "error" ? 6000 : 4000);
  }

  function flashSuccess(msg) { flash(msg, "success"); }
  function flashInfo(msg) { flash(msg, "info"); }
  function flashError(msg) { flash(msg, "error"); }

  // Fork #205: per-user "Hide shelf badges on covers" toggle wired to the
  // cog dropdown. Persists via the existing /ajax/view endpoint
  // (view_settings.cover.hide_shelf_badges) so no DB migration is needed.
  // Toggling the body class gives instant visual feedback; the server-rendered
  // class on the next page load keeps the state consistent across navigations.
  function toggleHideShelfBadges(actionEl) {
    var bodyEl = document.body;
    var isHidden = bodyEl.classList.contains("cover-hide-shelf-badges");
    var nextValue = !isHidden;
    if (nextValue) {
      bodyEl.classList.add("cover-hide-shelf-badges");
    } else {
      bodyEl.classList.remove("cover-hide-shelf-badges");
    }
    if (actionEl) {
      actionEl.setAttribute("aria-checked", nextValue ? "true" : "false");
      var mark = actionEl.querySelector(".book-organizer-settings-checkmark");
      if (mark) {
        mark.classList.remove("glyphicon-check", "glyphicon-unchecked");
        mark.classList.add(nextValue ? "glyphicon-check" : "glyphicon-unchecked");
      }
    }
    postJson("/ajax/view", { cover: { hide_shelf_badges: nextValue } })
      .catch(function () {
        // Server rejected the persist — revert UI so user state matches storage.
        if (nextValue) {
          bodyEl.classList.remove("cover-hide-shelf-badges");
        } else {
          bodyEl.classList.add("cover-hide-shelf-badges");
        }
        if (actionEl) {
          actionEl.setAttribute("aria-checked", isHidden ? "true" : "false");
          var m2 = actionEl.querySelector(".book-organizer-settings-checkmark");
          if (m2) {
            m2.classList.remove("glyphicon-check", "glyphicon-unchecked");
            m2.classList.add(isHidden ? "glyphicon-check" : "glyphicon-unchecked");
          }
        }
        flashError(i18n.coverSettingsSaveFailed || "Could not save cover display setting.");
      });
  }

  function bulkAddToShelf(shelfId, shelfName) {
    var ids = getSelectedIds().map(Number);
    if (!ids.length) {
      flashError(i18n.nothingSelected || "Select at least one book first.");
      return;
    }
    var n = ids.length;
    postJson("/shelf/add_selected_to_shelf", { shelf_id: Number(shelfId), book_ids: ids })
      .then(function (resp) {
        var data = resp.data || {};
        var added = data.added_count != null ? data.added_count : (resp.ok ? n : 0);
        var skipped = n - added;
        var allDuplicates = resp.status === 400 && skipped === n && (data.errors || []).every(
          function (e) { return /already in shelf/i.test(e); });

        if (allDuplicates) {
          flashInfo(fmt(i18n.allAlreadyOnShelf || "All {n} book(s) were already on {shelf}.",
                       { n: n, shelf: shelfName }));
          return;
        }
        if (resp.status === 200 || (resp.status === 207 && added === n)) {
          flashSuccess(fmt(i18n.addedToShelf, { n: added, shelf: shelfName }));
          return;
        }
        if (resp.status === 207 || (resp.ok === false && added > 0)) {
          flashInfo(fmt(i18n.addedToShelfPartial, { ok: added, n: n, shelf: shelfName }));
          return;
        }
        // Real error
        var msg = (data.errors && data.errors.length ? data.errors[0] : data.message) || ("HTTP " + resp.status);
        flashError(fmt(i18n.requestFailed, { err: msg }));
      })
      .catch(function (err) {
        flashError(fmt(i18n.requestFailed, { err: err.message || err }));
      });
  }

  function bulkMark(markAsRead) {
    var ids = getSelectedIds().map(Number);
    if (!ids.length) {
      flashError(i18n.nothingSelected || "Select at least one book first.");
      return;
    }
    var n = ids.length;
    postJson("/ajax/readselectedbooks", { selections: ids, markAsRead: !!markAsRead })
      .then(function (resp) {
        if (!resp.ok && resp.status !== 207) {
          var msg = (resp.data && resp.data.msg) || ("HTTP " + resp.status);
          flashError(fmt(i18n.requestFailed, { err: msg }));
          return;
        }
        var template = markAsRead ? i18n.markedRead : i18n.markedUnread;
        flashSuccess(fmt(template, { n: n }));
      })
      .catch(function (err) {
        flashError(fmt(i18n.requestFailed, { err: err.message || err }));
      });
  }

  function bulkDelete() {
    var ids = getSelectedIds().map(Number);
    if (!ids.length) {
      flashError(i18n.nothingSelected || "Select at least one book first.");
      return;
    }
    var n = ids.length;
    showConfirm(
      i18n.confirmDeleteTitle || "Delete books?",
      fmt(i18n.confirmDeleteBody || "This will permanently delete {n} book(s).", { n: n }),
      function () {
        postJson("/ajax/deleteselectedbooks", { selections: ids })
          .then(function (resp) {
            if (!resp.ok) {
              var msg = (resp.data && resp.data.msg) || ("HTTP " + resp.status);
              flashError(fmt(i18n.requestFailed, { err: msg }));
              return;
            }
            flashSuccess(fmt(i18n.deleted, { n: n }));
            setTimeout(function () { window.location.reload(); }, 600);
          })
          .catch(function (err) {
            flashError(fmt(i18n.requestFailed, { err: err.message || err }));
          });
      }
    );
  }

  // ---------- Event wiring ----------

  function onCoverClickCapture(e) {
    if (!isSelectMode()) return;
    var link =
      e.target.closest && (e.target.closest(COVER_LINK_SELECTOR) || e.target.closest(META_LINK_SELECTOR));
    if (!link) return;
    var book = link.closest(BOOK_SELECTOR);
    if (!book) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    toggleBook(book);
  }

  function onClick(e) {
    var multiselect =
      e.target.closest && e.target.closest(".book-organizer-multiselect-toggle");
    if (multiselect) {
      e.preventDefault();
      toggleSelectMode();
      return;
    }
    var actionEl =
      e.target.closest && e.target.closest("[data-organizer-action]");
    if (!actionEl) return;
    var action = actionEl.getAttribute("data-organizer-action");
    if (action === "exit") {
      e.preventDefault();
      exitSelectMode();
    } else if (action === "select-all") {
      e.preventDefault();
      selectAll();
    } else if (action === "clear") {
      e.preventDefault();
      clearSelection();
    } else if (action === "cover-settings") {
      // Legacy no-op kept for compatibility with the original menu markup.
      // The real toggle action below ("toggle-hide-shelf-badges") replaces it.
      e.preventDefault();
    } else if (action === "toggle-hide-shelf-badges") {
      e.preventDefault();
      e.stopPropagation();
      toggleHideShelfBadges(actionEl);
    } else if (action === "add-to-shelf") {
      e.preventDefault();
      var shelfId = actionEl.getAttribute("data-shelf-id");
      var shelfName = actionEl.getAttribute("data-shelf-name");
      bulkAddToShelf(shelfId, shelfName);
    } else if (action === "mark-read") {
      e.preventDefault();
      bulkMark(true);
    } else if (action === "mark-unread") {
      e.preventDefault();
      bulkMark(false);
    } else if (action === "delete-selected") {
      e.preventDefault();
      bulkDelete();
    }
  }

  function onKeydown(e) {
    if (e.key === "Escape" && isSelectMode()) {
      exitSelectMode();
    }
  }

  function init() {
    document.addEventListener("click", onCoverClickCapture, true);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeydown);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.BookOrganizer = {
    enterSelectMode: enterSelectMode,
    exitSelectMode: exitSelectMode,
    toggleSelectMode: toggleSelectMode,
    isSelectMode: isSelectMode,
    getSelectedIds: getSelectedIds,
    getSelectedBooks: getSelectedBooks,
    clearSelection: clearSelection,
    selectAll: selectAll,
    on: on,
  };
})();
