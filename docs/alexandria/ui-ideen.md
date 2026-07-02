# UI-Ideen

Alexandria soll nicht nur anders aussehen, sondern sich fuer den konkreten Kobo-Workflow ruhiger anfuehlen.

## Prinzipien

- Kobo-Auswahl zuerst, globale Admin-Optionen spaeter.
- Deutsche Begriffe als echte UX-Entscheidung, nicht als Woerterbuch-Uebersetzung.
- Weniger gleichzeitige Optionen auf einer Seite.
- Fortgeschrittene Einstellungen einklappen.
- Keine Sammlung erzeugen, nur weil Metadaten existieren.
- Serien sichtbar lassen, aber nicht als Standard-Sammlung duplizieren.

## Wichtige Ansichten

### Kobo-Auswahl

Eine Arbeitsansicht fuer die Frage: Was soll auf den Kobo?

Erwartete Elemente:

- Liste ausgewaehlter Buecher.
- Sammlungen pro Buch.
- Warnung bei sehr breiten Regeln.
- Filter fuer Universum, Inhaltstyp, Buchart und Lesestatus.
- Schnelle Aktion: aus Kobo-Auswahl entfernen.
- Sichtbare Kennzeichnung fuer Buecher in `Kobo: Ausgeschlossen`, damit klar
  ist, warum ein Buch trotz passender Regel nicht synchronisiert wird.
- Aktion: wieder fuer Kobo erlauben, indem das Buch aus
  `Kobo: Ausgeschlossen` entfernt wird.

### Sammlungen

Eine Ansicht fuer bewusst gepflegte Sammlungen:

- Universen.
- Leseprojekte.
- Sonderkategorien.
- Manuelle Kobo-Regale.

### Erweiterte Regeln

Magic-Shelf-Regeln bleiben moeglich, aber mit klareren Namen:

- "Automatische Sammlung" statt nur "Magic Shelf".
- "Bedingung" statt technischer Feld-/Operator-Sprache, wo moeglich.
- Vorschau: Welche Buecher wuerden aktuell enthalten sein?

## Deutsche Begriffsideen

- Shelf: Regal oder Sammlung, je nach Kontext.
- Magic Shelf: Automatische Sammlung.
- Kobo Sync: Kobo-Auswahl oder Auf Kobo uebertragen.
- Allow/Include: einschliessen.
- Exclude: ausschliessen.

## Warnungen, die Alexandria geben sollte

- Eine Regel wuerde sehr viele Buecher synchronisieren.
- Eine Sammlung basiert nur auf einem breiten Genre-Tag.
- Ein Buch ist fuer Kobo ausgewaehlt, hat aber keine sinnvolle Sammlung.
- Ein Buch ist in einer Kobo-Sammlung, aber nicht fuer den Kobo ausgewaehlt.
- Ein Buch wird durch eine Regel eingeschlossen, aber durch
  `Kobo: Ausgeschlossen` blockiert.
