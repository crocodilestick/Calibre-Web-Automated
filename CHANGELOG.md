# Changelog

All notable user-facing changes to Calibre-Web NextGen. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Docker tags:** `:latest` = newest stable release · `:dev` = every merge to main
(canary channel — what the maintainers run at home) · `:vX.Y.Z` = immutable pins
for rollback.

**Compatibility promise:** patch releases (`vX.Y.Z` → `vX.Y.Z+1`) are safe to
auto-update — no breaking config, database, or API changes without a `BREAKING`
callout at the top of the release notes.

Internal refactors, CI changes, and test-only work don't appear here — this file
is for things you can see or feel when running the app.

## [Unreleased]

### Fixed
- Kobo sync no longer fails behind reverse proxies with default buffer sizes
  (Synology DSM, stock nginx). The sync token header could exceed nginx's 4K
  default when Kobo store proxying was on; it's now compressed to roughly
  half the size, with older tokens still accepted — no device reconfiguration
  needed. If you added `proxy_buffer_size` overrides for this, they can stay
  (harmless) or go. (#331, reported by @Gusdezup)

### Added
- The book detail and edit pages now show the filename a book was imported
  with ("Imported as: …"). Ingest renames files to match their metadata —
  including wrong auto-matches — so the original name is the one stable
  reference for recognizing misidentified books while you fix their tags.
  Captured automatically for new imports from this version on. (#346,
  requested by @BakaPhoenix and @magdalar)

### Fixed
- Fixed a rare freeze where the whole app could lock up — pages never loading
  until the container was restarted — when a background task (thumbnail
  generation, metadata backup, duplicate scan…) hit the database at the same
  moment as a page load. Database access is now coordinated so the standoff
  can't happen.
- "Reload Metadata" now also reloads authors, tags, and series (with series
  number) from the book file — previously only title, description, publisher,
  publish date, and languages came through. Author changes also rename the
  book's folder and file to match, the same way editing in the web UI does.
  A file that's missing its author or tags fields leaves your existing data
  alone instead of wiping it. (#218, reported by @yodatak)

## [v4.0.156] – 2026-06-06

### Fixed
- **Magic Shelves marked for Kobo sync now actually reach your Kobo** — books
  deliver and the shelf appears as a collection on the device. Previously a
  global setting (off by default) silently swallowed the per-shelf "Enable Kobo
  sync" checkbox; if you'd ever ticked that checkbox, the upgrade enables the
  global setting for you automatically. The checkbox now also tells you when the
  global setting is off instead of silently doing nothing. (#359, reported with
  excellent diagnostics by @recruiterguy)

### Security
- `POST /duplicates/invalidate-cache` now requires authentication — previously
  it accepted unauthenticated requests on internet-facing deployments (limited
  impact: it could only force a duplicate-scan refresh). (#370, found and fixed
  by @8bitgentleman)

### Added
- A `:dev` docker channel: `ghcr.io/new-usemame/calibre-web-nextgen:dev` gets
  every merge as it lands — it's what we run at home. Versioned releases now
  batch to at most one per day, so release notifications get quieter.

## [v4.0.155] – 2026-06-06

### Fixed
- Kobo sync: after a Magic Shelf cache rebuild, the per-shelf delivery cursor
  could silently revert to a stale value, leaving newly-added low-numbered books
  undelivered until the next shelf change. (#368 follow-up)

## [v4.0.154] – 2026-06-06

### Fixed
- Kobo sync: adding a book to a Magic Shelf between syncs now reliably delivers
  it — the sync cursor detects the cache rebuild and re-walks the shelf. (#367
  follow-up)

## [v4.0.153] – 2026-06-06

### Fixed
- Kobo sync: Magic Shelves with more than 100 books no longer re-send the same
  first 100 books forever — delivery now pages through the whole shelf. (#366
  follow-up)

## [v4.0.152] – 2026-06-06

### Fixed
- Kobo sync: when more than 100 books were pending at once alongside a Magic
  Shelf refresh, some regular books could be skipped permanently. Nothing is
  dropped anymore. (#361 follow-up)

## [v4.0.151] – 2026-06-06

### Fixed
- Kobo sync: Magic Shelf delivery and cache refresh now work in
  sync-entire-library mode, not just "selected shelves only" mode. (#359)

## [v4.0.150] – 2026-06-05

### Changed
- Read/unread toggle on the book detail page now shows the action you're about
  to take (checkmark = "mark as read") instead of the current state, and the
  read badge uses a consistent checkmark icon everywhere. (#319)

## [v4.0.149] – 2026-06-05

### Added
- "Reload Metadata" button on the book detail page — re-reads title, author,
  and other metadata from the book file on disk after you've changed it
  externally (e.g. in Calibre desktop). (#218, requested by @yodatak)

## [v4.0.148] – 2026-06-05

### Fixed
- Sorting the Hidden Books page no longer dumps you into the unfiltered
  library. (#319, reported by @SethMilliken)

## [v4.0.147] – 2026-06-05

### Fixed
- Kobo sync: libraries with thousands of books imported in one batch (all
  sharing one timestamp) now sync completely — previously the device could loop
  on the same batch or skip the remainder. (#347, reported by @andree392)
- Kobo sync: first delivery pass for Magic Shelf membership. (#359)

---

Older releases: see the [GitHub releases page](https://github.com/new-usemame/Calibre-Web-NextGen/releases).
