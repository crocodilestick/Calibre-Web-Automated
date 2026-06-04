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
- [Pair with Shelfmark](#pair-with-shelfmark)
- [Common configurations](#common-configurations)
  - [Network shares (NFS, SMB, ZFS)](#network-shares-nfs-smb-zfs)
  - [Reverse proxy / Cloudflare Tunnel](#reverse-proxy--cloudflare-tunnel)
  - [Hardcover metadata provider](#hardcover-metadata-provider)
  - [KOReader sync](#koreader-sync)
  - [Kobo sync](#kobo-sync)
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

## Pair with Shelfmark

[Shelfmark](https://github.com/calibrain/shelfmark) by @calibrain is a self-hosted book search and request interface. Users search across torrent, usenet, IRC, and direct sources from a single UI; Shelfmark hands the download to your client of choice and drops the finished file straight into the CWA ingest folder, where this build picks it up automatically. Multi-user requests are built in, so you can share an instance with household readers and approve their picks.

Add it alongside `calibre-web` in the same compose file:

```yaml
  shelfmark:
    image: ghcr.io/calibrain/shelfmark:latest
    container_name: shelfmark
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
      - SEARCH_MODE=universal

      # Point Shelfmark at CWA's app.db (read-only mount below) so users
      # log in to Shelfmark with their existing CWA credentials.
      - CWA_DB_PATH=/auth/cw-config/app.db

      # Optional: shows a "Library" button in Shelfmark's header that
      # links back to this CWA instance.
      - CALIBRE_WEB_URL=http://your-host:8083

    volumes:
      - /path/to/shelfmark-config:/config

      # Read-only mount of your CWA config dir for the auth integration.
      - /path/to/cwa-config:/auth/cw-config:ro

      # Shelfmark's destination folder = CWA's ingest folder.
      # Downloads land here and this build ingests them on the next watch tick.
      - /path/to/cwa-ingest:/books

      # If you use a torrent or usenet client, mount its downloads dir
      # at the same path you mounted in the client itself, so Shelfmark
      # can locate the completed file.
      - /path/to/downloads:/downloads

    ports:
      - 8084:8084
    restart: unless-stopped
```

After Shelfmark starts, open it and pick **Settings → Security → Authentication Method → Calibre-Web Database**, then **Sync from Calibre-Web** to import users. The [Shelfmark docs](https://github.com/calibrain/shelfmark#readme) cover Prowlarr, qBittorrent, SABnzbd, and IRC source setup.

> Shelfmark went into maintenance-only status in May 2026; the v1.3.0 build is stable and the integration with CWA is settled, but new feature work upstream has paused. If you want to pin for reproducibility, use `ghcr.io/calibrain/shelfmark:v1.3.0` instead of `:latest`.

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

**Matching filenames across devices (OPDS downloads).** If you download books to KOReader over OPDS and sync progress by filename across several e-readers, turn on **Use server filenames** in KOReader's OPDS catalog settings (the checkbox when you add or edit the catalog). By default KOReader names a downloaded file `Author - Title.epub` from the catalog entry, which differs from the on-disk library name `Title - Author.epub` and forces a manual rename. CWA already sends the library name in the download's `Content-Disposition` header; with **Use server filenames** on, KOReader uses that name, so the file matches your library and your other devices without renaming.

### Kobo sync

Read your CWA library on a Kobo e-reader, with reading progress syncing both ways. Sync runs against your own server, so your library never leaves your network.

1. In Admin → Edit Basic Configuration, turn on **Enable Kobo sync**.
2. Open your user page (Admin → Users → your user, or your own profile) and click **Create/View** next to **Kobo Sync Token**. The dialog shows the exact `api_endpoint=` line for your account.
3. Plug the Kobo into a computer over USB and open `.kobo/Kobo/Kobo eReader.conf` in a text editor. Add or replace the `api_endpoint=` line with the one from the dialog, save, and eject the device cleanly.
4. On the Kobo, sync. Books on your Kobo Sync shelves appear on the device, and progress flows back to CWA.

To confirm the device is reaching your server, watch the logs while you sync — you should see requests to `/kobo/<token>/v1/...`:

```bash
docker logs -f calibre-web 2>&1 | grep /kobo/
```

**Behind a reverse proxy (nginx, Nginx Proxy Manager, Caddy, Cloudflare Tunnel)**

Kobo devices sync over HTTPS, so the `api_endpoint` has to be your public `https://` address. Put a proxy with a valid certificate in front and point it at the container's plain HTTP port:

- Proxy target is `http://<container-host>:8083`. The proxy terminates TLS on 443; the connection from the proxy to CWA stays HTTP. WebSocket support is not needed for Kobo sync.
- Generate the token while visiting CWA through the HTTPS address, so the `api_endpoint=` line the dialog shows already carries your public hostname.
- If you stack proxies (for example Cloudflare Tunnel in front of nginx), set [`TRUSTED_PROXY_COUNT`](#reverse-proxy--cloudflare-tunnel) to the number of proxies.

**nginx buffer sizes (important for Kobo sync)**

Kobo's `/v1/library/sync` response carries large headers (auth, sync tokens, library state). Nginx's default `proxy_buffer_size` (4 KB) and `proxy_buffers` (8 × 4 KB) are too small; the response is silently dropped before it reaches the device, and the Kobo shows *"Sync failed, please try again"* with **no error in the CWA log**. The nginx error log shows `upstream sent too big header while reading response header from upstream`. Add these to the `location /` block proxying CWA:

```nginx
proxy_buffer_size       32k;
proxy_buffers           4 32k;
proxy_busy_buffers_size 64k;
```

(Larger libraries may need `128k / 4 256k / 256k`.) Reload nginx after the change. On Synology DSM, the built-in reverse-proxy GUI doesn't expose these directives — drop a custom config at `/etc/nginx/conf.d/http.calibre_web.conf` that mirrors the DSM entry plus the buffer lines, then disable the DSM entry. DSM rewrites `nginx.conf` on reboot, so a Task Scheduler boot-event job that runs `nginx -s reload` reapplies the custom file. Nginx Proxy Manager users: add the three lines under the proxy host's *Advanced* tab.

See [`examples/nginx-reverse-proxy.conf`](examples/nginx-reverse-proxy.conf) for a complete reference snippet.

**If you keep a Kobo account signed in**

Signing into a Kobo account, or doing a factory reset, can rewrite the `api_endpoint=` line back to Kobo's own server, which sends sync to Kobo instead of your library. After signing in, re-check the conf line over USB and set it back if it changed. Many sideloaded setups sign out of the Kobo account so the device stops resetting the endpoint.

To keep the Kobo Store and your library working at the same time, turn on **Proxy unknown requests to Kobo Store** in Admin → Edit Basic Configuration. With it off (the default), any request CWA doesn't recognize gets an empty response — fine for a sideload-only device, but store features won't load.

---

## Troubleshooting

### "Cover-file is not a valid image file, or could not be stored"

Fixed in v4.0.13 and later. If you're still seeing it after upgrading, you probably have `root:root`-owned book directories from a pre-fix install. Run once:

```bash
docker exec calibre-web chown -R abc:abc /calibre-library
```

### "Generate Kobo Auth Token" returns a blank page

Fixed in v4.0.14 and later. Upgrade the image.

### Kobo says "Sync failed, please try again"

Almost always one of these:

1. The device isn't reaching your server. The `api_endpoint=` line in `.kobo/Kobo/Kobo eReader.conf` must point at your CWA address (not `storeapi.kobo.com`), and that address must be reachable over HTTPS. See [Kobo sync](#kobo-sync).
2. A Kobo account is signed in and **Proxy unknown requests to Kobo Store** is off, so the device's store calls get an empty response mid-sync. Turn that setting on, or sign out of the Kobo account on the device.
3. Behind a reverse proxy, the proxy can't reach the container. Confirm the proxy target is `http://<host>:8083` and that the certificate is valid.
4. **nginx is silently dropping the sync response because its default buffers are too small for Kobo's library-sync headers.** The CWA log shows the request arriving but nothing else; the nginx error log shows `upstream sent too big header`. Add `proxy_buffer_size 32k; proxy_buffers 4 32k; proxy_busy_buffers_size 64k;` to the proxy location. See the [nginx buffer sizes](#kobo-sync) note in the Kobo sync section.

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
| Hungarian (`hu`) | `██████████████████░░` 92% | 1621/1753 | 81 |
| German (`de`) | `██████████████████░░` 88% | 1551/1753 | 103 |
| French (`fr`) | `██████████████████░░` 88% | 1548/1753 | 100 |
| Japanese (`ja`) | `██████████████████░░` 88% | 1548/1753 | 226 |
| Spanish (`es`) | `██████████████████░░` 88% | 1547/1753 | 267 |
| Slovenian (`sl`) | `█████████████████░░░` 87% | 1518/1753 | 301 |
| Russian (`ru`) | `██████████████░░░░░░` 72% | 1264/1753 | 449 |
| Dutch (`nl`) | `██████████████░░░░░░` 71% | 1246/1753 | 273 |
| Italian (`it`) | `██████████████░░░░░░` 69% | 1208/1753 | 250 |
| Polish (`pl`) | `██████████████░░░░░░` 69% | 1208/1753 | 255 |
| Portuguese (Brazil) (`pt_BR`) | `██████████████░░░░░░` 69% | 1208/1753 | 382 |
| Korean (`ko`) | `██████████████░░░░░░` 69% | 1202/1753 | 250 |
| Chinese (Simplified, China) (`zh_Hans_CN`) | `█████████████░░░░░░░` 67% | 1173/1753 | 332 |
| Arabic (`ar`) | `████████████░░░░░░░░` 61% | 1062/1753 | 269 |
| Slovak (`sk`) | `████████████░░░░░░░░` 60% | 1051/1753 | 299 |
| Portuguese (`pt`) | `████████████░░░░░░░░` 60% | 1050/1753 | 347 |
| Indonesian (`id`) | `████████████░░░░░░░░` 59% | 1030/1753 | 349 |
| Galician (`gl`) | `████████████░░░░░░░░` 59% | 1028/1753 | 348 |
| Chinese (Traditional, Taiwan) (`zh_Hant_TW`) | `███████████░░░░░░░░░` 56% | 987/1753 | 367 |
| Swedish (`sv`) | `███████████░░░░░░░░░` 55% | 964/1753 | 377 |
| Greek (`el`) | `██████████░░░░░░░░░░` 51% | 900/1753 | 391 |
| Czech (`cs`) | `██████████░░░░░░░░░░` 50% | 880/1753 | 400 |
| Norwegian (`no`) | `██████████░░░░░░░░░░` 49% | 866/1753 | 435 |
| Vietnamese (`vi`) | `█████████░░░░░░░░░░░` 45% | 783/1753 | 359 |
| Finnish (`fi`) | `█████████░░░░░░░░░░░` 43% | 746/1753 | 389 |
| Ukrainian (`uk`) | `████████░░░░░░░░░░░░` 39% | 678/1753 | 374 |
| Turkish (`tr`) | `████████░░░░░░░░░░░░` 38% | 674/1753 | 384 |
| Khmer (`km`) | `██████░░░░░░░░░░░░░░` 32% | 553/1753 | 344 |
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
