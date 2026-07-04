# Kobo-Workflow

Dieses Dokument beschreibt den geplanten Umgang mit Kobo-Sync, Regalen und Magic Shelves.

## Erkenntnis zum aktuellen CWA-Verhalten

Magic Shelves in CWA koennen nach festen Metadatenfeldern filtern, zum Beispiel Titel, Autor, Tags, Serie, Sprache, Bewertung, Datum, Lesestatus und aehnliche Felder. Eine Regel wie "Buch ist in normalem Regal X" gehoert nach der bisherigen Code-Recherche nicht zu den vorhandenen Magic-Shelf-Regeln.

Wenn eine breite Magic Shelf wie `Fantasy` fuer Kobo-Sync aktiviert wird, landen potenziell alle Buecher mit diesem Tag auf dem Kobo. Das widerspricht dem Ziel, nur bewusst ausgewaehlte Buecher zu synchronisieren.

## Sofort nutzbarer Workaround ohne Codeaenderung

- Keine breiten Magic Shelves fuer Kobo-Sync aktivieren.
- Normale Regale fuer bewusst ausgewaehlte Kobo-Sammlungen verwenden.
- Universen nur dann als Regal/Sammlung nutzen, wenn sie beim Suchen auf dem Kobo wirklich helfen.
- Serien nicht zusaetzlich als Sammlung anlegen.
- Tags wie `Fantasy`, `Science Fiction` oder `Romance` nicht direkt als Kobo-Sync-Regel verwenden.

## Sinnvolle Sammlungsarten

- `Universum: <Name>` fuer echte, uebergreifende Welten.
- `Projekt: <Name>` fuer temporäre Lesevorhaben.
- `Kobo: Kurzliste` fuer Buecher, die bald gelesen werden sollen.
- `Kobo: Sachbuch`, `Kobo: Fanfiction`, `Kobo: Klassiker` nur, wenn diese Kategorien auf dem Kobo wirklich praktisch sind.

## Zielverhalten fuer Alexandria

Langfristig soll Auswahl und Sortierung getrennt werden:

- Ein explizites Auswahlkriterium bestimmt, ob ein Buch auf den Kobo darf.
- Sammlungen bestimmen nur, wie das Buch dort einsortiert wird.
- Magic Shelves sollen nach normalen Regalen filtern koennen.
- Magic Shelves sollen Calibre-Custom-Columns wie `Universum`, `Buchart` oder `Inhaltstyp` nutzen koennen.

Beispiel fuer spaetere Regeln:

```text
Kobo-Auswahl:
  Buch ist in Regal "Kobo: Sync"

Sammlung "Universum: Scheibenwelt":
  Buch ist in Regal "Kobo: Sync"
  UND Universum ist "Scheibenwelt"
```

Damit waere `Fantasy` wieder als Sortiermerkmal moeglich, ohne automatisch die gesamte Fantasy-Bibliothek zu synchronisieren.

## Geplantes Verhalten: Loeschen direkt auf dem Kobo

Wenn ein Buch direkt auf dem Kobo geloescht wird, soll Alexandria diese Aktion nicht als Loeschung aus der Bibliothek verstehen. Das Buch bleibt in Calibre erhalten. Die Aktion bedeutet nur: Dieses Buch soll nicht mehr auf diesen Kobo-Sync-Weg.

Historisch wurde dies ueber ein Ausschlussregal namens `Kobo: Ausgeschlossen` geloest. Ab Phase 1 wird diese aktive Steuerlogik jedoch durch ein dediziertes Datenmodell (`KoboBookOverride` in `cps/ub.py`) in der Datenbank abgeloest. Das alte Regal dient nur noch zur Visualisierung oder Migration.

Zielverhalten ab Phase 1:

- Ein DELETE vom Kobo erzeugt fuer dieses Buch einen Datenbank-Override-Eintrag (`reader_override = "never"`).
- Das Buch bleibt in der Calibre-Bibliothek und in seinen fachlichen Metadaten unveraendert.
- Die Kobo-Erlaubnislogik berechnet kuenftig:

```text
Kobo-erlaubte Buecher =
  alle einschliessenden Kobo-Quellen (normale Regale, Magic Shelves, etc.)
  MINUS alle Buecher mit reader_override == "never"
```

- Der `never`-Override hat absoluten Vorrang vor normalen Regalen, Magic Shelves und spaeteren Custom-Column-Regeln.
- Wenn ein Buch wieder auf den Kobo soll, muss der Override geloescht werden (Zustand `auto`). Alexandria bietet dafuer im Kobo-Dashboard die Aktion `Wieder fuer Kobo erlauben` an.
- Wenn ein Buch zwar durch eine Kobo-Regel ausgewaehlt ist, aber bewusst nicht auf den Kobo soll, kann es im Dashboard ueber `Nicht auf Kobo` manuell mit dem Override `never` versehen werden.
- Sammlungen zeigen im Dashboard, wie viele ihrer Buecher durch `Nicht auf Kobo` blockiert sind. Dadurch ist sichtbar, warum eine Sammlung auf dem Kobo weniger Buecher enthaelt als lokal.
- Wenn eine Sammlung lokale Buecher enthaelt, die aktuell nicht auf den Kobo gehen, zeigt das Dashboard dies als `Hinweis` (Info), nicht als kritische Warnung.

Wichtig: Der Blockier-Status wird direkt in der Tabelle `kobo_book_override` gespeichert. Es ist primaer eine Steuerregel fuer die Sync-Erlaubnis.

### Implementierungs-Stand

Phase 1 (Overrides-Datenmodell, universaler Sync-Ausschluss für reader_override='never', Kobo-DELETE Umstellung, Dashboard-Anpassungen, Migrationstest und Regressionsabdeckungen) ist vollständig implementiert und getestet. Die weiteren geplanten Ausbaustufen befinden sich auf der [Release-Roadmap](release-roadmap.md).
