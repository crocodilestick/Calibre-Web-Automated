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


def test_pdf_reader_loads_custom_workspace_assets_and_controls():
    template = (REPO_ROOT / "cps/templates/readpdf.html").read_text(encoding="utf-8")

    assert "css/pdf_reader.css" in template
    assert "js/pdf_reader.js" in template
    assert 'id="cwaBackToBook"' in template
    assert 'id="cwaNotesToggle"' in template
    assert 'id="cwaNotesPanel"' in template
    assert 'id="cwaThemeSelect"' in template
    assert "window.CWA_PDF_READER" in template
    assert "csrf_token()" in template
    assert 'cwa.pdfReader.{{ reader_storage_identity }}.{{ pdffile }}' in template


def test_pdf_reader_uses_native_pdfjs_page_colors_and_editors():
    template = (REPO_ROOT / "cps/templates/readpdf.html").read_text(encoding="utf-8")

    assert "PDFViewerApplicationOptions.set('annotationEditorMode', 0)" in template
    assert "PDFViewerApplicationOptions.set('enableHighlightEditor', true)" in template
    assert "PDFViewerApplicationOptions.set('enableUpdatedAddImage', true)" in template
    assert "PDFViewerApplicationOptions.set('forcePageColors', darkPages || sepiaPages)" in template
    assert "PDFViewerApplicationOptions.set('pageColorsBackground'" in template
    assert "PDFViewerApplicationOptions.set('pageColorsForeground'" in template


def test_pdf_reader_controller_syncs_state_and_page_notes():
    js = (REPO_ROOT / "cps/static/js/pdf_reader.js").read_text(encoding="utf-8")

    assert 'eventBus.on("pagechanging"' in js
    assert 'eventBus.on("scalechanging"' in js
    assert 'eventBus.on("rotationchanging"' in js
    assert 'eventBus.on("sidebarviewchanged"' in js
    assert 'request(config.stateUrl' in js
    assert 'request(config.notesUrl)' in js
    assert 'method: existing ? "PATCH" : "POST"' in js
    assert 'window.addEventListener("pagehide", flushState)' in js
    assert 'keepalive: Boolean(options.keepalive)' in js


def test_pdf_reader_styles_include_phone_and_tablet_layouts():
    css = (REPO_ROOT / "cps/static/css/pdf_reader.css").read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 620px)" in css
    assert "--cwa-toolbar-height: 52px" in css
    assert "width: 100vw" in css
    assert ".cwaColorChoice {\n    width: 44px;\n    height: 44px;" in css
    assert ".cwaNoteAction {\n    min-width: 44px;\n    min-height: 44px;" in css
