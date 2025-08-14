/* Calibre-Web Automated – fork of Calibre-Web
Copyright (C) 2018-2025 Calibre-Web contributors
Copyright (C) 2024-2025 Calibre-Web Automated contributors
SPDX-License-Identifier: GPL-3.0-or-later
See CONTRIBUTORS for full list of authors.
 */

var direction = $("#asc").data('order');  // 0=Descending order; 1= ascending order
var sort = 0;       // Show sorted entries

// Helper: get the primary list container regardless of template id
function getListContainer() {
    var $l = $("#list");
    if ($l.length) return $l;
    // Prefer the container right after the filter header
    var $near = $(".filterheader").nextAll(".container").first().find("div[id$='_list']").first();
    if ($near.length) return $near;
    $l = $("div[id$='_list']");
    if ($l.length) return $l.first();
    $l = $(".col-xs-12.col-sm-6").not("#second").first();
    return $l;
}

// Delegate events to handle dynamically rendered elements
$(document).on("click", "#sort_name", function() {
    $("#sort_name").toggleClass("active");
    var className = $("h1").attr("Class") + "_sort_name";
    var obj = {};
    obj[className] = sort;

    var count = 0;
    var index = 0;
    var store;
    var list = getListContainer();
    // Append 2nd half of list to first half for easier processing
    var cnt = $("#second").contents();
    list.append(cnt);
    // Count no of elements
    var listItems = list.children(".row");
    var listlength = listItems.length;
    // check for each element if its Starting character matches
    listItems.each(function() {
        if ( sort === 1) {
            store = this.attributes["data-name"];
        } else {
            store = this.attributes["data-id"];
        }
        $(this).find("a").html(store.value);
        if ($(this).css("display") !== "none") {
            count++;
        }
    });

    // Find count of middle element
    if (count > 20) {
        var middle = parseInt(count / 2, 10) + (count % 2);
        // search for the middle of all visible elements
        listItems.each(function() {
            index++;
            if ($(this).css("display") !== "none") {
                middle--;
                if (middle <= 0) {
                    return false;
                }
            }
        });
        // Move second half of visible elements
        $("#second").append(listItems.slice(index, listlength));
    }
    sort = (sort + 1) % 2;
});

$(document).on("click", "#desc", function() {
    // Recompute direction from DOM to avoid stale value after dynamic updates
    direction = $("#asc").hasClass("active") ? 1 : 0;
    // Always apply desc sort (no early return)
    $("#asc").removeClass("active");
    $("#desc").addClass("active");

    var page = $(this).data("id");
    $.ajax({
        method:"post",
        contentType: "application/json; charset=utf-8",
        dataType: "json",
        url: getPath() + "/ajax/view",
        data: "{\"" + page + "\": {\"dir\": \"desc\"}}",
    });
    var index = 0;
    var list = getListContainer();
    var second = $("#second");
    list.append(second.contents());
    var listItems = list.children(".row");
    var reversed, elementLength, middle;
    reversed = listItems.get().reverse();
    elementLength = reversed.length;
    // Find count of middle element
    var count = list.find("> .row:visible").length;
    if (count > 20) {
        middle = parseInt(count / 2, 10) + (count % 2);
        $(reversed).each(function() {
            index++;
            if ($(this).css("display") !== "none") {
                middle--;
                if (middle <= 0) {
                    return false;
                }
            }
        });
        list.append(reversed.slice(0, index));
        second.append(reversed.slice(index, elementLength));
    } else {
        list.append(reversed.slice(0, elementLength));
    }
    direction = 0;
});


$(document).on("click", "#asc", function() {
    // Recompute direction from DOM to avoid stale value after dynamic updates
    direction = $("#asc").hasClass("active") ? 1 : 0;
    // Always apply asc sort (no early return)
    $("#desc").removeClass("active");
    $("#asc").addClass("active");

    var page = $(this).data("id");
    $.ajax({
        method:"post",
        contentType: "application/json; charset=utf-8",
        dataType: "json",
        url: getPath() + "/ajax/view",
        data: "{\"" + page + "\": {\"dir\": \"asc\"}}",
    });
    var index = 0;
    var list = getListContainer();
    var second = $("#second");
    list.append(second.contents());
    var listItems = list.children(".row");
    var reversed = listItems.get().reverse();
    var elementLength = reversed.length;

    // Find count of middle element
    var count = list.find("> .row:visible").length;
    if (count > 20) {
        var middle = parseInt(count / 2, 10) + (count % 2);
        $(reversed).each(function() {
            index++;
            if ($(this).css("display") !== "none") {
                middle--;
                if (middle <= 0) {
                    return false;
                }
            }
        });
        list.append(reversed.slice(0, index));
        second.append(reversed.slice(index, elementLength));
    } else {
        list.append(reversed.slice(0, elementLength));
    }
    direction = 1;
});

$(document).on("click", "#all", function() {
    $("#all").addClass("active");
    $(".char").removeClass("active");
    // Reset dropdown selection if present
    var dd = $("#char-dropdown");
    if (dd.length) {
        dd.prop("selectedIndex", 0);
    }
    var cnt = $("#second").contents();
    var list = getListContainer();
    list.append(cnt);
    // Find count of middle element
    var listItems = list.children(".row");
    var listlength = listItems.length;
    var middle = parseInt(listlength / 2, 10) + (listlength % 2);
    // go through all elements and make them visible
    listItems.each(function() {
        $(this).show();
    });
    // Move second half of all elements
    if (listlength > 20) {
        $("#second").append(listItems.slice(middle, listlength));
    }
});

$(document).on("click", ".char", function() {
    $(".char").removeClass("active");
    $(this).addClass("active");
    $("#all").removeClass("active");
    var character = this.innerText;
    var count = 0;
    var index = 0;
    var list = getListContainer();
    // Append 2nd half of list to first half for easier processing
    var cnt = $("#second").contents();
    list.append(cnt);
    // Count no of elements
    var listItems = list.children(".row");
    var listlength = listItems.length;
    // check for each element if its Starting character matches
    listItems.each(function() {
        if (this.attributes["data-id"].value.charAt(0).toUpperCase() !== character) {
            $(this).hide();
        } else {
            $(this).show();
            count++;
        }
    });
    if (count > 20) {
        // Find count of middle element
        var middle = parseInt(count / 2, 10) + (count % 2);
        // search for the middle of all visible elements
        listItems.each(function() {
            index++;
            if ($(this).css("display") !== "none") {
                middle--;
                if (middle <= 0) {
                    return false;
                }
            }
        });
        // Move second half of visible elements
        $("#second").append(listItems.slice(index, listlength));
    }
});

// Support dropdown-based initial filtering when many characters
$(document).on("change", "#char-dropdown", function() {
    var character = $(this).val();
    if (!character) return;
    $("#all").removeClass("active");
    $(".char").removeClass("active");
    var count = 0;
    var index = 0;
    var list = getListContainer();
    // Append 2nd half of list to first half for easier processing
    var cnt = $("#second").contents();
    list.append(cnt);
    // Count no of elements
    var listItems = list.children(".row");
    var listlength = listItems.length;
    // check for each element if its Starting character matches
    listItems.each(function() {
        var id = this.attributes["data-id"].value;
        if (id.charAt(0).toUpperCase() !== character.toUpperCase()) {
            $(this).hide();
        } else {
            $(this).show();
            count++;
        }
    });
    if (count > 20) {
        // Find count of middle element
        var middle = parseInt(count / 2, 10) + (count % 2);
        // search for the middle of all visible elements
        listItems.each(function() {
            index++;
            if ($(this).css("display") !== "none") {
                middle--;
                if (middle <= 0) {
                    return false;
                }
            }
        });
        // Move second half of visible elements
        $("#second").append(listItems.slice(index, listlength));
    }
});
