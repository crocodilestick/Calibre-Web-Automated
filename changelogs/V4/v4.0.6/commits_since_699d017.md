### cwa
- cwa | 5fb41ddf8fcad91d9f19ecc18254f7459931e9e0 | 2026-02-05T00:21:52+01:00 | fix(kobo): bust cover cache on metadata sync | Kobo devices were keeping stale covers because CoverImageId and the image URL never changed when a cover was updated. This change appends a cache-busting suffix based on the cover file mtime (local) or book.last_modified (GDrive), and normalizes the suffix on image requests so lookups still resolve the base UUID. Adds debug logging when a cache-busted CoverImageId is emitted. Also adds a lightweight helper module to avoid heavy imports, plus unit tests for normalization and cover ID generation. Tests: /workspace/cwa/.venv/bin/python -m pytest tests/unit/test_kobo_cover_image_id.py [bug] Covers not updating on Kobo Fixes #1050
- cwa | 
44a072dd2862a1e87601cb399b6db20436085e73 | 2026-02-05T00:19:39+01:00 | Updated dev image build workflow to just have dev build number, no next version tag
- cwa | 
b4142950ef31ba0a31f4878346ccc06b8f578b74 | 2026-02-05T00:16:24+01:00 | fix(upload): bypass XHR uploadprogress on Safari, add upload request logging | - Skip XHR + progress decoration in uploadprogress.js for Safari so uploads fall back to standard form submit, leaving Chrome/Firefox behavior unchanged. - Log upload request details (user agent, content length, file field keys) at the start of the /upload handler for easier Safari diagnostics. [bug] Safari can't handle book upload Fixes #1049
- cwa | 
82e1e90b157ae639b451073139bdea5bc6d4a848 | 2026-02-05T00:04:27+01:00 | fix(kindle-epub-fixer): preserve valid language tags and expand ISO lists | - Preserve valid language tags that are not in Amazon’s allow-list instead of overwriting them with the default language. - Expand ISO 639-1 list to the full set of 2-letter codes, including legacy aliases (iw/ji/in). - Expand ISO 639-2 list to the full 3-letter set provided, covering bibliographic codes and additional languages. - Keep existing behavior for missing/invalid language tags and Kindle-focused normalization. [bug] Imported books always use the UI language despite correct metadata Fixes #1047
- cwa | 
5efe0b74a6f65405462478802fcf597bd80b1786 | 2026-02-03T16:12:22+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
40dadab27229c7a1813247259c368e0d4ff43192 | 2026-02-03T16:11:57+01:00 | Adjust checksum tests for KOReader feature flag | Skip checksum-generation unit tests when KOReader sync is disabled, matching the new early-exit behavior. Normalize subprocess output handling and skip logic across checksum tests. Skip ingest checksum integration tests when book_format_checksums is not initialized (expected with KOReader disabled). Add a dedicated unit test to assert the disabled path logs the message and performs no writes. Keep checksum assertions intact when KOReader is enabled.
- cwa | 
ce39c5146bcd2cc4da067d7956704f37bf62ceca | 2026-02-03T16:01:17+01:00 | Fix flash alerts truncating long translations | - make flash alerts responsive by using 90vw width with max width - allow multi-line wrapping by removing nowrap/ellipsis and enabling word wrapping - align danger alerts with the same responsive sizing and wrap behavior - keep auto height so messages expand instead of clipping #1025
- cwa | 
cec6fa23b03e5953fd0b591ef3fc5230afa6b421 | 2026-02-03T14:23:48+00:00 | Update translations [skip ci]
- cwa | 
da2b214c948392bb865c2be95300a5d919834900 | 2026-02-03T15:21:00+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
1a5a8bb951c8bd8f9656a0e9ae0e43c2be71d03e | 2026-02-03T15:20:36+01:00 | Enforce dark theme and migrate users at startup | - Force runtime theme selection to caliBlur (dark) for all requests. - Remove light theme options from user and global settings UI. - Ensure new users (local and OAuth) are created with dark theme. - Add one-time startup migration in cwa-init to set config_theme=1 and update all users to theme 1 in app.db. [bug] Login page Generic OAuth button has broken styling (gray on blue, no padding, misaligned) Fixes #1042
- cwa | 
6418f88e4b913f1445530ff486240078fb5acac9 | 2026-02-03T15:19:47+01:00 | Add per-user magic shelf ordering with manual + book-count modes | - add magic shelf ordering helpers and normalization in magic_shelf.py - add per-user order modes (manual/name/created/modified/book count) - apply ordering to sidebar magic shelves after count caching - persist magic shelf order + order mode in user profile and admin edit flows - add profile UI for magic shelf order with drag/drop list + mode selector - include book-count sort options in UI [Feature Request] Sort the magic shelves (either manual sort or alfabetical sort). Right now they appear in the order they are created. Fixes #1027
- cwa | 
92dea6f13e5cab4acae5d8186b6f6efff719ade5 | 2026-02-03T14:58:51+01:00 | Guard KOReader checksum access to prevent nil crash | - Avoid nil dereference when doc_settings is missing by safely reading partial_md5_checksum. - Add fallback checksum generation from the current document file (prefer util.partialMD5, then a local partial MD5 routine) to keep sync functional. - Skip push/pull with a user-facing warning if no checksum can be computed. - Preserve existing sync behavior and server response handling; only touches checksum lookup and safety guards. Fixes: #1039
- cwa | 
4d77944e05c2584685aa4aab34a4bd3a429cfd2e | 2026-02-03T12:49:05+00:00 | Update translations [skip ci]
- cwa | 
53127f26f45f99d97838f4665b200875e224cc55 | 2026-02-03T13:48:02+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
5e7e788ad333dee29a347df518c9fb75c29cb7f7 | 2026-02-03T13:42:30+01:00 | feat(cwa): gate KOReader sync/backfill, reduce DB locks, unify logs | - Add KOReader sync enable toggle (default off) and UI copy explaining backfill + restart - Gate KOReader sync endpoints and startup table creation behind the setting - Add lock‑aware retries + clearer warnings for KOReader table creation - Rework checksum backfill to compute checksums outside DB locks and bulk‑insert in short batches - Add KOReader sync settings helper + schema column Show disabled state on /kosync page; hide plugin download when disabled - Default all app logs to /dev/stdout, enforce on startup, and hide logfile field in UI - Keep dynamic checksum updates enabled while backfill is controlled by setting
- cwa | 
f20f1bd5ccde72affbbab59c7cdd3dcc02da379b | 2026-02-03T13:41:06+01:00 | Fix custom datetime column date shift in tables by normalizing values during JSON serialization | Normalize datetime values only within custom column lists in AlchemyEncoder Preserve top‑level datetime fields to avoid unintended UI changes Prevents one‑day offset for custom date columns in book list/table views due to timezone parsing [bug] Custom date field one day ahead of Calibre date Fixes #1036
- cwa | 
28f220711bfb43b3d058544cd8293376afd4f472 | 2026-02-03T12:01:35+01:00 | Bumped included Calibre version
- cwa | 
2d9b2d7edcb254d967e99359b60f8904d1a896a5 | 2026-02-03T10:59:04+00:00 | Update translations [skip ci]
- cwa | 
f69e6ec8849331264aeff1b363562eae4f91f97e | 2026-02-03T11:58:18+01:00 | fix(cwa-settings): sanitize quoted defaults for convert/ingest options | Fixes regression introduced in 9571f89 where defaults with double quotes were persisted literally (e.g., "epub", "new_record"). This caused ebook-convert to fail with “No plugin to handle output format: "epub"” and calibredb --automerge to reject "new_record" as an invalid choice. Changes: - Normalize target/ignored/retained formats in ingest to strip quotes and lowercase values. - Repair malformed settings on startup (auto_convert_target_format, auto_convert_*, auto_ingest_*) alongside existing migration fixes. [bug] Failed to upload file, no plugin available Fixes #1032 [bug] autoingest  failure v4.0.5 - invalid choice : '"new_record"' instead of 'new_record' Fixes #1038
- cwa | 
0998fe8313133925fc70a56e136175d386dc875f | 2026-02-03T11:56:59+01:00 | Issue #1030: restrict NETWORK_SHARE_MODE to network-share paths only | - Fix edit-title permission error on network-share setups by restoring chown for internal /app paths. - Limit NETWORK_SHARE_MODE chown skips to /config, /calibre-library, and /cwa-book-ingest (and subpaths) in cwa-init. - Keep ingest dir ownership fixes when ingest folder is not /cwa-book-ingest. - Make updater chown suppression path-aware so only network-share mounts are skipped. - Ensure upload ingest preflight only skips ownership changes on /cwa-book-ingest when NETWORK_SHARE_MODE is enabled. Fixes #1030.
- cwa | 
ee9e3b8de3c3b243e514ae2baae402de596b8f7f | 2026-02-03T11:10:27+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
dd3cda1058969b4011033887ad1a84334858afcc | 2026-02-03T11:09:43+01:00 | Commits for v4.05
- cwa | 
8bf37782a310e067d8f818ee5afdcfad1e00ffed | 2026-02-03T11:05:46+01:00 | Merge pull request #1029 from Mario13546/epub-fixer-regex-patch | Fix overly-permissive empty `src` `<img>` regex
- cwa | 
6ced033c4e8a6954bdfe3f445cfb6be6ec942cbe | 2026-02-02T14:36:47-05:00 | Corrected the regex of the epub fixer | Signed-off-by: Alex Pereira <alex.pereira.6464@gmail.com>
- cwa | 
43eb0c4553662b267ce2b67c094b46a1f0b2ca8b | 2026-02-02T14:04:02+01:00 | Updated collect_commit_messages.py script
