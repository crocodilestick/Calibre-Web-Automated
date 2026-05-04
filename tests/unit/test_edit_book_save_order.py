from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_directory_update_happens_before_comments_and_tags_are_staged():
    source = (REPO_ROOT / "cps/editbooks.py").read_text(encoding="utf-8")
    function_body = source[source.index("def do_edit_book") : source.index("def merge_metadata")]

    directory_update = function_body.index("helper.update_dir_structure")
    comments_update = function_body.index("edit_book_comments")
    tags_update = function_body.index("edit_book_tags")

    assert directory_update < comments_update
    assert directory_update < tags_update
