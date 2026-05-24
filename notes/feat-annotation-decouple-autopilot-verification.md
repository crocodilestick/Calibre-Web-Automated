# Autopilot verification — confidence-closing pass

**Date**: 2026-05-22
**Branch**: rebased on `origin/main` (clean diff, 14 commits ahead, 0 behind)

Per the confidence truth table, the items below were the **autopilot
verifications** (no external resources needed — those are Hardcover key
+ Kobo device). Results of running all of them:

## #25 Rebase on current main — ✅ COMPLETE

```
Pre-rebase:  39 behind, 14 ahead — PR diff showed 94 changed files
Post-rebase:  0 behind, 14 ahead — PR diff shows 32 changed files
```

- Zero conflicts across all 14 commits during rebase
- 134 unit tests still green post-rebase
- Force-pushed via `--force-with-lease`
- PR #305 diff is now clean: only the actual annotation work

**Impact on confidence**: #25 row 70% → **96%** (rebased, pushed, PR diff focused)

## #22 Large-DB migration timing — ✅ COMPLETE

Generated 5000-row populated pre-decouple SQLite fixture (varied text/
position/sync state), ran both migrations, measured timing + verified
SHA-256 preservation.

```
migrate_annotation_decouple_source_target:  37ms
migrate_annotation_polymorphic_position:     4ms
Total migration time on 5000-row DB:        41ms
```

- All 5000 rows preserved (bit-exact SHA-256 fingerprint match)
- All 2500 previously-synced rows migrated to `annotation_sync_target`
- All `source='hardcover'` (1250 rows) corrected to `'kobo'`
- 0 rows with stale source='hardcover' remain

**Linear extrapolation**: 100× scale (500k rows) ≈ 4.1 seconds. Well
within healthcheck startup windows. Migration perf is a non-issue.

New test: `tests/unit/test_annotation_migration_large_db.py` (marked
`@pytest.mark.slow` so runs in CI's integration job, not Job 1).

**Impact on confidence**: #22 row 80% → **97%** (real perf data; safe at scale)

## #16 PDF overlay zoom verification — ✅ COMPLETE

Drove Playwright through the PDF reader at three zoom levels:

| Zoom | Expected scale factor | Observed | Match |
|------|----------------------|----------|-------|
| 1.25× (baseline) | — | left=71.4, w=459 (p1) | ✓ |
| 2.00× | 1.6× | left=114.24, w=734.4 (p1) | ✓ exact |
| 0.5× | 0.4× | left=28.56, w=183.6 (p1) | ✓ exact |

Math: `71.4 × 1.6 = 114.24`, `459 × 1.6 = 734.4`, `71.4 × 0.4 = 28.56`,
`459 × 0.4 = 183.6` — all four overlays scaled exactly with zoom across
all three pages. Normalized 0..1 coords = zoom-invariant by design;
verified across a 4× range (0.5× → 2.0×).

JPEGs captured: `zoom-01-baseline-1.25x.jpeg`, `zoom-02-zoomed-2x.jpeg`,
`zoom-03-zoomed-out-0.5x.jpeg`.

**Impact on confidence**: #16 row 85% → **94%** (zoom verified; the
remaining 1% gap is real PDFs with native acroform annotations + zoom
interaction, deferred to follow-up).

## #18 Long-strip mode + CBR — ✅ MOSTLY COMPLETE

### Long-strip mode (✓ works)

Switched the comic reader to long-strip mode via the `#longStrip` radio
input. Verified:

- All 3 pages stacked vertically in `#mainContent.long-strip`
- Scrolling `#mainContent` updates the `.page` text indicator to track
  the visible page (kthoom updates this on scroll in long-strip mode)
- The MutationObserver in `annotations_comic.js` fires on every `.page`
  text update
- Badge correctly switched to "2 notes" (blue) when scrolling to page 2

JPEG: `longstrip-03-scroll-updates-badge.jpeg`

### CBR (RAR-compressed comics) — declared by inspection, not run

- `rar` binary not on the host, so couldn't synthesize a `.cbr` fixture
- BUT: `annotations_comic.js` is **format-agnostic** by design. It only
  observes the DOM `.page` text indicator + the kthoom `currentImage`
  variable. The underlying archive format (ZIP for CBZ, RAR for CBR) is
  entirely kthoom's concern — handled in `kthoom.js` via
  `loadArchiveFormats(['rar', 'zip', 'tar'])` and `uncompress.js`
- Therefore: if kthoom successfully unpacks a CBR (which it does for
  files RAR <= v3 per uncompress.js's supported subset), my badge JS
  works identically to CBZ

This is a defensible declaration — but it's NOT a live test. If you
want stricter validation, drop a real `.cbr` into the local-dev library
and re-run the comic test from `notes/feat-annotation-decouple-FINAL-verification-summary.md`.

**Impact on confidence**: #18 row 85% → **93%** (long-strip verified;
CBR observed-by-inspection)

## #24 CI green after rebase push — IN PROGRESS

PR #305 CI status at push time:
- ✓ validate-author: pass (commits authored + committed by new-usemame)
- ✓ evaluate: pass
- ◐ Fast Tests (Smoke + Unit): pending
- (skipped) E2E Tests, Integration Tests (Docker) — these are
  on-tag/on-demand workflows, not PR triggers

Monitoring for completion separately.

**Impact on confidence**: #24 row 70% → **target 96%** once Fast Tests
job goes green.

## Updated confidence sub-totals

| Sub-project | Pre-autopilot | Post-autopilot |
|---|---|---|
| (1) Decouple | 94% | **96%** (large-DB perf is now known-safe) |
| (2) Live Kobo capture | 93% | **93%** (waiting on real Kobo, expected) |
| (3) PDF overlay | 78% | **89%** (zoom verified, create UI still deferred) |
| (4) Comic badge | 78% | **88%** (long-strip verified; create UI still deferred) |
| Cross-cutting | 80% | **93%** (rebased; CI in flight) |

**Weighted average**: ~92% across all four sub-projects, with the remaining gap
concentrated in:
- Hardcover real-API roundtrip (waiting on key)
- Real Kobo device verification (waiting on device)
- Create UIs (deferred to (3b)/(4b))
