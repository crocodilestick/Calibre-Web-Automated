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
| GitHub CLI | verfuegbar | `env -u GITHUB_TOKEN gh auth status` ist erfolgreich fuer `salutaris91` |

## Sinnvoll Optional

| Werkzeug | Status | Bewertung |
|---|---|---|
| Graphify | verfuegbar, fokussierter Graph erstellt | `graphify 0.8.26`; `graphify-out/` wird lokal ignoriert |
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

## Fokussierter Graphify-Lauf: Kobo/Magic-Shelf

Der erste lokale Graph wurde bewusst nicht auf dem gesamten Repo erzeugt, sondern
auf einem kopierten, ignorierten Code-Scope unter `graphify-out/scope/kobo/`.
Enthalten sind:

- `cps/kobo.py`
- `cps/kobo_auth.py`
- `cps/kobo_cover_cache.py`
- `cps/kobo_sync_status.py`
- `cps/magic_shelf.py`
- `cps/shelf.py`
- `cps/web.py`
- `cps/metadata_provider/kobo.py`
- `tests/unit/test_kobo_cover_image_id.py`
- `tests/unit/test_kobo_shelf_sync_filters.py`
- `tests/unit/test_kobo_sync_timestamps.py`
- `tests/unit/test_magic_shelf_rules.py`

Ergebnis:

- 12 Code-Dateien
- ca. 25.919 Woerter
- 312 Graph-Knoten
- 558 Graph-Kanten
- 22 Communities
- keine LLM-/API-Kosten; AST-basierter Lauf mit 0 Input-/Output-Tokens
- `graphify-out/graph.json`, `graphify-out/graph.html` und
  `graphify-out/GRAPH_REPORT.md` lokal erzeugt

Der Benchmark meldet fuer diesen Scope ca. **3,8x weniger Tokens pro Query** als
ein naiver Vollkontext.

Wichtige Brueckenknoten laut Report:

- `build_filter_from_rule()` verbindet Normal-Shelf-Regeltests mit der
  Magic-Shelf-Engine.
- `invalidate_magic_shelf_cache()` verbindet Shelf-Mutationen mit Magic-Shelf-
  Engine und Tests.
- `HandleSyncRequest()` ist ein relevanter Kobo-Sync-Knoten.

Der Graph ist damit vor allem fuer Fragen rund um Kobo-Sync, Magic-Shelf-Regeln,
Shelf-Mutationen und die neuen Tests geeignet. Fuer UI-/Template-Fragen oder
breitere Entschlackung muss ein zweiter, anders zugeschnittener Scope gebaut
werden.

## Naechste offene Schritte

1. Docker/Compose lokal klaeren, bevor reale Container-Tests auf dem Mac
   erwartet werden.
2. Bei Codebase-Fragen zu Kobo/Magic-Shelf bevorzugt den fokussierten Graphify-
   Graph nutzen (`graphify query ...`).
3. Fuer UI-/Entschlackungsfragen bei Bedarf einen zweiten Graphify-Scope bauen.

## Mittelfristige Entschlackung

Der Fork soll upstream-nah bleiben, aber Alexandria braucht nicht jede
Upstream-Oberflaeche und jeden Workflow gleich stark. Nach den ersten
Kobo-Sync-Schritten sollte ein eigener, lesender Entschlackungs-Audit folgen:

- Welche UI-Bereiche sind fuer Alex' Kobo-zentrierten Alltag relevant?
- Welche Funktionen bleiben technisch erhalten, koennen aber ruhiger oder
  weniger prominent dargestellt werden?
- Welche Docker-, Script-, Doku- oder Testpfade sind fuer den persoenlichen Fork
  wirklich noetig?
- Welche Aenderungen waeren zu teuer fuer Upstream-Merges und sollten deshalb
  bewusst vermieden werden?

Wichtig: Entschlackung bedeutet zunaechst Priorisierung und UI-Beruhigung, nicht
das vorschnelle Loeschen von Upstream-Code.
