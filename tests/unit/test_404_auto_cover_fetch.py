# -*- coding: utf-8 -*-
"""fork #404 (@beanscg confirmed): ``auto_metadata_update_cover`` must actually
download and apply covers.

The auto-metadata cover branch checked the setting and the provider's cover
URL, then hit a bare ``pass`` — covers were never fetched, never written, and
``updated`` was never set. The fix routes the download through
``helper.save_cover_from_url`` — the manual editor's path, with its SSRF guard
(advocate), size cap and image validation — honors the per-book cover lock and
smart mode (only fill a missing cover), never applies the generic placeholder,
and refreshes the thumbnail cache after commit. A cover failure must never
void the rest of the metadata application (the fetch runs in the ingest
processor without a Flask app context, where helper's error-path ``_()``
calls can raise).
"""

import types

import pytest

import cps.metadata_helper as m


class _List(list):
    pass


class _Book:
    def __init__(self, *, has_cover=0):
        self.id = 7
        self.title = "Existing Title"
        self.path = "Author/Book (7)"
        self.has_cover = has_cover
        self.last_modified = None
        self.authors = _List()
        self.comments = _List()
        self.publishers = _List()
        self.tags = _List()
        self.series = _List()
        self.series_index = "1.0"
        self.pubdate = None
        self.ratings = _List()
        self.identifiers = _List()


class _FakeSession:
    def __init__(self):
        self.commits = 0

    def add(self, *a, **k):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _FakeCDB:
    def __init__(self):
        self.session = _FakeSession()


def _metadata(cover):
    return types.SimpleNamespace(title="", cover=cover)


def _settings(**over):
    base = {
        "auto_metadata_smart_application": False,
        "auto_metadata_update_title": False,
        "auto_metadata_update_authors": False,
        "auto_metadata_update_description": False,
        "auto_metadata_update_publisher": False,
        "auto_metadata_update_tags": False,
        "auto_metadata_update_series": False,
        "auto_metadata_update_published_date": False,
        "auto_metadata_update_rating": False,
        "auto_metadata_update_identifiers": False,
        "auto_metadata_update_cover": True,
    }
    base.update(over)
    return base


@pytest.fixture
def harness(monkeypatch):
    """Patch CWA_DB + the helper module the cover path imports lazily."""
    state = {
        "settings": _settings(),
        "save_calls": [],
        "save_result": (True, None),
        "locked": False,
        "thumb_calls": [],
    }
    monkeypatch.setattr(
        m, "CWA_DB",
        lambda: type("S", (), {"get_cwa_settings": staticmethod(lambda: state["settings"])})())

    import cps.helper as helper

    def fake_save(url, book_path):
        state["save_calls"].append((url, book_path))
        result = state["save_result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(helper, "save_cover_from_url", fake_save)
    monkeypatch.setattr(helper, "book_cover_is_locked", lambda book_id: state["locked"])
    monkeypatch.setattr(
        helper, "replace_cover_thumbnail_cache",
        lambda book_id, book_path=None, last_modified=None: state["thumb_calls"].append(book_id))
    return state


COVER_URL = "https://covers.example.org/b/id/12345-L.jpg"


def test_cover_is_downloaded_and_applied(harness):
    book = _Book()
    cdb = _FakeCDB()
    assert m._apply_metadata_to_book(book, _metadata(COVER_URL), cdb) is True
    assert harness["save_calls"] == [(COVER_URL, book.path)]
    assert book.has_cover == 1
    assert cdb.session.commits == 1
    assert harness["thumb_calls"] == [book.id]


def test_smart_mode_keeps_existing_cover(harness):
    harness["settings"] = _settings(auto_metadata_smart_application=True)
    book = _Book(has_cover=1)
    assert m._apply_metadata_to_book(book, _metadata(COVER_URL), _FakeCDB()) is False
    assert harness["save_calls"] == []


def test_smart_mode_fills_missing_cover(harness):
    harness["settings"] = _settings(auto_metadata_smart_application=True)
    book = _Book(has_cover=0)
    assert m._apply_metadata_to_book(book, _metadata(COVER_URL), _FakeCDB()) is True
    assert harness["save_calls"] == [(COVER_URL, book.path)]
    assert book.has_cover == 1


def test_cover_lock_is_honored(harness):
    harness["locked"] = True
    book = _Book()
    assert m._apply_metadata_to_book(book, _metadata(COVER_URL), _FakeCDB()) is False
    assert harness["save_calls"] == []
    assert book.has_cover == 0


def test_generic_placeholder_is_never_applied(harness):
    book = _Book(has_cover=1)
    md = _metadata("http://example.org/static/generic_cover.svg")
    assert m._apply_metadata_to_book(book, md, _FakeCDB()) is False
    assert harness["save_calls"] == []


def test_setting_off_skips_download(harness):
    harness["settings"] = _settings(auto_metadata_update_cover=False)
    assert m._apply_metadata_to_book(_Book(), _metadata(COVER_URL), _FakeCDB()) is False
    assert harness["save_calls"] == []


def test_download_failure_does_not_void_other_updates(harness):
    harness["save_result"] = (False, "Error Downloading Cover")
    harness["settings"] = _settings(auto_metadata_update_title=True)
    book = _Book()
    md = types.SimpleNamespace(title="Fetched Title", cover=COVER_URL)
    cdb = _FakeCDB()
    assert m._apply_metadata_to_book(book, md, cdb) is True  # title applied
    assert book.has_cover == 0
    assert book.title == "Fetched Title"
    assert cdb.session.commits == 1
    assert harness["thumb_calls"] == []  # no cover -> no thumbnail churn


def test_helper_exception_is_contained(harness):
    # No Flask app context in the ingest processor: helper's error-path _()
    # can raise. The cover boundary must swallow it.
    harness["save_result"] = RuntimeError("Working outside of application context")
    harness["settings"] = _settings(auto_metadata_update_title=True)
    book = _Book()
    md = types.SimpleNamespace(title="Fetched Title", cover=COVER_URL)
    assert m._apply_metadata_to_book(book, md, _FakeCDB()) is True
    assert book.has_cover == 0
    assert book.title == "Fetched Title"


def test_sniff_image_bytes_accepts_real_formats():
    import cps.helper as helper
    assert helper._sniff_image_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)          # JPEG
    assert helper._sniff_image_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)        # PNG
    assert helper._sniff_image_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8)  # WebP
    assert helper._sniff_image_bytes(b"BM" + b"\x00" * 20)                        # BMP


def test_sniff_image_bytes_rejects_junk():
    import cps.helper as helper
    assert not helper._sniff_image_bytes(b"")                       # empty
    assert not helper._sniff_image_bytes(b"Found")                  # 302 stub body
    assert not helper._sniff_image_bytes(b"<html><body>err</body>")  # error page
    assert not helper._sniff_image_bytes(b"GIF89a" + b"\x00" * 20)   # unsupported format


def test_download_guards_source_pin():
    """The 302-stub and junk-body guards must stay in save_cover_from_url:
    covers.openlibrary.org serves 302 + content-type image/jpeg, and the JPEG
    fast path in save_cover skips ImageMagick — without these a 9-byte stub
    overwrites a real cover (observed live on cwn-local, #404)."""
    import inspect
    import cps.helper as helper
    src = inspect.getsource(helper.save_cover_from_url)
    assert "img.status_code != 200" in src
    assert "_sniff_image_bytes" in src
    assert "allow_redirects=True" in src  # cover CDNs redirect; advocate re-validates each hop


def test_no_op_stub_is_gone_source_pin():
    import inspect
    src = inspect.getsource(m._apply_metadata_to_book)
    assert "_apply_cover_from_metadata" in src, (
        "the cover branch must call _apply_cover_from_metadata — the old "
        "branch ended in a bare `pass` and never fetched anything (#404)"
    )
    assert "TODO: Implement cover resolution" not in src
