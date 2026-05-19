# Calibre-Web-NextGen

A bug-fix build of [Calibre-Web-Automated](https://github.com/crocodilestick/Calibre-Web-Automated) (CWA). Same data layout, same configuration, same UI. The differences are listed in [`CHANGES-vs-upstream.md`](CHANGES-vs-upstream.md) and per release on the [Releases page](https://github.com/new-usemame/Calibre-Web-NextGen/releases).

Built on **[Calibre-Web-Automated](https://github.com/crocodilestick/Calibre-Web-Automated)** by [@crocodilestick](https://github.com/crocodilestick), which is built on **[Calibre-Web](https://github.com/janeczku/calibre-web)** by [@janeczku](https://github.com/janeczku) and contributors, which is built on **[Calibre](https://github.com/kovidgoyal/calibre)** by [@kovidgoyal](https://github.com/kovidgoyal). Original PR authors are credited by handle on every backport — see full [Credits](#credits) at the bottom.

[![Latest release](https://img.shields.io/github/v/release/new-usemame/Calibre-Web-NextGen)](https://github.com/new-usemame/Calibre-Web-NextGen/releases/latest)
[![Container](https://img.shields.io/badge/ghcr.io-calibre--web--nextgen-blue?logo=docker)](https://github.com/new-usemame/Calibre-Web-NextGen/pkgs/container/calibre-web-nextgen)
[![Open issues](https://img.shields.io/github/issues/new-usemame/Calibre-Web-NextGen)](https://github.com/new-usemame/Calibre-Web-NextGen/issues)

---

## Switch from upstream CWA

```diff
- image: crocodilestick/calibre-web-automated:latest
+ image: ghcr.io/new-usemame/calibre-web-nextgen:latest
```

```bash
docker compose pull && docker compose up -d
```

Library, settings, users, OAuth tokens, and KOReader sync state are preserved. Switching back is the reverse one-line change.

- **Bug?** [File it here.](https://github.com/new-usemame/Calibre-Web-NextGen/issues/new?template=bug_report.md)
- **Feature idea?** [Open a request.](https://github.com/new-usemame/Calibre-Web-NextGen/issues/new?template=feature_request.md) Anything goes, no checklist required — even half-formed ideas are welcome and help prioritize what to look at next.
- **New here?** See [Quick start](#quick-start) below.

---

## Table of contents

- [Why this fork exists](#why-this-fork-exists)
- [What's included](#whats-included)
- [Quick start](#quick-start)
- [Full Docker Compose setup](#full-docker-compose-setup)
- [First run](#first-run)
- [Migrating](#migrating)
  - [From upstream CWA](#from-upstream-cwa)
  - [From stock Calibre-Web](#from-stock-calibre-web)
- [Common configurations](#common-configurations)
  - [Network shares (NFS, SMB, ZFS)](#network-shares-nfs-smb-zfs)
  - [Reverse proxy / Cloudflare Tunnel](#reverse-proxy--cloudflare-tunnel)
  - [Hardcover metadata provider](#hardcover-metadata-provider)
  - [KOReader sync](#koreader-sync)
- [Troubleshooting](#troubleshooting)
- [Differences from upstream](#differences-from-upstream)
- [Contributing](#contributing)
- [Credits](#credits)

---

## Why this fork exists

CWA has an open PR queue with community-submitted bug fixes that aren't in the latest published image. This build picks the safe ones, ships them in regular releases, and adds fresh fixes for high-impact bugs that don't have an upstream PR yet. Scope is bug fixes; feature work is out of scope.

The data format and configuration are byte-compatible with upstream, so swapping images is reversible and migrations aren't needed in either direction.

---

## What's included

Everything CWA has, plus the patches in [`CHANGES-vs-upstream.md`](CHANGES-vs-upstream.md). A representative slice of fixes that are in this build but not in `crocodilestick/calibre-web-automated:latest`:

- Cover saves from Hardcover, Google Books, iTunes, and Open Library (was returning "not a valid image" since 4.0.6).
- Metadata search and the book-delete button on Safari.
- Generate Kobo Auth Token (was returning a blank page).
- Kobo bookmark sync no longer crashes when the client omits `Location`.
- Auth check added to 14 admin routes (`cwa_logs`, `convert`, `epub_fixer`, and others) that previously didn't require admin.
- Cover-enforcer shell-injection on filenames containing quotes.
- Reverse proxy: user-profile saves honor the path prefix.
- Docker healthcheck follows the `/ → /login` 302 instead of failing on it.
- `.cbr` and `.cbz` use IANA-registered mimetypes in OPDS feeds.
- Higher-resolution covers from Google Books, Amazon, and an iTunes-backed fallback for high-DPI e-readers (Libra Color, etc.).
- Translation PRs merged: ja, fr, cs, hu, zh_Hans, zh_Hant, and others.

---

## Quick start

Requirements: Docker and Docker Compose.

1. Make a folder for your library:

   ```bash
   mkdir -p ~/calibre-web/{config,library,ingest}
   cd ~/calibre-web
   ```

2. Save this as `docker-compose.yml`:

   ```yaml
   services:
     calibre-web:
       image: ghcr.io/new-usemame/calibre-web-nextgen:latest
       container_name: calibre-web
       environment:
         - PUID=1000
         - PGID=1000
         - TZ=America/New_York   # change to your timezone
       volumes:
         - ./config:/config            # settings, user db, logs
         - ./library:/calibre-library  # books live here
         - ./ingest:/cwa-book-ingest   # drop new books here to import
       ports:
         - 8083:8083
       restart: unless-stopped
   ```

3. Start it:

   ```bash
   docker compose up -d
   ```

4. Open `http://localhost:8083`, log in with `admin` / `admin123`, change the password.

Drop an `.epub` into `./ingest/` and it will appear in your library within a few seconds.

> Files in your library and ingest folders should be owned by your `PUID:PGID` user (1000 by default), not root. If you've copied books in as root, run once: `sudo chown -R 1000:1000 ~/calibre-web`.

---

## Full Docker Compose setup

A more complete compose file, with each option documented:

```yaml
services:
  calibre-web:
    image: ghcr.io/new-usemame/calibre-web-nextgen:latest
    container_name: calibre-web
    environment:
      # Match your host user/group so files in your library
      # are writable from both the container and the host.
      - PUID=1000
      - PGID=1000

      # https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
      - TZ=America/New_York

      # Override the in-container port if you need to.
      # If set below 1024, also uncomment cap_add below.
      - CWA_PORT_OVERRIDE=8083

      # Set this if your /config or /calibre-library volumes are
      # on an NFS or SMB share. See "Network shares" below.
      - NETWORK_SHARE_MODE=false

      # If you sit behind multiple proxies (e.g. Cloudflare Tunnel
      # then nginx then CWA), set this to the total proxy count so
      # session protection sees the right client IP. Default 1.
      - TRUSTED_PROXY_COUNT=1

      # Optional: Hardcover API token for the Hardcover metadata
      # provider. Free; sign up at https://hardcover.app/account/api
      # - HARDCOVER_TOKEN=eyJhbGciOiJIUzI1NiI...

    volumes:
      # Settings, user database, logs. Empty folder for new installs;
      # for existing CWA users, point at your existing /config.
      - /path/to/config:/config

      # Your Calibre library. New install? Use an empty folder and
      # CWA will set one up. Existing user? Point at the folder
      # containing your metadata.db.
      - /path/to/library:/calibre-library

      # Drop new books here to import them. WARNING: files in this
      # folder are DELETED after processing. Don't point this at a
      # folder you also use as long-term storage.
      - /path/to/ingest:/cwa-book-ingest

      # Optional: bind your existing Calibre plugins folder
      # - /path/to/calibre-plugins:/config/.config/calibre/plugins

    ports:
      - 8083:8083

    # Uncomment if CWA_PORT_OVERRIDE is below 1024.
    # cap_add:
    #   - NET_BIND_SERVICE

    restart: unless-stopped
```

### What goes in each volume

| Volume | What it is | Notes |
|---|---|---|
| `/config` | App settings, user accounts, OAuth tokens, KOReader sync state, logs | Empty folder for new installs. Carries over from CWA verbatim. |
| `/calibre-library` | Books and Calibre's `metadata.db` | If empty, CWA creates a fresh library. If multiple `metadata.db` files exist inside, CWA picks the largest. |
| `/cwa-book-ingest` | Drop zone for new books | Files here are **deleted** after processing. Don't park books here long-term. |

> Don't nest the binds. All three should be separate top-level folders. Putting `ingest` inside `library` produces recursive ingest behavior.

---

## First run

1. Open the UI at `http://your-host:8083`.
2. Log in with `admin` / `admin123`.
3. Change the admin password (Profile → Account).
4. Go to Admin → Edit Basic Configuration → Feature Configuration and enable **Allow Uploads**. Without this, the metadata-fetch and cover-from-URL features can't write to your library.
5. Drop a book into your ingest folder. It should appear in the library within a few seconds.

The Admin → Settings panel has many optional toggles (auto-convert formats, automatic backups, EPUB fixer, KOReader sync, OAuth, etc.). The [upstream wiki](https://github.com/crocodilestick/Calibre-Web-Automated/wiki) is the source of truth for those; this fork doesn't change them.

---

## Migrating

### From upstream CWA

One line. Stop the container, swap the image, start it.

```diff
- image: crocodilestick/calibre-web-automated:latest
+ image: ghcr.io/new-usemame/calibre-web-nextgen:latest
```

```bash
docker compose pull && docker compose up -d
```

Settings, users, OAuth tokens, and KOReader sync state are preserved. The data format is identical, so reverting is the reverse one-line change.

### From stock Calibre-Web

1. Stop your existing Calibre-Web container.
2. In the new compose file, point `/config` at the same `/config` folder you used for Calibre-Web.
3. Whatever you bound as `/books` in Calibre-Web should be bound as `/calibre-library` here.
4. Pick an empty folder for `/cwa-book-ingest` (it's CWA-specific; no equivalent in stock CW).
5. Start the container.

Users, settings, and shelves carry over. The first launch takes a few extra seconds while CWA registers itself with the existing app database.

---

## Common configurations

### Network shares (NFS, SMB, ZFS)

If `/config` or `/calibre-library` lives on a network share, set:

```yaml
- NETWORK_SHARE_MODE=true
```

This:
- Disables SQLite WAL mode (NFS and SMB don't reliably support it; without this you'll see "database is locked").
- Skips the recursive ownership-fix at startup (slow on NFS, often fails on SMB).
- Switches the ingest watcher from inotify to polling (network-FS inotify events are unreliable).

Tested and supported. Ingest is a few seconds slower; everything else behaves the same.

> If files end up owned by root after a copy: this build chowns files back to your `PUID:PGID` after each metadata-change cycle, but if you've copied files in as root before upgrading, run once: `docker exec calibre-web chown -R abc:abc /calibre-library` (replace `abc` if you've customized the user).

### Reverse proxy / Cloudflare Tunnel

Behind multiple proxies (e.g. Cloudflare Tunnel then nginx then CWA), set the proxy count:

```yaml
- TRUSTED_PROXY_COUNT=2
```

Without this, CWA may see different client IPs across requests and trigger Session Protection warnings, forcing re-login on every page load. Default is `1`.

### Hardcover metadata provider

[Hardcover](https://hardcover.app/) is a free metadata provider. To enable it:

1. Sign up at https://hardcover.app and grab an API token at https://hardcover.app/account/api.
2. Add to your compose env:

   ```yaml
   - HARDCOVER_TOKEN=eyJhbGciOiJIUzI1NiI...
   ```

   Or paste it into Admin → Edit Basic Configuration → Hardcover API Key in the UI.
3. Restart the container.

Hardcover then appears in the Fetch Metadata modal.

### KOReader sync

CWA has built-in KOReader progress sync; no separate kosync server is needed.

1. In KOReader, install the CWA plugin: visit `http://your-cwa:8083/kosync` for download and install instructions.
2. Point the plugin at `http://your-cwa:8083` and log in with your CWA username and password.
3. Read on any device. Progress syncs back to CWA, and from there to Kobo if Kobo sync is enabled.

---

## Troubleshooting

### "Cover-file is not a valid image file, or could not be stored"

Fixed in v4.0.13 and later. If you're still seeing it after upgrading, you probably have `root:root`-owned book directories from a pre-fix install. Run once:

```bash
docker exec calibre-web chown -R abc:abc /calibre-library
```

### "Generate Kobo Auth Token" returns a blank page

Fixed in v4.0.14 and later. Upgrade the image.

### "Database is locked" / app frozen

If your library is on a network share, set `NETWORK_SHARE_MODE=true` (see above). On local disk, this usually means a previous container shutdown was unclean: restart Docker, then the container.

### Session Protection warnings, forced re-login on every page

Set `TRUSTED_PROXY_COUNT` to match your proxy depth. See [Reverse proxy](#reverse-proxy--cloudflare-tunnel).

### Books in `/cwa-book-ingest` aren't picked up

Three common causes:

1. Files owned by root. Make sure ingest files are owned by your `PUID:PGID` user.
2. Watcher missed them. Click the **Refresh Library** button on the navbar; it does a one-shot scan.
3. Format isn't allowed. Check Admin → CWA Settings → Ingest for your allowed formats.

### Default login isn't working

The defaults are `admin` / `admin123` (lowercase). If you've already changed the password and forgotten it: stop the container, delete `config/app.db`, and restart. This resets the database. User accounts are lost; the library itself is untouched.

### Something else

Check the [issue tracker](https://github.com/new-usemame/Calibre-Web-NextGen/issues) or [open a new issue](https://github.com/new-usemame/Calibre-Web-NextGen/issues/new). Useful information:

- The version: `docker exec calibre-web cat /app/CWA_STABLE_RELEASE`
- Recent logs: `docker logs calibre-web 2>&1 | tail -50`
- What you did and what you expected to happen

---

## Differences from upstream

| Behavior | Upstream CWA `:latest` | This build |
|---|---|---|
| Cover saves from Hardcover/Google Books/iTunes/Open Library | Returns "not a valid image" | Saves and persists |
| Generate Kobo Auth Token | Blank page | Works |
| Safari metadata search | Silent 400 | Works |
| Safari book-delete button | Broken since the Feb-4 commit | Works |
| Kobo bookmark sync with missing `Location` | Crashes | Tolerates |
| `/kobo_auth/generate_auth_token` IDOR | Open (any user can mint another user's token) | Closed |
| Reverse-proxy user-profile updates | Drops path prefix | Honors `getPath()` |
| Docker healthcheck on `/ → /login` 302 | Trips on `curl -f` | Uses dedicated endpoint with service health checks |
| `.cbr` / `.cbz` OPDS mimetypes | Non-IANA | IANA-compliant |
| Cover resolution on high-DPI readers | Often 290×475 (Hardcover thumbnail) | 1000×1500+ via booster |
| Admin routes (`cwa_logs`, `convert`, `epub_fixer`, …) | 14 unauthenticated | All require admin |
| Translations: ja, fr, cs, hu, zh_Hans, zh_Hant | Open in PRs | Merged |

Backports are conservative. Anything that touches auth, schema, or dependencies gets a manual review before merging.

---

## Translations

The interface ships with the locales below. Completion is auto-refreshed on every push to `main` by [`scripts/generate_translation_status.py`](scripts/generate_translation_status.py); to contribute a translation, edit the `.po` file under [`cps/translations/`](cps/translations/) for your language and open a PR.

<!-- TRANSLATION_STATUS_START -->
| Language | Completion | Strings | Fuzzy |
|---|---|---:|---:|
| English (source) | 100% | source | — |
| Hungarian (`hu`) | `███████████████████░` 93% | 1590/1710 | 69 |
| French (`fr`) | `██████████████████░░` 90% | 1532/1710 | 82 |
| Japanese (`ja`) | `██████████████████░░` 90% | 1532/1710 | 208 |
| Spanish (`es`) | `██████████████████░░` 90% | 1531/1710 | 249 |
| German (`de`) | `██████████████████░░` 89% | 1520/1710 | 93 |
| Slovenian (`sl`) | `██████████████████░░` 88% | 1509/1710 | 291 |
| Russian (`ru`) | `███████████████░░░░░` 74% | 1257/1710 | 441 |
| Dutch (`nl`) | `██████████████░░░░░░` 72% | 1238/1710 | 265 |
| Italian (`it`) | `██████████████░░░░░░` 70% | 1200/1710 | 241 |
| Polish (`pl`) | `██████████████░░░░░░` 70% | 1200/1710 | 246 |
| Portuguese (Brazil) (`pt_BR`) | `██████████████░░░░░░` 70% | 1200/1710 | 374 |
| Korean (`ko`) | `██████████████░░░░░░` 70% | 1194/1710 | 241 |
| Chinese (Simplified, China) (`zh_Hans_CN`) | `██████████████░░░░░░` 68% | 1166/1710 | 325 |
| Arabic (`ar`) | `████████████░░░░░░░░` 62% | 1055/1710 | 262 |
| Slovak (`sk`) | `████████████░░░░░░░░` 61% | 1044/1710 | 292 |
| Portuguese (`pt`) | `████████████░░░░░░░░` 61% | 1043/1710 | 340 |
| Indonesian (`id`) | `████████████░░░░░░░░` 60% | 1023/1710 | 342 |
| Galician (`gl`) | `████████████░░░░░░░░` 60% | 1021/1710 | 341 |
| Chinese (Traditional, Taiwan) (`zh_Hant_TW`) | `███████████░░░░░░░░░` 57% | 980/1710 | 360 |
| Swedish (`sv`) | `███████████░░░░░░░░░` 56% | 957/1710 | 370 |
| Greek (`el`) | `██████████░░░░░░░░░░` 52% | 893/1710 | 384 |
| Czech (`cs`) | `██████████░░░░░░░░░░` 51% | 873/1710 | 393 |
| Norwegian (`no`) | `██████████░░░░░░░░░░` 50% | 858/1710 | 427 |
| Vietnamese (`vi`) | `█████████░░░░░░░░░░░` 46% | 778/1710 | 354 |
| Finnish (`fi`) | `█████████░░░░░░░░░░░` 43% | 740/1710 | 383 |
| Ukrainian (`uk`) | `████████░░░░░░░░░░░░` 39% | 674/1710 | 370 |
| Turkish (`tr`) | `████████░░░░░░░░░░░░` 39% | 668/1710 | 378 |
| Khmer (`km`) | `██████░░░░░░░░░░░░░░` 32% | 550/1710 | 341 |
<!-- TRANSLATION_STATUS_END -->

---

## Contributing

- **Bug reports:** [open a bug issue](https://github.com/new-usemame/Calibre-Web-NextGen/issues/new?template=bug_report.md). Reproduction steps, version tag, and a `docker logs` snippet help a lot.
- **Feature requests:** [open a feature issue](https://github.com/new-usemame/Calibre-Web-NextGen/issues/new?template=feature_request.md). The bar is low — bug reports get prioritized for code work, but feature requests shape what gets looked at when the bug queue is quiet, and they help upstream see what users actually want. Don't worry about whether it's "in scope"; just file it.
- **Pull requests:** welcome. The merge bar is "doesn't break anything that currently works." Changes touching auth, schema, or dependencies get a closer review. Backports keep the original author's handle in the commit message.
- **CWA PR authors with stalled work upstream:** if you'd like your PR shipped here too, open an issue or send the PR our way.

Governance: [`GOVERNANCE.md`](GOVERNANCE.md). Contributing details: [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Credits

Built on:

- **Calibre-Web-Automated** ([@crocodilestick](https://github.com/crocodilestick) and contributors) — the core software this build is based on. Original PR authors are credited by handle in every backport commit.
- **Calibre-Web** ([@janeczku](https://github.com/janeczku) and contributors) — the web UI underneath CWA.
- **Calibre** ([@kovidgoyal](https://github.com/kovidgoyal)) — the library underneath all of it.

Every backported patch is credited to its original author by GitHub handle in the commit message and in [`CHANGES-vs-upstream.md`](CHANGES-vs-upstream.md). To support upstream's continued development, [@crocodilestick has a Ko-fi](https://ko-fi.com/crocodilestick).

---

*License: GPL-3.0-or-later. See [`LICENSE`](LICENSE).*
