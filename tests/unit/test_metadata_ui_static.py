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
