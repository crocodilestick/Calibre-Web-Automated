### cwa
- cwa | 407cd6184558b37e9bd041d17245c7e80e006f80 | 2026-02-01T01:30:14+01:00 | Fix identifier edits by decoupling input names from types and normalizing saves | The edit form used type-based input names and fragile selectors, so removed rows still posted and identifier edits were unreliable (special characters, duplicates, and empty values). This change switches identifier rows to stable IDs with class hooks, updates metadata import to match by input values, and normalizes server-side parsing to trim, skip empty entries, and apply last-write-wins dedupe. Hardcover review updates now overwrite existing identifiers and ignore empty values.
- cwa | 
138104a00a97d3b1ae356d786651fc31f253dd89 | 2026-02-01T01:25:39+01:00 | Fixed styling of flash messages
- cwa | 
ea63e36f485daa452bed0767dde83e76016397c0 | 2026-02-01T01:22:33+01:00 | feat(admin): add last-resort Calibre DB restore with backups, checks, and cleanup | - Add a guarded “Restore Calibre Database” workflow to DB config UI with explicit warnings. - Auto-backup metadata.db + app.db to /config/backup/restore_<timestamp> and write restore.log there. - Run calibredb check_library before/after restore and log outputs to Docker logs and restore.log. - Restore database via calibredb restore_database --with-library, with timeouts and robust error handling. - Wipe only book-linked app.db tables to avoid broken references after ID regeneration. - Reconnect CalibreDB after restore to clear stale sessions. - Prevent concurrent restores with /tmp/restore_calibre_db.lock and clear stale lock on boot. - Improve DB-session safety: invalidate config on setup failures and redirect to DB config instead of 500s. - Add session guard in admin before_request for missing Calibre DB sessions. - Minor UI/JS updates to identifiers removal to use buttons instead of inline JS. [Feature Request] Add "Restore Database" button to CWA Web UI Fixes #898
- cwa | 
3e91a90c72bb259562d3803b8403e46ae6197da1 | 2026-02-01T00:39:11+01:00 | feat(admin): Add last-resort Calibre DB restore with auto-backup and app.db cleanup | - Implements a “Restore Calibre Database” workflow in the DB config screen for catastrophic metadata.db corruption. - Automatically backs up both /calibre-library/metadata.db and /config/app.db to /config/backup before any destructive action. - Runs calibredb restore_database to rebuild metadata.db from OPF files. - Wipes all book-linked tables in app.db (shelves, reading progress, bookmarks, downloads, etc.) to avoid broken references after book IDs change. - Preserves user accounts, shelf definitions, and settings. - Adds clear UI warnings and feedback for users. - Prevents 500 errors on DB/session failures by redirecting to config and invalidating config.db_configured if setup fails. - Addresses issues where persistent config or library path problems cause the app to break even after rollback, as reported in #984.
- cwa | 
68a3a292a07be1df2f4f56ba5fcf2af18a04a1cb | 2026-02-01T00:36:58+01:00 | Fix #986 and expose OPDS settings in admin user edit | Issue: Admin/new-user renders of user_edit.html lacked OPDS context, causing Jinja tojson on Undefined and a 500 when editing/adding users. Profile error re-render also missed OPDS/magic-shelf context, risking the same crash. OPDS controls were hidden on admin user edit pages and changes couldn’t be persisted for other users. Fix: Build OPDS context for admin/new-user renders and for profile error re-render. Show OPDS section on admin user edit. Persist OPDS order/visibility edits to the target user’s view_settings (not the admin). [bug] Can't edit or add users Fixes #986
- cwa | 
edb000232e3dd53033a5be8dcc5066888f8e6b53 | 2026-02-01T00:33:43+01:00 | Fixed shelf actions styling
- cwa | 
f61b6a27343e3c48787b5e645c742a3713d2648a | 2026-02-01T00:23:42+01:00 | Made the location and order of the buttons for the settings menus more logical
- cwa | 
e083f2bf03549e81a1b115506b0330cdc9872a69 | 2026-01-31T23:59:50+01:00 | Made it so that tags can be dynamically added and removed on the book details page
- cwa | 
add3222b6f782400a90d574c381ba0d4d3062376 | 2026-01-31T23:04:36+01:00 | Fixed the add to shelf and remove to shelf buttons broken by v4.0.3. Also make it so that you can click the file size pills to directly download the corresponding file
- cwa | 
2207e2d059834be6a6649a9ab25207cde211465e | 2026-01-31T23:03:19+01:00 | Fixed downloads of dodgy kepubs crashing and causing 500 errors
- cwa | 
7e9995bb7e08979e3231bc37c6fcecd7ca3b7f30 | 2026-01-31T23:02:13+01:00 | Removed unnecessary about link from side nav bar
- cwa | 
8c521f3c50b1a3d478d87b62c161a4ebf44b8112 | 2026-01-31T22:54:04+01:00 | Fix Kobo sync crash on missing date_added | - guard date_added when computing ts_created to avoid TypeError - add debug log for books missing date_added - prevents sync crash reported in #983 [bug] TypeError: '>' not supported between instances of 'NoneType' and 'datetime.datetime' on latest v4.0.3 Fixes #983
- cwa | 
645702805fec07af6c14484ee6535e243ea9c9b2 | 2026-01-31T20:50:33+01:00 | Fix metadata provider search robustness and null handling | Guard metadata search aggregation against provider exceptions and None results. Normalize provider error paths to return empty lists instead of None. Harden Google, Scholar, ComicVine, IBDb, and Douban parsing for missing fields. Fixes #981
- cwa | 
1643c8f24df9c5fcb52050cc93a82bdb916abcc1 | 2026-01-31T20:07:48+01:00 | Updated the README
- cwa | 
472cbc1abbbfb7fc044cc18016ba6b82b74d1614 | 2026-01-31T19:56:33+01:00 | Merge branch 'main' of https://github.com/crocodilestick/Calibre-Web-Automated
- cwa | 
398db871ed93f53ed0f7a8e5da7caf1e48c69fcb | 2026-01-31T19:55:47+01:00 | Updated README
