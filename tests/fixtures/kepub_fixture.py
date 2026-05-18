# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synthetic kepub + plain-EPUB fixture builder for the Kobo
position-converter test suite (H1 Phase 2).

Real device backups contain personal reading history (PII). These
fixtures recreate enough of the kepub structure — META-INF, OPF,
spine, KoboSpan-tagged chapters — for the converter to exercise every
code path without shipping anyone's data.

See ``notes/KOBO-WEB-READER-ANNOTATIONS-DESIGN.md`` §3 for the
position-format reference; §3.6 for the live-verified shape this
builder reproduces.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Animal Farm</dc:title>
    <dc:identifier id="bookid">{book_uuid}</dc:identifier>
  </metadata>
  <manifest>
{manifest_items}
  </manifest>
  <spine>
{spine_items}
  </spine>
</package>
"""


def _kobo_chapter_html(spans: list[tuple[str, str]]) -> str:
    """Build a kepub-style chapter where each tuple is
    ``(kobo_id, text)`` — emits ``<span id="kobo.<id>">text</span>``."""
    body_spans = "\n  ".join(
        f'<span id="{kid}">{txt}</span>' for kid, txt in spans
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter</title></head>
<body>
<p>
  {body_spans}
</p>
</body>
</html>
"""


def _plain_chapter_html(paragraphs: list[str]) -> str:
    """Plain-EPUB chapter — no KoboSpan IDs, just <p> nodes for
    DOM-index walking."""
    body = "\n  ".join(f"<p>{p}</p>" for p in paragraphs)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter</title></head>
<body>
  {body}
</body>
</html>
"""


def build_synthetic_kepub(dest: Path, book_uuid: str = "00000000-0000-0000-0000-deadbeefcafe") -> Path:
    """Write a 3-chapter synthetic kepub to ``dest``. Returns ``dest``.

    Chapters:
    - chapter1.html — KoboSpan IDs ``kobo.1.1`` .. ``kobo.1.4``
    - chapter2.html — KoboSpan IDs ``kobo.2.1`` .. ``kobo.2.3``
    - chapter3.html — plain (no KoboSpan IDs) for DOM-index-walk tests
    """
    chapters = {
        "chapter1.html": _kobo_chapter_html([
            ("kobo.1.1", "Four legs good."),
            ("kobo.1.2", "Two legs bad."),
            ("kobo.1.3", "All animals are equal."),
            ("kobo.1.4", "But some animals are more equal than others."),
        ]),
        "chapter2.html": _kobo_chapter_html([
            ("kobo.2.1", "Comrade Napoleon is always right."),
            ("kobo.2.2", "I will work harder."),
            ("kobo.2.3", "The seven commandments."),
        ]),
        "chapter3.html": _plain_chapter_html([
            "First plain paragraph.",
            "Second plain paragraph.",
            "Third plain paragraph.",
        ]),
    }

    manifest_lines = []
    spine_lines = []
    for i, fname in enumerate(chapters.keys(), 1):
        idref = f"ch{i}"
        manifest_lines.append(
            f'    <item id="{idref}" href="{fname}" media-type="application/xhtml+xml"/>'
        )
        spine_lines.append(f'    <itemref idref="{idref}"/>')

    opf = OPF_TEMPLATE.format(
        book_uuid=book_uuid,
        manifest_items="\n".join(manifest_lines),
        spine_items="\n".join(spine_lines),
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        for name, html in chapters.items():
            zf.writestr(f"OEBPS/{name}", html)
    return dest


def build_minimal_epub(dest: Path) -> Path:
    """An EPUB with no OEBPS/ prefix in the chapter paths — exercises
    the bare-basename branch of ``_resolve_spine_index``."""
    chapters = {
        "ch1.html": _kobo_chapter_html([("kobo.4.1", "Hello world.")]),
    }
    opf = OPF_TEMPLATE.format(
        book_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        manifest_items='    <item id="ch1" href="ch1.html" media-type="application/xhtml+xml"/>',
        spine_items='    <itemref idref="ch1"/>',
    )
    # Note: container.xml points at OEBPS/content.opf but the items
    # have no OEBPS/ prefix in their hrefs. parse_spine returns them
    # bare and _resolve_spine_index has to handle that.
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        for name, html in chapters.items():
            zf.writestr(f"OEBPS/{name}", html)
    return dest
