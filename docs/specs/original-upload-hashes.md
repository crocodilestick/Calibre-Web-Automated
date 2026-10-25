# Remember original upload hashes across CWA transformations
Idea: https://ideaforge.ikoro.in/idea/1235

## Why
Repeated imports of identical original files create extra books when metadata matching fails. Stored file hashes change after conversion or metadata enforcement. Upstream issue765 raised exactly this limitation.

## How
Store original SHA-256 provenance in cwa.db, associated with library UUID, book UUID and format. Compute original bytes before transformation. Assume the incoming file remains unchanged during one ingest; do not copy it for race detection. Record only confirmed successful imports, never heuristic latest-book IDs. Validate live references before skipping. Preserve explicit add-format behavior, invalidate replaced/deleted relationships and transfer only surviving formats on merges. Use an opt-in setting, disabled by default. Quarantine skipped inputs in processed_books/duplicates rather than deleting them. Missing or unconfirmed IDs never create provenance. A crash between the Calibre commit and provenance commit may cause a duplicate on retry, but must never suppress an unrelated upload. The current-file scan is part of this PR, reusing the local guard behavior. Keep legacy current-file matching and approximate duplicate management separate. Do not delete existing duplicates. Submit upstream and validate a pinned local image on an isolated library before rollout.

The ingest path removes CWA's generated `new_<uid>_<timestamp>_<microseconds>_` prefix from staged basenames only when its timestamp is valid, so metadata-free imports use the uploaded title. CWA-managed format replacement removes that format's old provenance first. A replacement made outside CWA can keep the same Calibre book UUID, so its old relationship can suppress a re-import while the replacement format exists; skipped inputs remain quarantined for recovery. Merge cleanup transfers only formats reported as surviving and is best-effort. If Calibre commits an import but the provenance write fails, the source stays available, but retry may create a duplicate because the index lacks that relationship.

## Validation Commands
python -m pytest tests/unit/test_original_upload_hashes.py tests/unit/test_original_upload_lifecycle.py tests/unit/test_original_upload_hardening.py tests/unit/test_cwa_db.py tests/unit/test_ingest_batch_dirty.py tests/unit/test_ingest_processor_startup.py
python -m compileall -q scripts

### Task 1: Review design
- [x] Inspect ingest and lifecycle integration points; record Claude design review and resolve findings.

### Task 2: Recognize repeated originals
- [x] Add CWA-owned persistent provenance, safe ingest lookup and success-only recording.
- [x] Cover transformations, changed bytes, failure/retry, deleted/replaced formats, library identity and legacy files.

### Task 3: Review and deliver
- [x] Complete native Review Gate and Claude peer attempt, resolving valid findings.
- [x] Validate a pinned candidate image on an isolated library copy.
- [x] Publish an upstream PR with attribution, linked issue and validation evidence: [PR 1627](https://github.com/crocodilestick/Calibre-Web-Automated/pull/1627).

Isolated validation used image `f639` at source revision `3eb2f01`. With the feature disabled, two identical PDFs created two books. With it enabled, an exact PDF repeat created no book and was quarantined, while same-size changed bytes imported. A real TXT-to-EPUB conversion passed CWA cover enforcement and metadata rewriting; repeating the original TXT before and after restart created no extra book. The 83-book frozen library retained all 82 physically present original-format files with their existing format hashes unchanged; one historical missing GraphQL path was tracked separately.
