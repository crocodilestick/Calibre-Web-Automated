### cwa
- cwa | 43eb0c4553662b267ce2b67c094b46a1f0b2ca8b | 2026-02-02T14:04:02+01:00 | Updated collect_commit_messages.py script
- cwa | 
70caf86375408edfb457a7533748af2c7b7b5eca | 2026-02-02T14:00:08+01:00 | feat: add per-user control for send-to-eReader modal and enforce direct-send fallback | add allow_additional_ereader_emails to user model with default enabled add migration to backfill new column in user table expose toggle on /me and admin user edit pages with explanatory help text persist toggle from both profile save and admin edit flows (including unchecked case) hide modal and additional-address input when disabled make send button direct-send to all configured eReader addresses when disabled validate selected emails server-side and block disallowed additional addresses harden modal JS for missing elements and add direct-send AJAX handler fix null book id in modal by adding fallback data-book-id update translation template with new UI strings
- cwa | 
6d39ef5a362348be7ce820ac4850f3355149884b | 2026-02-02T12:22:51+00:00 | Update translations [skip ci]
- cwa | 
f1ca700b40eca7940f78673cdbf99f072b2c7780 | 2026-02-02T13:22:19+01:00 | Merge pull request #820 from tmacphail/bugfix/ingest-folder-ownership | Parse folders to chown from dirs.json
- cwa | 
abe175de8212e7618e946640ef14c3583e173a71 | 2026-02-02T13:19:56+01:00 | Merge origin/main into pr/tmacphail/820
- cwa | 
85eadc0194b10df6daf921962b9110297229b940 | 2026-02-02T13:15:30+01:00 | scripts: fix translation update to avoid broken venv pybabel | Invoke Babel via python -m babel.messages.frontend and fall back when the venv interpreter is unusable, preventing pre-commit failures caused by bad shebangs or missing pybabel entrypoints.
- cwa | 
fb5306d9e7dbe668b3f2f443ae474c246f9cec79 | 2026-02-02T13:14:39+01:00 | cwa-init: harden requiredDirs parsing and keep /calibre-library default | Parse dirs.json via Python to avoid fragile shell regex and missing jq. Always include /calibre-library alongside /config and app path to prevent regressions if dirs.json is missing or malformed. Skip parsing if the file is absent, preserving existing behavior.
- cwa | 
708fafa9e33585e63df7e934bdf3a3db9e20b6a3 | 2026-02-02T11:48:08+00:00 | Update translations [skip ci]
- cwa | 
8a87c06662897b3f417a8d2047262aaee47897e4 | 2026-02-02T12:47:30+01:00 | Merge pull request #857 from jbergler/fix-kosync-header-auth | Allow header auth for kosync endpoint
- cwa | 
102f469699a656c6512cef88fd9b11a77faadadf | 2026-02-02T11:42:15+00:00 | Update translations [skip ci]
- cwa | 
009070031db06f9e50d0d0da2564d674a25fbff1 | 2026-02-02T12:41:37+01:00 | Merge pull request #1021 from ManuelDrescher/patch-5 | Fixed new fuzzy entries in locale DE
- cwa | 
f0ed80e5af724f57b0c5569aea3e112ff8af87e8 | 2026-02-02T12:41:28+01:00 | Merge branch 'main' into patch-5
- cwa | 
71726e805fb7d223fc6fac39184b5359718fbfb9 | 2026-02-02T11:40:31+00:00 | Update translations [skip ci]
- cwa | 
3c659b5d98731f0ed4a4324165f98dd054a46f13 | 2026-02-02T12:39:53+01:00 | Merge pull request #1020 from thehijacker/main | Updated Slovenian translation
- cwa | 
974e91c47b1337e260e910ef77643e0f191f4e3b | 2026-02-02T11:38:43+00:00 | Update translations [skip ci]
- cwa | 
69d4b9ea615fae282c6a9ab451ed4a49280ac3bc | 2026-02-02T12:38:09+01:00 | Merge branch 'main' into main
- cwa | 
38dfd0e29e8979922fd3b84a5f14e83799198f87 | 2026-02-02T12:33:35+01:00 | Merge pull request #1013 from DendyA/main | kindle_epub_fixer.py: Fixed the adding of duplicate xml declarations
- cwa | 
7b15aa49dc23c750ac6295d91d14d713a9e6cbc1 | 2026-02-02T12:33:27+01:00 | Merge branch 'main' into main
- cwa | 
d12ae7c2f2f00a80c3b945a48502244658ae1b5c | 2026-02-02T12:32:04+01:00 | Added recognition of DendyA's contribution
- cwa | 
cdca2f4a71cc0ff7cfce3f5cc0519e4154458d20 | 2026-02-02T12:31:29+01:00 | Merge branch 'main' of https://github.com/dendya/calibre-web-automated into pr/DendyA/1013
- cwa | 
704d38e63385f79132c8b240105cd9c854ae169c | 2026-02-02T11:28:36+00:00 | Update translations [skip ci]
- cwa | 
6e0a96125fbc8b7aceaa2fab1738c741bdd41898 | 2026-02-02T11:23:27+00:00 | Update translations [skip ci]
- cwa | 
2aea5ce748918119568561a4f47f70724cfee954 | 2026-02-02T12:22:37+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
4db290050a2b3f10eafb2c8a838201f8cb2b82af | 2026-02-02T12:22:11+01:00 | Title: Add diagnostics and harden cover handling during metadata saves Body: | Add timing/debug logs around the edit-book save flow, cover fetch, and DB commit. Introduce configurable cover download size in CWA settings (default 15 MB) and enforce size limits/timeouts. Wire new setting into schema, settings UI, and settings parsing/defaults. Skip ImageMagick conversion for already‑JPEG covers to avoid redundant processing on the request thread. Keep environment override for max bytes and log cover download size/duration. Changes are aimed at mitigating issue #1018 while enabling deeper diagnostics. [bug] saving fetched meta data results in server no longer responding Fixes #1018
- cwa | 
58aa5826536908cba244e68fe9be37f617e6a828 | 2026-02-02T11:08:40+00:00 | Update translations [skip ci]
- cwa | 
00f4e88edf66fa9006046e2946525de177a7b36a | 2026-02-02T12:07:26+01:00 | Added a pill element for displaying which shelves a book belongs to as well as alsoadding the ability to add and remove shelves on the fly
- cwa | 
bd9af2a4f3870312adb3cb1078130b6eac0e0273 | 2026-02-02T11:41:55+01:00 | Title: Add configurable cover download size limit for metadata saves Body: | Add CWA setting to control maximum cover image download size (default 15 MB). Enforce size limit and shorter timeouts during cover fetch to prevent request hangs. Wire setting into schema, settings UI, and settings parsing/defaults. Keep environment override for maximum bytes. This is a mitigation for issue #1018; monitoring for confirmation after re-test. [bug] saving fetched meta data results in server no longer responding Fixes #1018
- cwa | 
b021ab5ac3c8171dd26ccc4a3c5404fbc805d3d6 | 2026-02-02T11:28:53+01:00 | Merge branch 'main' into main
- cwa | 
7dd307deb2b867161265bbeadefe27c3133c792c | 2026-02-02T11:14:59+01:00 | Fix CI ingest permissions by aligning test container UID/GID | Use host UID/GID (or CWA_TEST_PUID/CWA_TEST_PGID) when starting test containers to avoid bind-mount permission errors. Update docker-compose test override in conftest.py to set dynamic PUID/PGID. Update DinD container run in conftest_volumes.py to set dynamic PUID/PGID. Export CWA_TEST_PUID/CWA_TEST_PGID in CI workflow before integration tests in tests.yml.
- cwa | 
11fc6d9f7a8e86aa10b573cca06c73114af5714e | 2026-02-02T09:55:57+01:00 | Fixed new fuzzy entries in locale DE | All new fuzzy entries were fixed
- cwa | 
13835b0855b2f56d26b78cbc58c5ada0a0365b5a | 2026-02-02T07:20:04+00:00 | Update translations [skip ci]
- cwa | 
75e1b7d20603f597ce779389149a4b1f0fa9ec23 | 2026-02-02T08:19:12+01:00 | Updated Slovenian translation
- cwa | 
d2c29e5cbbbbde5a5fdff0edac7e3b1a9b87d8d1 | 2026-02-02T00:32:50+00:00 | Update translations [skip ci]
- cwa | 
1d89d168dec3ebfae114dfb24b8ed0b75503ee6b | 2026-02-02T01:32:00+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
737fb05ac5c3d4f4485934224b45df3858cec52c | 2026-02-02T00:27:49+00:00 | Update translations [skip ci]
- cwa | 
9ea6a83a8fe6f9286c39625ee67e37b2762f7b93 | 2026-02-02T01:27:19+01:00 | Merge pull request #864 from fmguerreiro/japanese-translations | Complete Japanese translations: 198 new + 155 fuzzy fixes
- cwa | 
b7d39063cfff6ad575c6c46e8e2decaf20962cc1 | 2026-02-02T01:23:10+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated into pr/fmguerreiro/864
- cwa | 
2e7922fdaaccc30e79fcde9c15745e4659c8cf28 | 2026-02-01T16:14:26-08:00 | kindle_epub_fixer: Adding in the missing handling of leading whitespace, per crocodilestick's comment.
- cwa | 
6ee4c94a96ba7c194c67d9816facabb582949df2 | 2026-02-01T23:57:36+00:00 | Update translations [skip ci]
- cwa | 
aa5f0e3fb77ac7895a61ccdbbb58316a795c1778 | 2026-02-02T00:57:05+01:00 | Merge pull request #1012 from jaimetur/patch-1 | Fix and improve Spanish translations across the UI.
- cwa | 
46dbce4384358e143d0e64b4b7eb5be14f13d0ce | 2026-02-02T00:56:54+01:00 | Merge branch 'main' into patch-1
- cwa | 
59be92539482e7d7a20ff1a6dc04d5f9b93d1d47 | 2026-02-02T00:55:58+01:00 | Fixed syntax errors
- cwa | 
2488dae0462ae77a76bb21c3d5e2fdf489be15e2 | 2026-02-01T23:47:58+00:00 | Update translations [skip ci]
- cwa | 
18d89180c3408e76b2b958490233139d3650410c | 2026-02-02T00:47:25+01:00 | Merge pull request #997 from ManuelDrescher/patch-4 | Updated german translation after Major Upgrade to 4.X
- cwa | 
1b02b422c4bb06b577e470a3407b14789eab911e | 2026-02-02T00:45:10+01:00 | Added translation for Disable Standard Login (Username/Password)
- cwa | 
a77c5983389b530d57f02e055dc350fcdc8b7320 | 2026-02-02T00:36:09+01:00 | addresses the duplicate XML declaration for XML files lacking an encoding by replacing the existing declaration instead of always prepending a new one
- cwa | 
6f403d49e75f37716df4c3483993549c62b3342e | 2026-02-02T00:30:10+01:00 | Initial approach dropped any leading whitespace captured by xml_decl_pattern, unlike the existing path that preserves it. This can subtly alter files that include whitespace/BOM before the declaration. Altered the fix to preserve the leading whitespace while still resolving the duped declarations
- cwa | 
ec9bbcf14959591ea876e4f74afd8af5ae8bf7a8 | 2026-02-02T00:17:55+01:00 | feat(web,reader): expose KOReader progress and use as fallback resume | Fetch KoboReadingState progress (percent + timestamp) for authenticated users in show_book and pass to templates. Pass KOReader percent into EPUB reader bootstrap data. Display KOReader progress chip on book detail page when available. Use KOReader percent to resume EPUB only when no local progress and no bookmark. [bug] Kosync doesn't seem to work Fixes #996
- cwa | 
7cc9edeaef947fce30898d5b672eee94010e2595 | 2026-02-02T00:00:03+01:00 | Title: Fix KOReader sync crash on malformed responses Body: | Guard login/push/pull against missing server configuration. Add robust response parsing to avoid non-table body crashes. Require progress in pull responses and coerce percentage safely. Bump KOReader plugin version to 1.0.2. [bug] Kosync plugin crashing koreader on sync Fixes #1003
- cwa | 
1a8818af2fe19247ecbdb262c1e01fe7093843b2 | 2026-02-01T23:54:37+01:00 | feat(epub-fixer): add single-book runs, UI revamp, and robust cancel handling | add single-book EPUB fixer endpoint and wire it to the web UI search/selection flow reuse listbooks search to pick a title/author and trigger a single-file run update fixer UI layout (two-column layout, external link styling, bulk section, title styling) adjust in-page notifications: cap height/scrolling and reposition to prevent oversized alerts reload page after single-book run to show progress immediately ensure single-file fixer logs start/end markers so status tracking completes add script-level cancel trigger checks for both single and bulk runs add server-side cancel fallback to terminate stuck fixer processes
- cwa | 
3baae67d2ab1884c0acfc67c853edcc7c8087ee8 | 2026-02-01T14:37:07-08:00 | kindle_epub_fixer: Added an elif in fix_encoding() to handle replacing the existing xml declaration that is missing encoding info with one that has the encoding defined.
- cwa | 
443608115f9244f6d739b5af22c9f54a1c5c8ba8 | 2026-02-01T23:17:33+01:00 | Fix and improve Spanish translations across the UI. | Improve Spanish UI translations (fix awkward wording, keep filenames/variables intact, and refine key settings/duplicate-detection strings).
- cwa | 
49d3e6bfd631e0dcd6c575acb3ff13402a2c99d7 | 2026-02-01T23:00:14+01:00 | fix(editbooks): enforce EPUB metadata updates for bulk list edits | mark metadata dirty when list edits change title/authors/tags/series/languages/publisher/comments write metadata change logs for bulk edits to trigger cover/metadata enforcement include change metadata payload for audit/debugging during batch updates [bug] Updating Categories via Book List does not add it to the epub Fixes #998
- cwa | 
c337926cfdf77ee09aac09611062666d4f239193 | 2026-02-01T22:50:09+01:00 | fix(kobo): guard missing timestamps in sync | Move Kobo “created” timestamp selection into a shared helper and use it during sync to avoid None comparisons when timestamp/date_added are missing. The helper now falls back to last_modified and ultimately datetime.min, preventing the v4.0.4 crash while keeping behavior identical for normal records. Add unit tests covering all fallback combinations. Tests: pytest test_kobo_sync_timestamps.py Fixes #1011
- cwa | 
1ccb25dc882e7a1b547e65011e3669917aef841f | 2026-02-01T22:34:32+01:00 | fix(ub): make duplicates sidebar migration one‑time | The user sidebar flag for “Duplicates” was being re‑enabled for all admin users on every startup because the migration in migrate_user_table() ran unconditionally. This overwrote the saved “hide Duplicates” preference after each restart. Persist a migration marker in the config directory and only apply the admin sidebar backfill once. Subsequent restarts skip the change, preserving user settings while still upgrading existing installs. Notes: Uses a marker file under .cwa_migrations to avoid repeated changes. Leaves existing behavior intact for the first run. Fixes #1010
- cwa | 
95e5dffe245a79f296c40e2f99bca5bc11f09639 | 2026-02-01T22:24:51+01:00 | Fix upgrade DB init failures on network shares and read‑only libraries | Investigated upgrade reports (v3.1.4 → v4.x) showing SQLite disk I/O error during attach database for metadata.db. Root cause appears to be new WAL enablement + metadata.db DDL on startup; both can fail on NFS/SMB/unionfs/mergerfs or read‑only libraries. Secondary crash: setup_db() called config.invalidate(ex) when _MinimalConfig was used (from calibre_init), which lacked invalidate(), turning the underlying DB error into an AttributeError/500. Changes: Add _MinimalConfig.invalidate() to avoid AttributeError and mark db as unconfigured on failure. Skip WAL enablement when NETWORK_SHARE_MODE=true or metadata.db is not writable. Skip checksum-table DDL on metadata.db when WAL is skipped. Log a warning when WAL is disabled so users can see the fallback reason. Harden setup_db() invalidation calls with hasattr() checks. Update /admin/dbconfig troubleshooting text and fix JS confirm interpolation. Expected result: Upgrades that hit “disk I/O error” now fail gracefully and redirect to dbconfig instead of 500. Network-share deployments avoid WAL/DDL pitfalls while still providing clear guidance in logs/UI.
- cwa | 
65f1b06c43b9bb5b9ebc2f872b560ddb44a4dac8 | 2026-02-01T20:24:27+01:00 | Fixed login page styling
- cwa | 
16a3b9230f40aabfdf06fae54bb3b85fc21ec152 | 2026-02-01T17:39:24+01:00 | Issue #995: Add ingest directory preflight + init fix | Root cause: post‑V3.1.4 “ingest‑on‑upload” writes directly to /cwa-book-ingest from the web process. If that bind mount doesn’t exist or is root‑owned, uploads fail with “Failed to queue upload for processing” and no useful logs. Fix: Ensure ingest dir exists and is chowned during cwa-init (respects NETWORK_SHARE_MODE). Add upload preflight to validate ingest path and surface a clear user error. Improve logging around ingest directory creation failures. Normalize ingest preflight to avoid false negatives before chown. Result: upload now fails fast with actionable errors when permissions/mounts are wrong, and succeeds once /cwa-book-ingest is writable. [bug] Failed to queue upload for processing Fixes #995
- cwa | 
371ce84dbb766bd4e2b8c959d250ae8950048887 | 2026-02-01T17:38:49+01:00 | Fixed new book view mobile styling
- cwa | 
ca59b9569190b8857ce0f05cb9c16ae53bd9762d | 2026-02-01T16:40:42+01:00 | Fixed delete modal trigger and add book detail toolbar tooltips | [bug]Delete Button Not Working in 4.0.4 Fixes #1000
- cwa | 
3d0a6a4b8ab468bdd941a352e461675984d92973 | 2026-02-01T14:45:33+01:00 | Fuzzy entries | All fuzzy entries checked and corrected
- cwa | 
5bc7e4477854651e837ddadd01987b8a4bc19f24 | 2026-02-01T13:18:05+01:00 | Updated german translation after Major Upgrade to 4.X | After the major upgrade to version 4.x, many entries were missing translations (likely due to the new features)...or for other reasons. Missing translations have been added where available in messages.po.
- cwa | 
6e65e3ff4018f60f7d3770e9d523f3ee9d7344e4 | 2026-01-03T10:30:12+09:00 | Fix 155 fuzzy translations with correct Japanese.
- cwa | 
bb3d94d8da316dc57cef6998cf20fc931c4e429e | 2026-01-03T09:44:27+09:00 | Format multi-line translations to match project style.
- cwa | 
4c7d4d04c29829c2444f5798be03a2c776b15739 | 2026-01-03T09:37:48+09:00 | Add Japanese translations for 198 untranslated strings.
- cwa | 
24fb480c6d9c17997f0e973d6aab1d9f808d0ab2 | 2026-01-01T14:30:59+13:00 | allow header auth for kosync
- cwa | 
6c171e7ffa1d33f43a11af4deb66db2ae94d65a2 | 2025-12-08T13:11:17-08:00 | Add fallback parsing in case of no jq
- cwa | 
aac6191bc974854d3016869878ee6cf728a58bf1 | 2025-12-08T12:47:20-08:00 | Use dirs.json for list of required dirs in setup | Parse from dirs.json instead of hardcoding the list here. This produces a more complete list of directories needing ownership set because /cwa-book-ingest wasn't included previously.
