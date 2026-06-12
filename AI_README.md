# AI_README — assistant-driven setup for Calibre-Web-NextGen

You are an AI assistant and a human asked you to set up
[Calibre-Web-NextGen](https://github.com/new-usemame/Calibre-Web-NextGen) —
a self-hosted ebook server (web library + reader, automatic book ingest,
Kobo/KOReader sync, OPDS).

This file is written for **you**, not the human. Work through it top to
bottom. Ask the human only the questions in §1; detect everything else
yourself. Never skip a **VERIFY** gate — if one fails, use §7, and if you
still can't fix it, file an issue per §8 instead of leaving the human stuck.

Sections: [1 Ask](#1-ask-the-human) · [2 Detect](#2-detect-the-system) ·
[3 Install](#3-install-and-start) · [4 Secure](#4-secure-and-configure) ·
[5 First book](#5-prove-ingest-works) · [6 Plugins](#6-optional-calibre-plugins) ·
[7 Probes](#7-when-something-fails) · [8 Report issues](#8-when-you-cant-fix-it) ·
[9 Hand-off](#9-final-report-to-the-human)

## 1. Ask the human

Four questions, then stop asking:

1. **Where should book data live?** Default: `~/calibre-web` on this machine.
   An external drive or NAS path is fine (see §2 caveats).
2. **Port?** Default `8083`.
3. **Fresh start, or migrating** an existing Calibre library / Calibre-Web /
   CWA install? If migrating, get the path to the folder containing
   `metadata.db` (library) and, for CWA migrations, their old `/config` folder.
4. **A new admin password** (or offer to generate one). Needs ≥8 characters
   with upper, lower, digit, and special character — e.g. `Reading-2-Win!`.

## 2. Detect the system

Run, don't ask:

```bash
docker version --format '{{.Server.Os}}/{{.Server.Arch}}' && docker compose version
uname -sm
```

- No Docker → install it first (Docker Engine on Linux, Docker Desktop on
  macOS/Windows, Container Manager on Synology). That's a prerequisite, not
  part of this guide.
- The image supports `linux/amd64` and `linux/arm64` (Raspberry Pi 4/5 and
  Apple Silicon included). Other arches: stop and report per §8.

Adjust for the platform you found:

| Platform | What to do differently |
|---|---|
| Linux server | Set `PUID`/`PGID` to the human's `id -u` / `id -g` so library files stay editable outside the container. |
| macOS (Docker Desktop) | Defaults work; file-event watching automatically falls back to polling, so ingest takes a few extra seconds. Keep `PUID=1000`. |
| Windows | Use WSL2 + Docker Desktop, and keep the data folders **inside the WSL filesystem** (e.g. `~/calibre-web`), not under `/mnt/c/` — NTFS-bridged binds are slow and drop file events. |
| Synology / QNAP NAS | Use Container Manager / Container Station with the same compose. Set `PUID`/`PGID` to the NAS user's IDs (`id <user>` over SSH). |
| Data on NFS/SMB share | Add `- NETWORK_SHARE_MODE=true` to the environment. Required — without it SQLite locks up on network filesystems. |
| Path contains spaces | Quote every volume path in the compose file: `- "/Volumes/My Drive/calibre-web/config:/config"`. |

If the chosen port is taken (`docker ps`, or `lsof -i :<port>`), pick the
next free one and tell the human. If a container named `calibre-web` already
exists, use `calibre-web-nextgen` as the name instead.

## 3. Install and start

```bash
mkdir -p <data-dir>/{config,library,ingest}
```

Write `<data-dir>/docker-compose.yml` (substitute placeholders; quote paths
with spaces):

```yaml
services:
  calibre-web:
    image: ghcr.io/new-usemame/calibre-web-nextgen:latest
    container_name: calibre-web
    environment:
      - PUID=1000            # match the human's uid on Linux/NAS
      - PGID=1000
      - TZ=America/New_York  # the human's timezone, tz database name
      # - NETWORK_SHARE_MODE=true   # only if /config or library is on NFS/SMB
    volumes:
      - <data-dir>/config:/config
      - <data-dir>/library:/calibre-library
      - <data-dir>/ingest:/cwa-book-ingest
    ports:
      - "8083:8083"          # left side = the port the human picked
    restart: unless-stopped
```

Migrating? Point the `library` bind at the folder containing `metadata.db`,
and (CWA only) the `config` bind at their old config folder — both carry
over as-is. The ingest bind must stay a separate, otherwise-unused folder:
**files dropped there are deleted after import.** Never nest the three
folders inside each other.

```bash
cd <data-dir> && docker compose up -d
```

**VERIFY — wait for healthy** (first start takes 1–3 minutes):

```bash
docker inspect -f '{{.State.Health.Status}}' calibre-web   # repeat until "healthy"
```

## 4. Secure and configure

Set the admin password from §1 (the default install ships `admin`/`admin123`):

```bash
docker exec -e CALIBRE_DBPATH=/config calibre-web \
  python3 /app/calibre-web-automated/cps.py -s 'admin:<NewPassword>'
```

**VERIFY — authenticated request returns 200:**

```bash
curl -s -o /dev/null -w '%{http_code}' -u 'admin:<NewPassword>' http://localhost:<port>/opds
```

Then tell the human to log in at `http://<host>:<port>` and confirm the
password works in the browser too.

## 5. Prove ingest works

Put any DRM-free `.epub` into `<data-dir>/ingest/`. If the human has none,
use this known-good public-domain download (the `-f` matters — without it a
404 writes an empty file, which the ingest worker then sits on):

```bash
curl -fL -o "<data-dir>/ingest/pride-and-prejudice.epub" \
  "https://www.gutenberg.org/ebooks/1342.epub3.images"
```

The file disappears from `ingest/` and appears in the library — usually
within 30 seconds; allow up to 2 minutes on Docker Desktop (polling mode)
or with large files.

**VERIFY:**

```bash
curl -s -u 'admin:<NewPassword>' http://localhost:<port>/opds/new | grep -o '<title>[^<]*' | head -5
```

The book's title should be listed. If not: §7.

## 6. Optional: Calibre plugins

Only if the human asks for plugin-based features (DRM removal with their own
keys, `.acsm` support, etc.). The project ships **no** plugins; the human
supplies the same `.zip` files Calibre desktop uses, and they run during
ingest and conversion.

1. Add `- CWA_CALIBRE_USER_PLUGINS=true` to `environment:` and
   `docker compose up -d`.
2. Copy the plugin `.zip` files into `<data-dir>/config/.config/calibre/plugins/`.
3. `docker restart calibre-web`, then **VERIFY:**

```bash
docker logs calibre-web 2>&1 | grep "Registered Calibre plugin"
```

Plugins needing keys/accounts keep settings in files next to the zips —
configure the plugin in Calibre desktop once, then copy its settings files
(e.g. `plugins/dedrm.json`) into the same folder and restart. Full details:
[README → Calibre plugins](README.md#calibre-plugins-dedrm-and-others).
Don't choose plugins for the human; installing third-party code is their call.

## 7. When something fails

Read the log before changing anything:

```bash
docker logs calibre-web --tail 200 2>&1 | grep -iE "error|traceback|warn" | tail -30
```

| Symptom | Fix |
|---|---|
| Port already allocated | Change the left side of `ports:` and rerun `docker compose up -d`. |
| Health stuck on `starting` | First boot migrates databases; give it 3 minutes. Then read the full log. |
| `database is locked` / app frozen | Data is on a network share → set `NETWORK_SHARE_MODE=true` and restart. |
| Books stay in `ingest/` | Wait 60s (polling mode). Confirm the file is `.epub`/`.mobi`/`.azw3`/`.pdf` etc., then check the log for the file's name. |
| Permission denied on library files | On Linux/NAS, `PUID`/`PGID` don't match the folder owner: `sudo chown -R <PUID>:<PGID> <data-dir>`. |
| Login rejected after password set | The password command prints `Password for user 'admin' changed` on success — rerun it and watch for that line. |
| Web UI unreachable from another device | Host firewall, or the human used `localhost` instead of the machine's LAN IP. |

## 8. When you can't fix it

Don't leave the human with a half-working install and no path forward.
Collect the evidence, then help them file an issue at
**https://github.com/new-usemame/Calibre-Web-NextGen/issues/new**:

```bash
docker logs calibre-web --tail 300 > cwng-setup-issue.log 2>&1
docker inspect -f '{{.Config.Image}} {{.State.Health.Status}}' calibre-web >> cwng-setup-issue.log
uname -sm >> cwng-setup-issue.log
```

The issue should contain: what step of this file failed, the exact error,
the platform row from §2, and the log file — with anything private
(passwords, tokens, names in file paths) removed before posting. Issues from
real setups are how this project finds gaps; the maintainers respond.

## 9. Final report to the human

End with a short summary: the URL, the username (`admin`) and where you put
the password, where the three data folders are, how to add books (drop into
the ingest folder or use the web UI), and one line on how to update later:

```bash
cd <data-dir> && docker compose pull && docker compose up -d
```
