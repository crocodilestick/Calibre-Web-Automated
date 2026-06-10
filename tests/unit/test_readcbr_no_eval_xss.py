"""Regression: the comic (CBR/CBZ) reader must not eval() the stored bookmark.

`bookmark_key` is user-writable — any authenticated user can POST an arbitrary
string to /ajax/bookmark/<comic_id>/CBR and it is rendered verbatim into
window.calibre.bookmark. The old code ran `currentImage = eval(calibre.bookmark)`
on page load, so a stored payload like `alert(document.cookie)` executed in the
reader page (stored-XSS-equivalent / self-XSS escalation). The bookmark is only
ever a page index, so it must be parsed as an integer, never eval'd.
"""
import os
import re

HERE = os.path.dirname(__file__)
READCBR = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "templates", "readcbr.html")
)


def _src():
    with open(READCBR, encoding="utf-8") as fh:
        return fh.read()


def test_readcbr_does_not_eval_bookmark():
    src = _src()
    # No eval of the templated bookmark value anywhere in the comic reader.
    assert "eval(calibre.bookmark)" not in src
    assert not re.search(r"\beval\s*\(", src), "readcbr.html must not call eval()"


def test_readcbr_parses_bookmark_as_int():
    src = _src()
    assert "parseInt(calibre.bookmark, 10)" in src
    # And guards against NaN / negative so garbage falls back to page 0.
    assert "Number.isInteger(currentImage)" in src
