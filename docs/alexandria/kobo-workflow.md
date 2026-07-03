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

Wenn ein Buch direkt auf dem Kobo geloescht wird, soll Alexandria diese Aktion
nicht als Loeschung aus der Bibliothek verstehen. Das Buch bleibt in Calibre
erhalten. Die Aktion bedeutet nur: Dieses Buch soll nicht mehr auf diesen
Kobo-Sync-Weg.

Die bevorzugte Modellierung ist ein explizites Ausschlussregal, zum Beispiel:

```text
Kobo: Ausgeschlossen
```

Alternativ waere ein Name wie `Kobo: Archiv` moeglich. Fachlich ist
`Kobo: Ausgeschlossen` klarer, weil es keinen allgemeinen Bibliotheksstatus
behauptet, sondern nur die Sync-Entscheidung beschreibt.

Zielverhalten:

- Ein DELETE vom Kobo fuegt das Buch in das Ausschlussregal des Benutzers ein.
- Das Buch bleibt in der Calibre-Bibliothek und in seinen fachlichen Metadaten
  unveraendert.
- Die Kobo-Erlaubnislogik berechnet kuenftig:

```text
Kobo-erlaubte Buecher =
  alle einschliessenden Kobo-Quellen
  MINUS alle Buecher aus "Kobo: Ausgeschlossen"
```

- Das Ausschlussregal hat Vorrang vor normalen Regalen, Magic Shelves und
  spaeteren Custom-Column-Regeln.
- Wenn ein Buch wieder auf den Kobo soll, muss es aus `Kobo: Ausgeschlossen`
  entfernt werden. Alexandria bietet dafuer im Kobo-Dashboard die Aktion
  `Wieder erlauben` an.

Wichtig: Das Ausschlussregal darf nicht nur als sichtbare Kobo-Sammlung
behandelt werden. Es ist primaer eine Steuerregel fuer die Sync-Erlaubnis.

### Implementierungs-Mini-Spike

Der naechste technische Schritt sollte klein bleiben:

1. Hilfslogik fuer ein benutzerspezifisches System-Regal
   `Kobo: Ausgeschlossen` definieren.
2. Den Kobo-DELETE-Endpunkt so erweitern, dass er das Buch dort eintraegt,
   statt nur den Sync-Tracking-Eintrag zu entfernen.
3. `get_kobo_allowed_book_ids()` so erweitern, dass diese Buch-IDs von der
   erlaubten Menge abgezogen werden.
4. Tests ergaenzen:
   - Ein Buch wird per Magic Shelf erlaubt, auf dem Kobo geloescht und kommt
     beim naechsten Sync nicht wieder.
   - Ein Buch wird aus `Kobo: Ausgeschlossen` entfernt und darf danach wieder
     ueber normale Sync-Regeln erscheinen.
   - Im Full-Sync-Modus wird die bestehende Archivierungslogik nicht
     versehentlich veraendert.
