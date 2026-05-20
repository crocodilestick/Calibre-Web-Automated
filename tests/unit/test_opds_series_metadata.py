# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Acceptance tests for CWA #1361 (@AnthonyGress): surface series
metadata in OPDS catalog output.

Background. The OPDS feed entry block in ``cps/templates/feed.xml``
emitted title, authors, publisher, pubdate, languages, tags, cover,
acquisition links — but never the series the book belongs to. OPDS
readers that surface series grouping (Marvin, KOReader, FBReader,
the Calibre Companion app) had no signal to use.

Janeczku's plain CW shoves a literal ``SERIES: NAME [N]`` line into
the summary text (`cps/templates/feed.xml` in their master). Readable
but unstructured — readers can't parse it for grouping or sort
order. We do it the structured way: emit Calibre's ``<calibre:series>``
+ ``<calibre:series_index>`` namespace elements (what Calibre itself
emits in its OPDS feed) AND ``<dcterms:isPartOf>`` (Dublin Core, the
generic fallback) so reader apps that recognize either can group.

These tests pin:
1. The feed.xml root declares the Calibre namespace
   ``xmlns:calibre="http://calibre.kovidgoyal.net/2009/metadata"``.
2. The entry block conditionally emits ``<calibre:series>`` when the
   book has a series.
3. The entry block emits ``<calibre:series_index>`` alongside.
4. The entry block emits ``<dcterms:isPartOf>`` as a generic fallback.
5. Books without a series produce no series-related elements (the
   ``{% if %}`` guard works correctly).
6. The series name is XML-escaped (defense against series with `&`
   or `<` in the name).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FEED_XML = REPO_ROOT / "cps" / "templates" / "feed.xml"


def _feed_source() -> str:
    return FEED_XML.read_text()


def test_feed_root_declares_calibre_namespace():
    """The Atom <feed> root must declare the Calibre namespace so the
    per-entry calibre:series elements are valid XML."""
    src = _feed_source()
    assert re.search(
        r'xmlns:calibre\s*=\s*"http://calibre\.kovidgoyal\.net/2009/metadata"',
        src,
    ), (
        "cps/templates/feed.xml root <feed> element must include "
        "`xmlns:calibre=\"http://calibre.kovidgoyal.net/2009/metadata\"` "
        "so the per-entry <calibre:series> and <calibre:series_index> "
        "elements below are valid. See CWA issue #1361 (@AnthonyGress)."
    )


def test_entry_emits_calibre_series_when_book_has_series():
    """The entry loop must include a conditional <calibre:series> +
    <calibre:series_index> block gated on the book having a series."""
    src = _feed_source()
    # Source-pin: the calibre:series open tag must reference the series name.
    assert re.search(
        r"<calibre:series>\s*\{\{[^}]*entry\.Books\.series",
        src,
    ), (
        "cps/templates/feed.xml entry block must include "
        "`<calibre:series>{{ entry.Books.series[0].name|e }}</calibre:series>` "
        "(or equivalent) inside a `{% if entry.Books.series %}` guard."
    )
    assert "<calibre:series_index>" in src, (
        "The entry block must also emit <calibre:series_index> so OPDS "
        "readers can sort books within a series. See CWA #1361."
    )


def test_entry_emits_dcterms_ispartof_for_generic_readers():
    """Dublin Core ``isPartOf`` is the generic relationship. OPDS readers
    that don't recognize the Calibre namespace (or don't want to depend
    on it) can still pick up the series via dcterms."""
    src = _feed_source()
    assert re.search(
        r"<dcterms:isPartOf>\s*\{\{[^}]*entry\.Books\.series",
        src,
    ), (
        "cps/templates/feed.xml entry block must include "
        "`<dcterms:isPartOf>{{ entry.Books.series[0].name|e }}</dcterms:isPartOf>` "
        "(or equivalent) so non-Calibre-aware OPDS readers can still see "
        "the series. See CWA #1361."
    )


def test_series_elements_gated_on_series_existence():
    """The series elements MUST be inside an `{% if entry.Books.series %}`
    guard — books without a series can't index series[0] without
    raising IndexError on render. Pinning so a future refactor doesn't
    silently drop the guard."""
    src = _feed_source()
    # Find the calibre:series open tag. Walk backwards through the
    # source to find the nearest preceding `{% if %}`. The if condition
    # must reference `entry.Books.series` (the truthy check on the list).
    series_idx = src.find("<calibre:series>")
    assert series_idx >= 0, "calibre:series tag not found"
    preceding = src[:series_idx]
    # Find the last `{% if %}` opening before the tag.
    if_matches = list(re.finditer(r"\{%-?\s*if\s+([^%]+?)\s*-?%\}", preceding))
    assert if_matches, (
        "calibre:series must be inside a `{% if %}` block — without it, "
        "rendering a book that has no series would raise IndexError on "
        "`entry.Books.series[0]`."
    )
    nearest_if = if_matches[-1]
    condition = nearest_if.group(1)
    assert "entry.Books.series" in condition, (
        f"The `{{% if %}}` guarding <calibre:series> must check "
        f"`entry.Books.series` (truthy on non-empty list). Got "
        f"condition: {condition!r}."
    )


def test_series_value_is_xml_escaped():
    """The series name is user-controlled (it comes from the Calibre
    library metadata). If a series is named like `Smith & Jones` or
    contains `<` / `>` / `'` / `"`, the unescaped form breaks the XML.
    Pin the `|e` (Jinja escape) filter."""
    src = _feed_source()
    # The calibre:series + dcterms:isPartOf MUST use the `e` filter.
    series_block = re.search(
        r"<calibre:series>\s*\{\{[^}]+?\}\}\s*</calibre:series>",
        src,
    )
    assert series_block, "calibre:series block not found in expected shape"
    assert re.search(r"\|\s*e\s*\}", series_block.group(0)), (
        f"The series name inside <calibre:series> must use Jinja's "
        f"`|e` filter (or `escape`/`e`) so series names with `&`, `<`, "
        f"`>` characters don't break the XML. Got: {series_block.group(0)!r}."
    )
