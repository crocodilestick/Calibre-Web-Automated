# Release Notes: v4.0.8

# Changelog

## 🐛 Bug Fixes
### Kobo
* **First Sync on New Devices:** Freshly paired or factory-reset Kobos on current firmware failed their first sync with "Sync failed. Please try again." CWA now answers the device's `add-device` and token refresh requests, so the first sync completes. (Fixes #1476)

### Ingest
* **Books Waiting at Startup:** Books already in the ingest folder when CWA starts (copied in while it was down, or left behind by a restart) are now imported straight away, instead of sitting there until something touched them.
* **Polling Mode Repeats:** With `NETWORK_SHARE_MODE`, `CWA_WATCH_MODE=poll` or Docker Desktop, any file left in the ingest folder was handed to the importer again every 5 seconds. Each file is now picked up once, and again only if it changes.
* **Date Added in Non-UTC Timezones:** On containers with a `TZ` other than UTC, v4.0.7 stored the local time as UTC in a new book's "date added", so fresh imports could sort below books added earlier the same day. Imports now record the real UTC time. The OPDS feed's "updated" time had the same mix-up and is fixed too. (Fixes #1563)

### Duplicates
* **Bulk Delete & Merge Freeze:** Deleting or merging many books from the Duplicate Manager froze the whole web UI until it finished, because the duplicate list was rebuilt after every single book. It's now rebuilt once per operation. (Thanks to @cd-dr, who found this in PR #1095)

### Editing
* **Custom Columns:** Saving a book with custom columns no longer fails with a 500 error when the database reconnects mid-save (e.g. while a book is being imported). (Fixes #1536)

### KOReader Sync
* **Checksum Errors:** With KOReader sync turned off, downloads, imports, the cover enforcer and the EPUB fixer no longer try to store KOReader checksums, which filled the logs with "no such table: book_format_checksums" errors. (Fixes #1086, #1183)

## 🚀 Improvements
* **Much Faster Deletes on Large Libraries:** Deleting a book, or removing an author, tag, series, language or publisher from one, no longer loads every other book that uses it (for a language, that was the whole library). On a 2,000-book library, deleting 30 books from the Duplicate Manager went from 16 seconds, with the web UI frozen the whole time, to under 1.5 seconds.
* **Less Background Load:** Open pages no longer ask the server for the duplicate status every 2.5 seconds. It's checked when a page loads, when you come back to the tab and every few minutes, and only polled continuously while a duplicate refresh is running. (Fixes #1288)
* **Background Services Stop Cleanly:** The ingest service and metadata change detector now stop and restart properly. The ingest service ignored stop requests, and each restart of the metadata change detector left an extra watcher running, so metadata changes could be processed more than once.
* **Healthcheck:** The Docker healthcheck now gives up on its own after a couple of seconds, so a hung web server is reported as unhealthy cleanly instead of leaving connections open. (From PR #1335)
* **Book Loading:** The edit page now loads a book's authors, tags, formats, identifiers and custom columns with a few small queries instead of one large combined one.

## 🔧 Technical & CI
* **Tests:** The ingest service tests run in CI again, with new coverage for the startup import, the polling watcher, KOReader checksum handling, custom column loading, bulk deletes and the healthcheck.
* **KOReader Setting Check:** Checking whether KOReader sync is enabled now takes a single database query instead of re-checking the whole CWA database schema on every download and sync request.

---

# Thanks to our Contributors! 🙏

- **[@cd-dr](https://github.com/cd-dr)** — Found the Duplicate Manager bulk delete freeze (#1095)
- **[@I-Would-Like-To-Report-A-Bug-Please](https://github.com/I-Would-Like-To-Report-A-Bug-Please)** — Healthcheck time limits (#1335)
- **[@mjz1](https://github.com/mjz1)** — Tracked down the Kobo first-sync failure and tested the fix on a factory-reset device (#1476)
- **[@captain-marlow](https://github.com/captain-marlow)** — Diagnosed the custom column save error (#1536)
- **[@ghepting](https://github.com/ghepting)** — Pinned down the "date added" timezone bug, with the fix (#1563)
- **[@FabulousSpaceCat](https://github.com/FabulousSpaceCat)**, **[@Bugg6](https://github.com/Bugg6)** and **[@blurrycontour](https://github.com/blurrycontour)** — Reported the checksum errors and the constant duplicate status polling (#1086, #1183, #1288)

---

# Supporting the Project ❤️

CWA is and always will be free and open source. If it makes your library life easier and you're able to support development, contributions go directly to:
- Testing hardware (ereader devices & tablets etc.)
- Development tools and infrastructure
- Coffee ☕ (lots of coffee)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/crocodilestick)
