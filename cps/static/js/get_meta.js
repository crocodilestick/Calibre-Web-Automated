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
    $.each(book[attribute_name], function (i, el) {
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
      if (typeof tinymce !== "undefined" && tinymce.get("comments")) {
        tinymce.get("comments").setContent(book.description);
      } else {
        $("#comments").val(book.description);
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
      selectedIdentifiers = Object.keys(book.identifiers)
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

  function doSearch(keyword) {
    if (keyword) {
      $("#meta-info").text(msg.loading);
      $.ajax({
        url: getPath() + "/metadata/search",
        type: "POST",
        data: { query: keyword },
        dataType: "json",
        success: function success(data) {
          if (data.length) {
            $("#meta-info").html('<ul id="book-list" class="media-list"></ul>');
            data.forEach(function (book, idx) {
              var $book = $(templates.bookResult({ book: book, index: idx }));
              $book.find("button").on("click", function () {
                populateForm(book, idx);
              });
              applyMetaSelections($book);
              $("#book-list").append($book);
            });
          } else {
            $("#meta-info").html(
              '<p class="text-danger">' +
                msg.no_result +
                "!</p>" +
                $("#meta-info")[0].innerHTML
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
