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

## Erste geplante Code-Spikes (Reihenfolge)

1. **Sync-Mini-Bugfix mit Test**:
   Korrektur des `sync_shelves()`-Bugs bezüglich `not ub.Shelf.kobo_sync` (Umstellung auf `== False` oder saubere SQL-Bedingung) und Absicherung über einen gezielten automatisierten Test im CWA-Testbaum.
2. **Magic-Shelf-Regel „Buch ist in Regal X“**:
   Ergänzung des Magic-Shelf-Felds `shelf` (Regel „Buch ist in Regal X“), um dynamische, regalkombinierte Sammlungen zu ermöglichen.
3. **Kombinierte Custom-Column-Felder**:
   Custom-Column-Felder für Magic Shelves sichtbar und filterbar machen.
4. **Kobo-Auswahl vs. Kobo-Sammlung**:
   Kobo-Sync-Auswahllogik (darf das Buch auf den Kobo?) sauber trennen von der Sortierung in Kobo-Sammlungen.
