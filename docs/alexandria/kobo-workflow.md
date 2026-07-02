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
