# -*- coding: utf-8 -*-
"""Auto-metadata-fetch data-safety regression tests (fork #402/#403/#405).

These pin the lead consolidated fix for the metadata auto-fetch corruption cluster:

- #402 — selection must prefer the candidate whose ISBN matches the book's existing
  ISBN over a blind ``results[0]`` (so a wrong foreign edition can't be applied).
- #403 — "smart application" mode must guard ALL canonical fields, not just three:
  authors / series / published date / rating / identifiers must not overwrite an
  existing meaningful value. Before the fix these were unconditional overwrites.
- #405 — the default provider hierarchy must be a single source of truth (one
  constant; SQL schema, template and Python fallbacks agree and include Open
  Library), and the dead duplicate module ``cps.auto_metadata`` must be gone.

The behavioural tests construct lightweight fakes and monkeypatch ``CWA_DB`` so they
exercise the real ``_apply_metadata_to_book`` logic; the end-to-end proof is the live
container repro (admin auto-fetch on, ingest a book whose correct author/ISBN would
otherwise be replaced by a wrong-edition match).
"""

import importlib.util
import json
import pathlib

import pytest

import cps.metadata_helper as m
from cps.metadata_constants import (
    DEFAULT_METADATA_PROVIDER_HIERARCHY,
    DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


# --- fakes -------------------------------------------------------------------

class _List(list):
    """A list that also supports the ORM-ish .clear()/.append() the code uses."""


class _Ident:
    def __init__(self, itype, val):
        self.type = itype
        self.val = val


class _Author:
    def __init__(self, name):
        self.name = name


class _Book:
    def __init__(self, *, authors=None, identifiers=None, series=None,
                 pubdate=None, ratings=None):
        self.id = 1
        self.title = "Some Title"
        self.authors = _List(_Author(a) for a in (authors or []))
        self.comments = _List()
        self.publishers = _List()
        self.tags = _List()
        self.series = _List(series or [])
        self.series_index = "1.0"
        self.pubdate = pubdate
        self.ratings = _List(ratings or [])
        self.identifiers = _List(identifiers or [])


class _FakeSession:
    def add(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeCDB:
    def __init__(self):
        self.session = _FakeSession()

    # smart-mode preserve paths never reach these; provide no-op returns anyway.
    def get_author_by_name(self, name):
        return _Author(name)

    def get_publisher_by_name(self, name):
        return None

    def get_tag_by_name(self, name):
        return None

    def get_series_by_name(self, name):
        return None


def _settings(**over):
    base = {
        "auto_metadata_smart_application": False,
        "auto_metadata_update_title": True,
        "auto_metadata_update_authors": True,
        "auto_metadata_update_description": True,
        "auto_metadata_update_publisher": True,
        "auto_metadata_update_tags": True,
        "auto_metadata_update_series": True,
        "auto_metadata_update_published_date": True,
        "auto_metadata_update_rating": True,
        "auto_metadata_update_identifiers": True,
        "auto_metadata_update_cover": False,
    }
    base.update(over)
    return base


def _patch_settings(monkeypatch, **over):
    settings = _settings(**over)
    monkeypatch.setattr(m, "CWA_DB", lambda: type("S", (), {"get_cwa_settings": staticmethod(lambda: settings)})())


def _meta(**kw):
    """A metadata record with everything falsy unless overridden, so only the field
    under test is exercised."""
    from types import SimpleNamespace
    base = dict(title="", authors=[], description="", publisher="", tags=[],
                series=None, series_index=None, publishedDate=None, rating=None,
                identifiers={}, cover=None)
    base.update(kw)
    return SimpleNamespace(**base)


# --- #402: ISBN-priority selection -------------------------------------------

class TestISBNPrioritySelection:
    def test_picks_isbn_match_over_first_result(self):
        from types import SimpleNamespace as NS
        wrong = NS(identifiers={})
        right = NS(identifiers={"isbn": "978-0-316-05543-7"})
        # hyphenation differs — normalization must still match
        assert m._select_metadata_result([wrong, right], "9780316055437") is right

    def test_falls_back_to_first_when_no_book_isbn(self):
        from types import SimpleNamespace as NS
        first = NS(identifiers={})
        assert m._select_metadata_result([first, NS(identifiers={"isbn": "x"})], None) is first

    def test_falls_back_to_first_when_no_candidate_matches(self):
        from types import SimpleNamespace as NS
        first = NS(identifiers={"isbn": "111"})
        assert m._select_metadata_result([first, NS(identifiers={"isbn": "222"})], "999") is first

    def test_book_isbn_prefers_isbn13(self):
        b = _Book(identifiers=[_Ident("isbn", "1111111111"), _Ident("isbn13", "9782222222222")])
        assert m._book_isbn(b) == "9782222222222"


# --- #403: smart mode guards every canonical field ---------------------------

class TestSmartModeGuards:
    def test_existing_author_preserved_in_smart_mode(self, monkeypatch):
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        book = _Book(authors=["Donna Tartt"])
        m._apply_metadata_to_book(book, _meta(authors=["Katia Benovich"]), _FakeCDB())
        assert [a.name for a in book.authors] == ["Donna Tartt"]

    def test_existing_isbn_preserved_in_smart_mode(self, monkeypatch):
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        book = _Book(identifiers=[_Ident("isbn", "9780316055437")])
        m._apply_metadata_to_book(book, _meta(identifiers={"isbn": "2259221866"}), _FakeCDB())
        assert book.identifiers[0].val == "9780316055437"

    def test_existing_series_preserved_in_smart_mode(self, monkeypatch):
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        book = _Book(series=["Real Series"])
        m._apply_metadata_to_book(book, _meta(series="Wrong Series", series_index="3"), _FakeCDB())
        assert [s for s in book.series] == ["Real Series"]

    def test_existing_pubdate_preserved_in_smart_mode(self, monkeypatch):
        import datetime
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        real = datetime.date(2013, 10, 22)
        book = _Book(pubdate=real)
        m._apply_metadata_to_book(book, _meta(publishedDate="1999-01-01"), _FakeCDB())
        assert book.pubdate == real

    def test_existing_rating_preserved_in_smart_mode(self, monkeypatch):
        from types import SimpleNamespace as NS
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        book = _Book(ratings=[NS(rating=8)])
        m._apply_metadata_to_book(book, _meta(rating=2.0), _FakeCDB())
        assert book.ratings[0].rating == 8

    def test_smart_mode_fills_missing_identifier_type(self, monkeypatch):
        # smart mode should still ADD an identifier type the book is missing
        _patch_settings(monkeypatch, auto_metadata_smart_application=True)
        book = _Book(identifiers=[_Ident("isbn", "9780316055437")])
        m._apply_metadata_to_book(book, _meta(identifiers={"goodreads": "12345"}), _FakeCDB())
        vals = {i.type: i.val for i in book.identifiers}
        assert vals.get("isbn") == "9780316055437" and vals.get("goodreads") == "12345"

    def test_normal_mode_still_overwrites_author(self, monkeypatch):
        # regression guard: the fix must not break non-smart (default) overwrite behaviour
        _patch_settings(monkeypatch, auto_metadata_smart_application=False)
        book = _Book(authors=["Old Author"])
        m._apply_metadata_to_book(book, _meta(authors=["New Author"]), _FakeCDB())
        assert [a.name for a in book.authors] == ["New Author"]


# --- #405: single source of truth + dead module gone -------------------------

class TestProviderHierarchySingleSource:
    def test_constant_and_json_agree_and_include_openlibrary(self):
        assert json.loads(DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON) == DEFAULT_METADATA_PROVIDER_HIERARCHY
        assert "openlibrary" in DEFAULT_METADATA_PROVIDER_HIERARCHY

    def test_schema_default_matches_canonical_json(self):
        sql = (REPO / "scripts" / "cwa_schema.sql").read_text()
        assert DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON in sql, \
            "cwa_schema.sql metadata_provider_hierarchy default must equal the canonical JSON"

    def test_template_fallback_matches_canonical_json(self):
        html = (REPO / "cps" / "templates" / "cwa_settings.html").read_text()
        assert DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON in html

    def test_no_divergent_hierarchy_literals_remain(self):
        # the three old divergent literals must be gone from the Python sources
        for rel in ("cps/metadata_helper.py", "cps/cwa_functions.py"):
            src = (REPO / rel).read_text()
            assert '["google","douban","dnb"' not in src, f"old literal still in {rel}"
            assert '["ibdb","google","dnb"]' not in src, f"old literal still in {rel}"

    def test_dead_auto_metadata_module_removed(self):
        assert importlib.util.find_spec("cps.auto_metadata") is None, \
            "the dead duplicate cps/auto_metadata.py must be deleted (#405)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
