/**
 * Created by SpeedProg on 05.04.2015.
 */
/* global Bloodhound, language, Modernizr, tinymce, getPath */

if ($("#comments").length && typeof tinymce !== "undefined") {
    tinymce.init({
        selector: "#comments",
        plugins: 'code',
        branding: false,
        menubar: "edit view format",
        language: language
    });
}

if ($(".tiny_editor").length) {
    tinymce.init({
        selector: ".tiny_editor",
        plugins: 'code',
        branding: false,
        menubar: "edit view format",
        language: language
    });
}

$(".datepicker").datepicker({
    format: "yyyy-mm-dd",
    // forceParse (default true) reformats or blanks a hand-typed bare year on
    // blur, so "2020" never reaches the form. Keeping the raw value lets the
    // backend accept year-only / year-month dates (issue #472). The click path
    // is unaffected — picking a day still formats to YYYY-MM-DD.
    forceParse: false,
    language: language
}).on("change", function () {
    // Show a localized date over top of the standard YYYY-MM-DD field. Accept
    // year-only ("2020") and year-month ("2020-05") in addition to full dates
    // (issue #472); missing parts default to the 1st, matching what the backend
    // stores. Hide the mirror when the value isn't a recognizable date so the
    // user sees their raw input instead of a stale localized overlay.
    var results = /^\s*(\d{4})(?:[-\/\\](\d{1,2})(?:[-\/\\](\d{1,2}))?)?\s*$/.exec(this.value);
    var $mirror = $(this).next('input');
    if (results) {
        var year = parseInt(results[1], 10);
        var month = results[2] ? parseInt(results[2], 10) - 1 : 0;
        var day = results[3] ? parseInt(results[3], 10) : 1;
        var pubDate = new Date(year, month, day);
        $mirror
            .val(pubDate.toLocaleDateString(language.replaceAll("_","-")))
            .removeClass("hidden");
    } else {
        $mirror.addClass("hidden");
    }
}).trigger("change");

$(".datepicker_delete").click(function() {
    var inputs = $(this).parent().siblings('input');
    $(inputs[0]).data('datepicker').clearDates();
    $(inputs[1]).addClass('hidden');
});


/*
Takes a prefix, query typeahead callback, Bloodhound typeahead adapter
 and returns the completions it gets from the bloodhound engine prefixed.
 */
function prefixedSource(prefix, query, cb, source) {
    function async(retArray) {
        retArray = retArray || [];
        var matches = [];
        for (var i = 0; i < retArray.length; i++) {
            var obj = {name : prefix + retArray[i].name};
            matches.push(obj);
        }
        cb(matches);
    }
    source.search(query, cb, async);
}

function sourceSplit(query, cb, split, source) {
    var tokens = query.split(split);
    var currentSource = tokens[tokens.length - 1].trim();

    tokens.splice(tokens.length - 1, 1); // remove last element
    var prefix = "";
    var newSplit;
    if (split === "&") {
        newSplit = " " + split + " ";
    } else {
        newSplit = split + " ";
    }
    for (var i = 0; i < tokens.length; i++) {
        prefix += tokens[i].trim() + newSplit;
    }
    prefixedSource(prefix, currentSource, cb, source);
}

var authors = new Bloodhound({
    name: "authors",
    identify: function(obj) { return obj.name; },
    datumTokenizer: function datumTokenizer(datum) {
        return [datum.name];
    },
    queryTokenizer: Bloodhound.tokenizers.whitespace,
    remote: {
        url: getPath() + "/get_authors_json?q=%QUERY",
        wildcard: '%QUERY',
    },
});

$(".form-group #authors").typeahead(
    {
        highlight: true,
        minLength: 1,
        hint: true
    }, {
        name: "authors",
        display: 'name',
        source: function source(query, cb, asyncResults) {
            return sourceSplit(query, cb, "&", authors);
        }
    }
);


var series = new Bloodhound({
    name: "series",
    datumTokenizer: function datumTokenizer(datum) {
        return [datum.name];
    },
    // queryTokenizer: Bloodhound.tokenizers.whitespace,
    queryTokenizer: function queryTokenizer(query) {
        return [query];
    },
    remote: {
        url: getPath() + "/get_series_json?q=%QUERY",
        wildcard: '%QUERY',
        /*replace: function replace(url, query) {
            return url + encodeURIComponent(query);
        }*/
    }
});
$(".form-group #series").typeahead(
    {
        highlight: true,
        minLength: 0,
        hint: true
    }, {
        name: "series",
        displayKey: "name",
        source: series
    }
);

var tags = new Bloodhound({
    name: "tags",
    datumTokenizer: function datumTokenizer(datum) {
        return [datum.name];
    },
    queryTokenizer: function queryTokenizer(query) {
        var tokens = query.split(",");
        tokens = [tokens[tokens.length - 1].trim()];
        return tokens;
    },
    remote: {
        url: getPath() + "/get_tags_json?q=%QUERY",
        wildcard: '%QUERY'
    }
});

$(".form-group #tags").typeahead(
    {
        highlight: true,
        minLength: 0,
        hint: true
    }, {
        name: "tags",
        display: "name",
        source: function source(query, cb, asyncResults) {
            return sourceSplit(query, cb, ",", tags);
        }
    }
);

var languages = new Bloodhound({
    name: "languages",
    datumTokenizer: function datumTokenizer(datum) {
        return [datum.name];
    },
    queryTokenizer: function queryTokenizer(query) {
        return [query];
    },
    remote: {
        url: getPath() + "/get_languages_json?q=%QUERY",
        wildcard: '%QUERY'
        /*replace: function replace(url, query) {
            return url + encodeURIComponent(query);
        }*/
    }
});

$(".form-group #languages").typeahead(
    {
        highlight: true, minLength: 0,
        hint: true
    }, {
        name: "languages",
        display: "name",
        source: function source(query, cb, asyncResults) {
            return sourceSplit(query, cb, ",", languages);
        }
    }
);

var publishers = new Bloodhound({
    name: "publisher",
    datumTokenizer: function datumTokenizer(datum) {
        return [datum.name];
    },
    queryTokenizer: Bloodhound.tokenizers.whitespace,
    remote: {
        url: getPath() + "/get_publishers_json?q=%QUERY",
        wildcard: '%QUERY'
    }
});

$(".form-group #publisher").typeahead(
    {
        highlight: true, minLength: 0,
        hint: true
    }, {
        name: "publishers",
        displayKey: "name",
        source: publishers
    }
);

$("#search").on("change input.typeahead:selected", function(event) {
    if (event.target.type === "search" && event.target.tagName === "INPUT") {
        return;
    }
    var form = $("form").serialize();
    $.getJSON( getPath() + "/get_matching_tags", form, function( data ) {
        $(".tags_click").each(function() {
            if ($.inArray(parseInt($(this).val(), 10), data.tags) === -1) {
                if (!$(this).prop("selected")) {
                    $(this).prop("disabled", true);
                }
            } else {
                $(this).prop("disabled", false);
            }
        });
        $("#include_tag option:selected").each(function () {
            $("#exclude_tag").find("[value=" + $(this).val() + "]").prop("disabled", true);
        });
        $("#include_tag").selectpicker("refresh");
        $("#exclude_tag").selectpicker("refresh");
    });
});

/*$("#btn-upload-format").on("change", function () {
    var filename = $(this).val();
    if (filename.substring(3, 11) === "fakepath") {
        filename = filename.substring(12);
    } // Remove c:\fake at beginning from localhost chrome
    $("#upload-format").text(filename);
});*/

$("#btn-upload-cover").on("change", function () {
    var filename = $(this).val();
    if (filename.substring(3, 11) === "fakepath") {
        filename = filename.substring(12);
    } // Remove c:\fake at beginning from localhost chrome
    $("#upload-cover").text(filename);
});

// ---- Inline live preview for the cover_url field ----
// Debounced AJAX HEAD probe via /metadata/cover/preview. Surfaces
// dimensions + a friendly error before the user submits the form, so
// the field stops feeling "unreliable" — failures are visible at paste
// time, not after a full save round-trip. Endpoint URL comes from the
// data-cover-preview-endpoint attribute on the input itself so the
// preview path stays portable across reverse-proxy prefixes.
(function () {
    var $field = $("#cover_url");
    if ($field.length === 0) return;
    var endpoint = $field.attr("data-cover-preview-endpoint");
    if (!endpoint) return;
    var $preview = $("#cover_url_preview");
    var $previewImg = $("#cover_url_preview_img");
    var $previewMeta = $("#cover_url_preview_meta");
    var $feedback = $("#cover_url_preview_feedback");
    var debounce = null;
    var lastTried = "";
    var csrf = $('meta[name="csrf-token"]').attr("content")
            || $('input[name="csrf_token"]').first().val()
            || "";

    function setFeedback(text, kind) {
        $feedback.attr("class", "cwa-cover-url-feedback" + (kind ? " " + kind : ""));
        $feedback.text(text || "");
    }

    function clearPreview() {
        $preview.attr("hidden", true);
        $previewImg.attr("src", "");
        $previewMeta.text("");
    }

    function showPreview(payload, url) {
        $previewImg.attr("src", url);
        var bits = [];
        if (payload.width && payload.height) bits.push(payload.width + "×" + payload.height);
        if (payload.size_bytes) bits.push(Math.round(payload.size_bytes / 1024) + " KB");
        if (payload.content_type) bits.push(payload.content_type);
        $previewMeta.text(bits.join(" · "));
        $preview.removeAttr("hidden");
    }

    $field.on("input", function () {
        clearTimeout(debounce);
        var url = ($field.val() || "").trim();
        if (url === lastTried) return;
        if (url.length < 8) {
            clearPreview();
            setFeedback("");
            return;
        }
        debounce = setTimeout(function () {
            lastTried = url;
            setFeedback("Checking…", null);
            $.ajax({
                url: endpoint,
                type: "POST",
                contentType: "application/json",
                headers: csrf ? { "X-CSRFToken": csrf } : {},
                data: JSON.stringify({ url: url }),
            }).done(function (payload) {
                if (payload && payload.valid) {
                    setFeedback("Looks good — preview shown.", "is-ok");
                    showPreview(payload, url);
                } else {
                    setFeedback((payload && payload.error_message) || "Could not validate URL.", "is-error");
                    clearPreview();
                }
            }).fail(function () {
                setFeedback("Could not validate URL.", "is-error");
                clearPreview();
            });
        }, 400);
    });
})();

$("#book_edit_frm").on("submit", function () {
    if (typeof tinymce !== "undefined" && typeof tinymce.triggerSave === "function") {
        tinymce.triggerSave();
    }
});

$("#xchange").click(function () {
    this.blur();
    var title = $("#title").val();
    $("#title").val($("#authors").val());
    $("#authors").val(title);
});

