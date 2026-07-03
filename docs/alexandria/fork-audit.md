# Fork-Audit

Dieses Dokument sammelt, was vor der ersten Codeaenderung am Calibre-Web-Automated-Fork geprueft werden soll.

## Ausgangspunkt

Voraussichtlicher Upstream: `crocodilestick/Calibre-Web-Automated`.

Der Upstream muss noch lokal geklont oder als GitHub-Fork angelegt werden. Dieses Projekt enthaelt bisher nur die Planungs- und Projektstruktur.

## Bereits recherchierte Punkte & Review-Ergebnisse

- **Testlage**: Es existieren einige Kobo-Unit-Tests wie `test_kobo_sync_timestamps.py` und `test_kobo_cover_image_id.py`. Es gibt jedoch keine erkennbare Testabdeckung für Magic Shelves, den Query-Builder (`build_filter_from_rule()`) oder die Kobo-Erlaubnislogik.
- **Magic-Shelf-Regeln**: Diese sind im aktuellen CWA auf eine feste Feldliste begrenzt. Eine Regel für normale Regale wurde nicht gefunden.
- **Risiko bei breiten Regeln**: Die Magic-Shelf-Collection-Erzeugung nutzt in `kobo.py` bei `get_books_for_magic_shelf(...)` eine feste Seitengröße von `page_size=1000`. Sehr breite Regeln können Kobo-Sammlungen daher stillschweigend abschneiden, wenn mehr als 1000 Bücher matchen.
- **sync_shelves()-Bug**: Im Code wurde eine verdächtige Stelle gefunden: `not ub.Shelf.kobo_sync` wird verwendet. Das ist für SQLAlchemy-Queries potenziell fehlerhaft/unpräzise. Vermutlich sollte stattdessen `ub.Shelf.kobo_sync == False` (oder eine andere explizite SQL-Bedingung) genutzt werden. Dies soll im ersten Mini-Spike per Test abgesichert und behoben werden.
- **Kobo-Sync-Verhalten**: Kobo-Sync berücksichtigt normale Regale und Magic Shelves, wenn sie für Kobo-Sync aktiviert sind. Breite Magic Shelves sind riskant, weil sie unkontrolliert viele Bücher freigeben können.

## Andere Forks als Ideengeber

- `Domoel/Calibre-Web-Automated`: Kobo-nahe Idee, insbesondere erweiterte Loesch-/Sync-Mechanik.
- `sempai-san/cwa-nexus`: Multi-Library-Ansatz, eher Architektur-Idee als direkte UI-Basis.
- `jmarmstrong1207/Calibre-Web-Auto`: Mehr manuelle Kontrolle beim Ingest, passt als Produktprinzip.
- `doen1el/calibre-web-companion`: Kein CWA-Fork, aber moegliche UI-Inspiration.

Diese Forks sind nach aktuellem Eindruck keine bessere Basis als der Upstream, aber gute Quellen fuer einzelne Ideen.

### Ideengeber-Audit vom 2026-07-02

Es gibt aktuell keine eigene Roadmap-Datei im Repo. Bis eine Roadmap angelegt
wird, bleiben die Ideengeber-Einordnungen hier als Backlog-Notiz.

#### Domoel/Calibre-Web-Automated

**Status:** Als Idee relevant, nicht als Patch uebernehmen.

Der Fork ist nur wenige Commits vor Upstream und der zentrale Commit `fix kobo
sync` behandelt genau den fuer Alexandria interessanten Punkt: Wenn ein Buch
laut lokaler Tracking-Tabelle bereits auf dem Kobo ist, aber nicht mehr in der
aktuell erlaubten Kobo-Menge liegt, wird ein archiviertes `ChangedEntitlement`
an den Kobo gesendet und der Eintrag aus `KoboSyncedBooks` entfernt.

Der konkrete Patch ist fuer Alexandria trotzdem kein guter Uebernahme-Kandidat:

- Er ersetzt grosse Teile von `cps/kobo.py` statt eine kleine, testbare Aenderung
  zu isolieren.
- Er entfernt die gekapselte Timestamp-Hilfslogik aus `kobo_sync_utils.py` und
  fuehrt die Logik inline weiter.
- Er vereinfacht `HandleInitRequest()` und `NATIVE_KOBO_RESOURCES()` stark,
  wodurch bestehende Upstream-Fallbacks, Header und Proxy-Sonderfaelle verloren
  gehen koennen.
- Er mischt fachliche Sync-Logik mit Stil-/Kommentar-/Fehlertext-Aenderungen.

**Alexandria-Fazit:** Die Idee "gesynct minus erlaubt = vom Kobo entfernen" ist
richtig. Alexandria hat diesen Kern lokal bereits sauberer in
`get_kobo_allowed_book_ids()` und der Deletion-Logik von `HandleSyncRequest()`
aufgenommen. Weitere Arbeit sollte hier nicht Domoel kopieren, sondern die
lokale Logik mit gezielten Tests absichern: normale Regale, Magic Shelves,
Wechsel aus der erlaubten Menge heraus, sowie Full-Sync-Modus ohne
Entfernungslogik.

#### sempai-san/cwa-nexus

**Status:** Architektonisch spannend, aber fuer Alexandria vorerst parken.

Der Fork ist jung und fokussiert auf Multi-Library-Betrieb. Interessante Muster:

- Eigene Tabellen fuer Bibliotheken und Benutzerzugriff
  (`CalibreLibrary`, `UserLibraryAccess`).
- Request-Kontext fuer aktive Bibliothek (`g.active_library`,
  `g.user_libraries`).
- Spaetere Korrektur, dass CWA nicht einfach direkt auf `metadata.db` zeigen
  darf, sondern das bestehende `ATTACH metadata.db AS calibre` /
  `ATTACH app.db AS app_settings`-Muster braucht.
- Zentralisierung von Dateipfaden ueber `config.get_book_path()`, damit Cover,
  Downloads und Konvertierung zur aktiven Bibliothek passen.
- Ingest-Routing ueber einen Library-Override.

Die spaeteren Fix-Commits zeigen aber auch die Risiken: Multi-Library greift in
Session-Lebensdauer, attached SQLite-Datenbanken, Dateipfade, Admin-UI, Ingest
und Rechteverwaltung ein. Das ist fuer Alexandrias Kobo-Fokus aktuell zu breit.

**Alexandria-Fazit:** Nicht in die kurzfristige Roadmap aufnehmen. Erst wieder
anfassen, wenn Alexandria wirklich mehrere Calibre-Bibliotheken in einer Instanz
unterstuetzen soll. Dann zuerst ein Architektur-ADR schreiben, nicht direkt Code
uebernehmen.

#### jmarmstrong1207/Calibre-Web-Auto

**Status:** Produktprinzip merken, Code vorerst ignorieren.

Der Fork ist deutlich hinter Upstream und lebt hauptsaechlich von der Idee,
Auto-Ingest zugunsten eines manuellen Buttons zu deaktivieren. Das passt gut zu
Alexandrias Leitlinie "mehr Kontrolle, weniger Magie", ist aber kein guter
technischer Diff-Kandidat.

**Backlog-Idee:** Spaeter pruefen, ob Alexandria Auto-Ingest sichtbarer
steuerbar machen soll: manuell starten, sicher pausieren, klarer Status,
keine heimlichen Loesch-/Importeffekte.

#### doen1el/calibre-web-companion

**Status:** Spaetere UX-Inspiration.

Die Companion-App ist kein CWA-Fork, aber aktiv und als mobile/companionartige
Bedienoberflaeche interessant. Fuer die naechsten Kobo-Sync-Backend-Schritte ist
sie nicht relevant.

**Backlog-Idee:** Wieder ansehen, wenn die Alexandria-Kobo-Uebersicht oder eine
mobile Bedienlogik gestaltet wird, insbesondere fuer Offline-/Account-Wechsel-
und einfache Bibliotheksaktionen.

#### Priorisierte Konsequenz

1. Die geplanten Kobo-/Magic-Shelf-Schritte bleiben vorne.
2. Domoel dient nur noch als Vergleich fuer Tests zur Entfernungslogik.
3. cwa-nexus bleibt als Architektur-Warnschild fuer spaeter.
4. jmarmstrong1207 und calibre-web-companion werden als Produkt-/UX-Backlog
   gefuehrt, nicht als kurzfristige Codequellen.

## Audit-Checkliste

- Datenmodell fuer normale Regale und Magic Shelves verstehen.
- Kobo-Sync-Pfad von Regal zu Kobo-Collection nachvollziehen.
- Pruefen, ob Collection-Erzeugung und Sync-Erlaubnis heute gekoppelt sind.
- Magic-Shelf-Query-Builder (`build_filter_from_rule()`) identifizieren.
- Calibre-Custom-Columns im Datenmodell und in Queries finden.
- Uebersetzungs-/i18n-Struktur pruefen.
- UI-Technik pruefen: Templates, statische Assets, moegliche Svelte-Roadmap.
- Teststrategie fuer Kobo-Sync-Regeln festlegen.

## Empfehlung für das Projekt-Setup

Die Nutzung von Alexandria als Fork-root (d.h. CWA-Code direkt im Hauptverzeichnis des Repositories) bleibt die klare Empfehlung.
Vor dem eigentlichen Fork müssen jedoch alle Alexandria-spezifischen Meta-Inhalte in einem eigenen Unterordner (`docs/alexandria/`) abgelegt werden. Dadurch bleibt die Root-`README.md` weitgehend unberührt bzw. kann beim Import des Upstreams problemlos durch dessen Original-`README.md` ersetzt werden, ohne Alexandria-spezifische Doku zu verlieren.

## Erste geplante Code-Spikes (Reihenfolge — Erfolgreich umgesetzt)

Die ersten Spikes wurden erfolgreich abgearbeitet:
1. **Sync-Mini-Bugfix mit Test** (Erledigt: `sync_shelves()`-Filter korrigiert und getestet)
2. **Magic-Shelf-Regel „Buch ist in Regal X“** (Erledigt: Regeltyp `normal_shelf` implementiert)
3. **Kombinierte Custom-Column-Felder** (Verschoben / künftig optional, da Kobo-Entkopplung Priorität hatte)
4. **Kobo-Auswahl vs. Kobo-Sammlung** (Erledigt: Kobo-Entkopplung mit 2-Säulen-Prinzip, Ausschlussregal und Dashboard vollendet)

Für die weitere mittel- und langfristige Planung siehe die neue [Release-Roadmap](release-roadmap.md).
