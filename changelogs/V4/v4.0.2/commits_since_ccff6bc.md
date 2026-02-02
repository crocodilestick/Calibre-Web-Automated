### cwa
- cwa | 938cd36cdf1fbee6a9065fdc1f4e77359aa1da32 | 2026-01-30T22:03:38+01:00 | routes: rename versions page and redirect legacy /stats Problem: /stats was ambiguous; wanted /package-versions for package versions and /stats to point to CWA stats. Approach: add /package-versions, redirect /stats to /cwa-stats-show (301), update nav links.
- cwa | 
e1c32f1ea35efb825f895ed97281fafc0377ad95 | 2026-01-30T22:03:05+01:00 | admin/stats: remove upstream Calibre-Web version display Problem: “Stock Calibre‑Web” showed v0.0.0 and is no longer meaningful for this fork. Approach: remove upstream version computation and table row; drop Calibre‑Web from stats versions list.
- cwa | 
0a688f72361f1e868a76b20816847a161f4b87eb | 2026-01-30T22:02:26+01:00 | docker: unify Calibre/Kepubify build args Problem: multi‑stage defaults drifted (Calibre 9.0 installed but 8.9.0 recorded), so UI showed the wrong version. Approach: define shared ARG defaults once and re‑declare them per stage; drop the unused CW base label/arg.
- cwa | 
52458a102c32f2992a436effeab1b4dc068b8f40 | 2026-01-30T21:26:55+01:00 | Fix translation automation and dev build triggers | Make translation updates commit catalogs automatically Dispatch dev builds from translation workflow to keep main up-to-date Skip main push builds to avoid duplicate images Use Python module invocation for Babel to avoid broken venv shebangs
- cwa | 
09baaa9807772972994e16e518c4ce78fbf0f285 | 2026-01-30T20:26:09+00:00 | Update translations [skip ci]
- cwa | 
91a51c36655ef5c9fbb0f10bc54a2ca52541d087 | 2026-01-30T21:23:33+01:00 | fix(calibre-init): fill minimal config to prevent v4.0.1 AttributeError | Regression introduced by 0f3c2ef, which added app.db-based CalibreDB init with a _MinimalConfig that only included config_title_regex and config_calibre_dir. Newer request paths now hit this minimal-config flow and access missing settings like config_books_per_page, causing login crashes. Resolution: Load the commonly accessed config fields from app.db and default them when missing. Add focused unit tests covering both full and fallback schema paths. This keeps the original intent of background/ingest initialization while restoring stability for normal web requests.
- cwa | 
d11a1c45b7f61ecde93d94bee076017eae6dfea5 | 2026-01-30T20:58:44+01:00 | Updated translations. | Major Update to 4.0.0/.4.0.1 messes up translations Fixes #960
- cwa | 
218f2bc11f2c804ff5560a53540b985108f7689a | 2026-01-30T20:51:31+01:00 | Update translation automation and dev build flow | Fix stale catalogs by committing messages.pot/.po in update-translations workflow Trigger dev build from translation workflow so main builds use updated catalogs Skip main push builds in dev workflow to avoid duplicate images
- cwa | 
8c059e4fc618ef7cf3b8ecfbaa7aef8bb2e92ac3 | 2026-01-30T20:01:44+01:00 | Fix: honor cancel for Hardcover auto-fetch | The task only checked STAT_CANCELLED, but the UI sets running tasks to STAT_ENDED, so the loop kept running and blocking other tasks. Now it treats STAT_ENDED as cancel and checks during sleep/backoff to exit promptly. [bug] Auto-fetch Hardcover IDs: Auto-fetching Hardcover IDs does not stop Fixes #959
- cwa | 
e096e928f05e398034a7d7bfb309db33459e107e | 2026-01-30T19:51:20+01:00 | Fix OAuth link loop by scoping user binding to link flow | Prevented generic OAuth linking from auto-creating a new user when the email already exists, which caused UNIQUE constraint failures and redirect loops. Added a session-scoped “linking” guard so only explicit link actions bind to current_user, while normal OAuth logins keep existing behavior and we clear the flag after completion. [bug] OAuth - "UNIQUE constraint failed: user.email" On linking Account Fixes #952
- cwa | 
8685b7f738bbec2e27278abd2af0b6d233b2db62 | 2026-01-30T19:26:54+01:00 | Updated the Dockerfile to Calibre 9.0.0
- cwa | 
9a0afb99dd4eb71e41d7530515b8e58578129d64 | 2026-01-30T19:26:16+01:00 | Fix Calibre 9 metadata schema incompatibilities (books.isbn/flags) | Calibre 9 removed books.isbn, books.flags, and books.lccn from metadata.db. CWA’s ORM still mapped those fields, causing SQLAlchemy to emit SELECTs referencing missing columns and crash the UI with 500s (issues #954/#956/#958/#967). We updated the Books model to stop mapping the removed columns and added an isbn property that reads from the identifiers table as Calibre now stores ISBNs there. To preserve backward compatibility with older libraries that still have books.isbn, we added a fallback lookup that reads the column when it exists. Presence is detected at startup via PRAGMA table_info(books), so Calibre 9 and older databases both work without crashes. This restores Calibre 9 compatibility while keeping existing pre-9 metadata.db files functional.
- cwa | 
5f21630bdb393c90ceddb14d7bb29e19c8c35a82 | 2026-01-29T23:32:18-05:00 | fix(db): avoid nested migration transaction | Use engine.begin() in _run_ddl_with_retry to prevent InvalidRequestError when PRAGMA triggers autobegin under SQLAlchemy 2.x. Add a smoke test to guard the transaction pattern.\n\nRefs #950
- cwa | 
2a356c9a8ac1f747ad0e09a8a1a9885a11216ae2 | 2026-01-30T01:28:35+01:00 | Updated the README for the most recent release
- cwa | 
95f36df8a29960716ce55a12cf763de139f1ce4b | 2026-01-30T01:12:03+01:00 | Fixed arm build network config in build workflows
- cwa | 
8fee7c2dc6a6b1fa66a69b1278ab643f22a6726a | 2026-01-30T01:11:30+01:00 | Commit list to prepare v4.0.1 changelog
