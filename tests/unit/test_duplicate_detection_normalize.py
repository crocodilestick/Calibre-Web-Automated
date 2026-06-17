"""Duplicate-detection normalization + data-safety invariants (task #24).

The duplicate-detection keying surface (which decides what auto-resolve may
DELETE) had no test coverage. These pin:
  - RECALL: accent + punctuation variants of the same title/author collapse so
    real duplicates are found;
  - PRECISION (data-safety core): distinct titles/numbers NEVER collapse — a
    false merge would let auto-resolve delete a genuinely different book;
  - the D7 guard: an incomplete-metadata (title-less) book is a "duplicate of
    only itself" — never grouped, never auto-deleted;
  - the index NORMALIZATION_VERSION bump (so changing the normalizer rebuilds
    the on-disk index instead of mixing old + new keys);
  - select_book_to_keep newest/oldest.

RED on main (old normalizer didn't deaccent or strip punctuation; version v2);
GREEN on branch.
"""
from datetime import datetime, timezone

from cps.duplicates import (
    normalize_text_for_duplicates,
    normalize_title_for_duplicates,
    generate_group_hash,
    select_book_to_keep,
)
from cps import duplicate_index


# --- normalizer RECALL: genuine variants collapse -------------------------

def test_accents_are_folded():
    assert normalize_text_for_duplicates("Café Society") == normalize_text_for_duplicates("Cafe Society")
    assert normalize_text_for_duplicates("naïve") == "naive"
    assert normalize_text_for_duplicates("Jürgen") == normalize_text_for_duplicates("Jurgen")


def test_punctuation_is_collapsed():
    base = normalize_text_for_duplicates("The Book")
    assert normalize_text_for_duplicates("The Book!") == base
    assert normalize_text_for_duplicates("The--Book") == base
    assert normalize_text_for_duplicates("The, Book.") == base


def test_whitespace_case_collapse():
    assert normalize_text_for_duplicates("  The   BOOK ") == "the book"


def test_default_sentinel_for_empty():
    assert normalize_text_for_duplicates("", default="untitled") == "untitled"
    assert normalize_text_for_duplicates(None, default="untitled") == "untitled"


# --- normalizer PRECISION: distinct stay distinct (data-safety) -----------

def test_distinct_titles_do_not_collapse():
    assert normalize_text_for_duplicates("Dune") != normalize_text_for_duplicates("Dune: Messiah")
    assert normalize_text_for_duplicates("Volume 1") != normalize_text_for_duplicates("Volume 2")
    assert normalize_text_for_duplicates("Book One") != normalize_text_for_duplicates("Book Two")
    # numbers (edition/volume) must survive so they keep books apart
    assert "1" in normalize_text_for_duplicates("Vol. 1")
    assert normalize_text_for_duplicates("Harry Potter 1") != normalize_text_for_duplicates("Harry Potter 2")


def test_group_hash_matches_variants_not_distinct():
    assert generate_group_hash("Café", "José Saramago") == generate_group_hash("Cafe!", "Jose Saramago")
    assert generate_group_hash("Dune", "Herbert") != generate_group_hash("Dune Messiah", "Herbert")


def test_title_author_prefix_and_normalization():
    assert normalize_title_for_duplicates("Homer, The Iliad", "Homer") == "the iliad"
    assert normalize_title_for_duplicates("Café!") == "cafe"


# --- D7 data-safety guard: incomplete metadata never groups ----------------

class _FakeBook:
    def __init__(self, **kw):
        self.title = kw.get("title")
        self.authors = kw.get("authors")
        self.id = kw.get("id")
        self.timestamp = kw.get("timestamp")


def test_titleless_books_never_share_a_key():
    settings = {}  # defaults -> title + author criteria enabled
    k1 = duplicate_index.build_duplicate_key(_FakeBook(title=None, id=1), settings)
    k2 = duplicate_index.build_duplicate_key(_FakeBook(title=None, id=2), settings)
    assert k1 != k2, "two title-less books must NOT group together (auto-resolve could delete one)"


def test_index_normalization_version_bumped():
    # changing the normalizer must change the fingerprint so the index rebuilds
    assert duplicate_index.NORMALIZATION_VERSION == "duplicate-index-v3"


# --- selection strategy: which copy is kept --------------------------------

def test_select_newest_and_oldest():
    old = _FakeBook(id=1, timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc))
    new = _FakeBook(id=2, timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert select_book_to_keep([old, new], "newest").id == 2
    assert select_book_to_keep([old, new], "oldest").id == 1
