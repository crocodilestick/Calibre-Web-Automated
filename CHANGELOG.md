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

## [v4.0.161] - 2026-06-12

### Fixed
- Hardcover progress sync no longer dies on books without a chosen edition.
  Reading on a KOReader/Kobo device synced progress to the library fine, but
  the push to Hardcover failed every time with `'NoneType' object has no
  attribute 'get'` — typically when the book's entry on Hardcover has no
  edition picked, or when Hardcover rejects a status change. The sync now
  handles those responses, logs Hardcover-side errors with a full traceback,
  and tells you when a book needs an edition selected on Hardcover for
  page-based progress. (#433, reported by @SpookyUSAF)
- Search now opens on phones. Tapping the search icon in the top bar did
  nothing on mobile (most visibly in Safari on iOS) — the icon was covered by
  the header bar, so the tap never reached the search box, and the box never
  appeared. Tapping the icon now opens the search field as expected. Desktop is
  unchanged. (#425, reported by @getthething)
- On phones, the book detail page no longer shows an oversized, off-center
  cover. The cover used to render wider than its column and sit left of center
  (on the caliBlur theme), pushing the description far down the page. It now
  caps to its column and centers, and the title/spacing on narrow screens are
  tightened so the description sits closer to the top. (#288, reported with a
  screenshot by @iroQuai)

## [v4.0.160] - 2026-06-10

### Security
- Closed a cross-site scripting hole in the comic (CBR/CBZ) reader. The reader
  ran your saved page bookmark through JavaScript's `eval()`, so a bookmark
  value that contained code — which any logged-in account could store for a
  comic — would execute when the reader page opened. Bookmarks are now read
  strictly as a page number.

### Fixed
- The metadata search dialog now lists providers in the order you set under
  Settings, instead of alphabetically. Whatever provider order you configure
  for automatic metadata fetching is now also the order the search popup shows
  and ranks results in, so your preferred source appears first.
- Adding several books at once to a Kobo-synced shelf now syncs them to
  Hardcover, just like adding one book does. Before, only single adds reached
  Hardcover — "add all" from search results, multi-select adds, and
  add-series-to-shelf silently skipped it. The sync now runs as a background
  task (visible under Tasks, cancellable), so adding a long series doesn't
  hold the page open on an external service — and single adds respond faster
  for the same reason.
- The experimental "SQL" duplicate-scan mode no longer produces different (and
  sometimes wrong) results than the default mode. It grouped co-authored books
  into multiple duplicate groups at once and skipped a title normalization the
  default scan applies, so the same library showed different duplicates
  depending on an admin toggle. That mode now uses the same single grouping
  engine as everything else, keeping SQL only as the fast candidate prefilter.
- Books you've hidden no longer show up in your duplicate scan. The Duplicates
  page respected your language, tag, and archive filters but not your hidden
  list, so hidden books reappeared there and could even be swept into
  duplicate auto-resolution.
- Duplicate detection now catches copies whose titles differ only in unicode
  form or spacing. A "Café" imported from a Mac (decomposed accents) and a
  "Café" typed by hand, or "The  Book" with a double space, counted as
  different books and never showed up as duplicates. All duplicate matching
  now normalizes accents and whitespace first; the duplicate index rebuilds
  itself on first scan after the update, and your existing dismissals carry
  over automatically.
- Dismissed duplicate groups stay dismissed. Adding another copy of a book or
  editing its title changed the group's internal label, so groups you had
  dismissed popped back onto the Duplicates page (and could re-enter
  auto-resolve). Dismissals are now tied to the group's stable identity and
  survive new ingests and metadata edits; existing dismissals are upgraded
  automatically the first time they match. Two different groups that happened
  to share a display title also no longer share one dismissal.
- Merging duplicate books can no longer overwrite one of the kept book's
  files. If a file with the merge target's name was already on disk (from an
  earlier partial failure or a manual edit), the merge silently copied over
  it; it now refuses that group with a clear error and leaves every file
  untouched. A merge that fails partway also cleans up after itself instead
  of leaving stray copied files or phantom format entries behind.
- Finishing a book in KOReader now marks it read on the website when you use a
  custom "read" column. If your admin set a Calibre custom column as the read
  marker (a stock option under Feature Configuration), KOReader completions
  only wrote the built-in read list, so the book page checkmark stayed empty.
  The sync now also sets the custom column — and only ever sets it: re-opening
  a finished book never silently un-reads it.
- Automatic metadata fetch now actually downloads covers. The "update cover"
  option existed but did nothing — books imported with auto-fetch on never got
  their cover updated. Covers now download through the same safe path as the
  manual editor (size limits, image checks, server-side request protections),
  respect the per-book cover lock, and in "smart application" mode only fill in
  a missing cover, never replace one you have. (#404, confirmed by @beanscg)
- Downloading a cover by URL (manual editor and auto-fetch alike) no longer
  destroys the existing cover when the server misbehaves: a redirect stub or an
  error page served with an image content-type used to get saved as the cover
  file. The download now follows redirects properly (cover CDNs like Open
  Library's redirect every image) and verifies the bytes are really an image
  before anything is overwritten.
- Shelf reorder: the giant white sort icon (a down arrow with lines) that sat on
  top of the first covers on wide screens is gone. It was a leftover decoration
  from the old list-style reorder page — the theme drew it in what used to be
  empty space, and the new cover grid now fills that space. The wider your
  browser window, the bigger the icon got. (#320, reported with screenshots by
  @SpookyUSAF — the covers themselves were already the right size; this was the
  last piece.)
- Resolving duplicate books no longer loses your highlights, notes, reading
  progress, or shelf placement. When duplicates were merged or resolved, only
  the book files moved to the kept copy — anything you'd done on the removed
  copy (annotations, read status, Kobo reading position, shelf membership)
  silently disappeared. All of it now follows the kept book, whichever
  resolve strategy you use. Deleting a book and deleting a user also clean up
  everything that belongs to them now (deleted accounts previously left their
  annotations and annotation-backup files behind).
- Deleting a book no longer risks leaving a broken "ghost" entry if something
  fails partway through. Previously the book's files were removed before the
  library database was updated, so an error in between could leave an entry that
  still shows in your library but won't open. The database is now updated first
  and the files removed last, so a failure leaves the book fully intact. (Mirrors
  the same data-safety fix already made for duplicate resolution.)
- Shelf reorder covers: the stylesheet that keeps the covers at the normal
  thumbnail size now loads from the page head, alongside every other stylesheet,
  instead of from the page body. A body-loaded stylesheet link can be dropped by
  some reverse proxies, which left the covers oversized on an otherwise-correct
  page — the case @SpookyUSAF kept hitting on caliBlur even after v4.0.158/159.
  (#320 follow-up, reported by @SpookyUSAF)
- Automatic metadata fetch (the admin "auto metadata fetch" option, off by
  default) no longer overwrites a book's correct author, ISBN, series,
  publication date or rating with a wrong match's. Previously, with auto-fetch
  on, importing a book could silently replace good metadata with a random
  foreign edition's — and the "smart application" mode that's meant to only fill
  gaps didn't actually protect those fields. Now it prefers the edition whose
  ISBN matches your book, and smart mode never overwrites a value you already
  have (it only fills what's missing). Open Library is also now part of the
  default provider order.

## [v4.0.159] – 2026-06-09

### Added
- You can now add books to a shelf right from the shelf page. A new **Add Books**
  button opens a searchable picker — type to find books in your library, tick the
  ones you want, and add them all at once. Books already on the shelf show as
  "Already on this shelf" so you can't add duplicates, and it works on phone and
  desktop. Especially handy for filling a brand-new empty shelf.

### Fixed
- Resolving duplicate books no longer risks leaving a book in a broken,
  half-deleted state if something fails partway through. Previously the files
  were removed before the library database was updated, so an error in between
  could leave a "ghost" book that still showed in your library but wouldn't open.
  The database is now updated first and the files removed last, so a failure
  leaves the book fully intact and the duplicate is simply re-resolved next time.
- Resolving duplicate books is now safe even if a duplicate scan happens to run
  at the same moment. Before, the two could collide — deleting the same book
  twice, leaving a duplicate only half-removed, or throwing a brief error that
  left the library inconsistent. Now only one resolution runs at a time and the
  other steps aside, so your books stay intact.
- Duplicate detection no longer treats books that are *missing* a title or
  author as duplicates of each other. Two unrelated books that both happen to
  have no title (or no author) used to collapse together as a "duplicate" — and
  could then be offered up for deletion. They're now kept separate; only books
  with real matching metadata are grouped.
- Resolving duplicate books is more reliable: the resolver no longer closes a
  shared database connection mid-operation, which could cause errors or a
  half-finished cleanup when the library was being used at the same time.
- The shelf reorder screen's cover-size fix now reaches more setups: the covers
  were still showing oversized for some users on v4.0.158 (e.g. behind certain
  reverse proxies). The styling moved out of the page into a regular stylesheet
  and now sizes covers on its own, so they stay at the normal thumbnail size
  regardless of theme or proxy. (#320 follow-up, reported by @SpookyUSAF)
- On phones, the menu (hamburger) button is now on the **left**, the same side
  the navigation drawer slides out from — so the button and the menu it opens
  line up. Tapping it opens the menu; tapping outside still closes it.
- On phones, the select and settings buttons above a book list now sit on the
  right (matching the desktop layout), so tapping the gear opens its menu on
  screen instead of off the left edge where it was getting cut off.
- Pages no longer occasionally fall back to the old, deprecated light theme —
  including error pages. That fallback could happen when a request hit a snag
  while loading, and it was the underlying cause of display glitches like the
  oversized shelf-reorder covers (#320). The dark theme is now enforced even on
  error pages and requests that are interrupted before they finish loading.

## [v4.0.158] – 2026-06-08

### Fixed
- The shelf reorder screen now shows covers at the normal thumbnail size
  instead of blown-up "large icon" size, and the Back button lines up under
  the covers with proper spacing above it. (#320 follow-up, reported by
  @droM4X and @SpookyUSAF)

## [v4.0.157] – 2026-06-07

### Added
- You can now add a whole series to a shelf in one click: series pages have an
  "Add Series to Shelf" button that adds every book in series order, skipping
  ones already on the shelf. (#334, requested by @Glennza1962)
- The book detail and edit pages now show the filename a book was imported
  with ("Imported as: …"). Ingest renames files to match their metadata —
  including wrong auto-matches — so the original name is the one stable
  reference for recognizing misidentified books while you fix their tags.
  Captured automatically for new imports from this version on. (#346,
  requested by @BakaPhoenix and @magdalar)

### Changed
- Rearranging a shelf now happens in the same cover grid as the regular shelf
  view — drag a cover where it belongs, on desktop or phone (long-press to
  lift), or move it with the keyboard arrows. The order saves by itself on
  every change; the old cramped list and its Save button are gone. A shelf
  that changed in another tab no longer breaks saving. (#320, requested by
  @SpookyUSAF with design input from @droM4X)
- Series pages now list books in series order by default (1, 2, 3…) instead of
  newest-first — matching what the OPDS feed always did. Choosing a different
  sort still sticks for next time.
- On phones, the menu button now looks like one: a standard hamburger icon
  replaces the round profile-head glyph, which nobody recognized as the way
  to open the sidebar. Same spot (top right), same tap target; your profile
  options are inside the menu it opens, where they always were.

### Fixed
- On phones, opening the sidebar no longer dead-ends the page: tapping
  anywhere outside the menu now closes it (it used to do nothing, and the
  menu button itself became untappable behind the overlay — the page was
  stuck until a reload).
- Fixed a rare freeze where the whole app could lock up — pages never loading
  until the container was restarted — when a background task (thumbnail
  generation, metadata backup, duplicate scan…) hit the database at the same
  moment as a page load. Database access is now coordinated so the standoff
  can't happen.
- Kobo sync no longer fails behind reverse proxies with default buffer sizes
  (Synology DSM, stock nginx). The sync token header could exceed nginx's 4K
  default when Kobo store proxying was on; it's now compressed to roughly
  half the size, with older tokens still accepted — no device reconfiguration
  needed. If you added `proxy_buffer_size` overrides for this, they can stay
  (harmless) or go. (#331, reported by @Gusdezup)
- "Reload Metadata" now also reloads authors, tags, and series (with series
  number) from the book file — previously only title, description, publisher,
  publish date, and languages came through. Author changes also rename the
  book's folder and file to match, the same way editing in the web UI does.
  A file that's missing its author or tags fields leaves your existing data
  alone instead of wiping it. (#218, reported by @yodatak)
- Adding a single book to a Kobo-synced shelf without JavaScript now syncs it
  to Hardcover the same way the normal button does.
- Bulk shelf adds no longer claim books were added when a database error
  actually rolled everything back.

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
