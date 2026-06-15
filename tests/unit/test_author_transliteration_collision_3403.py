# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for janeczku/calibre-web #3403.

Two genuinely-distinct authors whose names transliterate to the same ASCII
string ("姚尧"/"妖妖" -> "yao yao", "George Pólya"/"George Polya" -> "george
polya", "John Le Carré"/"John Le Carre" -> "john le carre") could not coexist
through a metadata edit. Editing *any* field of a book by such an author —
even a cover-only change that never touches the author field — raised::

    (sqlite3.IntegrityError) UNIQUE constraint failed: authors.name

Root cause: the registered ``lower`` SQLite UDF is
``unidecode.unidecode(s.lower())`` (``cps/db.py``), so it strips accents and
transliterates. ``prepare_authors`` looked up the existing author with
``func.lower(db.Authors.name).ilike(in_aut).first()``; the folding ``lower``
made that filter match a *different* author, and ``.first()`` arbitrarily
picked the transliteration twin. The caller then renamed that twin onto the
submitted name, colliding with the real author's ``authors.name`` UNIQUE
constraint.

The fix routes the lookup through ``select_existing_author``, which prefers an
exact-name match (and then a true Unicode case-fold variant) so a
transliteration twin is never chosen for the rename path.

These tests pin the contract:
  1. Behavioural: with the *real* production ``lower`` UDF and a Calibre-shaped
     ``authors`` table, the old ``.first()`` selection renames the wrong author
     and raises IntegrityError; the new selection does not.
  2. Unit: ``select_existing_author`` prefers exact match over a twin
     regardless of candidate order, honours case-fold variants, never strips
     accents, and degrades to a deterministic fallback / ``None``.
  3. Source-pin: ``prepare_authors`` no longer calls ``.first()`` on the author
     filter and routes through ``select_existing_author`` — so a future edit
     can't silently reintroduce the blind ``.first()``.
"""

import ast
import sqlite3
from pathlib import Path

import pytest

from cps.db import lcase
from cps.editbooks import select_existing_author


REPO_ROOT = Path(__file__).resolve().parents[2]
EDITBOOKS = REPO_ROOT / "cps" / "editbooks.py"


class _Author:
    """Minimal stand-in for ``db.Authors`` — the helper only reads ``.name``."""

    def __init__(self, author_id, name):
        self.id = author_id
        self.name = name

    def __repr__(self):
        return f"_Author(id={self.id}, name={self.name!r})"


# Distinct author pairs that fold together under the unidecode ``lower`` UDF.
TRANSLITERATION_TWINS = [
    ("妖妖", "姚尧"),                       # Chinese homophones (the original report)
    ("George Pólya", "George Polya"),       # accent vs no-accent (apetresc)
    ("John Le Carré", "John Le Carre"),     # accent vs no-accent (wnmurphy)
]


def test_production_lower_udf_folds_distinct_authors():
    """Guard the premise: the real ``lower`` UDF really does collapse the twins.

    If this ever stops being true (e.g. ``lcase`` drops unidecode), the
    collision disappears and the rest of these tests no longer describe a real
    risk — so fail loudly rather than pass vacuously.
    """
    for edited, twin in TRANSLITERATION_TWINS:
        assert lcase(edited) == lcase(twin), (
            f"{edited!r} and {twin!r} are expected to fold together under the "
            f"production lower UDF"
        )


def _seed_calibre_authors(con, edited, twin):
    """Create a Calibre-shaped authors table with the production ``lower`` UDF
    and two distinct authors that transliterate alike."""
    con.create_function("lower", 1, lcase)  # exact production registration
    con.execute(
        "CREATE TABLE authors ("
        " id INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL COLLATE NOCASE,"
        " sort TEXT,"
        " UNIQUE(name))"
    )
    # Insert the twin FIRST so a naive ``.first()`` is liable to pick it.
    con.execute("INSERT INTO authors(id, name, sort) VALUES (1, ?, ?)", (twin, twin))
    con.execute("INSERT INTO authors(id, name, sort) VALUES (2, ?, ?)", (edited, edited))
    con.commit()


def _matching_authors(con, in_aut):
    """Mirror ``func.lower(db.Authors.name).ilike(in_aut)`` against the engine.

    SQLAlchemy renders ``func.lower(col).ilike(x)`` as
    ``lower(lower(col)) LIKE lower(x)``; with the unidecode UDF the double
    ``lower`` is idempotent.
    """
    rows = con.execute(
        "SELECT id, name FROM authors WHERE lower(lower(name)) LIKE lower(?)",
        (in_aut,),
    ).fetchall()
    return [_Author(r[0], r[1]) for r in rows]


@pytest.mark.parametrize("edited,twin", TRANSLITERATION_TWINS)
def test_old_first_selection_raises_integrity_error(edited, twin):
    """The pre-fix behaviour: selecting the twin and renaming it collides.

    The author filter is unordered, so the old ``.first()`` could return either
    twin — that non-determinism is part of the defect. Here we make the failure
    deterministic by selecting the twin explicitly (the case the old ``.first()``
    hits whenever the scan returns it first) and showing the rename onto the
    submitted name violates the ``authors.name`` UNIQUE constraint.
    """
    con = sqlite3.connect(":memory:")
    try:
        _seed_calibre_authors(con, edited, twin)
        candidates = _matching_authors(con, edited)
        # The folding UDF must surface BOTH distinct authors as candidates, so a
        # blind .first() can land on the wrong one.
        assert len(candidates) == 2, f"expected both twins to match, got {candidates}"
        names = {c.name for c in candidates}
        assert names == {edited, twin}

        # The old code renames whatever the lookup returned when its name differs
        # from the submitted one. When that is the twin, the rename collides.
        twin_row = next(c for c in candidates if c.name == twin)
        assert twin_row.name != edited
        with pytest.raises(sqlite3.IntegrityError, match="authors.name"):
            con.execute(
                "UPDATE authors SET name=?, sort=? WHERE id=?",
                (edited, edited, twin_row.id),
            )
    finally:
        con.close()


@pytest.mark.parametrize("edited,twin", TRANSLITERATION_TWINS)
def test_fixed_selection_avoids_collision(edited, twin):
    """The fix: ``select_existing_author`` picks the exact match → no rename."""
    con = sqlite3.connect(":memory:")
    try:
        _seed_calibre_authors(con, edited, twin)
        candidates = _matching_authors(con, edited)

        chosen = select_existing_author(candidates, edited)
        assert chosen is not None
        assert chosen.name == edited, (
            f"must select the exact-name author, not a transliteration twin; "
            f"got {chosen!r}"
        )
        # Because the chosen author already has the submitted name, the caller's
        # ``in_aut != renamed_author.name`` guard is False → no rename attempted.
        assert chosen.name == edited  # rename guard would short-circuit
    finally:
        con.close()


def test_select_prefers_exact_over_twin_regardless_of_order():
    a_twin = _Author(1, "George Polya")
    a_exact = _Author(2, "George Pólya")
    for ordering in ([a_twin, a_exact], [a_exact, a_twin]):
        chosen = select_existing_author(ordering, "George Pólya")
        assert chosen is a_exact, f"exact match must win for order {ordering}"


def test_select_honours_case_only_variant_without_stripping_accents():
    # Case-only difference IS the same author → legitimate "adopt new casing".
    king = _Author(1, "Stephen King")
    assert select_existing_author([king], "stephen king") is king
    # But an accent difference is NOT a case variant → must not be claimed as
    # the same author when no exact match exists in a multi-candidate set.
    polya_plain = _Author(1, "George Polya")
    polya_accent = _Author(2, "George Pólya")
    chosen = select_existing_author([polya_plain, polya_accent], "George Pólya")
    assert chosen is polya_accent


def test_select_single_candidate_is_legitimate_rename_target():
    # DB has only the accent-less author; user supplies the accented form. There
    # is no twin to collide with, so renaming the lone candidate is correct.
    only = _Author(1, "George Polya")
    chosen = select_existing_author([only], "George Pólya")
    assert chosen is only  # caller will rename "Polya" -> "Pólya"


def test_select_empty_returns_none():
    assert select_existing_author([], "Anybody") is None


def test_prepare_authors_routes_through_helper_and_drops_blind_first():
    """Source-pin: prepare_authors must not reintroduce the blind ``.first()``."""
    tree = ast.parse(EDITBOOKS.read_text(encoding="utf-8"))
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_authors"
    )
    src = ast.get_source_segment(EDITBOOKS.read_text(encoding="utf-8"), func)

    assert "select_existing_author(" in src, (
        "prepare_authors must resolve the author via select_existing_author"
    )
    # The author filter must be materialised with .all() and disambiguated, not
    # collapsed with a blind .first() that can pick a transliteration twin.
    assert "ilike(in_aut)).first()" not in src.replace(" ", ""), (
        "prepare_authors must not call .first() directly on the author filter"
    )


def test_upload_author_resolution_routes_through_helper():
    """Source-pin the same disambiguation on the upload author-resolution path.

    ``prepare_authors_on_upload`` shares the accent-folding lookup; it only
    reads ``.sort`` (so it never crashed) but a blind ``.first()`` could attach
    an upload to a transliteration twin. It must use the same helper.
    """
    source = EDITBOOKS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_authors_on_upload"
    )
    src = ast.get_source_segment(source, func)
    assert "select_existing_author(" in src
    assert "ilike(inp)).first()" not in src.replace(" ", "")
