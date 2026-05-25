# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Kobo Bookmark → EPUB CFI converter (production port of the
99.3%-round-trip-proven prototype from the 2026-05-17 borrow-day
session).

See ``notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md`` §3.5 for the
algorithm rationale and §3.6 for the round-trip evidence. This module
is the H1 Phase 2 deliverable; P3's import endpoint calls
:func:`compute_cfi_range` per highlight at ingest time, P5's web-reader
JS consumes the resulting CFI strings via ``epub.js``'s
``rendition.annotations.highlight(cfi, ...)``.

Production hardening over the prototype:

* **DOM parser instead of regex** — `lxml.html.fromstring` plus
  XPath lookups replace the brittle ``<span[^>]*id=...>`` regex that
  produced the prototype's lone 0.7% failure on nested spans.
* **Per-EPUB cache** — parsing a 30 KB chapter HTML on every one of a
  book's 100+ highlights is wasteful; the spine + per-chapter parsed
  tree are cached behind ``functools.lru_cache`` keyed by EPUB path +
  mtime so a re-uploaded book invalidates automatically.
* **ContextString fallback** — when CFI resolution fails (for example
  the EPUB was re-uploaded with a different KoboSpan ID layout), the
  module re-anchors to the surrounding text snippet that Kobo stores
  in ``Bookmark.ContextString`` — a degraded match that still puts the
  highlight in the right paragraph.
* **Plain EPUB (no KoboSpan IDs)** — when ``StartContainerChildIndex``
  is not the ``-99`` selector sentinel, the module falls back to
  DOM-index walking via ``StartContainerChildIndex`` instead of the
  KoboSpan ``id`` lookup.

The public surface is intentionally narrow — :func:`compute_cfi_range`
plus :func:`parse_spine`. Internal helpers are underscore-prefixed and
not part of the import-contract.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from lxml import html as lxml_html

log = logging.getLogger(__name__)

# OPF / container.xml namespace constants. ElementTree expects the URL
# explicitly because no XML default-namespace handling.
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}

# Sentinel value Kobo writes in ``StartContainerChildIndex`` when the
# corresponding ``StartContainerPath`` is a CSS selector (kepub case)
# rather than a DOM-index walk path (plain EPUB case). Discovered
# empirically against 145 real highlights from Maggie's Animal Farm
# kepub (see design doc §3.6 finding 2).
KOBO_SELECTOR_SENTINEL = -99

# A path that resembles ``span#kobo\\.4\\.1`` — Kobo escapes the dots
# because the source format is a literal CSS selector. The capturing
# group preserves the un-escaped id form (``kobo.4.1``).
_KOBOSPAN_PATH_RE = re.compile(r"#([\w.\\-]+)$")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KoboPosition:
    """One Kobo highlight's position fields, exactly as they live in the
    ``KoboReader.sqlite.Bookmark`` table (see
    ``notes/KOBO-PROTOCOL-REFERENCE.md`` §10.1)."""

    content_id: str                       # "<book_uuid>!!<chapter_file>"
    start_container_path: str
    start_container_child_index: Optional[int]
    start_offset: int
    end_container_path: str
    end_container_child_index: Optional[int]
    end_offset: int
    context_string: Optional[str] = None  # for fallback re-anchoring


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_cfi_range(epub_path: Path, position: KoboPosition) -> Optional[str]:
    """Return an ``epubcfi(...)`` string anchoring ``position`` inside
    the EPUB at ``epub_path``, or ``None`` if the position cannot be
    resolved even with the ContextString fallback.

    The CFI is consumable directly by epub.js's
    ``rendition.annotations.highlight(cfi, ...)`` — no further
    transformation needed at the JS layer.

    The function never raises on a malformed position; degraded inputs
    log a warning and return ``None`` so the import path can record the
    raw position fields (for re-anchoring later) without dropping the
    highlight entirely.
    """
    if not isinstance(epub_path, Path):
        epub_path = Path(epub_path)
    if not epub_path.is_file():
        log.warning("compute_cfi_range: %s does not exist", epub_path)
        return None
    if not position.content_id or "!!" not in position.content_id:
        log.warning(
            "compute_cfi_range: malformed content_id %r — expected '<uuid>!!<chapter>'",
            position.content_id,
        )
        return None

    chapter_file = position.content_id.split("!!", 1)[1]
    cache_key = (str(epub_path), epub_path.stat().st_mtime_ns)
    try:
        spine = _get_spine(cache_key, epub_path)
    except Exception as e:
        log.warning("compute_cfi_range: spine parse failed for %s: %s", epub_path, e)
        return None
    if not spine:
        log.warning("compute_cfi_range: empty spine for %s", epub_path)
        return None

    spine_index = _resolve_spine_index(spine, chapter_file)
    if spine_index is None:
        log.warning(
            "compute_cfi_range: chapter %r not in spine of %s",
            chapter_file, epub_path,
        )
        return None
    spine_step = f"/6/{2 * (spine_index + 1)}"

    start_id = _extract_kobospan_id(position.start_container_path)
    end_id = _extract_kobospan_id(position.end_container_path)

    if start_id and end_id:
        # The kepub path — KoboSpan IDs present. Walk the chapter DOM to
        # produce a structurally valid, portable source-document CFI
        # (proper 3-part range, offsets on text nodes). The KoboSpan id is
        # the reliable anchor whenever it's present; child_index is only
        # consulted for plain EPUBs below. (Kobo writes child_index=-99 in
        # KoboReader.sqlite, but the live reading-services PATCH omits it,
        # so live-captured annotations store NULL — gating the selector
        # path on child_index==-99 broke every live capture, found via
        # real-device test 2026-05-24.)
        #
        # The web reader does NOT consume this CFI — epub.js injects
        # wrapper divs at render time, so it regenerates a wrapper-aware
        # CFI client-side from the KoboSpan id (annotations.js). This
        # string is for export portability / spec-compliant resolvers.
        try:
            tree = _get_chapter_dom(cache_key, epub_path, chapter_file)
            if tree is not None:
                cfi = _kepub_range_cfi(
                    tree, spine_step, start_id, end_id,
                    position.start_offset, position.end_offset,
                )
                if cfi:
                    return cfi
        except Exception as e:
            log.warning(
                "compute_cfi_range: kepub DOM walk failed for %s::%s — %s",
                epub_path, chapter_file, e,
            )
        # KoboSpan ids present but unresolvable in the DOM (re-uploaded
        # book with a different layout?) — fall through to context.
        return _fallback_via_context(
            epub_path, cache_key, chapter_file, spine_step, position,
        )

    # Plain-EPUB fallback: no KoboSpan IDs to anchor on. Walk by child
    # index instead. The CFI step encoding for child-index walks is
    # ``/2N`` for the Nth element child (1-indexed), even-only so odd
    # steps stay reserved for text nodes.
    start_step = _child_index_to_cfi_step(position.start_container_child_index)
    end_step = _child_index_to_cfi_step(position.end_container_child_index)
    if start_step is None or end_step is None:
        # Neither selector nor child-index — last resort, re-anchor via
        # context_string against the parsed chapter DOM.
        return _fallback_via_context(
            epub_path, cache_key, chapter_file, spine_step, position,
        )

    return f"epubcfi({spine_step}!{start_step}:{position.start_offset},{end_step}:{position.end_offset})"


@lru_cache(maxsize=64)
def _get_spine(cache_key: tuple, epub_path_arg: Path) -> list[str]:
    """Cache-keyed wrapper over :func:`parse_spine`. ``cache_key``
    encodes ``(path_str, mtime_ns)`` so a re-uploaded EPUB invalidates
    automatically. ``epub_path_arg`` is the actual ``Path`` used —
    passing it explicitly lets lru_cache invalidate on stat changes
    without re-stat'ing on hits."""
    return parse_spine(epub_path_arg)


def parse_spine(epub_path: Path) -> list[str]:
    """Return the EPUB's spine — a list of chapter HTML hrefs in
    reading order. Used to compute the ``/6/2N`` part of the CFI."""
    if not isinstance(epub_path, Path):
        epub_path = Path(epub_path)

    with zipfile.ZipFile(epub_path) as zf:
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8")
        except KeyError:
            opf_path = "content.opf"
        else:
            root = ET.fromstring(container)
            rf = root.find(".//c:rootfile", _CONTAINER_NS)
            if rf is not None and rf.get("full-path"):
                opf_path = rf.get("full-path")
            else:
                opf_path = "content.opf"

        try:
            opf = zf.read(opf_path).decode("utf-8")
        except KeyError:
            return []

    root = ET.fromstring(opf)
    manifest = {
        it.attrib["id"]: it.attrib.get("href", "")
        for it in root.findall(".//opf:manifest/opf:item", _OPF_NS)
    }
    spine_refs = root.findall(".//opf:spine/opf:itemref", _OPF_NS)
    out = []
    for ref in spine_refs:
        idref = ref.get("idref")
        if idref and idref in manifest:
            out.append(manifest[idref])
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_kobospan_id(container_path: str) -> Optional[str]:
    """Parse ``span#kobo\\.4\\.1`` → ``kobo.4.1``. Returns ``None`` if
    no ``#<id>`` fragment present (e.g. a plain-EPUB DOM path)."""
    if not container_path:
        return None
    m = _KOBOSPAN_PATH_RE.search(container_path)
    if not m:
        return None
    return m.group(1).replace("\\", "")


def _cfi_element_step(el) -> str:
    """One CFI step for an element relative to its parent, using
    epub.js's numbering: element children are numbered 2, 4, 6, … (the
    Nth element child, 1-based, times two), with the element's ``id``
    appended as an assertion. Text nodes don't shift element numbering —
    lxml only yields element/comment/PI children when iterating, so the
    index is naturally element-only, matching epub.js's ``.children``."""
    parent = el.getparent()
    if parent is None:
        return ""
    sibs = [c for c in parent if isinstance(c.tag, str)]
    try:
        idx = sibs.index(el)
    except ValueError:
        idx = 0
    step = f"/{2 * (idx + 1)}"
    eid = el.get("id")
    return step + (f"[{eid}]" if eid else "")


def _element_chain_below_body(el):
    """Return the element chain ``[body_child, …, el]`` — every element
    from ``<body>``'s direct child down to ``el`` inclusive, excluding
    ``<body>`` itself (the CFI anchors body as the literal ``/4`` prefix,
    matching epub.js and the EPUB CFI convention for ``<html><head/>
    <body/></html>``)."""
    chain = []
    cur = el
    while cur is not None:
        parent = cur.getparent()
        if parent is None:
            break
        chain.append(cur)
        ptag = parent.tag if isinstance(parent.tag, str) else ""
        if ptag == "body" or ptag.endswith("}body"):
            break
        cur = parent
    chain.reverse()
    return chain


def _kepub_range_cfi(tree, spine_step, start_id, end_id, start_offset, end_offset):
    """Build a valid 3-part EPUB CFI range
    (``epubcfi(<common>,<start>,<end>)``) anchoring a highlight between
    two KoboSpans in the parsed chapter ``tree``.

    The CFI is computed against the *source* document (no reader
    wrappers), so it is portable — a spec-compliant resolver follows the
    element path and validates the ``[kobo.x.y]`` id assertions. The web
    reader does NOT consume this string: epub.js injects wrapper divs at
    render time that shift every step, so the reader regenerates its own
    wrapper-aware CFI client-side from the KoboSpan id (see
    ``cps/static/js/reading/annotations.js``). Returns ``None`` if either
    span is absent from the chapter."""
    start_matches = tree.xpath("//*[@id=$v]", v=start_id)
    end_matches = tree.xpath("//*[@id=$v]", v=end_id)
    if not start_matches or not end_matches:
        return None
    start_el, end_el = start_matches[0], end_matches[0]

    start_chain = _element_chain_below_body(start_el)
    end_chain = _element_chain_below_body(end_el)
    if not start_chain or not end_chain:
        return None

    # Deepest shared ancestor element (compare by identity).
    common_len = 0
    for a, b in zip(start_chain, end_chain):
        if a is b:
            common_len += 1
        else:
            break
    common_chain = start_chain[:common_len]
    start_rest = start_chain[common_len:]
    end_rest = end_chain[common_len:]

    base = f"{spine_step}!/4" + "".join(_cfi_element_step(e) for e in common_chain)
    if not start_rest and not end_rest:
        # Same KoboSpan — the common path already reaches it. Both ends
        # are text-node offsets into that span's first text node (/1).
        return f"epubcfi({base},/1:{start_offset},/1:{end_offset})"
    start_path = "".join(_cfi_element_step(e) for e in start_rest) + f"/1:{start_offset}"
    end_path = "".join(_cfi_element_step(e) for e in end_rest) + f"/1:{end_offset}"
    return f"epubcfi({base},{start_path},{end_path})"


def _child_index_to_cfi_step(child_index: Optional[int]) -> Optional[str]:
    """Convert ``StartContainerChildIndex`` to a CFI step. Kobo's
    1-indexed Nth-child becomes CFI's ``/2N`` even-step convention.
    Returns ``None`` if the index is missing or the sentinel value."""
    if child_index is None or child_index == KOBO_SELECTOR_SENTINEL or child_index <= 0:
        return None
    return f"/{2 * child_index}"


def _resolve_spine_index(spine: list[str], chapter_file: str) -> Optional[int]:
    """Match the ``chapter_file`` (a bare basename) against entries in
    ``spine`` (which may have ``OEBPS/`` or other prefixes)."""
    for i, href in enumerate(spine):
        if href == chapter_file or href.endswith("/" + chapter_file):
            return i
    return None


def _fallback_via_context(
    epub_path: Path,
    cache_key: tuple,
    chapter_file: str,
    spine_step: str,
    position: KoboPosition,
) -> Optional[str]:
    """Last-resort: parse the chapter DOM and search for
    ``context_string`` to derive an approximate text-offset CFI. The
    resulting CFI is intentionally less precise than the KoboSpan
    fast-path — it points at the chapter root with a text-content
    offset, which epub.js can still render as a highlight, just with
    paragraph-level rather than span-level accuracy."""
    if not position.context_string:
        return None
    try:
        tree = _get_chapter_dom(cache_key, epub_path, chapter_file)
    except Exception as e:
        log.warning(
            "compute_cfi_range fallback: DOM parse failed for %s::%s — %s",
            epub_path, chapter_file, e,
        )
        return None
    if tree is None:
        return None
    body_text = tree.text_content() or ""
    idx = body_text.find(position.context_string)
    if idx < 0:
        # Try a tighter slice — Kobo's ContextString includes ±50 chars
        # of surrounding text; the highlight itself is at offset
        # `start_offset` within that.
        if position.start_offset < len(position.context_string):
            anchor = position.context_string[position.start_offset:]
            idx = body_text.find(anchor[:80] if len(anchor) > 80 else anchor)
        if idx < 0:
            return None
    # CFI step into the body's text content — same `spine_step!/4`
    # rendition fragment, then a single text-offset.
    return f"epubcfi({spine_step}!/4:{idx},/4:{idx + (position.end_offset - position.start_offset)})"


@lru_cache(maxsize=256)
def _get_chapter_dom(cache_key: tuple, epub_path_arg: Path, chapter_file: str):
    """Cache the parsed lxml tree for one chapter. Invalidated by the
    same ``cache_key`` ``(path, mtime_ns)`` as ``_get_spine`` so
    re-uploads bust both caches together."""
    with zipfile.ZipFile(epub_path_arg) as zf:
        candidates = [chapter_file] + [
            n for n in zf.namelist() if n.endswith("/" + chapter_file)
        ]
        for name in candidates:
            try:
                raw = zf.read(name)
            except KeyError:
                continue
            try:
                return lxml_html.fromstring(raw)
            except Exception:
                continue
    return None
