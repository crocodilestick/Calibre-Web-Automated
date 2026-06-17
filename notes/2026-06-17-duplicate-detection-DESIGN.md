# Duplicate detection — robustness + test strategy (task #24)

The duplicate subsystem is already mature (`cps/duplicates.py`,
`cps/duplicate_index.py`, `cps/tasks/duplicate_scan.py`, `duplicates.html`,
notifier) with real data-safety scaffolding (D2–D11: serialize lock, per-book
re-fetch, user-data migration, DB-delete-before-file-delete, backup-before-
delete, audit log, index cleanup). The gaps were a **weak normalizer** and
**almost no tests** (1 auth test; zero for the algorithm or the delete paths).

## Shipped in this increment

**Safe, precision-preserving normalizer robustness** (`normalize_text_for_duplicates`):
- accent folding (NFKD + drop combining marks): `Café` == `Cafe`, `naïve` == `naive`;
- punctuation → space: `The Book!` == `The--Book` == `The Book`.
- Only accents + punctuation are removed; every word and number survives, so
  distinct titles (`Dune` vs `Dune: Messiah`, `Volume 1` vs `Volume 2`) still
  hash apart. This is the key data-safety property — a normalizer that
  over-collapsed would let auto-resolve DELETE genuinely different books.
- `normalize_title_for_duplicates` rewritten so the `"Author, "` prefix strip
  runs on a comma-preserving form *before* punctuation folding (otherwise it
  broke, and over-stripped any title starting with the author's name — caught
  by a test).
- `duplicate_index.NORMALIZATION_VERSION` bumped v2 → v3 so the fingerprint
  changes and the on-disk index rebuilds with the new keys (queries filter
  `WHERE criteria_fingerprint = ?`, so old rows are ignored, not mixed in).

**First real test coverage** (`tests/unit/test_duplicate_detection_normalize.py`):
recall (accent/punct variants collapse), **precision** (distinct titles/numbers
never collapse), the **D7 guard** (a title-less book is a duplicate of only
itself — never grouped/auto-deleted), the version bump, and select_book_to_keep
newest/oldest.

## Deferred — and WHY (each raises false-positive → data-loss risk)

These improve recall but risk grouping *distinct* books, which auto-resolve
could then delete. They need precision-first design + their own tests before
shipping, and several need an integration harness with a real Calibre DB:

1. **Author-format folding** (`Smith, John` ↔ `John Smith` ↔ `J. Smith`):
   valuable, but initials/suffixes/co-author-order make it easy to over-merge.
2. **ISBN / identifier cross-edition matching:** two editions share work-level
   identity but are legitimately different files; merging them is a *choice*,
   not obviously correct — must be opt-in.
3. **Fuzzy title matching** (edit distance): inherently precision-risky; only
   safe as a *review-suggestion*, never an auto-delete input.
4. **Subtitle/edition stripping** (`Dune` vs `Dune: Part One`): would merge a
   book with its sequel/companion — do NOT add to the auto-delete key.
5. **Format-subset grouping** ([EPUB] vs [EPUB,PDF]): interacts with the merge
   strategy; design alongside merge, not detection.

## Deferred — delete-orchestration tests (highest follow-up value)

`auto_resolve_duplicates()` (the code that actually DELETES books) is untested.
Needs an integration harness (real Calibre DB fixture) characterizing:
- the D2 lock serializes concurrent resolutions (no double-delete);
- DB row is deleted before files (D3) — on DB error, files survive;
- user data (annotations/progress/shelves) migrates to the kept book (D4);
- a backup folder is written before delete (D11);
- the dry-run preview matches the executed result;
- rollback/leftover behavior on mid-loop failure.

This is the single most valuable next increment for a feature that deletes user
data — pin the safety scaffolding with tests before any further algorithm change.
