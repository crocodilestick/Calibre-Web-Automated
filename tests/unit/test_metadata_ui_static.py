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


def test_caliblur_quick_read_formats_match_read_book():
    import re
    js = (REPO_ROOT / "cps/static/js/caliBlur.js").read_text(encoding="utf-8")
    constants = (REPO_ROOT / "cps/constants.py").read_text(encoding="utf-8")

    match = re.search(r"var readableFormats = \[(.*?)\];", js, re.S)
    assert match, "readableFormats list not found in caliBlur.js"
    offered = set(re.findall(r"'([a-z0-9]+)'", match.group(1)))

    audio = re.search(r"EXTENSIONS_AUDIO = \{(.*?)\}", constants).group(1)
    audio_formats = set(re.findall(r"'([a-z0-9]+)'", audio))

    # read_book() opens every audio format in the audio player.
    assert audio_formats <= offered
    # Formats read_book() cannot open must not be offered.
    assert not offered & {"mobi", "azw3", "fb2", "html"}
