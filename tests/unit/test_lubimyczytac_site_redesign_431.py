# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for fork issue #431 — lubimyczytac.pl search broken.

Symptom (reporter @sltvtr): metadata search against the LubimyCzytac.pl
provider returns "No results found" even though the HTTP request succeeds
(200). Root cause: lubimyczytac.pl redesigned its search results and book
pages in 2026. The provider's XPaths still targeted the old DOM
(`authorAllBooks__single` tiles, `collapse-content` description, a single
`application/ld+json` block), so `parse_search_results` matched zero nodes
and the detail parser silently dropped publisher / description / dates.

These tests run the real parser against captured fixtures of the redesigned
pages (`tests/fixtures/lubimyczytac/`). They fail on the pre-fix XPaths
(zero search results, empty detail fields) and pass once the XPaths track
the new DOM.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from lxml.html import fromstring

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "lubimyczytac"


def _load_lubimyczytac_module():
    """Load cps/metadata_provider/lubimyczytac.py without the full `cps`
    package init (which boots login/database side effects). We shim the
    light dependencies and load the real Metadata base + provider files."""
    if "cps.metadata_provider.lubimyczytac" in sys.modules:
        return sys.modules["cps.metadata_provider.lubimyczytac"]

    cps_dir = REPO_ROOT / "cps"

    if "cps" not in sys.modules:
        cps_pkg = types.ModuleType("cps")
        cps_pkg.__path__ = [str(cps_dir)]
        sys.modules["cps"] = cps_pkg

        constants = types.ModuleType("cps.constants")
        constants.STATIC_DIR = str(cps_dir / "static")
        constants.USER_AGENT = "Calibre-Web-NextGen-tests"
        sys.modules["cps.constants"] = constants

        logger_mod = types.ModuleType("cps.logger")
        logger_mod.create = lambda *_a, **_k: types.SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            info=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        )
        sys.modules["cps.logger"] = logger_mod

        iso_mod = types.ModuleType("cps.isoLanguages")
        # The provider maps Polish/English labels to ISO codes itself; the
        # localisation step just needs to echo a stable string back.
        iso_mod.get_language_name = lambda _locale, code: code
        sys.modules["cps.isoLanguages"] = iso_mod

    # Load the real Metadata base (only needs cps.constants, now shimmed).
    if "cps.services.Metadata" not in sys.modules:
        services_pkg = types.ModuleType("cps.services")
        services_pkg.__path__ = [str(cps_dir / "services")]
        sys.modules["cps.services"] = services_pkg
        meta_spec = importlib.util.spec_from_file_location(
            "cps.services.Metadata", cps_dir / "services" / "Metadata.py"
        )
        meta_mod = importlib.util.module_from_spec(meta_spec)
        sys.modules["cps.services.Metadata"] = meta_mod
        meta_spec.loader.exec_module(meta_mod)

    provider_pkg = types.ModuleType("cps.metadata_provider")
    provider_pkg.__path__ = [str(cps_dir / "metadata_provider")]
    sys.modules["cps.metadata_provider"] = provider_pkg
    spec = importlib.util.spec_from_file_location(
        "cps.metadata_provider.lubimyczytac",
        cps_dir / "metadata_provider" / "lubimyczytac.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cps.metadata_provider.lubimyczytac"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lc():
    return _load_lubimyczytac_module()


@pytest.fixture(scope="module")
def search_root():
    return fromstring((FIXTURES / "search_wiedzmin.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def book_root():
    return fromstring((FIXTURES / "book_138913.html").read_text(encoding="utf-8"))


def _parser_for(lc, root):
    return lc.LubimyCzytacParser(root=root, metadata=lc.LubimyCzytac())


def test_search_results_parsed_from_redesigned_listing(lc, search_root):
    """parse_search_results must find the `book-card--l` tiles in the
    redesigned `listSearch` container. Pre-fix XPaths matched 0 nodes —
    this is the exact "No results found" the reporter saw."""
    parser = _parser_for(lc, search_root)
    matches = parser.parse_search_results()
    assert len(matches) >= 10, (
        f"Expected at least 10 search matches from the redesigned listing, "
        f"got {len(matches)} — the search-result XPath is stale again."
    )


def test_first_search_match_fields(lc, search_root):
    """Title, authors, url and the derived lubimyczytac id must extract
    cleanly from a redesigned book-card."""
    parser = _parser_for(lc, search_root)
    first = parser.parse_search_results()[0]
    assert "Wiedźmin" in first.title
    assert first.authors == ["Andrzej Sapkowski"]
    assert first.url == "https://lubimyczytac.pl/ksiazka/138913/wiedzmin"
    assert first.id == "138913"
    assert first.source.id == "lubimyczytac"


def test_detail_publisher_parsed(lc, book_root):
    """Publisher moved from a dt/dd row to a `Wydawnictwo:` span link.
    Pre-fix this returned None."""
    parser = _parser_for(lc, book_root)
    assert parser._parse_publisher() == "Nowa Fantastyka"


def test_detail_description_parsed(lc, book_root):
    """Description now reads from the full `#book-description` block instead
    of the truncated `og:description` meta fallback. Characterisation pin:
    the parsed description must carry the real book blurb."""
    parser = _parser_for(lc, book_root)
    description = parser._parse_description()
    assert description
    assert "Egzemplarz dołączony do gry" in description


def test_detail_language_parsed(lc, book_root):
    """Język dt/dd → ISO code mapping must resolve to Polish on the
    redesigned page. The exact rendering ("pol" vs the localised "Polish")
    depends on whether the real cps.isoLanguages is loaded, so pin on
    non-empty + Polish."""
    parser = _parser_for(lc, book_root)
    languages = parser._parse_languages(locale="en")
    assert languages, "language row no longer parsed — Język XPath is stale"
    assert any("pol" in lang.lower() for lang in languages)


def test_ld_json_book_block_selected(lc, book_root):
    """The page now emits an Organization ld+json block before the Book
    block; _parse_from_summary must pick the Book one. Pre-fix it read
    block[0] (Organization) and datePublished came back None."""
    parser = _parser_for(lc, book_root)
    assert parser._parse_from_summary(attribute_name="datePublished") == "1986-12-01"


def test_search_result_xpath_targets_book_card(lc):
    """Source-pin the new container class so a future revert to the old
    `authorAllBooks__single` selector is caught even without a live page."""
    assert "book-card" in lc.LubimyCzytac.BOOK_SEARCH_RESULT_XPATH
    assert "authorAllBooks__single" not in lc.LubimyCzytac.BOOK_SEARCH_RESULT_XPATH
