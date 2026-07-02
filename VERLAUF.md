# Verlauf

Fortlaufende, **eingecheckte** Historie dieses Projekts — wie `STAND.md`, nur
dass nichts gelöscht wird. Zweck: den gesamten Entwicklungsverlauf lückenlos
nachvollziehen, ohne `git log` durchforsten zu müssen.

**Pflege (minimaler Aufwand):** Beim Abschluss eines Arbeitsschritts den aktuellen
`STAND.md`-Block mit Datums-Überschrift **oben** hier einfügen, dann `STAND.md`
für die nächste Aufgabe leeren. Gleiches Format → reines Copy-Paste.

| Datei | Zeitfenster | Versioniert? | Pflege |
|---|---|---|---|
| `STAND.md` | nur **jetzt** | nein (gitignored) | überschreiben |
| `VERLAUF.md` | **gesamte Historie** | ja (eingecheckt) | oben anhängen |
| Git-History | jeder Commit (technisch) | ja | automatisch |

> Tipp: Für reine Werkzeug-/Meta-Repos genügt oft die Git-Historie allein —
> `VERLAUF.md` lohnt sich vor allem dort, wo echte Feature-Arbeit lückenlos und
> ohne Git-Kenntnisse lesbar sein soll.

---

## 2026-07-02 — Lokale Mac-Docker-Testumgebung

- **Feature/Bug:** Lokale Mac-Docker-Testumgebung fuer CWA Alexandria
- **Branch / Worktree:** `setup/local-docker-dev` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status (Abschluss):** erledigt

### Erledigt

- `/local-dev/` in `.gitignore` eingetragen (ohne unnötige Leerzeilen am Dateiende).
- `init_local_dev.sh` erstellt und robuster gestaltet (bricht mit `exit 1` ab, wenn Template-DBs fehlen).
- Skript ausgeführt und die korrekte Erstellung der Pfade unter `./local-dev` verifiziert.
- `docker-compose.local.yml` erstellt, um CWA auf Port 8085 mit relativem Mount auf `./local-dev` und vollem Root-Workspace-Bind für Live-Editing auszuführen.
- `docs/alexandria/local-development.md` erstellt (inklusive ngrok-Sicherheitshinweisen und Root-Mount-Warnungen) und in `docs/alexandria/README.md` (Next Step & Dokumente) aktualisiert/verlinkt.
- Lokalen Commit `5675a23` auf dem Branch `setup/local-docker-dev` erstellt.
- Branch nach GitHub gepusht und Pull Request #2 erstellt.

### Nächster Schritt (zum Zeitpunkt)

- Bereit für Merge/PR-Erstellung (durch Alex).

### Offene Entscheidungen (damals)

- PR-Merge auf GitHub.

### Belege

- `./init_local_dev.sh` läuft sauber durch; `.gitignore` ist angepasst und bereinigt; lokaler Commit `5675a23` gepusht; PR #2 offen (siehe `walkthrough.md`).

---

## 2026-07-02 — Kobo sync shelves filter bugfix

- **Feature/Bug:** Kobo `sync_shelves()`-Filter-Bugfix
- **Branch / Worktree:** `fix/kobo-sync-shelves-filter` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status (Abschluss):** erledigt

### Erledigt

- In `sync_shelves()` den fehlerhaften SQLAlchemy-Filter `not ub.Shelf.kobo_sync` ersetzt.
- In `kobo_sync_utils.py` den Helper `kobo_sync_disabled_filter()` ergänzt, der `False` und `NULL` als nicht Kobo-synchronisiert behandelt.
- Lokales minimales `.venv` aufgesetzt, um die Kobo-Unit-Tests isoliert auf macOS ausführen zu können (ohne OpenLDAP/Wand).
- Unit-Test `tests/unit/test_kobo_shelf_sync_filters.py` um echten SQLAlchemy-SQLite-Dialekt-Kompilierungstest erweitert.
- Alle 13 Kobo-bezogenen Unit-Tests (`test_kobo_shelf_sync_filters.py`, `test_kobo_sync_timestamps.py`, `test_kobo_cover_image_id.py`) erfolgreich ausgeführt.
- Lokalen Commit `76326e9` erstellt.
- Branch `fix/kobo-sync-shelves-filter` erfolgreich nach GitHub gepusht.

### Nächster Schritt (zum Zeitpunkt)

- Bereit für Merge/PR-Erstellung (durch Alex).

### Offene Entscheidungen (damals)

- Keine. Der Branch wurde wie gewünscht abgesichert und hochgeladen.

### Belege

- Alle 13 Unit-Tests bestanden (siehe `walkthrough.md`); Kompilierungstest für SQLiteDialect grün; Commit `76326e9` gepusht.

---

## 2026-07-02 — GitHub-ready Fork-root-Umzug

- **Feature/Bug:** Fork-root-Umzug fuer CWA Alexandria
- **Branch / Worktree:** `setup/fork-root-import` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status (Abschluss):** erledigt

### Erledigt

- GitHub-Fork `salutaris91/cwa-alexandria` von `crocodilestick/Calibre-Web-Automated` angelegt.
- CWA-Fork mit Git-Historie in die Projektwurzel uebernommen.
- Remotes gesetzt: `origin` zeigt auf Alex' Fork, `upstream` auf das originale CWA-Repository.
- Alexandria-Doku unter `docs/alexandria/` wieder eingespielt; Upstream-`README.md` in der Projektwurzel bewusst erhalten.
- Projektlokale Agent-/Uebergabedateien wieder ergänzt und auf den nun bekannten Fork-root-Stack aktualisiert.
- `.gitignore` so angepasst, dass `docs/alexandria/**` versioniert wird und `STAND.md` lokal bleibt.

### Nächster Schritt (zum Zeitpunkt)

- Setup-Branch prüfen, committen und nach Freigabe pushen.
- Danach erster Code-Spike: `sync_shelves()`-Bugfix mit gezieltem automatisiertem Test im CWA-Testbaum.

### Offene Entscheidungen (damals)

- Ob der Setup-Branch direkt nach GitHub gepusht wird.
- Ob der erste Bugfix in einem neuen Branch auf Basis dieses Setup-Stands startet.

### Belege

- Fork-URL: `https://github.com/salutaris91/cwa-alexandria`
- Lokale Remotes: `origin=https://github.com/salutaris91/cwa-alexandria.git`, `upstream=https://github.com/crocodilestick/Calibre-Web-Automated.git`

---

## 2026-07-02 — Projektstart und Strukturvorbereitung

- **Feature/Bug:** Projektstart fuer CWA Alexandria & Doku-Strukturierung
- **Branch / Worktree:** noch kein Git-Repo; lokaler Projektordner `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status (Abschluss):** erledigt

### Erledigt

- Projektordner mit dem zentralen AI-Coding-Starter-Kit und spezifischen Anpassungen initialisiert.
- Doku-Bereich `docs/alexandria/` angelegt und Alexandria-spezifische Doku (`README.md`, `vision.md`, `fork-audit.md`, `kobo-workflow.md`, `kobo-setup-runbook.md`, `ui-ideen.md`) dorthin kopiert sowie Pointer-Stubs an den alten Orten eingerichtet, um Kollisionen beim späteren Upstream-Fork zu vermeiden.
- Pointer-Stubs für die Doku in `docs/` und eine Pointer-Root-`README.md` angelegt.
- Fork-Audit um Review-Ergebnisse präzisiert (Kobo-Unit-Tests wie `test_kobo_sync_timestamps.py`/`test_kobo_cover_image_id.py` ergänzt, Magic-Shelf-Risiko `page_size=1000` dokumentiert, `sync_shelves()`-Bug als ersten Spike fixiert).
- Relative Verlinkungen in den Alexandria-Dokus aktualisiert.

### Nächster Schritt (zum Zeitpunkt)

- Fork-root-Umzug/Fork-Clone nach expliziter Bestätigung vorbereiten.

### Offene Entscheidungen (damals)

- Repository-Name: `cwa-alexandria` oder `cw-alexandria`.
- Soll der GitHub-Fork direkt angelegt werden oder erst lokal ohne externen Seiteneffekt weitergearbeitet werden?

### Belege

- Doku-Strukturierung erfolgreich abgeschlossen; Pointer-Stubs getestet; `docs/alexandria/fork-audit.md` mit Review-Präzisierungen erweitert.

---

## JJJJ-MM-TT — <Kurztitel des Schritts>

- **Feature/Bug:**
- **Branch / Worktree:**
- **Status (Abschluss):** (erledigt / teilweise / verworfen)

### Erledigt
-

### Nächster Schritt (zum Zeitpunkt)
-

### Offene Entscheidungen (damals)
-

### Belege
- (ausgeführte Befehle + Ergebnis, geänderte Dateien, Commit/PR)

---

## JJJJ-MM-TT — <vorheriger Schritt>

- **Feature/Bug:**
- **Status (Abschluss):**

### Erledigt
-

### Belege
-
