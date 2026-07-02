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

## 2026-07-02 — Kobo-Dashboard & Sammlungs-Zusammenführung

- **Feature/Bug:** Kobo-Dashboard und Sammlungen-Sidebar-Zusammenführung
- **Branch / Worktree:** `feature/kobo-dashboard` auf `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Erfolgreich abgeschlossen. Sämtliche Dashboard-Berechnungen (Union-Sync-Menge, eReader-Synchronisationsstatistiken, eReader-Token-Prüfungen, Magic-Shelf ID-Ermittlung ohne Cache-Seiteneffekte, Download-Berechtigungsprüfungen) wurden implementiert. Das Dashboard zeigt Kobo-Sammlungen gemischt, aber mit Typ-Kennzeichnung. Die Sidebar fasst normale und Magic-Regale unter der Überschrift "Sammlungen" zusammen. Alle 4 Unit-Tests in `tests/unit/test_kobo_dashboard.py` wurden erfolgreich ausgeführt und alle 20 Kobo- und Magic-Shelf-Tests bestehen fehlerfrei.

### Erledigt

- **Backend-Logik & Zirkularimport-Vermeidung**:
  - `cps/kobo_dashboard.py` neu erstellt, um die Kobo-Dashboard Berechnungs- und Aggregationslogik (`get_kobo_dashboard_data`) zu kapseln.
  - Zirkularimport durch Lazy-Import von `get_kobo_allowed_book_ids` innerhalb der Aggregationsfunktion vermieden.
  - ID-Ermittlung für Magic Shelves (`get_magic_shelf_book_ids_direct`) direkt über die Calibre-Datenbank (via `cdb.common_filters()`) implementiert, was den Cache umgeht und Zirkularbezüge sowie cache-schreibende Seiteneffekte vermeidet (greift jedoch für Rechte- und Tag-Filter über common_filters() weiterhin auf den current_user-Kontext zu).
- **Routen & Templates**:
  - Route `/kobo_auth/dashboard` in `cps/kobo_auth.py` hinzugefügt (abgesichert über `@user_login_required`). Sie übergibt `page="kobo_dashboard"`.
  - HTML-Template `cps/templates/kobo_dashboard.html` im Bootstrap-Stil von Calibre-Web erstellt. Es visualisiert den Kobo-Verbindungsstatus, Sync-Modus, Statistiken, System-Warnungen und die Kobo-Sammlungen.
- **Seitenleisten-Konsolidierung (Navigation)**:
  - Normale Regale und Magic Shelves in `cps/templates/layout.html` unter dem gemeinsamen Abschnitt „Sammlungen“ (nacheinander sortiert) zusammengefasst.
  - Link zur „Kobo-Auswahl“ in der Sidebar hinzugefügt, sichtbar über die in `render_title_template()` global an das Template übergebene Variable `kobo_sync_enabled` und `current_user.is_authenticated`.
- **Tests**:
  - 4 Unit-Tests in `tests/unit/test_kobo_dashboard.py` geschrieben (inkl. Mocking von CalibreDB, config-Parametern und `current_user` in einer Flask-Request-Umgebung).
  - Alle 20 Kobo- und Magic-Shelf-Tests erfolgreich lokal ausgeführt.

## 2026-07-02 — Smoke-Test Kobo-Entkopplung (2-Säulen-Prinzip)

- **Feature/Bug:** Smoke-Test für Kobo-Entkopplung
- **Branch / Worktree:** `main` auf `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Erfolgreich abgeschlossen. Sämtliche API-Sync-Mechanismen, Sicherheits-Schranken (für normale Regale & Magic-Shelves), leere Kollektionen, DB-Migrationen und der inkrementelle Löschpfad wurden in der lokalen Docker-Umgebung (OrbStack) verifiziert. Ein kritischer Flask 500 BuildError bei der Token-Generierung wurde analysiert und per Container-Neustart-Workaround umgangen.

### Erledigt

- **Docker-Laufzeit & Umgebung**:
  - Lokale Docker-Laufzeit **OrbStack** erfolgreich in Betrieb genommen.
  - Analyse des SQLite Dateisystem-Lockings unter VirtioFS: Parallele Schreibzugriffe von CLI-Clients führen zu Corruption (`disk I/O error`). Der Testablauf wurde um ein sicheres Offline-DB-Setup erweitert.
- **Datenbank-Migration**:
  - Spalte `kobo_display` bei normalen Regalen und Magic-Shelves sowie die Wertübernahme erfolgreich verifiziert.
- **Ablauf-Blocker dokumentiert (Workaround)**:
  - HTTP 500 BuildError bei Token-Generierung zur Laufzeit identifiziert. Neustart-Workaround im Testplan und in der Dokumentation verankert.
- **API-Verifikation (Sicherheits-Schranke & Leere Kollektionen)**:
  - Zweiphasige Verifikation der Sicherheits-Schranke: Im Full-Sync ist Buch_B über die aktiven Trägerregale sync-berechtigt und wird ausgeliefert. Erst nach der Deletion der Trägerregale wird Buch_B im inkrementellen Sync mit `IsRemoved: true` entfernt und aus den verbleibenden Display-Only-Kollektionen (normale Regale und Magic-Shelves) herausgefiltert.
  - Display-Only Magic-Shelves (`kobo_sync=0` und `kobo_display=1`) liefern nur sync-berechtigte Bücher aus.
  - Leere Kollektionen werden als Kobo-Tags mit `"Items": []` übertragen (verifiziert für normale Regale und Magic-Shelves).
- **Inkrementeller Sync & Löschpfade**:
  - App-Löschpfade über die echten Endpunkte `/shelf/delete/20` und `/magicshelf/100/delete` (mit `{"success": true}` Response) verifiziert. Beide erzeugen korrekte `shelf_archive` Einträge.
  - Inkrementeller Sync mit echtem `x-kobo-synctoken` belegt die Deletion-Übermittlung: Beide gelöschten Shelves werden als `DeletedTag` übertragen.
  - Entkopplungs-Mechanismus: Das nicht mehr sync-berechtigte Buch wird beim inkrementellen Sync mit `"IsRemoved": true` an den Reader übertragen.
  - Aufräum-Mechanismus: `shelf_archive`-Einträge werden nach dem Sync automatisch und rückstandslos gelöscht.

## 2026-07-02 — Kobo-Entkopplung (2-Säulen-Prinzip)

- **Feature/Bug:** Kobo-Entkopplung (2-Säulen-Prinzip)
- **Branch / Worktree:** `feature/kobo-sync-decoupling` auf `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Implementiert, lokal verifiziert, Blocker behoben, Unit- & Integrationstests erfolgreich durchgeführt und als Pull Request auf GitHub eingereicht (PR #5).

### Erledigt

- **Datenbank & Migrationen (`cps/ub.py`)**:
  - Spalte `kobo_display` zu `Shelf` und `MagicShelf` hinzugefügt.
  - `migrate_shelf_table` und `migrate_magic_shelf_table` implementiert, die das neue Flag automatisch mit dem Zustand von `kobo_sync` initialisieren.
- **UI-Ebene**:
  - **`shelf_edit.html`**: Checkbox `kobo_display` („Als Kobo-Sammlung anzeigen“) hinzugefügt (immer sichtbar, wenn Kobo-Sync konfiguriert ist).
  - **`magic_shelf_edit.html`**: Checkbox `shelf-kobo-display` im HTML und JavaScript hinzugefügt.
- **Controller & Routen**:
  - **`cps/shelf.py`**: `create_edit_shelf` verarbeitet und speichert nun `kobo_display`. Bei Aktivierung wird der Archivierungseintrag gelöscht.
  - **`cps/web.py`**: `create_magic_shelf` und `edit_magic_shelf` verarbeiten und speichern das AJAX-Flag `kobo_display`.
  - **`cps/web.py:delete_magic_shelf`**: Archiviert gelöschte Magic-Shelves via `ShelfArchive` unter Verwendung des exakten Erstellers (`shelf.user_id`), um gelöschte Sammlungen sofort an Kobo-Geräte zu propagieren.
- **Sync-Engine & Blocker-Fix (`cps/kobo.py`)**:
  - Helper `get_kobo_allowed_book_ids(user_id)` zur Ermittlung der Vereinigung (Union) aller `kobo_sync==True` Quellen implementiert.
  - Die Lösch- und Synchronisationslogik von `HandleSyncRequest` nutzt diesen Helper zur Bestimmung der erlaubten Buchmenge.
  - `sync_shelves` und die Magic-Shelf-Sync-Schleifen nutzen `kobo_display` statt `kobo_sync` für das Sammlungs-Rendering und filtern DeletedTags zeitlich über `last_modified > tags_last_modified`.
  - **Sicherheits-Schranke**: In `create_kobo_tag` und `create_kobo_tag_magic` werden die Sammlungsbücher gegen `allowed_book_ids` gefiltert, sodass nur freigegebene Bücher in Kobo-Sammlungen erscheinen.
  - **Blocker-Fix (Reading-State-Filter)**: Der Filter für `changed_reading_states` nutzt nun direkt `allowed_book_ids` anstelle der nicht mehr initialisierten `magic_shelf_book_ids` Variable (NameError behoben).
- **Tests & Verifikation**:
  - 6 neue Unit- und Integrationstests in `tests/unit/test_kobo_decoupling.py` geschrieben (inkl. full route sync tests).
  - Alle 29 Kobo- und Magic-Shelf-Tests in Python 3.11 erfolgreich ausgeführt.
  - `git diff --check` fehlerfrei bereinigt.

## 2026-07-02 — Integration normale Regale als Magic-Shelf-Regelquelle

- **Feature/Bug:** Erste Umsetzungsphase: Integration normale Regale als Magic-Shelf-Regelquelle
- **Branch / Worktree:** `feature/normal-shelf-magic-rule` auf `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Implementiert, verifiziert, Review-Findings behoben und freigegeben.

### Erledigt

- **Core Engine (`cps/magic_shelf.py`):**
  - `FIELD_MAP` um `normal_shelf` erweitert.
  - `build_query_from_rules` und `build_filter_from_rule` um `is_public` Parameter erweitert.
  - Berechtigungsprüfung: Öffentliche Magic Shelves dürfen keine privaten normalen Regale referenzieren (werden mit `false()` blockiert).
  - Operator-Validierung: `equal` und `not_equal` sind als einzige Operatoren zulässig, alle anderen evaluieren zu `false()`.
  - `invalidate_magic_shelf_cache()` implementiert, wirft bei Fehlern eine Exception (Integrität der Mutationspfade).
- **Web-Routen & UI:**
  - `shelves_map` im Flask GET-Pfad für Erstellen/Editieren an Template übergeben.
  * XSS-Sicherung: Sichere Serialisierung der Regalnamen über den Jinja-Filter `tojson` (kein unsicheres `json.dumps|safe`).
  * Preview-Semantik an das `is_public` Checkbox-Element gekoppelt, um synchrone Backend-Validierung im UI widerzuspiegeln.
  * Strikte Typen-Prüfung (`is True`) in Preview-API implementiert.
- **Cache-Invalidierung in Mutationspfaden:**
  - `invalidate_magic_shelf_cache()` in allen 12 Mutations-Schreib-Pfaden vor dem Commit eingebunden (Tabelle siehe Walkthrough).
  - Kobo-Sync-Pfade nutzen `bypass_cache=True` bei `get_books_for_magic_shelf`.
- **Tests & Verifikation:**
  - 10 Unit-Tests in `tests/unit/test_magic_shelf_rules.py` geschrieben.
  - Alle 10 Unit-Tests in Python 3.11-Umgebung via `uv` erfolgreich ausgeführt.
  - 13 Kobo-Regressionstests erfolgreich ausgeführt.
  - `git diff --check` fehlerfrei bereinigt.

### Nächster Schritt

- Kobo-Entkopplung (2-Säulen-Prinzip mit Sync-Flags und Kobo-Sammlungen).

## 2026-07-02 — Magic-Shelf-Regeln Audit und Spezifikation

- **Feature/Bug:** Magic-Shelf-Regeln Audit und Spezifikation (Erweiterung normale Regale & Entkopplungs-Konzept)
- **Branch / Worktree:** `research/magic-shelves-audit` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status (Abschluss):** erledigt (online gemerged)

### Erledigt

- **Audit-Aktualisierung ([magic-shelves-audit.md](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/docs/alexandria/magic-shelves-audit.md)):**
  - Fachliche Einbindung der Kobo-Entkopplung (2-Säulen-Prinzip, Kobo-Übersicht/Dashboard, Serien-Ausnahme).
  - 1000-Bücher-Deckel-Warnung aufgenommen.
  - Spaltenname auf `ub.BookShelf.shelf` korrigiert.
  - Backend-Berechtigungsprüfungen (Sicherheitsgrenze) konzipiert.
  - Cache-Invalidierungsstrategie bewertet (Änderung normale Regale).
  - Präzisierung der Cross-Model-Joins (SQL-Joins möglich, aber ID-Listen-Variante ist Upstream-näher).
- **Versionierter Implementierungsplan ([magic-shelves-plan.md](file:///Users/alex/Documents/Programmierungsprojekte/cwa-alexandria/docs/alexandria/magic-shelves-plan.md)):**
  - Detaillierter Plan im Projektordner versioniert, um Reviewbarkeit in Git zu gewährleisten.
  - Feldname auf `normal_shelf` geändert.
  - Operator-Einschränkung (`equal` und `not_equal` only) in UI und Backend verankert.
  - **Sicherheits-Fix:** Fehler und Permission-Verstöße im Backend evaluieren zu `sqlalchemy.false()`, um unberechtigte AND-Bypasses durch `None` zu verhindern.
  - **Typ-Sicherheit:** `int(value)` wird mit `try/except` für manipuliertes JSON abgesichert und liefert `false()`.
  - **Globale Cache-Bereinigung:** Bei Regalmanipulationen in `cps/shelf.py` wird die gesamte Cache-Tabelle `ub.MagicShelfCache` gelöscht, um Stale-Probleme bei geteilten Regalen zu vermeiden.
  - Testplan erweitert (Kobo-Sicherung, private Regale abweisen, leere Regale, String-Werte).
- Lokalen Commit `efa3b48` auf dem Branch `research/magic-shelves-audit` erstellt, nach GitHub gepusht, PR #3 erstellt und online gemergt.

### Nächster Schritt (zum Zeitpunkt)

- Start der ersten technischen Umsetzungsphase (Integration normale Regale als Regelquelle).

### Offene Entscheidungen (damals)

- Keine (durch Online-Merge von PR #3 abgeschlossen).

### Belege

- PR #3 erfolgreich gemergt: `https://github.com/salutaris91/cwa-alexandria/pull/3`

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
