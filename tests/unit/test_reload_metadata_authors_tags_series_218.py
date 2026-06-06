# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #218 follow-up (@yodatak, 2026-06-06): the v4.0.149 reload covered
title/comments/publisher/pubdate/languages and deferred authors, tags, and
series — "i try the new 4.0.151 and some parts works but it don't reload all
the metadata."

This extension wires the three deferred fields through the SAME helpers the
edit-book save path uses (so relationship bookkeeping — author_sort
regeneration, tag dedup + orphan cleanup, series create-on-demand — stays
identical), pairs title/author changes with helper.update_dir_structure the
way every edit path does (the v4.0.149 title reload skipped it — same-class
gap, fixed here), and gates each field on the file actually CARRYING a value
so a tool that drops <dc:creator>/<dc:subject> can't stomp curated data:

  * get_epub_info returns the literal string 'Unknown' for a missing
    creator and '' for missing subject/series — both must be treated as
    "file has nothing to say", not as new values.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EDITBOOKS = REPO_ROOT / "cps" / "editbooks.py"


def _body() -> str:
    src = EDITBOOKS.read_text(encoding="utf-8")
    match = re.search(
        r"def reload_metadata_from_disk\(book_id\):.*?(?=\ndef |\n@|\Z)",
        src,
        re.DOTALL,
    )
    assert match, "Could not locate reload_metadata_from_disk body"
    return match.group(0)


@pytest.mark.unit
class TestReloadCoversDeferredFields:
    def test_authors_via_handle_author_on_edit(self):
        body = _body()
        assert "handle_author_on_edit" in body, (
            "authors must reload via handle_author_on_edit — the helper the "
            "edit-book save path uses for author_sort regeneration and "
            "rename handling (#218 follow-up)"
        )

    def test_tags_via_edit_book_tags(self):
        body = _body()
        assert "edit_book_tags" in body, (
            "tags must reload via edit_book_tags (dedup + orphan cleanup)"
        )

    def test_series_via_edit_book_series(self):
        body = _body()
        assert "edit_book_series" in body, (
            "series must reload via edit_book_series (create-on-demand)"
        )

    def test_dir_structure_updated_on_title_or_author_change(self):
        """Every edit path pairs title/author changes with
        helper.update_dir_structure so the on-disk Author/Title (id)
        layout converges with the database. Reload must too — otherwise
        reload leaves the library in a state no other write path
        produces."""
        body = _body()
        assert "update_dir_structure" in body, (
            "reload must call helper.update_dir_structure when title or "
            "authors changed — the v4.0.149 title-only reload skipped it"
        )

    def test_rename_failure_rolls_back_never_commits(self):
        """Adversarial-review finding: the edit-book POST path responds to
        an update_dir_structure error with rollback + bail. Reload must
        mirror that — committing metadata for a layout the move didn't
        produce leaves the catalog pointing at paths that don't exist."""
        body = _body()
        m = re.search(
            r"if rename_error:.*?calibre_db\.session\.rollback\(\).*?return jsonify\(",
            body, re.DOTALL)
        assert m, (
            "rename_error must trigger session.rollback() and an error "
            "return — never warn-and-commit"
        )

    def test_file_moves_run_outside_the_writers_lock(self):
        """Adversarial-review finding: metadata_db_write_lock's contract is
        single-commit duration (it coordinates with the ingest processor,
        #192). File renames inside it can starve ingest for the length of
        a folder move on slow storage. Only the COMMIT may hold it —
        matching the edit-book POST path."""
        body = _body()
        lock_positions = [m.start() for m in re.finditer(r"metadata_db_write_lock\(\)", body)]
        assert len(lock_positions) == 1, (
            f"expected exactly one metadata_db_write_lock() in the reload "
            f"(around the commit), found {len(lock_positions)}"
        )
        dir_call = body.index("update_dir_structure")
        assert dir_call < lock_positions[0], (
            "update_dir_structure must run BEFORE (outside) the writers' "
            "lock; only the commit holds it"
        )


@pytest.mark.unit
class TestAbsentFieldSafetyGates:
    def test_author_unknown_sentinel_does_not_stomp(self):
        """get_epub_info yields the literal 'Unknown' when the file has no
        <dc:creator>. Passing that through handle_author_on_edit would
        replace the book's real authors with 'Unknown'."""
        body = _body()
        assert re.search(r"meta\.author[^\n]*['\"]Unknown['\"]", body), (
            "the author reload must exclude the get_epub_info 'Unknown' "
            "sentinel — a file without <dc:creator> must not stomp authors"
        )

    def test_empty_tags_do_not_wipe_curated_tags(self):
        """get_epub_info yields '' for missing <dc:subject>. edit_book_tags('')
        would diff curated tags against [''] and wipe them. Absence in the
        file is ambiguous (tool may simply not write subjects) — skip."""
        body = _body()
        m = re.search(r"if\s+meta\.tags[^\n:]*:", body)
        assert m, (
            "tags reload must be gated on meta.tags being non-empty so a "
            "subject-less file can't wipe curated tags"
        )

    def test_empty_series_does_not_clear(self):
        body = _body()
        m = re.search(r"if\s+meta\.series\s+and\s", body)
        assert m, (
            "series reload must be gated on meta.series being non-empty"
        )

    def test_series_index_validated_without_flash(self):
        """edit_book_series_index flashes on invalid input — a flash inside
        a JSON endpoint leaks a stale message into the next rendered page.
        The reload must validate the numeric shape itself."""
        body = _body()
        assert re.search(r"replace\('\.', '', 1\)\.isdigit\(\)", body), (
            "series index must be numeric-validated inline (the flash-based "
            "edit_book_series_index helper is for form requests)"
        )

    def test_parse_epub_series_signals_absence_as_empty(self):
        """Adversarial-review finding (CONFIRMED class): parse_epub_series
        fabricated series_id='1' when the file carried no
        calibre:series_index meta — so a file with a series NAME but no
        index made reload stomp a curated index back to 1 on every run.
        Absence must surface as '' so the reload gate skips it. Behavioral:
        run the real parser against minimal OPF trees."""
        from lxml import etree
        from cps.epub import parse_epub_series

        ns = {
            "n": "urn:oasis:names:tc:opendocument:xmlns:container",
            "pkg": "http://www.idpf.org/2007/opf",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        opf_no_index = (
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<meta name="calibre:series" content="Foo"/>'
            '</metadata></package>'
        )
        tree = etree.fromstring(opf_no_index.encode())
        out = parse_epub_series(ns, tree, {})
        assert out["series"] == "Foo"
        assert out["series_id"] == "", (
            "missing calibre:series_index must yield '' (absence), not a "
            "fabricated '1' that stomps curated indexes on reload"
        )

        opf_with_index = opf_no_index.replace(
            "</metadata>",
            '<meta name="calibre:series_index" content="4"/></metadata>',
        )
        tree2 = etree.fromstring(opf_with_index.encode())
        out2 = parse_epub_series(ns, tree2, {})
        assert out2["series_id"] == "4"

    def test_series_index_compares_numerically(self):
        """Caught live on the second reload of the same book: series_index
        is a REAL column, so a string compare (str(4.0) != "4") reports a
        change on every reload — each one re-marking the book modified and
        churning Kobo-sync cursors. The compare must be numeric."""
        body = _body()
        assert re.search(
            r"float\(book\.series_index\s+or\s+0\)\s*!=\s*float\(series_id\)",
            body,
        ), (
            "series_index reload must compare float-to-float — a string "
            "compare makes every reload a spurious modification"
        )
