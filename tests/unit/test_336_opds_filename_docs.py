# SPDX-License-Identifier: GPL-3.0-or-later
"""Doc regression test for fork issue #336 (@batiti93).

Reporter: OPDS downloads to KOReader land as `Author - Title.epub`, but the
CWA library names files `Title - Author.epub`, so the names differ and
cross-device read-status sync (filename-based) needs a manual rename each time.

Investigation (verified against KOReader source, opds.koplugin/opdsbrowser.lua):

* CWA's OPDS download endpoint already sends the correct library name in the
  `Content-Disposition` header (`filename=...Title - Author.epub`). This is NOT
  a server bug — confirmed by curling /opds/download/<id>/<fmt>/.
* KOReader's `OPDSBrowser:getFileName` builds `item.author .. " - " .. item.title`
  ("Author - Title") from the catalog entry by default, ignoring the header.
* Only when the catalog's **Use server filenames** toggle (`raw_names`) is ON
  does `getFileName` return nil and KOReader fall back to `getServerFileName`,
  which reads the `Content-Disposition` filename — i.e. CWA's `Title - Author`.

So the resolution is the KOReader **Use server filenames** setting, not a code
change (swapping `<author>`/`<title>` in the feed would corrupt the catalog for
every client). This test pins the README guidance so the answer isn't silently
lost — a user hitting the same symptom finds it in one search instead of
re-opening the issue.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    assert README.exists()
    return README.read_text(encoding="utf-8")


@pytest.mark.unit
class TestOpdsFilenameGuidance:
    def test_readme_documents_use_server_filenames(self, readme):
        assert re.search(r"use server filenames", readme, re.IGNORECASE), (
            "README must document KOReader's 'Use server filenames' OPDS "
            "setting (#336): it's the resolution for OPDS downloads naming "
            "files 'Author - Title' instead of the library's 'Title - Author'."
        )

    def test_readme_explains_the_default_mismatch(self, readme):
        """The note must name BOTH orderings so a user recognizes their
        symptom — KOReader's default Author-Title vs the library Title-Author."""
        lower = readme.lower()
        assert "author - title" in lower and "title - author" in lower, (
            "README must contrast KOReader's default `Author - Title` naming "
            "with the library's `Title - Author` so a user recognizes the "
            "#336 symptom."
        )

    def test_guidance_lives_in_koreader_section(self, readme):
        """Pin the note to the KOReader sync section (its logical home), so a
        future README reshuffle doesn't orphan it under, say, Kobo sync."""
        m = re.search(r"### KOReader sync\n(.*?)(?=\n### )", readme, re.DOTALL)
        assert m, "expected a '### KOReader sync' section in README"
        section = m.group(1).lower()
        assert "use server filenames" in section, (
            "the 'Use server filenames' guidance must live in the KOReader "
            "sync README section (#336)."
        )
