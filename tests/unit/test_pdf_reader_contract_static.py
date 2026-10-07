from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pdf_reader_models_are_per_user_and_book():
    models = (REPO_ROOT / "cps/ub.py").read_text(encoding="utf-8")

    assert "class PdfReaderState(Base):" in models
    assert "class PdfReaderNote(Base):" in models
    assert "UniqueConstraint('user_id', 'book_id'" in models
    assert "Index('ix_pdf_reader_note_user_book_page', 'user_id', 'book_id', 'page_number')" in models
    assert "body = Column(Text, nullable=False)" in models


def test_pdf_reader_api_is_authenticated_pdf_only_and_strict():
    web = (REPO_ROOT / "cps/web.py").read_text(encoding="utf-8")

    assert '@web.route("/ajax/pdf-reader/<int:book_id>/state", methods=[\'GET\', \'PUT\'])' in web
    assert '@web.route("/ajax/pdf-reader/<int:book_id>/notes", methods=[\'GET\', \'POST\'])' in web
    assert "@user_login_required\n@viewer_required\ndef pdf_reader_state" in web
    assert "@user_login_required\n@viewer_required\ndef pdf_reader_notes" in web
    assert "calibre_db.get_book_format(book_id, 'PDF') is not None" in web
    assert "unknown = set(payload) - PDF_READER_STATE_FIELDS" in web
    assert "unknown = set(payload) - PDF_READER_NOTE_FIELDS" in web
    assert "def _pdf_reader_json_payload():" in web
    assert 'raise ValueError("Request body must be a JSON object")' in web
    assert "not isinstance(payload['page_number'], int)" in web
    assert "not isinstance(body, str)" in web
    assert "ub.PdfReaderNote.user_id == user_id" in web
    assert "ub.PdfReaderNote.book_id == book_id" in web


def test_pdf_reader_rows_are_removed_with_their_user():
    admin = (REPO_ROOT / "cps/admin.py").read_text(encoding="utf-8")

    assert "ub.session.query(ub.PdfReaderState).filter(content.id == ub.PdfReaderState.user_id).delete()" in admin
    assert "ub.session.query(ub.PdfReaderNote).filter(content.id == ub.PdfReaderNote.user_id).delete()" in admin


def test_pdf_reader_rows_follow_book_and_library_lifecycle():
    editbooks = (REPO_ROOT / "cps/editbooks.py").read_text(encoding="utf-8")
    admin = (REPO_ROOT / "cps/admin.py").read_text(encoding="utf-8")

    assert "ub.session.query(ub.PdfReaderState).filter(ub.PdfReaderState.book_id == book_id).delete()" in editbooks
    assert "ub.session.query(ub.PdfReaderNote).filter(ub.PdfReaderNote.book_id == book_id).delete()" in editbooks
    format_delete = editbooks[editbooks.index("def delete_book_from_table") :]
    assert "if book_format.upper() == 'PDF':" in format_delete
    assert "ub.session_commit()" in format_delete
    assert "ub.session.query(ub.PdfReaderState).delete()" in admin
    assert "ub.session.query(ub.PdfReaderNote).delete()" in admin


def test_pdf_reader_route_exposes_auth_mode_to_template():
    web = (REPO_ROOT / "cps/web.py").read_text(encoding="utf-8")

    assert "reader_authenticated = bool(current_user.is_authenticated)" in web
    assert "reader_storage_identity=str(current_user.id) if reader_authenticated else 'anonymous'" in web


def test_note_cards_inherit_their_selected_color_class():
    script = (REPO_ROOT / "cps/static/js/pdf_reader.js").read_text(encoding="utf-8")

    assert 'card.className = "cwaNoteCard cwaColor-" + note.color;' in script
    assert 'setProperty("--note-color", "var(--note-color)")' not in script


def test_pdf_reader_rejects_corrupt_device_cache_and_out_of_range_zoom():
    script = (REPO_ROOT / "cps/static/js/pdf_reader.js").read_text(encoding="utf-8")
    template = (REPO_ROOT / "cps/templates/readpdf.html").read_text(encoding="utf-8")
    web = (REPO_ROOT / "cps/web.py").read_text(encoding="utf-8")

    assert "var state = sanitizeState(config.initialState);" in script
    assert "var notes = sanitizeNotes(readJson(config.notesStorageKey, []));" in script
    assert "if (!Array.isArray(value))" in script
    assert "return numericScale >= 0.1 && numericScale <= 10;" in script
    assert 'Object.prototype.toString.call(state) !== "[object Object]"' in template
    assert "not 0.1 <= float(scale_value) <= 10.0" in web
