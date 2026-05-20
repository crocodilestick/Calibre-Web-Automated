/* This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
 *    Copyright (C) 2018  idalin<dalin.lin@gmail.com>
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
/* global _, i18nMsg, tinymce, getPath */

$(function () {
  var msg = i18nMsg;
  var keyword = "";
  var metaSelectionKey = "cwa.metaSelection";
  var metaSelectionCache = null;
  var metaAlertTimer = null;

  var templates = {
    bookResult: _.template($("#template-book-result").html()),
  };

  function isLocalStorageAvailable() {
    try {
      var testKey = "__cwa_meta_test__";
      localStorage.setItem(testKey, "1");
      localStorage.removeItem(testKey);
      return true;
    } catch (e) {
      return false;
    }
  }

  function getMetaSelections() {
    if (metaSelectionCache !== null) {
      return metaSelectionCache;
    }
    if (!isLocalStorageAvailable()) {
      metaSelectionCache = {};
      return metaSelectionCache;
    }
    try {
      var stored = localStorage.getItem(metaSelectionKey);
      metaSelectionCache = stored ? JSON.parse(stored) : {};
      if (typeof metaSelectionCache !== "object" || metaSelectionCache === null) {
        metaSelectionCache = {};
      }
    } catch (e) {
      metaSelectionCache = {};
    }
    return metaSelectionCache;
  }

  function setMetaSelection(key, value) {
    var selections = getMetaSelections();
    selections[key] = value;
    if (!isLocalStorageAvailable()) {
      return;
    }
    try {
      localStorage.setItem(metaSelectionKey, JSON.stringify(selections));
    } catch (e) {
      // Ignore storage failures (quota/private mode)
    }
  }

  function applyMetaSelections(container) {
    var selections = getMetaSelections();
    container
      .find('input[type="checkbox"][data-meta-value]')
      .each(function () {
        var key = $(this).data("meta-value");
        if (Object.prototype.hasOwnProperty.call(selections, key)) {
          $(this).prop("checked", selections[key]);
        }
      });
  }

  function getUniqueValues(attribute_name, book) {
    var presentArray = $.map(
      $("#" + attribute_name)
        .val()
        .split(","),
      $.trim
    );
    if (presentArray.length === 1 && presentArray[0] === "") {
      presentArray = [];
    }
    $.each(book[attribute_name] || [], function (i, el) {
      if ($.inArray(el, presentArray) === -1) presentArray.push(el);
    });
    return presentArray;
  }

  function populateForm(book, idx) {
    var updateItems = Object.fromEntries(
      Array.from(document.querySelectorAll(`[data-meta-index="${idx}"]`)).map(
        (value) => [value.dataset.metaValue, value.checked]
      )
    );
    if (updateItems.description) {
      var description = book.description || "";
      if (typeof tinymce !== "undefined" && tinymce.get("comments")) {
        tinymce.get("comments").setContent(description);
        tinymce.get("comments").save();
      } else {
        $("#comments").val(description);
      }
    }
    if (updateItems.tags) {
      var uniqueTags = getUniqueValues("tags", book);
      $("#tags").val(uniqueTags.join(", "));
    }
    var uniqueLanguages = getUniqueValues("languages", book);
    if (updateItems.authors) {
      var ampSeparatedAuthors = (book.authors || []).join(" & ");
      $("#authors").val(ampSeparatedAuthors);
    }
    if (updateItems.title) {
      $("#title").val(book.title);
    }
    $("#languages").val(uniqueLanguages.join(", "));
    if (updateItems.rating) {
      var roundedRating = Math.round(book.rating);
      var ratingWidget = $("#rating").data("rating");
      if (ratingWidget && typeof ratingWidget.setValue === "function") {
        ratingWidget.setValue(roundedRating);
      }
      $("#rating").val(roundedRating);
    }

    if (updateItems.cover && book.cover && $("#cover_url").length) {
      $(".cover img").attr("src", book.cover);
      $("#cover_url").val(book.cover);
    }
    if (updateItems.pubDate) {
      $("#pubdate").val(book.publishedDate).trigger("change");
    }
    if (updateItems.publisher) {
      $("#publisher").val(book.publisher);
    }
    if (updateItems.series && typeof book.series !== "undefined") {
      $("#series").val(book.series);
    }
    if (updateItems.seriesIndex && typeof book.series_index !== "undefined") {
      $("#series_index").val(book.series_index);
    }
    if (typeof book.identifiers !== "undefined") {
      selectedIdentifiers = Object.keys(book.identifiers || {})
        .filter((key) => updateItems[key])
        .reduce((result, key) => {
          result[key] = book.identifiers[key];
          return result;
        }, {});
      populateIdentifiers(selectedIdentifiers);
    }
    var $alert = $("#meta-import-alert");
    if ($alert.length) {
      if (metaAlertTimer) {
        clearTimeout(metaAlertTimer);
        metaAlertTimer = null;
      }
      $alert.show().addClass("is-visible");
      metaAlertTimer = setTimeout(function () {
        $alert.removeClass("is-visible");
        setTimeout(function () {
          $alert.hide();
        }, 250);
      }, 2000);
    }
  }

  function findIdentifierRow(type) {
    var normalized = (type || "").trim().toLowerCase();
    var match = null;
    $("#identifier-table tbody tr").each(function () {
      var $typeInput = $(this).find("input.identifier-type");
      if (!$typeInput.length) {
        return;
      }
      var currentType = ($typeInput.val() || "").trim().toLowerCase();
      if (currentType === normalized) {
        match = $(this);
        return false;
      }
    });
    return match;
  }

  function populateIdentifiers(identifiers) {
    for (const property in identifiers) {
      console.log(`${property}: ${identifiers[property]}`);
      var $row = findIdentifierRow(property);
      if ($row && $row.length) {
        $row.find("input.identifier-type").val(property);
        $row.find("input.identifier-val").val(identifiers[property]);
      } else {
        addIdentifier(property, identifiers[property]);
      }
    }
  }

  function addIdentifier(name, value) {
    var randId = Math.floor(Math.random() * 1000000).toString();
    var line = "<tr>";
    line +=
      '<td><input type="text" class="form-control identifier-type" name="identifier-type-' +
      randId +
      '" required="required" placeholder="' +
      _("Identifier Type") +
      '" value="' +
      name +
      '"></td>';
    line +=
      '<td><input type="text" class="form-control identifier-val" name="identifier-val-' +
      randId +
      '" required="required" placeholder="' +
      _("Identifier Value") +
      '" value="' +
      value +
      '"></td>';
    line +=
      '<td><button type="button" class="btn btn-default identifier-remove">' +
      _("Remove") +
      "</button></td>";
    line += "</tr>";
    $("#identifier-table").append(line);
  }

  function renderProviderStatus(providers) {
    if (!providers || !providers.length) return "";
    var STATUS_COPY = {
      ok:           { cls: "text-success",  icon: "ok-circle"   },
      empty:        { cls: "text-muted",    icon: "minus-sign"  },
      rate_limited: { cls: "text-warning",  icon: "time"        },
      blocked:      { cls: "text-danger",   icon: "ban-circle"  },
      missing_key:  { cls: "text-warning",  icon: "lock"        },
      error:        { cls: "text-danger",   icon: "exclamation-sign" },
      disabled:     { cls: "text-muted",    icon: "off"         }
    };
    var visible = providers.filter(function (p) { return p.status !== "disabled"; });
    if (!visible.length) return "";
    var html = '<div class="provider-status" style="margin-bottom:10px; font-size:90%;">';
    visible.forEach(function (p) {
      var spec = STATUS_COPY[p.status] || STATUS_COPY.error;
      var label;
      if (p.status === "ok") {
        label = p.count + " result" + (p.count === 1 ? "" : "s");
      } else if (p.status === "empty") {
        label = p.message || "no results";
      } else {
        label = p.message || p.status;
      }
      html +=
        '<div class="' + spec.cls + '">' +
          '<span class="glyphicon glyphicon-' + spec.icon + '" aria-hidden="true"></span> ' +
          '<strong>' + p.name + '</strong>: ' + $('<div>').text(label).html() +
          (p.duration_ms ? ' <span class="text-muted">(' + p.duration_ms + ' ms)</span>' : '') +
        '</div>';
    });
    html += "</div>";
    return html;
  }

  function doSearch(keyword) {
    if (keyword) {
      $("#meta-info").text(msg.loading);
      $.ajax({
        url: getPath() + "/metadata/search",
        type: "POST",
        data: {
          query: keyword,
          csrf_token: $("input[name='csrf_token']").first().val(),
        },
        dataType: "json",
        success: function success(data) {
          // Tolerate both the new {results, providers} shape and the older
          // bare-array shape (in case a stale cached JS hits a new server).
          var results  = (data && data.results)   ? data.results   : (Array.isArray(data) ? data : []);
          var providers = (data && data.providers) ? data.providers : [];
          var providerHtml = renderProviderStatus(providers);

          if (results.length) {
            $("#meta-info").html(providerHtml + '<ul id="book-list" class="media-list"></ul>');
            results.forEach(function (book, idx) {
              var $book = $(templates.bookResult({ book: book, index: idx }));
              $book.find("button").on("click", function () {
                populateForm(book, idx);
              });
              applyMetaSelections($book);
              $("#book-list").append($book);
            });
            // Reveal the sort dropdown and reset to default ordering on every
            // fresh search so users start from a known state.
            $("#meta-sort").val("default");
            window.__metaSortMode = "default";
            $("#meta-sort-bar").show();
          } else {
            $("#meta-sort-bar").hide();
            $("#meta-info").html(
              providerHtml +
              '<p class="text-danger">' + msg.no_result + "!</p>"
            );
          }
        },
        error: function error() {
          $("#meta-info").html(
            '<p class="text-danger">' +
              msg.search_error +
              "!</p>" +
              $("#meta-info")[0].innerHTML
          );
        },
      });
    }
  }

  function populate_provider() {
    $("#metadata_provider").empty();
    $.ajax({
      url: getPath() + "/metadata/provider",
      type: "get",
      dataType: "json",
      success: function success(data) {
        var anyDisabled = false;
        var disabledNames = [];
        data.forEach(function (provider) {
          // Hide globally disabled providers but collect their names for a note
          if (provider.hasOwnProperty('globally_enabled') && !provider.globally_enabled) {
            anyDisabled = true;
            disabledNames.push(provider.name);
            return; // Skip rendering this provider
          }

          var checked = provider.active ? "checked" : "";
          var inputId = 'show-' + provider.name;
          var $provider_button =
            '<input type="checkbox" id="' + inputId + '" class="pill" data-initial="' +
            provider.initial + '" data-control="' + provider.id + '" ' + checked + '>' +
            '<label for="' + inputId + '">' +
            provider.name + ' <span class="glyphicon glyphicon-ok" aria-hidden="true"></span>' +
            '</label>';
          $("#metadata_provider").append($provider_button);
        });
        if (anyDisabled) {
          var disabledList = disabledNames.join(', ');
          var note = $('<div class="text-muted" style="margin-bottom:8px;">' +
                       '<span class="glyphicon glyphicon-lock" aria-hidden="true"></span> ' +
                       'Some providers are disabled: ' + disabledList + '</div>');
          $("#metadata_provider").prepend(note);
        }
      },
    });
  }

  $(document).on("change", ".pill", function () {
    var element = $(this);
    var id = element.data("control");
    var initial = element.data("initial");
    var val = element.prop("checked");
    var params = { id: id, value: val };
    if (!initial) {
      params["initial"] = initial;
      params["query"] = keyword;
    }
    $.ajax({
      method: "post",
      contentType: "application/json; charset=utf-8",
      dataType: "json",
      url: getPath() + "/metadata/provider/" + id,
      data: JSON.stringify(params),
      success: function success(data) {
        element.data("initial", "true");
        data.forEach(function (book, idx) {
          var $book = $(templates.bookResult({ book: book, index: idx }));
          $book.find("button").on("click", function () {
            populateForm(book, idx);
          });
          applyMetaSelections($book);
          $("#book-list").append($book);
        });
      },
    });
  });

  $(document).on("change", 'input[type="checkbox"][data-meta-value]', function () {
    var key = $(this).data("meta-value");
    var val = $(this).prop("checked");
    if (key) {
      setMetaSelection(key, val);
    }
  });

  $("#meta-search").on("submit", function (e) {
    e.preventDefault();
    keyword = $("#keyword").val();
    $(".pill").each(function () {
      $(this).data("initial", $(this).prop("checked"));
    });
    doSearch(keyword);
  });

  function renderKeysPanel(entries) {
    if (!entries || !entries.length) {
      $("#meta-keys-list").html('<p class="text-muted">' + _("No key-supporting providers found.") + "</p>");
      return;
    }
    var $list = $("<div></div>");
    entries.forEach(function (entry) {
      var inputId = "meta-key-input-" + entry.id;
      var statusBadge = entry.configured
        ? '<span class="label label-success">' + _("Configured") + "</span>"
        : '<span class="label label-default">' + _("Not configured") + "</span>";
      var actionButton = entry.can_edit
        ? '<button type="button" class="btn btn-primary btn-sm meta-key-save" data-provider="' + entry.id + '">' + _("Save") + "</button>"
        : '<span class="text-muted">' + _("Admin only") + "</span>";
      var inputAttrs = entry.can_edit ? "" : ' disabled';
      var placeholder = entry.configured
        ? _("Leave blank to keep the existing key, or paste a new one to replace it. Type 'clear' to remove.")
        : _("Paste your API key here");
      var row = $(
        '<div class="meta-key-row" style="margin-bottom:14px; padding-bottom:14px; border-bottom:1px solid rgba(255,255,255,.07);">' +
          '<div style="margin-bottom:6px;">' +
            '<strong>' + entry.name + '</strong> ' + statusBadge +
            ' &middot; <a href="' + entry.signup + '" target="_blank" rel="noopener">' + _("Get key") + ' &rarr;</a>' +
          '</div>' +
          '<div class="text-muted" style="font-size:88%; margin-bottom:6px;">' + entry.help + '</div>' +
          '<div class="input-group">' +
            '<input type="text" class="form-control meta-key-input" id="' + inputId + '" placeholder="' + placeholder + '" autocomplete="off"' + inputAttrs + '>' +
            '<span class="input-group-btn">' + actionButton + '</span>' +
          '</div>' +
          '<div class="meta-key-feedback text-success" style="display:none; margin-top:6px;"></div>' +
        '</div>'
      );
      $list.append(row);
    });
    $("#meta-keys-list").empty().append($list);
  }

  function loadKeysPanel() {
    $.ajax({
      url: getPath() + "/metadata/keys",
      type: "GET",
      dataType: "json",
      success: renderKeysPanel,
      error: function () {
        $("#meta-keys-list").html('<p class="text-danger">' + _("Failed to load API key inventory.") + "</p>");
      }
    });
  }

  $(document).on("click", "#meta-keys-toggle", function () {
    var $panel = $("#meta-keys-panel");
    var willShow = $panel.is(":hidden");
    $(this).attr("aria-expanded", willShow ? "true" : "false");
    if (willShow) {
      $panel.show();
      loadKeysPanel();
    } else {
      $panel.hide();
    }
  });

  $(document).on("click", ".meta-key-save", function () {
    var $btn = $(this);
    var providerId = $btn.data("provider");
    var $row = $btn.closest(".meta-key-row");
    var $input = $row.find(".meta-key-input");
    var $feedback = $row.find(".meta-key-feedback");
    var raw = ($input.val() || "").trim();
    if (!raw) {
      $feedback.removeClass("text-success").addClass("text-danger")
        .text(_("Enter a key, or type 'clear' to remove an existing one.")).show();
      return;
    }
    var payloadValue = (raw.toLowerCase() === "clear") ? "" : raw;
    $btn.prop("disabled", true).text("…");
    $.ajax({
      url: getPath() + "/metadata/keys/" + providerId,
      type: "POST",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({ value: payloadValue, csrf_token: $('input[name="csrf_token"]').val() }),
      headers: { "X-CSRFToken": $('input[name="csrf_token"]').val() },
      dataType: "json",
      success: function (resp) {
        $input.val("");
        $feedback.removeClass("text-danger").addClass("text-success")
          .text(resp.configured ? _("Key saved.") : _("Key cleared."))
          .show();
        // Refresh the inventory so the badge re-renders.
        loadKeysPanel();
      },
      error: function (xhr) {
        var msgText = (xhr.responseJSON && xhr.responseJSON.error) || _("Save failed.");
        $feedback.removeClass("text-success").addClass("text-danger").text(msgText).show();
        $btn.prop("disabled", false).text(_("Save"));
      }
    });
  });

  $("#get_meta").click(function () {
    populate_provider();
    var bookTitle = $("#title").val();
    $("#keyword").val(bookTitle);
    keyword = bookTitle;
    doSearch(bookTitle);
  });
  $("#metaModal").on("show.bs.modal", function (e) {
    $(e.relatedTarget).one("focus", function (e) {
      $(this).blur();
    });
  });
});
