from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_metadata_description_apply_syncs_tinymce_to_textarea():
    js = (REPO_ROOT / "cps/static/js/get_meta.js").read_text(encoding="utf-8")

    assert 'var description = book.description || "";' in js
    assert 'tinymce.get("comments").setContent(description);' in js
    assert 'tinymce.get("comments").save();' in js


def test_metadata_result_button_is_apply_not_save():
    template = (REPO_ROOT / "cps/templates/book_edit.html").read_text(encoding="utf-8")

    assert '<button class="btn btn-default">{{_("Apply")}}</button>' in template


def test_metadata_search_aborts_previous_request_and_shows_progress():
    js = (REPO_ROOT / "cps/static/js/get_meta.js").read_text(encoding="utf-8")

    assert "searchRequest.abort();" in js
    assert '$("#do-search").addClass("is-searching")' in js
    assert '$("#metaModal").on("hidden.bs.modal"' in js


def test_metadata_dialog_fits_phone_screen():
    css = (REPO_ROOT / "cps/static/css/caliBlur.css").read_text(encoding="utf-8")
    mobile = css[css.index("@media only screen and (max-width: 767px)"):]

    assert "transform: none !important" in mobile
    assert "overflow-y: auto" in mobile
