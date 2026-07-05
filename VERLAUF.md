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

## 2026-07-05 — Einstellungen zusammenführen und beruhigen

- **Feature/Bug:** Einstellungen zusammenführen und beruhigen (Roadmap-Punkt 2 - Finaler Abschluss & Politur)
- **Branch / Worktree:** `feature/alexandria-settings-consolidation`
- **Status:** Alle Phasen und Blocker behoben, Passwörter geschützt, Duplikaterkennung integriert, deutsche L10n abgeschlossen, drift-unit-tested und abnahmebereit.

### Erledigt
- [x] Phase 0: Feldinventar und Drift-Test
- [x] Phase 1: Shell & Navigation (Blueprint, CSS, Tabs, Integration in layout/user_edit)
- [x] Phase 2: E-Mail + Wartung (Tabs, Fetch-Submit, Option-Lists)
- [x] Phase 3: Spiegel-Infrastruktur + Bibliothek + Kobo (Spiegel-Makros, Kobo-Tab, Restriktionen)
- [x] Phase 4: Automatisierung + Experten (Format-Grids, Drag&Drop, Experten-Tab cwa)
- [x] Phase 5: Experten Server/Login-Formular + Feinschliff (Babel, Doku, Diffs)
- [x] Blocker 1: Form-Aktionen in `bibliothek.html` und `kobo.html` auf `admin.ajax_config` korrigiert. Link "System Status" in `_tabs.html` auf funktionierenden `admin.admin` Endpoint korrigiert und Linktext semantisch passend in "Admin page" geändert.
- [x] Blocker 2: `config_kobo_sync_magic_shelves` Wert-Erhalt in `_macros.html` über direktes config-Lookups gelöst.
- [x] Blocker 3: Optionen für `duplicate_auto_resolve_strategy` korrigiert und echte `duplicate_scan_method` Dropdown-Steuerung in `experten.html` integriert.
- [x] Blocker 4: Hardcover/Unrendered-Metadata-Provider beim JS-Submit in `experten.html` und `automatisierung.html` erhalten.
- [x] Blocker 5: `_tabs.html` in `user_edit.html` mit `{% if profile %}`-Guard versehen, um Admin-User-Edit-Pages nicht zu verändern oder zu brechen.
- [x] Blocker 6: Wartungs-Endpunkte in `wartung.html` auf korrekte Routen (`admin.update_thumbnails`, `admin.shutdown` mit parameter payload `2` für reconnect_db, `admin.queue_metadata_backup`, `admin.shutdown` mit parameter `0` für restart, `admin.shutdown` mit parameter `1` für shutdown) korrigiert.
- [x] Sollte 7: LDAP- und SMTP-Passwortklartextlecks beim Spiegeln in `_macros.html` behoben.
- [x] Sollte 8: Submitter-Button-Erkennung in `settings.js` integriert, um Test- und OAuth-Buttons funktionstüchtig zu machen.
- [x] Sollte 9: Local `_()` Übersetzungssystem in `settings.js` über `window.settingsTranslations` in `_shell.html` repariert.
- [x] Sollte 10: Duplikat-Erkennung Detailoptionen vollständig in `experten.html` gruppiert.
- [x] Sollte 11: 72 neue deutsche Übersetzungseinträge in `messages.po` eingepflegt und `de` Catalog kompiliert.
- [x] Sollte 12: Drift-Tests um Datenbank-Modelleigenschafts-Check (`test_model_properties_existence`) erweitert und alle Testfälle erfolgreich verifiziert.
- [x] Hygiene: Alle Whitespace-Fehler behoben und `scratch/` Hilfs-Verzeichnis vollständig entfernt.

### Belege
- pytest drift tests: `../../../.venv/bin/pytest -v tests/test_settings_drift.py` -> `5 passed in 0.94s`
- pybabel compile: `../../../.venv/bin/pybabel compile -d cps/translations -l de` -> Erfolgreich kompiliert.
- Syntax & lint check: `node --check cps/static/js/settings.js` & `python -m py_compile cps/settings_ui.py` -> OK.
- Whitespace-Check: `git diff --check origin/main..HEAD` -> Bestanden (keine Ausgaben).
- Working directory sauber: `git status --short --branch` -> Keine uncommitteten Änderungen, 100% sauber.

## 2026-07-05 — Kobo-Begriffe und UX-Texte glätten

- **Feature/Bug:** Kobo-Begriffe und UX-Texte zwischen Dashboard und Buchdetailseite glätten.
- **Branch / Worktree:** `feature/kobo-ux-smoothing`
- **Status:** Erfolgreich implementiert, unit-getestet (71/71 Tests bestanden) und manuell sowie per `git diff --check` verifiziert.

### Erledigt

- **Detailseite (`detail.html`)**:
  - `Aktueller Sync-Zustand (Ist auf Reader):` -> `Aktueller Sync-Zustand (Ist auf dem Reader):`
  - `Kobo-Sammlungen:` -> `Reader-Sammlungen:`
  - Tooltip für `no_source` -> `Keine Reader-Freigabe durch ein Regal` (statt `In keinem Kobo-Synchronisations-Regal`)
- **Dashboard (`kobo_dashboard.html`)**:
  - Panel-Überschrift `Kobo-Sammlungen` -> `Reader-Sammlungen`
  - Spaltentitel `Kobo-Sync` -> `Bücher übertragen`
  - Spaltentitel `Sync-berechtigt` -> `Darf auf den Reader`
  - Status `Display-Only` -> `Nur Sammlung anzeigen`
  - Beschreibung Zwei-Säulen-Sync: `Nur Bücher in Regalen mit Kobo-Sync-Häkchen werden übertragen.` -> `Nur Bücher in Regalen mit aktivierter "Bücher übertragen"-Option werden auf das Gerät geladen.`
  - Beschreibung "Nicht auf Kobo": `Diese Bücher bleiben in Alexandria, werden aber beim Kobo-Sync ausgelassen.` -> `Diese Bücher bleiben in Alexandria, werden aber bei der Kobo-Übertragung ausgelassen.`
  - Statusmeldung: `Deine Kobo-Synchronisation läuft sauber!` -> `Deine Kobo-Übertragung läuft sauber!`
  - Empty State `Magic Shelves` / `Kobo-Display` -> `Keine Regale oder automatischen Sammlungen sind für die Kobo-Anzeige konfiguriert.`
  - Filter-Button `In keiner Sammlung` -> `In keiner Reader-Sammlung (verwaist)`
  - Spaltentitel `Kobo-Sammlungen` -> `Reader-Sammlungen`
  - Tooltip für `no_source` -> `Keine Reader-Freigabe durch ein Regal`
  - Dropdown-Optionen `Immer auf Reader` / `Nie auf Reader` -> `Immer auf dem Reader` / `Nie auf dem Reader`
  - Statusspalte & AJAX `Auf Reader` / `Auf Reader (nicht mehr freigegeben)` -> `Auf dem Reader` / `Auf dem Reader (nicht mehr freigegeben)`
  - AJAX-Detail-Modal Texte zu Kobo-Sammlungen überall zu `Reader-Sammlungen` geglättet.
  - AJAX-Detail-Modal Fehlertext `Nicht im Kobo-Sync erlaubt (keine Kobo-Auswahltabelle...)` -> `Nicht für den Reader freigegeben (in keinem Regal mit Übertragungs-Freigabe enthalten)`
- **Unit-Tests (`test_kobo_detail_override.py`)**:
  - Assertion an das neue Label `Reader-Sammlungen:` angepasst.
- **Nachkontrolle**:
  - `git diff --check` fehlerfrei ausgeführt.
  - `grep_search` auf alte UI-Strings im geänderten Template-Scope ohne Treffer abgeschlossen.

### Belege

- Unit-Tests bestanden: `.venv/bin/pytest tests/unit/test_kobo_detail_override.py tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_explanation.py tests/unit/test_kobo_decoupling.py` (71 passed in 1.09s).
- `git diff --check` sauber.

## 2026-07-05 — Kobo-Transparenz auf der Buchdetailseite angleichen

- **Feature/Bug:** Kobo-Transparenz auf der Buchdetailseite an das Dashboard angleichen.
- **Branch / Worktree:** `feature/kobo-detail-transparency`
- **Status:** Implementiert und unit-getestet (54/54 Tests bestanden). `git diff --check` sauber.

### Erledigt

- **CSS & Badges**: Styling-Klassen für `.kobo-reasons-container` und `.kobo-reason-badge` in `detail.html` eingefügt.
- **Sammlungszeile**: „Kobo-Sammlungen:“-Reihe zur Statusübersicht hinzugefügt, die `kobo_actual_collections` auflistet.
- **Begründungs-Badges**: Textbasierte Erklärung durch kompakte, farbige Badges (Manuell, Regal, Automatische Sammlung, Ganze Bibliothek, Manuell blockiert, Ist im Archiv, Keine Kobo-Freigabe) ersetzt.
- **Warn-Badge**: Die Zusatzwarnung „Keine Reader-Sammlung“ integriert, gesteuert über `kobo_explanation.is_allowed_on_device and not kobo_explanation.kobo_actual_collections`.
- **Unit-Tests**: 3 Template-Rendering-Szenarien in `test_kobo_detail_override.py` implementiert, die das tatsächlich erzeugte HTML verifizieren.
- **Git Check**: `git diff --check` erfolgreich ausgeführt (keine Whitespace-Fehler).

### Belege

- Unit-Tests bestanden: `.venv/bin/pytest tests/unit/test_kobo_detail_override.py` (18 passed in 0.75s).
- `git diff --check` sauber.

## 2026-07-05 — Kobo-Reader-Sammlung-Warnung im Kobo-Dashboard

- **Feature/Bug:** Kobo-Reader-Sammlung-Warnung (Zusatzerklärung für Bücher, die auf den Reader dürfen, aber in keiner Reader-Sammlung sind).
- **Branch / Worktree:** `feature/kobo-reader-collection-warning`
- **Status:** Umgesetzt und getestet, in `main` gemerged.

### Erledigt

- **Badge & Tooltip-Implementierung**: Wenn ein Buch freigegeben ist (`is_allowed=True`/`is_allowed_on_device=True`), aber keine Kobo-Sammlungen hat, wird der Badge „Keine Reader-Sammlung“ samt Tooltip-Erklärung angezeigt.
- **AJAX-Handler-Erweiterung**: Der Badge wird auch live über JavaScript aktualisiert und bei `error_generating_explanation` stabil gehalten.
- **Unit-Tests**: Assertions im Template-Smoke-Test erweitert und neue Tests `test_workspace_book_warning_for_no_collections` (Datenstruktur) und `test_workspace_book_warning_renders_in_template` (Template-Snippet-Rendering) hinzugefügt.

### Belege

- Unit-Tests erfolgreich ausgeführt (70 Tests bestanden):
  ```
  tests/unit/test_kobo_dashboard.py PASSED
  tests/unit/test_kobo_explanation.py PASSED
  tests/unit/test_kobo_decoupling.py PASSED
  tests/unit/test_kobo_detail_override.py PASSED
  ```

## 2026-07-05 — Kobo-Dashboard: kompakte Begründungs-Badges im Arbeitsbereich

- **Feature/Bug:** Kobo-Dashboard: kompakte Begründungs-Badges im Arbeitsbereich
- **Branch / Worktree:** `feature/kobo-workspace-reason-badges`
- **Status:** Erledigt. Erfolgreich implementiert, getestet und lokal committet.

### Erledigt
- **Backend-Datenanpassung**: `release_sources` und `blocker_reasons` in `cps/kobo_dashboard.py` an das `workspace_books`-Array angehängt.
- **Template-Integration**: Jinja-Markup in `cps/templates/kobo_dashboard.html` eingebettet, um die Begründungs-Badges unter dem Buchtitel anzuzeigen. Text für Archiviert zu „Ist im Archiv“ präzisiert, `no_source` als „Keine Kobo-Freigabe“ benannt. Priorisierung (`never_override` > `archived` > `no_source`) implementiert.
- **AJAX-Aktualisierung**: jQuery-Handler erweitert, um bei Einstellungs-Dropdown-Änderung die Badges live zu aktualisieren. AJAX-Fallback bei `error_generating_explanation` abgesichert (Badges stabil halten).
- **Verifikation**: Zusätzliche Test-Assertions im Template-Smoke-Test und neuer Unit-Test `test_get_kobo_dashboard_data_reasons_and_sources_passed_to_workspace` hinzugefügt. Alle Tests grün (68 passed).

## 2026-07-05 — Kobo-Reader-Modell Phase 4: Overrides direkt im Dashboard-Arbeitsbereich editieren

- **Feature/Bug:** Kobo-Reader-Modell Phase 4 (Dashboard Workspace Aktionen: Overrides direkt im Dashboard-Arbeitsbereich editieren - UX-Politur)
- **Branch / Worktree:** `feature/kobo-reader-dashboard-override-edit`
- **Status:** Phase 4 vollständig implementiert, durch Alex freigegeben, nach `main` gemerged.

### Erledigt

- **Backend-Entkopplung & Fehler-Härtung**: Die Route `/kobo_auth/book/<book_id>/override` in `cps/kobo_auth.py` committet die DB-Änderung isoliert. Post-commit-Erklärungsfehler werden abgefangen und durch `None`-Werte für `is_allowed_on_device` und `is_synced` im Fallback-JSON signalisiert.
- **Frontend-UX & Filter-Verfeinerung**: Im AJAX-Erfolgs-Handler (`kobo_dashboard.html`) wird der aktive Filter erneut angewendet. Um zu verhindern, dass bei aktivem Filter „Manuelle Ausnahmen“ die Zeile sofort verschwindet, wenn ein Buch auf `auto` gestellt wird, bleiben Zeilen mit einer aktiven Undo-Aktion (`.kobo-undo-btn`) immer sichtbar. Der Undo-Link bleibt somit klickbar, bis der Benutzer einen anderen Filter wählt oder die Seite aktualisiert.
- **Erweiterte AJAX-Testabdeckung**: 3 zusätzliche Testmethoden für AJAX in `tests/unit/test_kobo_detail_override.py` implementiert, die unter anderem die Rückgabe von `None` bei post-commit Ausnahmen in der Kobo-Erklärung vollständig abdecken (insgesamt 7 neue Testmethoden).
- **Formatierungs- & Staging-Disziplin**: Gezielt gestaged, `dirs.json` blieb unstaged.

### Belege

- Unit-Tests bestanden: `.venv/bin/pytest tests/unit/test_kobo_detail_override.py tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_explanation.py tests/unit/test_kobo_decoupling.py` (67 passed in 0.90s)

## 2026-07-04 — Kobo-Reader-Modell Phase 3: Arbeitsbereich „Bücher auf dem eReader“ (Read-Only)

- **Feature/Bug:** Kobo-Reader-Modell Phase 3: Arbeitsbereich „Bücher auf dem eReader“ (Read-Only)
- **Branch / Worktree:** `feature/kobo-reader-dashboard-workspace`
- **Status:** Phase 3 vollständig implementiert, lokal committet und alle 60 Unit-Tests erfolgreich verifiziert.

### Erledigt

- **Datenbank- & Batch-Optimierung**: `get_kobo_books_sync_explanations(user_id, book_ids)` in `cps/kobo.py` implementiert, um N+1 Queries beim Batch-Status-Abruf im Dashboard zu verhindern. Sie nutzt SQL-Batches und eager loading für Buchverknüpfungen.
- **Einzelfunktions-Refactoring**: `get_kobo_book_sync_explanation` refactored, um intern den Batch-Helper aufzurufen und Logikdrift auszuschließen. Zur 100%igen Kompatibilität mit existierenden Test-Mocks weicht die Funktion für `n = 1` automatisch auf die bewährten Einzelabfragen ab.
- **Dashboard-Datenaufbereitung**: `get_kobo_dashboard_data` in `cps/kobo_dashboard.py` erweitert, um die `workspace_books` (Mischung aus auf dem Gerät befindlichen und manuell konfigurierten/erlaubten Büchern) zu berechnen und an das Template zu übergeben. Im Full-Sync-Modus wird die Grundmenge performant auf `KoboSyncedBooks` + `KoboBookOverride` limitiert.
- **Workspace UI-Panel**: Ein neues Dashboard-Panel „Arbeitsbereich: Bücher auf dem Reader“ in `cps/templates/kobo_dashboard.html` mit einer performanten Bootstrap-Tabelle und jQuery-Filtertasten (Alle auf dem Reader / Verwaist / Ausstehender Sync / Manuelle Ausnahmen) implementiert.
- **Übersetzungen**: Neue deutsche UI-Labels und Tooltips in `messages.po` übersetzt und zu `.mo` kompiliert.
- **Testabdeckung**: 3 neue Golden-Case Unit-Tests in `tests/unit/test_kobo_dashboard.py` hinzugefügt, die den Batch-Helper, passive Sammlungszuordnung und Full-Sync-Dashboardgrenzen absichern. Alle 60 Kobo-Tests bestanden erfolgreich.

### Belege

- Unit tests passed: `.venv/bin/pytest tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_explanation.py tests/unit/test_kobo_decoupling.py tests/unit/test_kobo_detail_override.py`
- git commit: `5b910e8` (feature/kobo-reader-dashboard-workspace)

## 2026-07-04 — Kobo-Reader-Modell Phase 2: UI-Slice (Buchdetailseite & Overrides)

- **Feature/Bug:** Kobo-Reader-Modell Phase 2 (Buchdetailseite & Overrides)
- **Branch / Worktree:** `feature/kobo-detail-page-override`
- **Status:** Phase 2 vollständig implementiert, übersetzt, lokal getestet und alle 57 Unit-Tests erfolgreich verifiziert.

### Erledigt

- **Backend-Erweiterung**: `get_kobo_book_sync_explanation` in `cps/kobo.py` gibt jetzt `"reader_override"` zurück (sowohl regulär als auch im Not-found-Fall).
- **POST-Route**: `@kobo_auth.route("/book/<int:book_id>/override")` mit `@user_login_required` und vollständiger CSRF- und Scope-Sichtbarkeitsprüfung über `cdb.common_filters` in `cps/kobo_auth.py` implementiert. Ungültige Werte werden mit `400` abgewiesen, unautorisierte via standardmäßiges Flask-Login-Verhalten.
- **show_book-Integration**: `show_book` in `cps/web.py` lädt die Kobo-Erklärung und übergibt sie an das Detail-Template.
- **UI-Slice**: Kobo-Sync-Panel in `cps/templates/detail.html` am Ende des Metadaten-Bereichs eingebettet. Es visualisiert getrennt die Übertragungs-Freigabe („Freigabe erteilt“ vs. „Bleibt in der Cloud“), den aktuellen Sync-Zustand des Geräts und bietet die Auswahl über Radio-Buttons samt CSRF-geschütztem Absende-Button.
- **Archiv-Semantik**: Archiv-Schranken-Prüfung integriert (roter/gelber Warnhinweis bei archivierten Büchern).
- **Übersetzungen**: Neue UI-Texte und Route-Flash-Nachrichten in `cps/translations/de/LC_MESSAGES/messages.po` übersetzt und kompiliert.
- **Testabdeckung**: Neue Testdatei `tests/unit/test_kobo_detail_override.py` mit 10 neuen Tests (always, never, auto, invalid, Scope, template context sowie echten CSRF- und Auth-Integrationstests über den Flask-Client) erstellt. Alle 57 Kobo-Tests bestehen fehlerfrei.

### Belege

- Unit tests passed: `.venv/bin/pytest tests/unit/test_kobo_explanation.py tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_decoupling.py tests/unit/test_kobo_detail_override.py`
- Compilation passed: `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de`
- Syntax- und Git Checks fehlerfrei (inklusive `git diff --check`).

## 2026-07-04 — Kobo-Reader-Modell Phase 1: Datenmodell & Sync-Eligibility

- **Feature/Bug:** Phase 1 des neuen Kobo-Reader-Modells (Datenmodell & Sync-Eligibility).
- **Branch / Worktree:** `feature/kobo-reader-override-eligibility`
- **Status:** Phase 1 vollständig implementiert, lokal committet und alle 47 Unit-Tests erfolgreich verifiziert.

### Erledigt

- Neues Datenmodell `KoboBookOverride` (Tabelle `kobo_book_override` mit SQLAlchemy-Schema) in `cps/ub.py` definiert und in `add_missing_tables()` integriert.
- Helper-Methoden `get_kobo_blocked_book_ids(user_id)` und die aktualisierte `get_kobo_allowed_book_ids(user_id)` in `cps/kobo.py` implementiert, um reader-spezifische Overrides (`always` / `never` / `auto`) zu verarbeiten. `Kobo: Ausgeschlossen` wird nicht mehr als active Sync-Entscheidung verwendet.
- Kobo-Live-Synchronisation in `cps/kobo.py` (`HandleSyncRequest()`) angepasst: blockierte Bücher werden bei der Deletionslogik, den geänderten Büchern (`changed_entries`), den geänderten Leseständen (`changed_reading_states`) sowie in normalen und magischen Kobo-Sammlungen (`sync_shelves()`) in beiden Sync-Modi (Full & Selective Sync) ausgeschlossen.
- Kobo-DELETE Request-Handler `HandleBookDeletionRequest()` angepasst: sowohl im Full Sync als auch im Selective Sync wird nun `reader_override = "never"` gesetzt.
- Dashboard-Statistiken in `cps/kobo_dashboard.py` (`get_kobo_dashboard_data()`) angepasst: Zähler und Warnungen ziehen `never`-Blocker ab; `allowed_book_count` berücksichtigt nun Kobo-Format-Filterung im Full-Sync-Pfad und schließt blockierte IDs direkt im SQL-Filter aus, um Subtraktionsfehler bei nicht sichtbaren Büchern zu verhindern.
- Die Dashboard-Aktionen "Nicht auf Kobo" und "Wieder erlauben" in `cps/kobo_auth.py` auf `KoboBookOverride` umgestellt. `allow_excluded_book()` löscht nur noch `never`-Overrides, wodurch `always` geschützt wird.
- Behebung des `NameError` bei `KOSyncProgress` in `add_missing_tables()` durch lokalen Import.
- UI-Templates (`kobo_dashboard.html`) bereinigt: "Kobo: Ausgeschlossen" durch "Nicht auf Kobo" ersetzt, JS-Modal um `never_override` Blocker erweitert.
- Workflow-Dokumentation `docs/alexandria/kobo-workflow.md` aktualisiert und das alte Hilfsregal historisch eingeordnet. Ältere Dokumente (`release-roadmap.md`, `ui-ideen.md`) von Rest-Referenzen bereinigt.
- Unit-Tests in `tests/unit/test_kobo_decoupling.py`, `tests/unit/test_kobo_explanation.py` und `tests/unit/test_kobo_dashboard.py` erweitert und auf das neue Overrides-Modell angepasst (inklusive erweitertem Migrationstest für Unique Constraints, Dashboard-Full-Sync-Abzugs-Tests und Regressionsschutz-Tests).
- Kompilierung und Syntaxprüfung (`py_compile`) sowie `git diff --check` fehlerfrei durchgeführt.

### Nächster Schritt

- Phase 2 (UI und Bearbeitbarkeit auf der Buchdetailseite) angehen, sobald das Feedback vorliegt.

## 2026-07-04 — Kobo-Reader-Modell (Konzept)

- **Feature/Bug:** Konzeptdokument zur Vereinfachung des Kobo-/Reader-Modells (Grundlage für künftige Features).
- **Branch / Worktree:** `main` (zuvor `docs/kobo-reader-model`)
- **Status:** Konzeptdokument erstellt, verifiziert und in `main` gemergt.

### Erledigt

- Konzeptdokument `docs/alexandria/kobo-reader-model.md` erstellt.
- Mentales Modell präzisiert: „Regale geben Vorgaben. Bücher entscheiden. Regale können auf dem Reader als Sammlungen angezeigt werden.“
- Begrifflichkeiten und Glossar für deutsche UX-Begriffe etabliert.
- Unabhängige eReader-Sammlungssteuerungen per Regal (`kobo_sync` und `kobo_display`) entkoppelt.
- Globales tri-state Buchentscheidungs-Modell (Automatisch / Immer / Nie) inklusive Prioritätskaskade konzipiert.
- Text-Mockups für Dashboard-Batch-Bearbeitung, Buchdetail-Sektion und den Arbeitsbereich „Bücher auf dem Reader“ entworfen.
- Alle Review-Findings erfolgreich behoben (Whitespaces gereinigt, Glossardefinitionen und Mockup-Filter widerspruchsfrei gelöst).

### Belege

- git check passed: `git diff --check main...HEAD`
- Konzept in `main` gemergt und auf origin gepusht.

## 2026-07-03 — Kobo-Dashboard: Live-Smoke-Test und JS-Ladefix

- **Feature/Bug:** Live-Smoke-Test und Fix der Kobo-Dashboard-Modal-Initialisierung.
- **Branch / Worktree:** `fix/kobo-dashboard-js-load-order`
- **Status:** Live-Bug gefunden, behoben und lokal verifiziert.

### Erledigt

- Live-Test auf `http://localhost:8085/kobo_auth/dashboard` durchgeführt.
- Bug gefunden: Dashboard-Click-Handler liefen vor global geladenem jQuery; dadurch öffneten die Info-Icons kein Modal (`ReferenceError: $ is not defined`).
- Template-Fix: Dashboard-JavaScript aus `block body` in den dafür vorgesehenen `block js` verschoben.
- Regressionstest ergänzt, der die Script-Block-Reihenfolge absichert.
- Live-Smoke-Test grün: Buch-Info, Sammlungsdetails und verschachtelter Buchdetails-Link öffnen die erwarteten Modals.

### Belege

- Unit tests passed: `.venv/bin/pytest tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_explanation.py`
- git check passed: `git diff --check`
- Browser smoke passed: `Buch_A` Detailmodal, `Leere-Normale-Kollektion` Sammlungsmodal, `Buch_B` Nested-Detailmodal.

## 2026-07-03 — Kobo-Dashboard: Sync-Transparenz (UI-Teil)

- **Feature/Bug:** Frontend-UI für Kobo-Synchronisations-Transparenz (Roadmap-Punkt 1, UI-Teil).
- **Branch / Worktree:** `feature/kobo-sync-explanation-ui`
- **Status:** Implementiert, Review-Findings behoben und erfolgreich getestet.

### Erledigt

- Backend-Routen `/kobo_auth/book/<id>/explanation` und `/kobo_auth/collection/<id>/explanation` in `cps/kobo_auth.py` mit User-Ownership-Schranke und Buchtitel-Anreicherung implementiert.
- Bootstrap Modal in `cps/templates/kobo_dashboard.html` mit AJAX-Logik zur Visualisierung der Synchronisations-Transparenz pro Buch und Sammlungs-Status eingebunden.
- **Review-Fix (Blocker):** Der Detail-Link für Kobo-Sammlungen wird jetzt angezeigt, wenn mindestens ein Buch nicht freigegeben ist (`col.allowed_books < col.total_books`), unabhängig von der Anzahl der Bücher im Ausschlussregal.
- **Review-Fix (Reverse-Proxy):** AJAX-Pfade im JavaScript-Teil werden dynamisch mittels `url_for(...)` generiert, um Inkompatibilitäten bei Reverse-Proxy-Präfixen zu verhindern.
- **Review-Fix (Magic-Shelf-Label):** Magic-Shelf-Kategorien im Buchmodal werden anhand von `magic_shelf` korrekt als „automatisch“ (statt fälschlicherweise als „normal“) gelabelt.
- **Review-Fix (Trailing Whitespace):** Sämtliche Trailing Whitespaces wurden aus den Test- und HTML-Dateien entfernt (`git diff --check main` läuft fehlerfrei durch).
- Neue Testabdeckung in `tests/unit/test_kobo_dashboard.py` (Vollsync, Security-Checks, alle Blocker-Gründe) erfolgreich integriert.
- Übersetzungskatalog für Deutsch neu kompiliert.

### Belege

- All unit tests passed: `.venv/bin/pytest tests/unit/test_kobo_dashboard.py tests/unit/test_kobo_explanation.py`
- git check passed: `git diff --check main`
- Compiled catalog: `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de`

## 2026-07-03 — Kobo-Sync Erklärungslogik (Backend-Basis)

- **Feature/Bug:** Backend-Erklärlogik + Tests für Kobo-Synchronisations-Transparenz (Roadmap-Punkt 1, erster Schritt).
- **Branch / Worktree:** `feature/kobo-sync-explanation-backend`
- **Status:** Backend-Logik und Tests erfolgreich implementiert und verifiziert.

### Erledigt

- Backend-Funktion `get_kobo_book_sync_explanation(user_id, book_id)` in `cps/kobo.py` implementiert, die den genauen Status eines Buchs bzgl. Auswahl, Ausschlussregal, Archivierung, Kobo-Sichtbarkeit und Sammlungen aufschlüsselt.
- Umfassende Unit-Tests in `tests/unit/test_kobo_explanation.py` erstellt, die alle 10 Basisfälle und Kantenfälle (z.B. Magic-Shelf-Deaktivierung, 1000er-Cap, Archivierungs-Semantik) prüfen und erfolgreich durchlaufen.
- Bestehende Kobo-Decoupling-Tests erfolgreich verifiziert (keine Regressionen).

### Nächster Schritt

- Frontend-UI für die Anzeige dieser Erklärlogik aufbauen (z. B. Detail-Overlay/Modal oder Anzeigebereich im Dashboard).

## 2026-07-03 — Kobo-Dashboard: Nicht-auf-Kobo-Hinweise

- **Feature/Bug:** Sammlungen zeigen ruhigere Hinweise, wenn enthaltene Buecher durch `Nicht auf Kobo` blockiert oder nicht fuer Kobo ausgewaehlt sind.
- **Branch / Worktree:** `feature/kobo-dashboard-blocked-collection-warnings`
- **Status:** Implementiert und gezielt getestet.

### Erledigt

- Dashboard-Sammlungen berechnen `blocked_books` separat von `allowed_books`.
- Collection-Tabelle zeigt eine eigene Spalte `Nicht auf Kobo`.
- Hinweis `BLOCKED_BOOKS_IN_COLLECTION` zeigt, wenn eine Sammlung blockierte Buecher enthaelt.
- Generische `nicht fuer Kobo ausgewaehlt`-Hinweise zaehlen blockierte Buecher nicht doppelt.
- System-Sektion spricht von `Hinweisen` statt `Warnungen`; nur echte Fehler bleiben als `Kritisch` sichtbar.
- Deutsche Singular-/Pluralform fuer Buch-Zaehler korrigiert (`1 Buch`, nicht `1 Buecher`).
- Kontrast der hellen Dashboard-Panels, Tabellen und Hinweisboxen verbessert.
- Gelbe Warnungsoptik im System-Hinweisbereich und Warn-Dreieck in der Sammlungstabelle durch neutrale Hinweisoptik ersetzt.
- Leerzustand im Bereich `Nicht auf Kobo` auf die neue Begrifflichkeit umgestellt.
- Babel-Vorlage und deutscher Katalog fuer die neuen Dashboard-Texte aktualisiert.
- Doku in `docs/alexandria/kobo-workflow.md` und `docs/alexandria/ui-ideen.md` aktualisiert.
- Unit-Tests fuer blocked-count, Hinweis-Typ, Singularform und Template-Smoke angepasst.

### Belege

- `.venv/bin/pytest tests/unit/test_kobo_dashboard.py` erfolgreich.
- `.venv/bin/pytest tests/unit/test_kobo_decoupling.py` erfolgreich.
- `PYTHONPYCACHEPREFIX=/tmp/cwa-alexandria-pycache .venv/bin/python -m py_compile cps/kobo_dashboard.py` erfolgreich.
- `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de` erfolgreich.
- Relevanter Katalogvergleich: keine fehlenden Kobo-Dashboard-Strings im deutschen Katalog.
- `git diff --check` fehlerfrei.

## 2026-07-03 — Kobo-Dashboard: Manuell Nicht auf Kobo

- **Feature/Bug:** Gegenaktion zum Wiederzulassen: Buecher im Dashboard manuell aus der Kobo-Auswahl ausschliessen.
- **Branch / Worktree:** `feature/kobo-dashboard-block-action`
- **Status:** Implementiert und gezielt getestet.

### Erledigt

- Dashboard liefert im Zwei-Saeulen-Sync eine Liste `Fuer Kobo ausgewaehlt`.
- Neue POST-Aktion `Nicht auf Kobo` verschiebt ein erlaubtes Buch in `Kobo: Ausgeschlossen`.
- Route ist auf Zwei-Saeulen-Sync begrenzt und vermeidet doppelte/unsinnige Ausschluesse.
- UX-Texte im Dashboard vereinheitlicht: `Fuer Kobo ausgewaehlt`, `Nicht auf Kobo`, `Wieder fuer Kobo erlauben`.
- Babel-Vorlage und deutscher Katalog fuer die neuen Texte aktualisiert.
- Doku in `docs/alexandria/kobo-workflow.md` und `docs/alexandria/ui-ideen.md` aktualisiert.
- Unit-Tests fuer erlaubte Dashboard-Buecher, Blockier-Route und Template-Smoke ergaenzt.

### Belege

- `.venv/bin/pytest tests/unit/test_kobo_dashboard.py` erfolgreich.
- `.venv/bin/pytest tests/unit/test_kobo_decoupling.py` erfolgreich.
- `PYTHONPYCACHEPREFIX=/tmp/cwa-alexandria-pycache .venv/bin/python -m py_compile cps/kobo_auth.py cps/kobo_dashboard.py` erfolgreich.
- `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de` erfolgreich.
- Relevanter Katalogvergleich: keine fehlenden Kobo-Auth-/Dashboard-Strings im deutschen Katalog.
- `git diff --check` fehlerfrei.

## 2026-07-03 — Kobo-Dashboard Smoke-Test und Politur

- **Feature/Bug:** Smoke-Test und kleine UI-Politur fuer die Wiederzulassen-Sektion.
- **Branch / Worktree:** `feature/kobo-dashboard-smoke-polish`
- **Status:** Implementiert und gezielt getestet.

### Erledigt

- Dashboard-Sektion `Nicht auf Kobo` bleibt auch ohne blockierte Buecher sichtbar.
- Sektion zeigt die Anzahl blockierter Buecher, eine kurze Statusbeschreibung und einen Leerzustand.
- Button `Wieder erlauben` hat einen klaren Tooltip fuer den naechsten Sync.
- Smoke-Tests fuer Dashboard-Render-Kontext und Template-Wiederzulassen-Flow ergaenzt.
- Babel-Vorlage und deutscher Katalog fuer die neuen Dashboard-Texte aktualisiert.
- `docs/alexandria/ui-ideen.md` nachgefuehrt.

### Belege

- `.venv/bin/pytest tests/unit/test_kobo_dashboard.py` erfolgreich.
- `.venv/bin/pytest tests/unit/test_kobo_decoupling.py` erfolgreich.
- `PYTHONPYCACHEPREFIX=/tmp/cwa-alexandria-pycache .venv/bin/python -m py_compile cps/kobo_auth.py cps/kobo_dashboard.py` erfolgreich.
- `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de` erfolgreich.
- Relevanter Katalogvergleich: keine fehlenden Kobo-Dashboard-Strings im deutschen Katalog.
- `git diff --check` fehlerfrei.
- Lokaler Browser-Smoke-Test auf `http://localhost:8085` erfolgreich: DELETE simuliert, Buch erscheint in der Sektion "Nicht auf Kobo", Badge-Zähler erhöhen sich, Klick auf "Wieder erlauben" löscht den DB-Eintrag fehlerfrei und setzt `last_modified` korrekt, Counter sinken wieder auf 0.

## 2026-07-03 — Wiederzulassen aus Kobo-Ausgeschlossen

- **Feature/Bug:** Wiederzulassen-Aktion fuer Buecher in `Kobo: Ausgeschlossen`.
- **Branch / Worktree:** `feature/kobo-reallow-excluded-book`
- **Status:** Implementiert und gezielt getestet.

### Erledigt

- Kobo-Dashboard zeigt Buecher aus `Kobo: Ausgeschlossen` als blockierte Buecher an.
- Sync-Statistik zeigt die Anzahl blockierter Buecher.
- POST-Aktion `Wieder erlauben` entfernt passende `BookShelf`-Eintraege aus allen gleichnamigen Ausschlussregalen des aktuellen Benutzers.
- Route setzt die `ub_shelf`-Relationship explizit vor dem Delete, damit der bestehende `before_flush`-Hook sicher funktioniert.
- Unit-Tests fuer Dashboard-Daten und Wiederzulassen-Route ergaenzt.
- Doku in `docs/alexandria/kobo-workflow.md` und `docs/alexandria/ui-ideen.md` aktualisiert.
- Babel-Vorlage `messages.pot` aktualisiert und deutsche Kobo-Dashboard-/Wiederzulassen-Strings in `cps/translations/de/LC_MESSAGES/messages.po` ergaenzt.
- UI-Tippfehler `Schnittstelle active` zu `Schnittstelle aktiv` korrigiert.

### Belege

- `.venv/bin/pytest tests/unit/test_kobo_dashboard.py` erfolgreich.
- `.venv/bin/pytest tests/unit/test_kobo_decoupling.py` erfolgreich.
- `PYTHONPYCACHEPREFIX=/tmp/cwa-alexandria-pycache .venv/bin/python -m py_compile cps/kobo_auth.py cps/kobo_dashboard.py` erfolgreich.
- `.venv/bin/python -m babel.messages.frontend compile -d cps/translations -l de` erfolgreich.
- Relevanter Katalogvergleich: keine fehlenden Kobo-/Dashboard-Strings im deutschen Katalog.
- `git diff --check` fehlerfrei.

## 2026-07-03 — Smoke-Test Kobo-Ausgeschlossen und Runtime-Fix

- **Feature/Bug:** Echter lokaler Smoke-Test fuer `Kobo: Ausgeschlossen` nach PR #9.
- **Branch / Worktree:** `test/kobo-exclusion-smoke`
- **Status:** Smoke-Test erfolgreich abgeschlossen; dabei gefundenen Runtime-Fehler eng behoben.

### Erledigt

- Lokale Docker-Testumgebung auf `http://localhost:8085` genutzt.
- Bestehende lokale Testdaten verwendet: `Buch_A` war ueber `Kobo-Freigabe` erlaubt und in `kobo_synced_books` als synchronisiert getrackt.
- Erster echter Kobo-DELETE reproduzierte HTTP 500: Der neue `BookShelf`-Eintrag wurde nur ueber die Fremdschluessel-ID erzeugt, wodurch der bestehende `before_flush`-Hook keine `ub_shelf`-Relationship sah.
- Fix in `cps/kobo.py`: Der selektive DELETE-Pfad haengt neue Ausschluss-Eintraege ueber `exclusion_shelf.books.append(ub.BookShelf(book_id=...))` an.
- Unit-Test angepasst, damit die Relationship-Nutzung im selektiven DELETE abgesichert ist.
- Zweiter echter Kobo-DELETE fuer `Buch_A` lieferte `204 NO CONTENT`.
- Echte Sync-Antwort lieferte keine New-/Changed-Entitlements fuer `Buch_A`.
- DB-Pruefung: `Kobo: Ausgeschlossen` wurde mit `kobo_sync=0`, `kobo_display=0` angelegt und enthaelt Buch 2.

### Belege

- `curl -X DELETE .../v1/library/51a96fae-5e78-474f-b0bc-4c83dc12fec0` zuerst `500`, nach Fix `204`.
- `curl .../v1/library/sync` nach Fix `200`; Payload enthaelt keine `Buch_A`-/UUID-/Entitlement-Treffer.
- `sqlite3 local-dev/config/app.db`: `31|Kobo: Ausgeschlossen|1|0|0` und `2|31`.
- `.venv/bin/pytest tests/unit/test_kobo_decoupling.py` erfolgreich.
- `.venv/bin/pytest tests/unit/test_kobo_dashboard.py` erfolgreich.
- `git diff --check` fehlerfrei.

## 2026-07-02 — Kobo-Loeschen als Ausschlussregal (Kobo: Ausgeschlossen)

- **Feature/Bug:** Kobo-Loeschen als Ausschlussregal (Kobo: Ausgeschlossen) implementiert, gehärtet und getestet.
- **Branch / Worktree:** `feature/kobo-exclusion-shelf`
- **Status:** Erfolgreich abgeschlossen. Alle 14 Unit-Tests und Dashboard-Tests laufen grün.

### Erledigt

- **System-Exclusion-Shelf Helper:** `get_or_create_kobo_exclusion_shelf(user_id)` implementiert. Es stellt sicher, dass alle existierenden Regale mit dem Namen `Kobo: Ausgeschlossen` auf `kobo_sync=False` and `kobo_display=False` zurückgesetzt werden, um eReader-Sammlungs-Synchronisationen robust zu verhindern.
- **Selective Deletion Path:** `HandleBookDeletionRequest` trägt Bücher bei selektivem Sync ins Ausschlussregal ein und invalidiert den Magic-Shelf Cache, anstatt das Buch aus der Calibre-Bibliothek zu entfernen.
- **Strikte Deletion-Fehlerbehandlung:** Datenbankfehler im selektiven Deletion-Pfad führen via `abort(500)` zum Abbruch und Rollback; `remove_synced_book()` wird erst nach erfolgreichem Ausschluss ausgeführt.
- **Allowed Books Abzug:** `get_kobo_allowed_book_ids(user_id)` zieht alle Bücher aus allen Regalen namens `Kobo: Ausgeschlossen` lesend und robust ab (keine Schreibeffekte).
- **Full-Sync Unverändert:** Die Full-Sync/Archivierungslogik wurde nicht verändert.
- **Automatisierte Tests:** 6 neue Unit- und Integrationstests verifizieren den Abzug, das selektive DELETE, Fehlerverhalten im DB-Pfad, Bereinigung bestehender Regale, die Full-Sync-Archivierungsberechtigung und den Device-Entitlement-Abzug mit `IsArchived: True`.

### Belege

- Alle 14 Unit-Tests in `test_kobo_decoupling.py` erfolgreich ausgeführt.
- Alle 4 Unit-Tests in `test_kobo_dashboard.py` erfolgreich ausgeführt.
- `git diff --check` fehlerfrei.

## 2026-07-02 — Kobo-Loeschen als Ausschlussregal

- **Feature/Bug:** Kobo-Loeschen als Ausschlussregal-Entscheidung dokumentieren.
- **Branch / Worktree:** `docs/kobo-delete-exclusion-shelf` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Abgeschlossen. Entscheidung dokumentiert; noch keine Codeaenderungen.

### Erledigt

- **Produktentscheidung:** DELETE direkt vom Kobo bedeutet keine Bibliotheksloeschung, sondern Ausschluss aus der Kobo-Synchronisation.
- **Ausschlussregal:** `Kobo: Ausgeschlossen` als bevorzugtes System-/Steuerregal dokumentiert; klarer als ein allgemeines `Archiv`.
- **Sync-Regel:** Kobo-Erlaubnis wird kuenftig als einschliessende Quellen minus Ausschlussregal gedacht.
- **UI-Idee:** Kobo-Auswahl soll blockierte Buecher sichtbar kennzeichnen und eine Aktion zum Wiederzulassen anbieten.
- **Mini-Spike:** Naechste technische Umsetzung in kleinen Schritten dokumentiert: System-Regal-Hilfslogik, DELETE-Endpunkt, `get_kobo_allowed_book_ids()`-Abzug und fokussierte Tests.

### Belege

- `docs/alexandria/kobo-workflow.md` und `docs/alexandria/ui-ideen.md` lokal geprueft.
- `git diff --check` fehlerfrei.

## 2026-07-02 — Ideengeber-Audit externe Forks

- **Feature/Bug:** Ideengeber-Audit fuer externe CWA-/Companion-Forks.
- **Branch / Worktree:** `docs/ideengeber-audit` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Abgeschlossen. Audit-Einordnung dokumentiert; keine Codeaenderungen.

### Erledigt

- **Domoel/Calibre-Web-Automated**: Als Kobo-Sync-Ideengeber bewertet. Ergebnis: Idee zur Entfernungslogik relevant, konkreter Patch zu gross und zu riskant fuer direkte Uebernahme.
- **sempai-san/cwa-nexus**: Als Multi-Library-Architekturbeispiel bewertet. Ergebnis: spaeter interessant, aktuell zu breit fuer Alexandrias Kobo-Fokus.
- **jmarmstrong1207/Calibre-Web-Auto**: Als Produktprinzip "manueller Ingest statt Magie" im Backlog vermerkt.
- **doen1el/calibre-web-companion**: Als spaetere UX-/Companion-Inspiration im Backlog vermerkt.
- **Roadmap-Check**: Keine Roadmap-Datei gefunden; Backlog-Notizen deshalb in `docs/alexandria/fork-audit.md` dokumentiert.

### Belege

- GitHub-Repo-Metadaten und Patch-Diffs per `curl` geprueft.
- Lokaler Kobo-Sync-Pfad in `cps/kobo.py` mit Domoels Patch-Idee abgeglichen.
- `git diff --check` fehlerfrei.

## 2026-07-02 — Lokale Docker-Dev Bugfixes (Regal-500, Deutsch-L10n, Dashboard-Theme-Readability)

- **Feature/Bug:** Lokale Docker-Dev Bugfixes (Regal-500, Deutsch-L10n, Dashboard-Theme-Readability)
- **Branch / Worktree:** `fix/local-dev-bugs` in `/Users/alex/Documents/Programmierungsprojekte/cwa-alexandria`
- **Status:** Erfolgreich abgeschlossen. Lokale Docker-Dev Bugfixes wurden implementiert, getestet und lokal committed.

### Erledigt

- **Shelf HTTP 500 Fix**: TypeError in `render_title_template` behoben, indem `kobo_sync_enabled` per `kwargs.setdefault` gesetzt wird, wenn nicht bereits von Aufrufern übergeben.
- **L10n Deutsch/Mehrsprachigkeit Fix**: Automatisches Übersetzen/Kompilieren der `.po` in `.mo` Dateien im Startup-Skript `cwa-init` ergänzt, falls mindestens eine `.mo`-Datei im Übersetzungsbaum fehlt (was durch den Host-Mount in local dev der Fall ist). Dies erzeugt alle `.mo` Dateien lokal auf dem Host, so dass sie in Git ignoriert bleiben aber im Container funktionieren. Lokalen Dev-Workflow in `local-development.md` dokumentiert.
- **Dashboard Theme/Kontrast**: Custom Stylesheet in `kobo_dashboard.html` integriert, das Tabellen-Zeilen, Badges und System-Warnungen auch im dunklen `caliBlur` Theme mit klarem Kontrast und ansprechendem Premium-Design anzeigt.
- **Tests**: Unit-Tests in `test_kobo_decoupling.py` um einen Testfall für das default-passing von `kobo_sync_enabled` in `render_title_template` erweitert. Alle 21 Kobo-/Magic-Shelf-Tests erfolgreich lokal ausgeführt.

### Belege

- Alle 21 Unit-Tests laufen grün.
- `git diff --check` fehlerfrei bereinigt.

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
