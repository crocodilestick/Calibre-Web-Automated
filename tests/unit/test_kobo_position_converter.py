# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Kobo position → epub.js CFI converter
(``cps.services.kobo_position``) — H1 Phase 2.

The prototype documented in ``notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md``
§3.6 was verified against 145 real highlights from a real Kobo device
and produced 99.3% round-trip success — 144 exact matches, 1
nested-span failure caused by regex extraction. The production module
swaps the regex span scanner for lxml DOM parsing; these tests pin
the surface that P3's import endpoint will rely on.

Test surface:
* parse_spine returns chapter hrefs in spine order
* Kobo-id selector format extracts the unescaped id
* Single-span kepub highlight → exact CFI
* Multi-span kepub highlight → CFI references the correct end span
* Mid-span start offset (offset > 0) → CFI carries the right offset
* Three-digit span suffix (kobo.4.11 / kobo.4.13) → no regex eating
* Plain EPUB (no KoboSpan IDs) → falls back to child-index walk
* Missing content_id / wrong file / invalid path → None, no raise
* DOM cache invalidates on EPUB mtime change
* ContextString fallback when both selector + child-index are absent
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.fixtures.kepub_fixture import build_synthetic_kepub, build_minimal_epub


@pytest.fixture
def synthetic_kepub(tmp_path):
    return build_synthetic_kepub(tmp_path / "synth.kepub")


@pytest.fixture
def minimal_epub(tmp_path):
    return build_minimal_epub(tmp_path / "minimal.epub")


@pytest.fixture(autouse=True)
def _clear_position_caches():
    """The module-level lru_caches survive across tests. Reset them
    between cases so each test sees a clean fixture state — required
    for the mtime-invalidation test below."""
    from cps.services import kobo_position
    kobo_position._get_spine.cache_clear()
    kobo_position._get_chapter_dom.cache_clear()
    yield


# ---------------------------------------------------------------------------
# parse_spine + helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpineParse:
    def test_spine_returns_chapters_in_order(self, synthetic_kepub):
        from cps.services.kobo_position import parse_spine

        spine = parse_spine(synthetic_kepub)
        assert spine == ["chapter1.html", "chapter2.html", "chapter3.html"]

    def test_spine_empty_for_nonexistent_file(self, tmp_path):
        from cps.services.kobo_position import parse_spine

        bogus = tmp_path / "does-not-exist.epub"
        with pytest.raises(Exception):
            # zipfile.ZipFile will raise FileNotFoundError; that's the
            # caller's signal that the EPUB is missing.
            parse_spine(bogus)


@pytest.mark.unit
class TestExtractKoboSpanId:
    def test_unescapes_dots(self):
        from cps.services.kobo_position import _extract_kobospan_id

        assert _extract_kobospan_id("span#kobo\\.4\\.1") == "kobo.4.1"

    def test_three_digit_suffix(self):
        """The prototype regex sometimes ate the third digit when the
        kepub had spans like ``kobo.4.11``. Pin the production helper."""
        from cps.services.kobo_position import _extract_kobospan_id

        assert _extract_kobospan_id("span#kobo\\.4\\.11") == "kobo.4.11"
        assert _extract_kobospan_id("span#kobo\\.4\\.13") == "kobo.4.13"

    def test_no_fragment_returns_none(self):
        from cps.services.kobo_position import _extract_kobospan_id

        assert _extract_kobospan_id("OEBPS/chapter6.html") is None
        assert _extract_kobospan_id("") is None


# ---------------------------------------------------------------------------
# compute_cfi_range — kepub fast path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeCfiRangeKepub:
    def test_single_span_highlight(self, synthetic_kepub):
        """Span boundaries are identical (start_id == end_id) — the
        most common case (~60% of highlights per design doc §3.6
        finding 4)."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99,
            end_offset=15,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # chapter1 is spine index 0 → /6/2. The fixture chapter is
        # <body><p><span id=kobo.1.1>…</span>…</p></body>, so the span is
        # body(/4) > p(/2) > 1st span(/2). Same start/end span → a 3-part
        # range CFI whose common path reaches the span and whose ends are
        # text-node (/1) offsets.
        assert cfi == "epubcfi(/6/2!/4/2/2[kobo.1.1],/1:0,/1:15)"

    def test_live_capture_null_child_index_uses_selector(self, synthetic_kepub):
        """Live reading-services PATCH capture omits StartContainerChildIndex,
        so child_index is stored as NULL (not the -99 sentinel). When the
        KoboSpan IDs are present, the selector path must still be used —
        a real-device test (2026-05-24) found that gating the selector
        path on child_index == -99 meant every live-captured kepub
        highlight resolved to None and never rendered as a web-reader
        overlay."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=None,   # live capture stores NULL
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=None,
            end_offset=15,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        assert cfi == "epubcfi(/6/2!/4/2/2[kobo.1.1],/1:0,/1:15)", (
            "NULL child_index with KoboSpan IDs present must still resolve "
            "via the selector path (live-captured kepub highlights)"
        )

    def test_multi_span_highlight(self, synthetic_kepub):
        """Highlight spans two consecutive KoboSpans — about 40% of
        real highlights (design doc §3.6 finding 4). Pin that the CFI
        carries the terminal span id, not the start id."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.3",
            end_container_child_index=-99,
            end_offset=21,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # Cross-span: common ancestor is the <p> (/4/2); the two ends
        # diverge to the 1st (/2) and 3rd (/6) spans, each with a /1
        # text-node offset.
        assert cfi == "epubcfi(/6/2!/4/2,/2[kobo.1.1]/1:0,/6[kobo.1.3]/1:21)"

    def test_mid_span_start_offset(self, synthetic_kepub):
        """The "Comrade Napoleon" example from design doc §3.6 — start
        offset 90 into a single span — pins that the offset round-trips
        without truncation."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter2.html",
            start_container_path="span#kobo\\.2\\.1",
            start_container_child_index=-99,
            start_offset=8,  # mid-word offset
            end_container_path="span#kobo\\.2\\.1",
            end_container_child_index=-99,
            end_offset=17,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # chapter2 is spine index 1 → /6/4. Single span, mid-span offsets.
        assert cfi == "epubcfi(/6/4!/4/2/2[kobo.2.1],/1:8,/1:17)"

    def test_three_digit_span_suffix_round_trips(self, tmp_path):
        """The prototype's 0.7% failure was on three-digit span ids —
        regex extraction sometimes ate the third digit. Pin that the
        lxml port handles ``kobo.4.11`` cleanly."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range
        from tests.fixtures.kepub_fixture import _kobo_chapter_html, OPF_TEMPLATE, CONTAINER_XML
        import zipfile

        # Build a one-chapter kepub with three-digit span ids.
        chapter = _kobo_chapter_html([
            (f"kobo.4.{i}", f"word{i}") for i in range(1, 14)
        ])
        opf = OPF_TEMPLATE.format(
            book_uuid="three-digit-test",
            manifest_items='    <item id="ch1" href="chapter.html" media-type="application/xhtml+xml"/>',
            spine_items='    <itemref idref="ch1"/>',
        )
        kepub = tmp_path / "threedigit.kepub"
        with zipfile.ZipFile(kepub, "w") as zf:
            zf.writestr("META-INF/container.xml", CONTAINER_XML)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/chapter.html", chapter)

        pos = KoboPosition(
            content_id="three-digit-test!!chapter.html",
            start_container_path="span#kobo\\.4\\.11",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.4\\.13",
            end_container_child_index=-99,
            end_offset=29,
        )
        cfi = compute_cfi_range(kepub, pos)
        # 13 spans in one <p>: kobo.4.11 is the 11th element child (/22),
        # kobo.4.13 the 13th (/26); common ancestor is the <p> (/4/2).
        assert cfi == "epubcfi(/6/2!/4/2,/22[kobo.4.11]/1:0,/26[kobo.4.13]/1:29)"


# ---------------------------------------------------------------------------
# CFI round-trip — the generated CFI resolves back to the right span/text
# ---------------------------------------------------------------------------


def _walk_cfi_element_path(tree, path):
    """Resolve a CFI element path like ``/4/2/2[kobo.1.1]`` against a
    parsed lxml tree, returning the landed element. Even steps are the
    Nth element child (1-based = step/2). ``/4`` is <body>. Used by the
    round-trip tests to prove the converter's element numbering is
    correct — independent of the string-equality assertions above."""
    import re as _re
    body = tree.xpath("//body")[0]
    # The leading /4 anchors <body>; walk the remaining even steps.
    steps = _re.findall(r"/(\d+)(?:\[([^\]]+)\])?", path)
    # First step is /4 = body itself; skip it, then descend.
    cur = body
    for raw, assertion in steps[1:]:
        n = int(raw)
        if n % 2 != 0:
            break  # reached a text step — element walk done
        idx = n // 2 - 1
        children = [c for c in cur if isinstance(c.tag, str)]
        cur = children[idx]
        if assertion:
            assert cur.get("id") == assertion, (
                f"CFI step /{n}[{assertion}] landed on id={cur.get('id')!r}"
            )
    return cur


@pytest.mark.unit
class TestCfiRoundTrip:
    """The string assertions above pin the exact CFI; these prove that
    string actually resolves back to the highlighted text when walked
    against the source DOM — so a future numbering change can't pass by
    updating only the expected-string constant."""

    def test_single_span_roundtrip(self, synthetic_kepub):
        from cps.services.kobo_position import (
            KoboPosition, compute_cfi_range, _get_chapter_dom,
        )

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99,
            end_offset=15,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # epubcfi(common,start,end) — common reaches the span.
        common = cfi[len("epubcfi("):-1].split(",")[0].split("!", 1)[1]
        cache_key = (str(synthetic_kepub), synthetic_kepub.stat().st_mtime_ns)
        tree = _get_chapter_dom(cache_key, synthetic_kepub, "chapter1.html")
        span = _walk_cfi_element_path(tree, common)
        assert span.get("id") == "kobo.1.1"
        # /1:0 .. /1:15 over the span's text → the exact highlighted run.
        assert span.text[0:15] == "Four legs good."

    def test_multi_span_roundtrip(self, synthetic_kepub):
        from cps.services.kobo_position import (
            KoboPosition, compute_cfi_range, _get_chapter_dom,
        )

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.3",
            end_container_child_index=-99,
            end_offset=21,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        parts = cfi[len("epubcfi("):-1].split(",")
        common = parts[0].split("!", 1)[1]
        cache_key = (str(synthetic_kepub), synthetic_kepub.stat().st_mtime_ns)
        tree = _get_chapter_dom(cache_key, synthetic_kepub, "chapter1.html")
        # Common ancestor is the <p>; start/end paths are relative to it.
        common_el = _walk_cfi_element_path(tree, common)
        assert common_el.tag == "p"
        start_el = _walk_cfi_element_path(tree, common + parts[1])
        end_el = _walk_cfi_element_path(tree, common + parts[2])
        assert start_el.get("id") == "kobo.1.1"
        assert end_el.get("id") == "kobo.1.3"
        assert start_el.text.startswith("Four legs")
        assert end_el.text[0:21] == "All animals are equal"


# ---------------------------------------------------------------------------
# compute_cfi_range — plain EPUB child-index fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeCfiRangePlainEpub:
    def test_plain_epub_uses_child_index(self, synthetic_kepub):
        """chapter3 in the fixture has no KoboSpan IDs. Kobo would
        emit a non-selector path + a real (non-sentinel) child index.
        The converter should produce a CFI with even-step elements."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter3.html",
            start_container_path="/html/body/p[2]",
            start_container_child_index=2,
            start_offset=0,
            end_container_path="/html/body/p[2]",
            end_container_child_index=2,
            end_offset=23,
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # chapter3 is spine index 2 → /6/6. Child index 2 → /4 step.
        assert cfi == "epubcfi(/6/6!/4:0,/4:23)"


# ---------------------------------------------------------------------------
# compute_cfi_range — error/edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeCfiRangeEdgeCases:
    def test_malformed_content_id_returns_none(self, synthetic_kepub):
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="no-double-bang-here",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99,
            end_offset=10,
        )
        assert compute_cfi_range(synthetic_kepub, pos) is None

    def test_chapter_not_in_spine_returns_none(self, synthetic_kepub):
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000!!nonexistent_chapter.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99,
            end_offset=10,
        )
        assert compute_cfi_range(synthetic_kepub, pos) is None

    def test_missing_epub_returns_none(self, tmp_path):
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="x!!chapter1.html",
            start_container_path="span#kobo\\.1\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.1\\.1",
            end_container_child_index=-99,
            end_offset=10,
        )
        assert compute_cfi_range(tmp_path / "does-not-exist.epub", pos) is None

    def test_bare_basename_chapter_match(self, minimal_epub):
        """The minimal_epub fixture has chapter hrefs without OEBPS/
        prefix — pin that ``_resolve_spine_index`` finds them."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa!!ch1.html",
            start_container_path="span#kobo\\.4\\.1",
            start_container_child_index=-99,
            start_offset=0,
            end_container_path="span#kobo\\.4\\.1",
            end_container_child_index=-99,
            end_offset=11,
        )
        cfi = compute_cfi_range(minimal_epub, pos)
        assert cfi == "epubcfi(/6/2!/4/2/2[kobo.4.1],/1:0,/1:11)"


# ---------------------------------------------------------------------------
# DOM cache invalidation on EPUB mtime change
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCacheInvalidation:
    def test_spine_cache_invalidates_when_epub_replaced(self, tmp_path):
        """A user re-uploading a book must invalidate the spine cache.
        The lru_cache is keyed on (path, mtime_ns) so replacing the
        file with different content should produce a fresh parse."""
        from cps.services.kobo_position import parse_spine, _get_spine

        epub = tmp_path / "book.kepub"
        build_synthetic_kepub(epub)

        spine_v1 = parse_spine(epub)
        assert spine_v1 == ["chapter1.html", "chapter2.html", "chapter3.html"]

        # Wait at least one filesystem tick + replace with the minimal
        # fixture (single chapter) so the cache key changes.
        time.sleep(0.01)
        epub.unlink()
        build_minimal_epub(epub)
        # Touch with a different mtime explicitly so APFS/HFS+
        # nanosecond resolution doesn't pretend they're identical.
        new_mtime = epub.stat().st_mtime_ns + 1_000_000_000  # +1 sec
        import os
        os.utime(epub, ns=(new_mtime, new_mtime))

        spine_v2 = parse_spine(epub)
        assert spine_v2 == ["ch1.html"]
        # Cache must reflect the new mtime — calling through the wrapper
        # with the new key yields the new spine.
        cached = _get_spine(
            (str(epub), epub.stat().st_mtime_ns), epub
        )
        assert cached == ["ch1.html"]


# ---------------------------------------------------------------------------
# ContextString fallback re-anchoring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContextStringFallback:
    def test_fallback_anchors_via_context_text(self, synthetic_kepub):
        """When neither the KoboSpan id nor a valid child index is
        usable, fall back to searching the chapter text for the
        ``context_string`` and producing a degraded offset-based CFI."""
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        # No KoboSpan id (path doesn't end in #...), no child index
        # (None on both ends). Must fall through to context.
        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="/html/body/p",
            start_container_child_index=None,
            start_offset=0,
            end_container_path="/html/body/p",
            end_container_child_index=None,
            end_offset=21,
            context_string="All animals are equal.",
        )
        cfi = compute_cfi_range(synthetic_kepub, pos)
        # The fallback produces a non-None CFI string with the right
        # shape — text-content offset rather than span anchor.
        assert cfi is not None
        assert cfi.startswith("epubcfi(/6/2!/4:")

    def test_fallback_returns_none_when_no_context(self, synthetic_kepub):
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="/html/body/p",
            start_container_child_index=None,
            start_offset=0,
            end_container_path="/html/body/p",
            end_container_child_index=None,
            end_offset=10,
            context_string=None,
        )
        assert compute_cfi_range(synthetic_kepub, pos) is None

    def test_fallback_returns_none_when_context_not_in_chapter(self, synthetic_kepub):
        from cps.services.kobo_position import KoboPosition, compute_cfi_range

        pos = KoboPosition(
            content_id="00000000-0000-0000-0000-deadbeefcafe!!chapter1.html",
            start_container_path="/html/body/p",
            start_container_child_index=None,
            start_offset=0,
            end_container_path="/html/body/p",
            end_container_child_index=None,
            end_offset=20,
            context_string="This text is nowhere in the chapter.",
        )
        assert compute_cfi_range(synthetic_kepub, pos) is None
