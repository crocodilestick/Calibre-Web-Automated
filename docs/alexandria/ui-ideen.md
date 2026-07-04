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
- Hinweis bei sehr breiten Regeln.
- Filter fuer Universum, Inhaltstyp, Buchart und Lesestatus.
- Schnelle Aktion: `Nicht auf Kobo`, um ein Buch bewusst aus der
  Kobo-Auswahl auszuschliessen.
- Sichtbare Kennzeichnung fuer blockierte Buecher (`reader_override = "never"`), damit klar ist, warum ein Buch trotz passender Regel nicht synchronisiert wird.
- Aktion: `Wieder fuer Kobo erlauben`, indem der Blocker-Override geloescht wird. Eine erste Dashboard-Aktion dafuer ist
  implementiert; spaeter kann die Darstellung noch dichter in die eigentliche
  Kobo-Auswahl integriert werden.
- Dashboard-Politur: Die Sektion `Nicht auf Kobo` bleibt sichtbar, zeigt die
  Anzahl blockierter Buecher, einen Leerzustand und die Aktion
  `Wieder fuer Kobo erlauben`.
- Dashboard-Gegenaktion: Die Sektion `Fuer Kobo ausgewaehlt` zeigt im
  Zwei-Saeulen-Sync erlaubte Buecher und bietet `Nicht auf Kobo` als direkte
  Blockieraktion an.

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

## Hinweise, die Alexandria geben sollte

- Eine Regel wuerde sehr viele Buecher synchronisieren.
- Eine Sammlung basiert nur auf einem breiten Genre-Tag.
- Ein Buch ist fuer Kobo ausgewaehlt, hat aber keine sinnvolle Sammlung.
- Ein Buch ist in einer Kobo-Sammlung, aber nicht fuer den Kobo ausgewaehlt.
- Ein Buch wird durch eine Regel eingeschlossen, aber durch
  `Kobo: Ausgeschlossen` blockiert. Im Dashboard wird dies fuer Sammlungen
  inzwischen als `Nicht auf Kobo`-Zaehler und Hinweis sichtbar.
