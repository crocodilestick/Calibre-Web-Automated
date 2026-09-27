# Release Notes: v4.0.7

# Changelog

## 🔒 Security
**Please update.** This release fixes several access-control problems:
* **Kobo Auth Tokens:** Any logged-in user could create, view or delete another user's Kobo sync token, and use it to sign a device in as that user. Tokens can now only be managed by their owner or an admin. (Fixes #1303)
* **CWA Service Pages:** The Convert Library and EPUB Fixer start/cancel/status pages, and the CWA log viewer/downloads, were reachable without logging in. They now require an admin account. (Fixes #1304)
* **Internal Endpoints:** The endpoints CWA's own background services use to talk to the web app (`/cwa-internal/*`) could be reached from outside by spoofing a request header. They now require a shared secret that only CWA's own processes can read.
* **Single-Book EPUB Fixer:** Now requires edit rights. With anonymous browsing enabled it was reachable by guests.

## ✨ New Features
* **KOReader Sync:**
    * **Hardcover Progress:** Reading progress pushed from KOReader is now also sent to Hardcover. (PR #1324)
    * **Shared Progress Across Copies:** Progress is now stored against the Calibre book rather than the file checksum, so different copies/formats of the same book on different devices stay in sync. (PR #1225)
    * **Plugin Menu:** The CWASync menu now lives under "Tools" in KOReader, and its sync actions are disabled (with a reason shown) when no book is open. (PR #1371, #1074)
* **OPDS:**
    * **Custom Columns:** Custom columns are now exposed as category elements in the OPDS feed. (PR #1129)
* **Magic Shelves:** Added a "Currently Reading" template, and the read-status filter now supports "In Progress". (PR #1201)
* **Web Reader:** KEPUB files can now be opened in the web reader. (PR #1318)
* **Kobo Annotations:** Annotations synced to Hardcover now carry a tag matching their highlight colour. (PR #1166)
* **Auto-Send Subfolders:** Books dropped into an ingest subfolder named after a user are auto-sent only to that user (if they have auto-send enabled), instead of to everyone. (PR #1221)
* **Page Jump:** The pagination ellipsis is now a dropdown you can use to jump straight to a page. (PR #1387)

## 🎨 Interface
* **Login Page:** Redesigned as a single centred card with the CWA logo, clearer fields, a show-password toggle, and matching buttons for SSO, GitHub, Google and Magic Link logins.
* **Book Covers:**
    * **Even Shadows:** Covers now have a soft shadow all the way round, replacing the grey glow along the bottom edge.
    * **No More Stretching:** Every cover sits in the same 2:3 frame and is cropped to fit instead of stretched, so square and wide covers are no longer distorted. The placeholder cover now matches that shape.
    * **First Cover Size:** The first book in the grid no longer renders smaller than the others.
* **Phone Layout:**
    * **Book Grid:** 3 columns instead of 2, so you can see far more of your library at once.
    * **Sort Buttons:** One row you can swipe sideways, instead of a two-row block.
    * **Menu:** The menu button is now a ☰ on the left, the side the menu opens from, instead of your avatar on the right. The menu itself is a dark panel with a compact profile row, evenly spaced items and a highlight on the current page.
* **Tablet Layout:** 3 columns beside the sidebar instead of 2.
* **Sort Toolbar:** Tidier rounded toolbar with consistent buttons on every screen size.

## 🚀 Improvements
* **Kobo Sync Performance:**
    * **Much Faster Syncs:** Reading-state handling and metadata loading were rewritten to avoid per-book queries, saving up to ~15 seconds per sync request on large libraries. (PR #1344)
    * **On-Demand KEPUBs:** KEPUB conversion now happens when a book is downloaded instead of up front. Opening your Kobo token page no longer converts every EPUB in the library. (PR #1344, Fixes #817)
* **Ingest & Duplicates:**
    * **Smarter Ingest:** Stale and repeated watcher events are ignored, missing files exit early, and database reconnects/duplicate refreshes are batched until an import run goes quiet. This stops the ingest service reprocessing the same files on polling/NFS setups. (PR #1349)
    * **Incremental Duplicate Scanning:** Duplicates are now tracked in an index that updates incrementally after imports and edits, instead of rescanning the whole library. (PR #1353)
    * **Ingest Runs as `abc`:** The ingest service now drops root privileges, so imported books are owned by the same user as the web app. The ingest status files are handed to `abc` at startup too, so status tracking works on fresh installs and with `NETWORK_SHARE_MODE`. (PR #1145)
* **Stability:**
    * **Thumbnail Deadlock:** Fixed a database deadlock between cover thumbnail generation and metadata saves that could freeze the web UI. (PR #1346)
    * **Detached Sessions:** Book relationships now load eagerly, fixing intermittent 500 errors when pages rendered after the database session closed. (PR #1279, Fixes #1067)
    * **Healthcheck:** The Docker healthcheck now follows the redirect to `/login`, so healthy containers are no longer marked unhealthy. (PR #1298)
* **OPDS Covers:** OPDS feeds now request cached medium-resolution covers instead of reading full-size originals from disk for every book. (PR #1447)

## 🐛 Bug Fixes
### Scheduling
* **Scheduled Convert Library / EPUB Fixer:** Scheduled runs crashed before starting, so they never ran. They now run as expected. (Fixes #1481)
* **Schedule Buttons:** The "Schedule 5m / 15m" buttons only worked when browsing from the server itself, and could otherwise hang the web UI for 10 seconds. Both are fixed.
* **Status Page on Fresh Installs:** The Convert Library and EPUB Fixer status checks no longer error before their first run.

### Kobo & Readers
* **Modern Kobo Firmware:** Serve an OIDC discovery document and local reading-services stubs so fully-local sync works on firmware 4.45+. (PR #1367)
* **Bookmarks:** Fixed a crash when a Kobo bookmark has no location, and 0% progress is no longer dropped from bookmark responses. (PR #1213, #1362)
* **Shelf-Only Sync:** Fixed a stale collection filter when syncing only selected shelves. (PR #1443)
* **Reverse Proxies:** Kobo download and cover URLs no longer include the internal port behind Cloudflare Tunnel and similar proxies, and the external port setting is now optional. (PR #1143)
* **KOReader Plugin:** Fixed progress sync errors on some older KOReader versions. (PR #1131)
* **Web Reader:** Restored the missing back button. (PR #1231, Fixes #1203)

### Safari & Browser
* **Safari Forms:** Fixed save buttons on the user edit/create pages and other forms that did nothing in Safari. (PR #1104, Fixes #1078)
* **Safari Metadata Search:** Fixed metadata search failing immediately in Safari. (PR #1096)
* **Quick Send:** The caliBlur quick "Send to eReader" button now works for users without upload permission. (PR #1164)

### Metadata & Editing
* **Save Loss:** Fixed edits sometimes being lost when a save also renamed the book's folder. (PR #1331)
* **Fetched Descriptions:** Fetched descriptions are now saved on the first click. The result button is renamed "Apply". (PR #1336)
* **Metadata Modal:** No longer crashes when a provider returns results without authors, tags or identifiers. (PR #1330)

### Library & Misc
* **Recently Added:** Newly imported books now get the current time as their "date added" rather than their publication date. (PR #1280)
* **Magic Shelves:** Sorting by author no longer returns an empty shelf. (PR #1233, Fixes #1232)
* **Email:** Sending falls back to the original file if the metadata export fails. (PR #1236, Fixes #1235). Fixed a TypeError when running eReader send tasks. (PR #1406)
* **Restore Database:** The "Restore Calibre Database" button now works. It was nested inside another form and silently submitted that instead. (PR #1444)
* **Duplicates:** The resolution log now uses local time, and the cooldown setting is saved correctly. (PR #1435)
* **User Profiles:** Profile pictures now load behind a reverse proxy with a path prefix. (PR #1283, Fixes #1188)
* **Comics:** CBR/CBZ files now use their registered MIME types. (PR #1322)
* **Ingest Folder:** CWA no longer changes the ingest folder's ownership before checking network share mode. (PR #1226)
* **Docker Compose:** Fixed the invalid timezone example. (PR #1229, Fixes #1197)

## 🌍 Translations
* Merged 48 community translation PRs across 12 languages: Czech, Hungarian, Korean, Turkish, Dutch, Ukrainian, Traditional Chinese, Simplified Chinese, Spanish, Russian, German and French. Thank you to everyone who contributed!
* **Slovak:** Fixed a missing placeholder that broke compilation.

## 🔧 Technical & CI
* **Test Suite:** Unit tests no longer share the real `/config/cwa.db`, which was making CI fail at random. New tests cover route authentication.
* **CI:** Fixed Docker SDK shadowing in integration tests and translation-update push races, and bumped codecov-action to v5.
* **Development:** Templates and Python code auto-reload in development mode. (PR #1378)

## ⚠️ Upgrade Notes
* **Duplicates:** After upgrading, run one full scan from the Duplicates page to build the new duplicate index.
* **File Ownership:** The ingest service now runs as the `abc` user (your `PUID`/`PGID`). If earlier versions left root-owned books in your library, fix their ownership once if you see "Permission denied" errors when editing or deleting them.
