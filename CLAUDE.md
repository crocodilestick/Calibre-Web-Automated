# CLAUDE.md — CWA Alexandria

> Die generischen Hausregeln, Skills und Subagenten liegen **global** (ausgespielt
> via `build-global.sh` nach `~/.claude`, `~/.codex`, `~/.gemini/config`) und
> gelten in jedem Projekt. Hier steht **nur Projektspezifisches**.
>
> Diese Datei wird (zusammen mit dem generierten `AGENTS.md`/`.agents/AGENTS.md`)
> von den Tools zusätzlich zu den globalen Regeln gelesen.

## Projektspezifisch

### Projektziel

CWA Alexandria ist ein persoenlicher, schrittweiser Fork von Calibre-Web-Automated fuer Alex' Calibre/Kobo-Workflow. Ziel ist kontrollierte Kobo-Synchronisation, bessere Sammlungen, deutsche UX-Texte und eine ruhigere Oberflaeche.

### Stack & Architektur

- Basis: Fork-root von Calibre-Web-Automated, Upstream `crocodilestick/Calibre-Web-Automated`.
- Sprache/Framework: Python, Flask, Jinja-Templates, Bootstrap/jQuery, SQLAlchemy, Babel sowie Docker/s6-nahe Betriebsdateien.
- Einstiegspunkt: `cps.py` startet `cps.main.main()`.
- Wichtige Alexandria-Dateien:
  - `docs/alexandria/` fuer Entscheidungen, Audits und Workflow-Notizen.
  - `STAND.md` fuer aktuellen Stand (lokal/ignoriert).
  - `VERLAUF.md` fuer abgeschlossene Etappen.

### Commit-Co-Author-Zeile

Jede Commit-Message endet mit:
```
Co-Authored-By: AI Coding Assistant <noreply@github.com>
```

### Build / Test / Run

- Tests ausfuehren: CWA nutzt `pytest`; bei Aenderungen zuerst gezielte Tests im betroffenen Bereich ausfuehren.
- App starten: bevorzugt ueber die vorhandenen CWA-Docker-/Compose-Dateien pruefen, bevor lokale Sonderwege dokumentiert werden.
- Lint/Format: upstream-nahe bleiben und keine neuen Formatter/Linter einfuehren, solange CWA dafuer kein klares Projektmuster hat.
- Docker-Builds fuer das Ziel-Deployment auf dem x86-NAS immer mit: `docker buildx build --platform linux/amd64`

### Projektspezifische Pflicht-Updates nach jedem Feature-Schritt

- `STAND.md` nachfuehren.
- Relevante Dokumentation in `docs/` aktualisieren, wenn sich Workflow, Datenmodell oder Entscheidungslage aendert.
- Bei dauerhaften Entscheidungen `VERLAUF.md` beim Abschluss mit dem vorherigen `STAND.md`-Block ergaenzen.
- Vor Kobo-Sync-Aenderungen immer dokumentieren, welche Buecher durch die Regel freigegeben wuerden.

### Fachliche Leitplanken

- Serien nicht standardmaessig als Kobo-Sammlungen modellieren.
- Breite Genre-Regeln wie `Fantasy` nicht ungeprueft fuer Kobo-Sync verwenden.
- Auswahl fuer Kobo und Sortierung in Sammlungen fachlich getrennt denken.
- Upstream-nahe, kleine Aenderungen bevorzugen.
- Keine externen GitHub-/Fork-/Deploy-Aktionen ohne explizite Bestätigung von Alex.
