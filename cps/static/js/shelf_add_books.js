/* Calibre-Web-NextGen — "Add books" picker for the shelf page.
 *
 * Opens a modal from the shelf's "Add Books" button, live-searches the library
 * via GET /shelf/<id>/available_books (books already on the shelf come back
 * flagged and are shown disabled), lets the user multi-select, and POSTs the
 * chosen ids to /shelf/add_selected_to_shelf — the one server-side write path,
 * which validates + dedupes. i18n strings come from data-* on the modal so the
 * script needs no build-time translation.
 */
(function () {
  "use strict";

  var btn = document.getElementById("add_books_to_shelf");
  var modal = document.getElementById("addBooksModal");
  if (!btn || !modal) {
    return;
  }

  var searchInput = document.getElementById("addBooksSearch");
  var resultsEl = document.getElementById("addBooksResults");
  var emptyEl = document.getElementById("addBooksEmpty");
  var countEl = document.getElementById("addBooksCount");
  var submitBtn = document.getElementById("addBooksSubmit");
  var shelfNameEl = document.getElementById("addBooksShelfName");
  var errorEl = document.getElementById("addBooksError");

  var shelfId = Number(btn.getAttribute("data-shelf-id"));
  var availableUrl = btn.getAttribute("data-available-url");
  var addUrl = btn.getAttribute("data-add-url");

  var i18n = {
    selected: modal.getAttribute("data-i18n-selected") || "{count} selected",
    add: modal.getAttribute("data-i18n-add") || "Add",
    addN: modal.getAttribute("data-i18n-add-n") || "Add {count}",
    empty: modal.getAttribute("data-i18n-empty") || "No books found.",
    added: modal.getAttribute("data-i18n-added") || "Already on this shelf",
    error: modal.getAttribute("data-i18n-error") || "Could not add the books. Please try again."
  };

  var selected = new Set();
  var debounceTimer = null;
  var requestSeq = 0;

  function fmt(template, count) {
    return String(template).replace("{count}", count);
  }

  function csrfToken() {
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : "";
  }

  function updateFooter() {
    var n = selected.size;
    countEl.textContent = fmt(i18n.selected, n);
    submitBtn.disabled = n === 0;
    submitBtn.textContent = n > 0 ? fmt(i18n.addN, n) : i18n.add;
  }

  function setError(message) {
    if (!errorEl) {
      return;
    }
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function makeRow(book) {
    var row = document.createElement("button");
    row.type = "button";
    row.className = "add-books-row" + (book.in_shelf ? " is-in-shelf" : "");
    row.setAttribute("data-book-id", book.id);
    row.setAttribute("role", "option");
    if (book.in_shelf) {
      row.disabled = true;
      row.setAttribute("aria-disabled", "true");
    }
    if (selected.has(book.id)) {
      row.classList.add("is-selected");
    }
    row.setAttribute("aria-selected", selected.has(book.id) ? "true" : "false");

    var img = document.createElement("img");
    img.className = "add-books-cover";
    img.src = book.cover;
    img.alt = "";
    img.loading = "lazy";

    var meta = document.createElement("span");
    meta.className = "add-books-meta";
    var title = document.createElement("span");
    title.className = "add-books-title";
    title.textContent = book.title;
    var author = document.createElement("span");
    author.className = "add-books-author";
    author.textContent = book.in_shelf ? i18n.added : book.authors;
    meta.appendChild(title);
    meta.appendChild(author);

    var check = document.createElement("span");
    check.className = "add-books-check glyphicon";

    row.appendChild(img);
    row.appendChild(meta);
    row.appendChild(check);

    if (!book.in_shelf) {
      row.addEventListener("click", function () {
        toggle(book.id, row);
      });
    }
    return row;
  }

  function toggle(bookId, row) {
    if (selected.has(bookId)) {
      selected.delete(bookId);
      row.classList.remove("is-selected");
      row.setAttribute("aria-selected", "false");
    } else {
      selected.add(bookId);
      row.classList.add("is-selected");
      row.setAttribute("aria-selected", "true");
    }
    updateFooter();
  }

  function render(books) {
    resultsEl.innerHTML = "";
    if (!books.length) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;
    var frag = document.createDocumentFragment();
    books.forEach(function (book) {
      frag.appendChild(makeRow(book));
    });
    resultsEl.appendChild(frag);
  }

  function search(query) {
    var seq = ++requestSeq;
    resultsEl.setAttribute("aria-busy", "true");
    fetch(availableUrl + "?query=" + encodeURIComponent(query), {
      headers: { "Accept": "application/json" },
      credentials: "same-origin"
    })
      .then(function (r) {
        return r.ok ? r.json() : Promise.reject(r.status);
      })
      .then(function (data) {
        if (seq !== requestSeq) {
          return; // a newer search superseded this one
        }
        render((data && data.books) || []);
      })
      .catch(function () {
        if (seq === requestSeq) {
          render([]);
        }
      })
      .then(function () {
        resultsEl.removeAttribute("aria-busy");
      });
  }

  function openModal() {
    selected.clear();
    setError("");
    updateFooter();
    shelfNameEl.textContent = btn.getAttribute("data-shelf-name") || "";
    searchInput.value = "";
    resultsEl.innerHTML = "";
    emptyEl.hidden = true;
    search("");
    if (window.jQuery && window.jQuery(modal).modal) {
      window.jQuery(modal).modal("show");
    } else {
      modal.classList.add("in");
      modal.style.display = "block";
    }
    setTimeout(function () {
      searchInput.focus();
    }, 250);
  }

  function closeModal() {
    if (window.jQuery && window.jQuery(modal).modal) {
      window.jQuery(modal).modal("hide");
    } else {
      modal.classList.remove("in");
      modal.style.display = "none";
    }
  }

  function submit() {
    if (!selected.size) {
      return;
    }
    submitBtn.disabled = true;
    setError("");
    fetch(addUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
      body: JSON.stringify({ shelf_id: shelfId, book_ids: Array.from(selected) })
    })
      .then(function (r) {
        return r.json().then(
          function (d) { return { status: r.status, data: d }; },
          function () { return { status: r.status, data: {} }; }
        );
      })
      .then(function (res) {
        if (res.status >= 200 && res.status < 300) {
          // 200 success or 207 partial — the added books appear on the reloaded
          // shelf; any already-present ones were skipped server-side.
          closeModal();
          window.location.reload();
        } else {
          // 400 / 403 / 500 (e.g. a session that expired while the picker was
          // open): keep the picker open and surface the failure instead of
          // silently closing + reloading with nothing added.
          setError((res.data && res.data.message) || i18n.error);
          submitBtn.disabled = selected.size === 0;
        }
      })
      .catch(function () {
        setError(i18n.error);
        submitBtn.disabled = selected.size === 0;
      });
  }

  btn.addEventListener("click", openModal);
  submitBtn.addEventListener("click", submit);
  searchInput.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    var q = searchInput.value.trim();
    debounceTimer = setTimeout(function () {
      search(q);
    }, 250);
  });
})();
