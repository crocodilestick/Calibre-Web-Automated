# Capability-Check

Stand: 2026-07-02

Dieser Check klaert, welche Skills, MCP-Server, Connectoren und lokalen Werkzeuge
fuer die naechste Alexandria-Phase noetig oder sinnvoll sind. Er ersetzt keine
Feature-Spezifikation, sondern macht sichtbar, womit wir arbeiten koennen.

## Erforderlich

| Bereich | Status | Befund |
|---|---|---|
| Git | verfuegbar | `git version 2.53.0`; Branch-Arbeit moeglich |
| Python-Testumgebung | verfuegbar | `.venv/bin/python` ist Python 3.11.15 |
| pytest | verfuegbar | `.venv/bin/pytest` ist pytest 9.1.1 |
| ripgrep | verfuegbar | `rg` liegt unter `/opt/homebrew/bin/rg` |
| Review-Protokoll | verfuegbar | Regeln stehen in `AGENTS.md`; Worker/Reviewer-Trennung ist eingerichtet |
| Docker/Compose | offen | `docker` ist in dieser Shell nicht verfuegbar |
| GitHub CLI | offen | `gh auth status` meldet fuer `salutaris91` einen ungueltigen Token |

## Sinnvoll Optional

| Werkzeug | Status | Bewertung |
|---|---|---|
| Graphify | verfuegbar, noch kein Graph | `graphify 0.8.26` ist installiert; `graphify-out/` wird lokal ignoriert |
| Browser-/UI-Pruefung | spaeter | Sinnvoll, sobald die Kobo-zentrierte UI konkret angepasst wird |
| GitHub-MCP/Connector | spaeter | Sinnvoll fuer PR-/Issue-Arbeit, aber nicht noetig fuer lokale Code-Aenderungen |

## Graphify-Detection

Graphify wurde nicht vollstaendig gebaut, sondern zunaechst nur detektiert. Der
vollstaendige Repo-Scan ist fuer einen ersten Lauf zu breit:

- 733 unterstuetzte Dateien
- ca. 4.893.683 Woerter
- 1 sensible Datei uebersprungen
- Dateitypen: 413 Code-Dateien, 127 Dokumente, 193 Bilder

Top-Level-Verteilung:

| Bereich | Dateien |
|---|---:|
| `cps/` | 568 |
| `tests/` | 45 |
| `README_images/` | 29 |
| `changelogs/` | 21 |
| `scripts/` | 21 |
| `(root)` | 15 |
| `.github/` | 10 |
| `docs/` | 9 |
| `kubernetes/` | 6 |
| `koreader/` | 4 |

Empfehlung: Fuer den ersten echten Graphify-Lauf nicht das gesamte Repo scannen,
sondern gezielt starten. Fuer die kommende Kobo-Entkopplung bietet sich zuerst
ein fokussierter Graph auf `cps/` plus relevante Tests an; falls das noch zu gross
ist, enger auf `cps/kobo.py`, `cps/magic_shelf.py`, `cps/shelf.py`,
`cps/web.py`, Templates und die betroffenen Unit-Tests.

## Naechste offene Schritte

1. Docker/Compose lokal klaeren, bevor reale Container-Tests auf dem Mac
   erwartet werden.
2. GitHub CLI erneut authentifizieren, bevor Branches/PRs per `gh` verwaltet
   werden.
3. Graphify gezielt initialisieren, sobald Alex den Scan-Umfang bestaetigt.

