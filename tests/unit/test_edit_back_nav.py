"""Regression: cover-editor + edit-metadata back navigation (operator #26).

- The cover picker's back link returns to the book DETAIL page by default, and to
  the edit-metadata page only when the picker was opened from there
  (``?origin=edit``). Previously it always hardcoded edit-metadata, so opening the
  picker from the detail page (clicking the cover) and pressing back wrongly landed
  on edit-metadata.
- The edit-metadata page now has an explicit "Back to book" link to the detail
  page (it previously only had a bottom "Cancel" button).

Source-pins on the templates + route (the source of truth). RED on main, GREEN here.
"""
import os

HERE = os.path.dirname(__file__)
COVER_PY = os.path.normpath(os.path.join(HERE, "..", "..", "cps", "cover_picker.py"))
COVER_HTML = os.path.normpath(os.path.join(HERE, "..", "..", "cps", "templates", "cover_picker.html"))
EDIT_HTML = os.path.normpath(os.path.join(HERE, "..", "..", "cps", "templates", "book_edit.html"))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_cover_picker_route_is_origin_aware():
    s = _read(COVER_PY)
    assert 'request.args.get("origin")' in s
    assert 'url_for("web.show_book"' in s             # default destination -> book detail
    assert 'url_for("edit-book.show_edit_book"' in s  # origin=edit -> edit metadata
    assert "back_url=back_url" in s
    assert "back_label=back_label" in s


def test_cover_picker_template_uses_dynamic_back():
    s = _read(COVER_HTML)
    assert "{{ back_url }}" in s
    assert "{{ back_label }}" in s
    # The old hardcoded "always go to edit metadata" link must be gone.
    assert "url_for('edit-book.show_edit_book'" not in s


def test_edit_page_opens_cover_picker_with_origin():
    s = _read(EDIT_HTML)
    assert "cover_picker.cover_picker_page" in s
    assert "origin='edit'" in s


def test_edit_page_has_back_to_book_link():
    s = _read(EDIT_HTML)
    assert "cwa-edit-back" in s
    assert "Back to book" in s
    assert "url_for('web.show_book'" in s


def test_edit_form_usable_on_phone():
    # The desktop `margin-left: 40rem` offset is dropped on phones so the form
    # (and the back link) are no longer pushed off-screen on mobile.
    s = _read(EDIT_HTML)
    assert "@media (max-width: 767px)" in s
    assert "#book_edit_frm > .col-sm-9" in s
    assert "margin-left: 0 !important" in s
