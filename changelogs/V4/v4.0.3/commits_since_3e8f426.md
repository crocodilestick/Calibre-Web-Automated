### cwa
- cwa | 4fb64c3d3622302dc71f5dc05b6395d756f06cb4 | 2026-01-31T18:44:00+01:00 | Merge pull request #977 from finevine/translation/french-26-01-31 | Translation/french 26 01 31
- cwa | 
ddb5c646b60f7f9be43312a625ef25c577f493c9 | 2026-01-31T18:43:52+01:00 | Merge branch 'main' into translation/french-26-01-31
- cwa | 
f3a7b35fd4b8ec90160029d7e343dedc1c430ebd | 2026-01-31T17:32:55+00:00 | Update translations [skip ci]
- cwa | 
75dd25a59dc67732f6df6586078669728755bba2 | 2026-01-31T18:31:48+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
828219be78cde7c08f7595dac3197cfdb1da86bd | 2026-01-31T18:30:10+01:00 | Merge remote-tracking branch 'origin/main' into pr/finevine/977
- cwa | 
fd08e9408080cc49ca06751a49d4b0c00d7793ad | 2026-01-31T18:19:58+01:00 | Added the ability to delete books in the book details screen without having to go to the edit screen
- cwa | 
d21e305784697c0da60165775a6e6eaeb06ef315 | 2026-01-31T18:16:41+01:00 | Added More useful metadata to the book details pages
- cwa | 
3439216ef5c4389617077f984cd36bddb72331fd | 2026-01-31T18:07:16+01:00 | Rebuilt the book details page form scratch to be more useful modern and responsive
- cwa | 
e93e4009ab89ff089a1ea9c088289c6087d92e3f | 2026-01-31T16:11:10+01:00 | Fix: trigger metadata enforcement for inline edits and coalesce duplicate logs | editbooks.py: mark metadata dirty + write change logs for inline/book-list metadata updates to ensure EPUB enforcement runs. cover_enforcer.py: coalesce multiple logs per book to newest entry, delete duplicates, and avoid repeated processing. [bug] Series information not written into epub when updating metadata Fixes #726
- cwa | 
4f64e4edb06b6c66e277b9396501fa3dce9223c0 | 2026-01-31T14:37:38+01:00 | feat(ui): persist metadata field choices, show toast feedback, and add file size badges | [Feature Request] Remember Metadata Fields on manual search Fixes #891 German Metadata Fixes #858
- cwa | 
8b300c158b5f717d90890ca822a61bf43c141360 | 2026-01-31T14:22:13+01:00 | ability to reject all hardcover id matches at once | [Feature Request] Hardcover Match Global "Reject All" Fixes #964
- cwa | 
195f0562ae892de0d28b388d1ebdb4deb563cb40 | 2026-01-31T13:12:37+00:00 | Update translations [skip ci]
- cwa | 
c34518fd968da95eccfb41cd29f2927217aeea9d | 2026-01-31T14:11:58+01:00 | Merge pull request #969 from jordibrouwer/patch-2 | Update Dutch translation for server restart message
- cwa | 
6ad5bad8dd5e20d0ab649925ea653f438d89b566 | 2026-01-31T13:10:22+00:00 | Update translations [skip ci]
- cwa | 
7865568cc0e4578c79c324603f9cf94bd13137b7 | 2026-01-31T14:09:37+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
95e59034e323425ac115e0497d01d872467ca3c3 | 2026-01-31T14:06:18+01:00 | opds: add magic shelves to OPDS catalog + fix empty magic shelf feeds Add /opds/magicshelfindex and /opds/magicshelf routes, include magic shelves in OPDS feed rendering Fix OPDS magic shelf paging and cache behavior to avoid empty results Update feed list rendering for magic shelf entries opds: make root catalog per‑user with ordering + visibility Replace static OPDS root with dynamic entry list Store per‑user OPDS order/hidden entries in view_settings Split Shelves vs Magic Shelves in the OPDS root ui: add drag‑and‑drop OPDS ordering with per‑entry visibility toggles on /me Drag/drop list modeled after Duplicate Format Priority Ranking Toggle visibility per entry while preserving default fallbacks
- cwa | 
98643dd7c740aa1bb91d37cdeaf9a836d957bf56 | 2026-01-31T13:53:25+01:00 | Fix Calibre 9 schema crash (books.isbn/flags) with safe ISBN fallback | Calibre 9 removed books.isbn, books.flags, and books.lccn from metadata.db. CWA’s ORM still mapped these fields, so SQLAlchemy emitted SELECTs for missing columns and the UI crashed with 500s (issues #954/#956/#958/#967/#979). This change removes the obsolete column mappings, reads ISBNs from the identifiers table, and adds a backward‑compatible fallback to books.isbn when it exists. I also detect the presence of books.isbn via PRAGMA calibre.table_info(books) at startup to avoid repeated lookup failures. This restores Calibre 9 compatibility while keeping older libraries working. [bug] Fixes #979
- cwa | 
ae89765c38150254674c345b0111fe2f2908402d | 2026-01-31T13:27:49+01:00 | [Feature Request] Hardcover Match Confidence Threshold Any Value | Changes step to 0.01 from 0.05 Fixes #965
- cwa | 
8ab6d99ed3cdf13a1aedd324666ce1c147da8ec3 | 2026-01-31T13:24:01+01:00 | Fix Kobo OAuth for unregistered devices | point oauth_host to CWA when Kobo Store proxy is disabled add dummy /oauth/* endpoints that return placeholder tokens resolves Issue #879 for unregistered devices
- cwa | 
4e9b83efdfbc3920a9779c6acef6b55e161b98df | 2026-01-31T13:08:56+01:00 | Fix EPUB OPF parsing for Kobo downloads | strip BOM/leading whitespace before parsing OPF XML prevents lxml “XML declaration allowed only at the start” errors [bug] Could not download epub to Kobo Clara BW Fixes #975
- cwa | 
09cdddff052926750106213f292ecdfb45b17937 | 2026-01-31T13:02:20+01:00 | Fix kobo sync to include magic shelf-only books | include magic shelf book IDs in allow-list when syncing only specific shelves prevent deletions of magic-shelf-only books ensure reading-state sync respects magic shelf allow-list resolves Issue #976 (magic shelf books not syncing to Kobo) [bug] MagicShelf exclusive books don't sync to kobo Fixes #976
- cwa | 
b77cdb05680dac1e190c9cd39217d4502faec6b6 | 2026-01-31T11:16:04+00:00 | Update translations [skip ci]
- cwa | 
ae95cab40249c36c3b03a1590dd980a93d08be92 | 2026-01-31T12:15:04+01:00 | Preserve admin roles when OAuth groups missing/empty | Cause: Enabling OAuth with group-based admin management could revoke admin rights if the provider returned no groups claim (or an empty list). The code treated that as “not in admin group” and removed the role. Solution: Only apply group-based admin updates when a groups claim is present and non-empty. This preserves existing roles when the provider doesn’t supply group data. Admin permissions removed by enabling OAuth Fixes #978
- cwa | 
e242c7942d70ed3d38fb3f8d65c13259ab2b81fd | 2026-01-31T11:53:01+01:00 | Fix OAuth login email collision by matching existing users | Issue: After linking a generic OAuth provider, logging in via OAuth could still fail with “UNIQUE constraint failed: user.email”. The login path only matched by provider username, so when the provider username differed from the existing CWA username but the email matched, it attempted to create a new user and hit the unique email constraint. Solution: For non-link OAuth logins, add an email fallback lookup before creating a new account. If a user with the provider’s email already exists, bind the OAuth login to that user instead of creating a duplicate. This prevents the UNIQUE email error and redirect loop while keeping the explicit link flow unchanged. [bug] **IN 4.0.2** OAuth - "UNIQUE constraint failed: user.email" On linking Account Fixes #973
- cwa | 
becfc746519fb33db93af3a780975ab3dfa2a43d | 2026-01-31T09:57:20+01:00 | Update French translations in messages.po to reflect recent text changes and corrections.
- cwa | 
05144b34f69191a31f766aa849eea637e30a9a23 | 2026-01-31T08:33:15+00:00 | Update translations [skip ci]
- cwa | 
c64319f522c3842affb09b3cd7fbf974191cee36 | 2026-01-30T23:48:11+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
599d7fb969693ec77a606b7cd5c9cd7dd123760e | 2026-01-30T23:44:43+01:00 | Added removal for zombie digests from new **persistent** arm runner for future releases
- cwa | 
437b3aad5ecd3c90a54b02e325194261d8e241cd | 2026-01-30T23:43:15+01:00 | Consolidated commits that compose v4.0.2 for changelog
- cwa | 
3659d383e1ad33396974e1cbc71f15cf850022ad | 2026-01-30T20:41:40+01:00 | Update Dutch translation for server restart message
